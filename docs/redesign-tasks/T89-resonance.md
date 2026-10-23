# T89：`topology` / `irc-compare` 识别共振等价（修 R1）

## 分支与目标

- 分支：`codex/t89-resonance`；基于最新 main，一张任务单一个 PR。**开发机做。**
- **来源：** T68 风险报告 R1；10-17 只读调查结论：
  - 连接推断正确；键级和形式电荷位置由 RDKit `DetermineBondOrders` 选定一种局域写法（例如 nitronate 总把负电荷放在 O 上）；
  - 现有比较器逐编号比较键级、再比较含键级和形式电荷的 `graph_key`，**不识别共振等价**；调查中两几何恰好选到同一写法，所以没有误判，但两几何被推断成不同共振写法时（例如 IRC 路径上变形较大），会被误判为“变了”；
  - 两条 R1 strict xfail 要求推断结果等于人声明的局域写法，这在只有 XYZ 时**原则上不可满足**；
  - “只比较连接 + 片段电荷”的简化规则：去掉 H 会漏判互变异构，完全不看立体会漏判对映体。
- **目标：** 让比较器在**含全部 H 的连接关系相同**且**每个片段（按原子归属）的总电荷相同**时，判断键级 / 形式电荷的差异是否为共振等价；是则视为未变化并在报告中注明；立体检查完全保留、独立进行。改写两条 R1 xfail。
- 资料：`ag/src/ag/irc_compare.py`（`compare_endpoint`、键级比较、`graph_keys`）、`ag/src/ag/topology.py`（`compare_minimum`）、`ag/src/ag/geometry.py`（`infer_molecule`、`graph_key`）、`ag/tests/test_inference_risk.py`、`docs/research/rdkit-inference-risk.md`、10-17 调查记录（只读，在开发机临时目录，不入仓库）。

## 允许改动的路径

- `ag/src/ag/irc_compare.py`：只改键级 / graph_key 比较之后的判定，以及报告字段。
- `ag/src/ag/geometry.py`：只**新增**一个共振等价判断函数；`infer_molecule`、`graph_key` 行为不变。
- `ag/src/ag/topology.py`：仅在需要透传新字段时改。
- `ag/tests/test_inference_risk.py`、`ag/tests/test_irc_compare.py`（或现有对应测试文件）、`ag/tests/test_topology.py`：新增和改写用例。
- `docs/research/rdkit-inference-risk.md`：R1 一节末尾追加“T89 处理”说明（不改原记录）。
- `ag/README.md`：topology / irc-compare 一节补一句。
- `docs/redesign-tasks/T89-resonance.md`：本任务单。

## 要做的

1. **判定顺序（比较两个已推断的分子 A、B，原子编号一一对应）：**
   1. 元素序列、电荷、多重度不同 → 维持现有处理；
   2. 距离推断出的连接关系不同（含 H，按编号）→ 维持现有处理（`changed`），不做共振判断；
   3. 连接关系相同，但键级或形式电荷不同 → 先核对**每个连通片段**（按原子归属，不是排序后的电荷集合）的总电荷是否相同；不同 → 维持 `changed`；
   4. 片段电荷也相同 → 用 RDKit 的共振枚举（`ResonanceMolSupplier`，或在 PR 中说明的等效方法）对 A 枚举共振式，判断 B 的“含编号的键级 + 形式电荷”是否在其中（为对称起见，也对 B 枚举、找 A）；在其中 → **共振等价**：键级比较视为一致，报告写 `resonance_equivalent: true` 及涉及的原子 / 键；不在其中 → 维持现有不一致结论；
   5. 立体比较照旧独立进行；共振等价不影响立体结论（立体不同仍是 `changed`）。
2. **共振枚举设上限**（例如最多 1000 个共振式，参数写成常量）；超过上限或枚举失败 → 该项判 `unknown` 并注明原因，**不默认等价**。
3. **报告：** 新增字段 `resonance_check`（是否执行、结果、枚举数量、是否达到上限）；`bond_differences` 保留原始逐键差异，另加 `bond_differences_resonance_equivalent: true/false`，方便人工核对。Markdown 中写明“键级 / 电荷位置差异经判断为共振等价”。
4. **改写 R1 的两条 strict xfail：**
   - 新测试 1：nitronate、乙酸根、烯醇负离子各自的两种共振写法（同编号几何）→ 比较器结论为共振等价（未变化）；
   - 新测试 2：把“推断写法不等于人声明的局域写法”作为**明确记录的已知限制**（普通断言推断结果是某一合法共振式、总电荷正确），不再保留永远不可能通过的 xfail；
   - 删除原 xfail 时在测试注释和风险报告中说明理由。
5. **反例必须仍被检出（来自调查）：** nitronate + HF → 硝基甲烷 + F⁻；丙酮烯醇负离子 + HF → 丙酮 + F⁻；乙醛 ↔ 乙烯醇；含硼邻位手性碳的对映体。

## 不允许

- 不放宽连接关系、片段电荷、立体的比较；不去掉 H 比较。
- 不改 `infer_molecule`、`graph_key` 的现有输出。
- 共振判断失败时不默认等价。

## 测试

- 上述三组共振式（含调查中的插值几何若干个）→ 共振等价；四个反例 → 仍为 changed / 不匹配。
- 人为构造“连接相同、片段电荷相同、但不是共振式”的例子（例如电荷放在不可能的位置）→ 不等价。
- 枚举达到上限 → unknown。
- 现有 topology / irc-compare 夹具：输出除新增字段外与 main 一致（哈希对比，排除版本字段）。
- 开发中只跑相关测试；推送前本地跑一次全量 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，之后以 CI 为准。敏感扫描与 `git diff --cached --check`。

## 真实环境验证

- 纯本地分析，不需要集群。合并前在开发机上用 L3 重跑一次 `ag irc-review` 依赖的 `irc-compare`（输出写到 study 以外），结论与之前一致。
- 合并后由研究 A 主会话只读重跑已有 topology / irc-compare 报告（输出写到 study 以外），列出结论有变化的 Attempt 交监督方（可与 T73 的合并后核查一起做）。

## 停止条件

- 需要改 `infer_molecule` 或 `graph_key` 的输出。
- 共振枚举在合理时间内无法处理 80–100 原子的体系（给出耗时数据后停下汇报）。
- 现有夹具的结论发生变化（新增字段除外）。

## 合并前审阅与交付

- 需要监督方审阅：是。
- PR 描述第一行：`Task: T89`；附共振式与反例的前后对照。
- 合并只由负责人操作。

## 版本记录

- T116 脱敏：研究标识、编号与环境字面量改为泛称；原工单结构和结论不变。
