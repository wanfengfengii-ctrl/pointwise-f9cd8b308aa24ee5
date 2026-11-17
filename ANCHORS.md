# 规则跨度锚点条件分析

## 已有业务与新增结果

README.md 及现有源码提供完整 V1：不可变加权语法、来源修订、队列冻结、无标注序列证据和规则次数、原子发布、固定报告及复算包。V1 接口和原测试保持兼容。本次新增已核实标注的联合条件分析；本文件及 anchored_examples.py 仅提供契约与调用数据，不提供目标实现。

## 调用与输入

在 sequence_lab.analysis.execute 提供：

```python
analyze_anchored(db, grammar_ref, cohort_id, member_id,
                 anchors=(), rule_ids=(), *, fault=None) -> int
```

返回已发布的 analysis_id；db 和各身份沿用 README 的定义。rule_ids 沿用零至两个不同原始规则 ID 的规则，与 anchors 独立选择，统计可以包含未被标注的规则。语法、序列长度及精确支持边界均沿用 V1。

anchors 接受 list 或 tuple，含零至两个不同的三元组；每项也接受 list 或 tuple，恰含 (rule_id,i,j)。rule_id 为固定语法内原始规则的字符串 ID；i、j 为非布尔整数，0≤i<j≤冻结成员的序列码点数。不同是指完整三元组不同；同一规则可标注两个不同跨度。非法形状、重复项、未知规则、布尔或越界坐标，以及 V1 已拒绝的绑定或统计选择，均抛 AnalysisRequestError，requests、analyses、reports 不增加记录。坐标相对冻结副本，不相对最新来源；不进行 Unicode 归一化。

## 联合事件与输出

每个锚点表示同一完整有序解析树中，该原始规则至少有一次应用的产出跨度恰为[i,j)；全部锚点取交集，不限定二元拆分点，不限制该应用之外的规则使用。
emit 应用覆盖一个码点，unary 应用覆盖其子树全部产出，binary 应用覆盖左右子树产出的相邻整体。循环可在同一跨度重复应用，标注只要求出现，次数仍逐次累计。零权重规则及不能共同满足的锚点仍是合法请求，产生零质量。

对全部满足标注的有限解析精确求和，不截断一元循环。evidence 为序列与全部锚点事件的联合质量，不能除以无标注序列质量；均值和完整协方差在该联合事件下共同条件化。沿用 AnalysisResult.canonical_record() 的四字段结构 status、evidence、rule_ids、statistics，所有数值仍为 Fraction，rule_ids 顺序不变。正质量为 status="ok"；无统计选择时 means=()、covariance=()。零质量为 status="impossible"、evidence=Fraction(0)、statistics=None。

空标注与 analyze_sequence 的数学结果一致；重排锚点不改变数学结果。允许全量重算、标准有理线性代数及对子集重复求解，不规定内部表示。

## 固定交付及兼容

新增入口保存调用时的独立副本，锚点按输入顺序规范为 tuple[tuple[str,int,int], ...]。公开读回位置：
- load_published_analysis(db,aid)["request"]["request"]["anchors"]；
- read_report(db,rid).request["anchors"]；
- 复算包 report.request.anchors 以及 report.parents.fixed.request.anchors。

这些位置保存同一口径；result 结构不新增 anchors 字段，成果必须通过已核验的固定请求与锚点绑定。请求、成果、报告及复算包共同保存锚点，读取不推断，更正、对象修改及重开不改变旧交付。此处“成果保存锚点”指其固定请求关联，非要求在 result 重复字段。

继续使用 create_report、read_report、export_report 和 load_reproduction_bundle。后两者按既有父链、成员、指纹及错误边界核验新增口径，非法锚点负载须被拒绝。旧的无 anchors 请求、已发布成果、报告及 version=1 复算包仍可读取、导出和复算；不得因补空字段改变旧固定记录的口径或指纹。旧 analyze_sequence 调用仍保持原行为。无需迁移数据库或新增编码标签。

沿用 after_request、after_result、before_commit 故障点；失败不留下本次请求或成果，允许重试。沿用导出的 during_write、before_replace、原子替换及保全旧目标边界。

离库复算按包内 parents.grammar、parents.cohort 和 parents.member 重建固定输入；新请求使用包内 anchors 与 rule_ids 调用 analyze_anchored，旧请求使用 analyze_sequence。比较完整 result；不得回取当前来源。仅锚点条件不同就可能改变结果，因此导出不能遗漏实际锚点。

## 手算调用与交付验证

anchored_examples.py 定义六组合法输入及手算预期。默认执行 V1 无标注链，命令为 `python3.11 -B anchored_examples.py`；完成新增入口后用 `python3.11 -B anchored_examples.py --anchored` 检查锚点调用及报告读回。该开关在初始 V1 尚不可用，属于本次开发缺口。

- 等权 S→AB、S→BA，A、B 都发射 a：aa 的无标注质量为1；只锚定 ab 的 [0,2) 得质量1/2，两展开次数分别恒为1和0。共同锚定 ab、ba 的 [0,2) 得 impossible。
- S→S 与 S→a 各1/2：a 上锚定循环 [0,1)，质量1/2，循环次数均值2、方差2。
- 确定 S→AA、A→a：在 [0,1)、[1,2) 锚定同一发射规则，质量1，总次数2、方差0。
- 确定发射 é🙂 时，🙂 的跨度为 [1,2)，零统计选择仍得质量1和空统计容器。
- 零权重循环的存在锚点合法，质量0、统计为 None。

补独立无循环小语法的有限解析枚举对照，核对联合质量、均值及完整协方差；循环用手算核账。覆盖空锚点、重排、非法输入拒绝，以及发布失败回滚重试。新增分析创建报告后更正来源，关闭并重开文件数据库，核对旧请求及结果，导出后离库复算；读取不得重新推断。保留全部原测试。提供简短交接不变量说明。

继续使用现有 .pointwise-runtime.json：保留 version=1、kind=cli、setup 的 argv 数组列表及 verify/demo 的 argv 数组格式。扩展其实际入口或原 verify.py/demo.py，使 verify 运行完整原回归及新增联合核验，失败返回非零；demo 展示联合矛盾，以及更正来源后重开旧报告并离库复算的真实结果。现有原演示继续可执行。
