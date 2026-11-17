# 海岬序列研究室

Python 3.11 标准库离线分析链。仪器操作员提交字符序列修订，分析员用固定加权语法解释序列，质控人员读取规则次数的精确均值、协方差及可复算报告。无需安装依赖。

## 当日流程

1. 分析员登记带原始规则 ID 的语法修订，固定解释口径。
2. 操作员提交来源批次，系统完整校验后原子接纳最高修订。
3. 分析员冻结来源，保存字符与修订副本。
4. 选择固定语法、队列成员及零至两个不同规则。
5. 编译全部原始边、一元闭合与应用贡献。
6. 按有序非空跨度计算全部有限解析及联合次数矩。
7. 原子发布成果，质控人员据此生成固定报告。
8. 导出复算包，关闭重开后复核；后续更正不改变旧交付。

## 运行

在项目根目录执行：

```sh
python3.11 -B verify.py
python3.11 -B demo.py
python3.11 -B -m unittest discover -s tests -t . -v
```

verify 调度完整原套件。demo 在测试临时目录使用真实 SQLite 数据库，展示两个同形循环规则、源更正后的 impossible、重开旧报告及互斥二元展开。导出通过正常接口执行，断言通过后打印 POINTWISE_SCENARIO 实测记录。所有演示文件在结束时清理。

## 公开 API

以项目根目录为导入路径，所有数据库参数均为 open_database 返回的 Database；支持上下文管理器，默认 :memory:，传路径则创建或打开该 SQLite 文件。

|模块|接口|
|---|---|
|delivery.database|open_database(path=":memory:")，Database.transaction()，close()|
|grammar.model|Rule(rule_id,lhs,kind,rhs,weight)，GrammarRevision(grammar_id,revision,start,nonterminals,alphabet,rules)|
|grammar.revisions|save_grammar(db,grammar) -> 整数 grammar_ref；load_grammar_revision(db,grammar_ref)|
|cohort.records|SequenceUpdate(source_id,revision,sequence=None,withdrawn=False)|
|cohort.revisions|apply_sequences(db,updates) -> ApplyResult；load_current_sources(db,source_ids=None)|
|cohort.snapshots|freeze_cohort(db,source_ids) -> 整数 cohort_id；load_cohort_snapshot；load_snapshot_member|
|analysis.execute|analyze_sequence(db,grammar_ref,cohort_id,member_id,rule_ids=(),fault=None) -> 整数 analysis_id；analyze_anchored(db,grammar_ref,cohort_id,member_id,anchors=(),rule_ids=(),*,fault=None)|
|delivery.publish|load_published_analysis(db,analysis_id) -> 独立字典，包含 request、result|
|reporting.reports|create_report(db,analysis_id) -> 整数 report_id|
|reporting.read|read_report(db,report_id) -> FixedReport，canonical_record() 返回完整记录|
|reporting.export|export_report(db,report_id,output_path,fault=None) -> 复算包；load_reproduction_bundle(path)|

fault 是仅限关键字的可选函数，接收阶段字符串并可以抛错。分析阶段为 after_request、after_result、before_commit；导出阶段为 during_write、before_replace。异常传播并清理本次未提交状态；导出的 OSError 包装为 ReportExportError。允许原请求重试，不承诺分析请求幂等去重。模块路径前缀均为 sequence_lab。

```python
from samples import seed_demo
from sequence_lab.delivery.database import open_database
from sequence_lab.cohort.snapshots import freeze_cohort
from sequence_lab.analysis.execute import analyze_sequence
from sequence_lab.reporting.reports import create_report
from sequence_lab.reporting.read import read_report

with open_database() as db:
    grammar_ref = seed_demo(db)
    cohort_id = freeze_cohort(db, ["sample_01"])
    analysis_id = analyze_sequence(db, grammar_ref, cohort_id, "sample_01", ("p", "q"))
    report = read_report(db, create_report(db, analysis_id))
    print(report.result)
```

## 领域契约

规则 kind 为 emit、unary、binary。rhs 为元组：emit 含一个 Unicode 码点，一元含一个非终结符，二元含有序左右两个非终结符。weight 必须为非负 Fraction，每个非终结符的权重和严格等于 1。最多 8 个非终结符、16 条规则，无空串规则。原始规则 ID 在一个修订内唯一，同形及零权重规则分别保留。字母表明确声明发射字符；未知右部符号拒绝。一元矩阵 U 的谱半径必须不超过 19/20，采用有理主子式精确判定，边界相等接纳，高行和无环语法也可接纳。语法不要求整体必然终止。

来源修订为正整数，非撤回序列为 1—24 个 Unicode 码点；不做裁剪、大小写或 NFC 转换。撤回必须 sequence=None 且 withdrawn=True。整批先校验形状；相对调用开始时的最高修订忽略更旧合法记录，其余同版冲突整批拒绝，包括批内冲突。批内多个新版本排序后以最高版生效。更高版本可以恢复来源。冻结保存完整值；未知、撤回或重复选择使整个冻结失败。空队列合法，不能从中绑定成员。

语法同身份同修订同内容幂等；同版异内容拒绝。新语法修订不修改旧修订。来源不在语法字母表的字符属于合法零证据输入。未知输入身份、非成员、重复规则或超过两个规则均拒绝且不发布。

计算对固定完整序列的全部有限有序解析共同条件化，包括一元循环任意有限次经过及二元全部合法拆分。跨度为码点半开区间 [i,j)，拆分满足 i<k<j。每次规则应用逐次计数；次数单位为一次解析中的应用次数。输出 evidence 为无量纲 Fraction。正证据 result 为 status="ok"，rule_ids 保持请求顺序，statistics 含 means 元组与完整 covariance 元组矩阵；零规则请求为两个空元组。协方差可以为负。零证据 status="impossible"、evidence=Fraction(0)、statistics=None；不能将不可条件化解释成零次数。计算完全确定，无抽样或浮点容差。

手算核账：自循环 q、发射 1-q 对 a 的证据 1、循环均值 q/(1-q)、方差 q/(1-q)^2。两个不同 ID 循环各 1/4、发射 1/2 时，各均值 1/2、方差 3/4、协方差 1/4。等权 AB/BA 且子节点都发射 a 时，aa 中两展开规则协方差 -1/4。S→AA 的同一确定发射规则使用两次，普通二阶矩 4、方差 0。

## 固定交付与错误

SQLite 表分别保存不可变语法、当前来源、完整队列、固定请求、分析和报告，外键及指纹连接父链。分析请求与成果同事务提交；计算中间态不可读取。报告只消费已发布成果，读取不编译、不分析，不回退当前来源。返回对象均独立，调用方修改它们不修改数据库。直接改库不是编辑接口；检测到缺父项、串链或内容指纹不一致则拒绝读取和导出。

初始化识别新库及版本 1；未知版本拒绝，重复初始化不清表、不重置 ID、不播种。samples.seed_demo 通过正常接口提交明确样例身份；同版冲突报错，更高来源修订保留，不覆盖用户更正。

非法语法抛 GrammarValidationError；同版语法冲突抛 GrammarRevisionConflict。非法来源抛 SequenceValidationError，同版冲突抛其子类 SequenceRevisionConflict。冻结错误为 SnapshotSelectionError，分析绑定错误为 AnalysisRequestError。未知已发布分析读取为 KeyError，报告创建错误为 ReportCreationError，未知报告为 ReportNotFound，父链错误为 ProvenanceError。编码错误为 CodecError，不支持的库版本为 UnsupportedSchemaVersion。均不发布部分成果。

codec 的结构化 JSON 带 version=1，每个值有显式类型标签；Fraction 使用规范整数分子和正分母，拒绝零分母、非约分表示、未知标签、重复键及不完整结构。无 float、pickle 或外部依赖。

导出带格式版本，包含报告、完整原始语法、冻结队列、所选成员修订、请求顺序与精确结果。先完整写入目标同目录临时文件，再原子替换；失败保留旧目标或不生成新目标，清理临时文件。复核者可用 load_reproduction_bundle 读取，按 parents.grammar 重建 GrammarRevision，按 parents.cohort 用 SequenceUpdate 登记，重新冻结后以原 rule_ids 分析，比较 result。数据库外部 ID 仅作来源标识，复算数学结果不依赖其具体数值。

## 回归与代码归属

grammar 的四模块负责不可变口径与接纳；cohort 四模块负责来源批次和冻结；compiler 四模块负责执行边、一元闭合和原始贡献；analysis 四模块负责绑定、证据、联合矩和执行；delivery 四模块负责精确编码、版本库及发布；reporting 四模块负责固定报告、父链核验与原子导出。所有生产路径均在真实分析交付链中使用。

tests/test_analysis.py 覆盖确定发射、几何循环、同形身份、互斥分支、零证据及请求、顺序、Unicode、权重扫描、二元交叉矩、带循环递归和互相转换。tests/test_anchored.py 用独立有限解析枚举对照无循环小语法，并行循环手算核账，覆盖空锚点、重排、零权重、Unicode 与双锚点矛盾。tests/test_anchored_delivery.py 覆盖非法锚点整次拒绝、故障点回滚重试、更正后重开、离库复算与复算包锚点篡改。tests/test_examples.py 核对 anchored_examples.py 六组手算。tests/test_inputs.py 覆盖非法语法原子拒绝、精确支持边界、批次冲突、版本顺序、撤回恢复和快照隔离。tests/test_delivery.py 覆盖发布故障点、初始化、精确编码、磁盘重开、离库复算、对象独立、父链损坏、原子导出和真实替换错误。所有测试使用真实标准库计算及 SQLite，不依赖网络。锚点实现口径与核对方法见 HANDOFF.md。
