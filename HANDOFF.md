# 交接不变量：规则跨度锚点条件分析

本文件记录 `analyze_anchored` 交付后的实现口径与核对方法。业务契约见
`ANCHORS.md`，V1 契约见 `README.md`。

## 1. 事件语义

锚点 `(rule_id, i, j)` 表示：在**同一棵**完整有序解析树中，原始规则
`rule_id` 至少有一次应用的产出跨度为码点半开区间 `[i, j)`。多个锚点取
交集；不限定二元拆分点，也不限制锚点之外的规则使用。一元循环在同一
跨度重复经过时只要求"至少一次"，但次数统计仍逐次累计。

因此 `evidence` 是"序列 × 全部锚点事件"的联合质量，**不能**除以无标注
序列的质量。均值与完整协方差都以该联合质量为唯一条件分母。

## 2. 算法

`sequence_lab/analysis/anchored.py` 的图表单元按
`(非终结符, 锚点位掩码)` 取值：掩码记录"子树内已经出现过哪些锚点事件"。
一个跨度 `[i, j)` 的单元只能见到跨度恰为 `[i, j)` 的锚点：

- 该跨度的 emit / binary 基底节点；
- 该跨度的 unary 闭包链上的每次应用。

子单元的掩码按位 OR 合并。对每一掩码解一个有理线性系统（一元闭包），
见证型一元应用把子掩码 `child` 映到 `child | own`，同掩码重复应用是普通
转移。特殊情形 `child = mask` 且 `own ⊆ mask` 归入同掩码项，避免循环
自引用。全部系数为 `Fraction`，不做截断、抽样或浮点近似。

复杂度：`O(n^3 · 4^A · (1 + d^2))`，`A ≤ 2`，`d ≤ 2`。长度 24、两个
锚点、递归二元语法的实测约 0.3 秒。

## 3. 固定请求与交付

- 请求结构在 V1 的 `grammar_ref/cohort_id/member_id/rule_ids` 之外**可选**地
  增加 `anchors`，仅当调用 `analyze_anchored` 时写入；`analyze_sequence`
  的请求字节与 V1 完全一致。
- 锚点按输入顺序规范为 `tuple[tuple[str, int, int], ...]`，并在三处读回：
  - `load_published_analysis(db, aid)["request"]["request"]["anchors"]`
  - `read_report(db, rid).request["anchors"]`
  - 复算包 `report.request.anchors` 与 `report.parents.fixed.request.anchors`
- `result` 结构不变（仍是 `status/evidence/rule_ids/statistics`），锚点只
  通过已核验的固定请求绑定。
- 读取路径只做校验，不编译、不重算、不回取当前来源。缺父项、串链、指纹
  不一致、锚点重复/越界/未知规则、两处锚点副本不一致，均拒绝读取或导出。
- 旧记录不补空字段，指纹与字节不变。

## 4. 拒绝与回滚

`AnalysisRequestError` 覆盖：非法形状、重复三元组、未知规则、布尔或非
整数坐标、`i < 0`、`i >= j`、`j > len(冻结成员)`、超过两个锚点、以及
V1 已有的绑定/规则选择错误。所有校验发生在写入之前；失败时
`requests/analyses/reports` 计数不变。`after_request / after_result /
before_commit` 故障点保持原语义，异常传播并回滚本次事务，允许原请求重试。

## 5. 核对方法

- `tests/test_anchored.py`：
  - `_enumerate` 是对无循环小语法的独立有限树枚举器，直接按锚点集合过滤
    解析并计算联合质量、均值、完整协方差，与图表结果逐一比对（多语法、
    多序列、多规则选择、双锚点组合）。
  - 循环语法用手算核账：`S→S` 与 `S→a` 各 `1/2`、锚定循环 `[0,1)` 时
    质量 `1/2`、均值 `2`、方差 `2`；`q=2/5` 的一般式
    `q/(1-q)`、`q/(1-q)^2` 一并验证。两个不同循环各 `1/4`、发射 `1/2` 时，
    单锚点与双锚点的质量（`1/3`、`1/6`）、均值与完整协方差按
    负多项分布手算核对。
  - 空锚点与 `analyze_sequence` 逐字段相等；锚点重排不改变结果；零权重
    锚点合法且为 impossible；Unicode 码点跨度按码点计。
- `tests/test_anchored_delivery.py`：非法输入整次拒绝、同一规则两个跨度
  合法、三个故障点回滚与重试、创建报告后更正来源并重开文件库、导出后离库
  复算、旧记录无 `anchors` 字段且字节不变、复算包锚点篡改与重复锚点负载
  被拒。
- `tests/test_examples.py`：`anchored_examples.py` 六组手算样例的
  ordinary 与 anchored 结果及报告读回位置。
- `demo.py` 演示联合矛盾（两展开同时锚定 → impossible）、单锚点半质量，
  以及更正来源后重开旧报告并离库复算得到同一结果，打印
  `POINTWISE_ANCHORED` 实测记录。

## 6. 命令

```sh
python3.11 -B verify.py                              # 完整回归（42 项）
python3.11 -B demo.py                                # 原演示 + 锚点演示
python3.11 -B anchored_examples.py                   # V1 无标注样例
python3.11 -B anchored_examples.py --anchored        # 锚点样例
```

`.pointwise-runtime.json` 保持 `version=1`、`kind=cli`、空的 `setup`，以及
`verify`/`demo` 的 argv 数组格式；新增核验已并入 `verify.py` 的既有发现
范围（`tests/` 目录），无需改动清单。
