# T73：`ag topology` 不确定接触不再把顶层状态提升为 changed（修 R2）

版本：v2（2026-10-16）。按负责人转达的审阅意见修订，取代 v1：片段数不确定性不能覆盖
`compare_endpoint` 已确定的键变化；新增确定变化与不确定接触并存的回归要求。

## 分支与目标

- 分支：`codex/t73-topology-uncertain`；基于 v4.2.1 合并后的最新 main，一张任务单一个 PR。**开发机做。**
- **开工条件：** v4.2.1（T67）已合并并打 tag。
- **目标：** 修 T68 报告里的 R2。现在 B–O 等接触落在不确定区间（共价半径和的 1.2–1.5 倍）时，`compare_endpoint` 正确给出 unknown，但随后 `_check_fragments_and_mapping` 只按“确定相连”的边数片段，得到片段数变化，把顶层状态改成 `changed`。修改后：**片段数变化只有在不确定接触按“相连”和按“不相连”两种处理下都成立时，才据此报 `changed`；否则保留不确定性，并写明是哪几个不确定接触导致的。若 `compare_endpoint` 已因确定的 `bond_differences` 返回 changed，则保持 changed，不因片段数不确定而降级。**
- **为什么：** 顶层 `changed` 会被理解为“确定发生了断键/成键”，掩盖了下面的 unknown。某研究候选含有不确定原子接触，正是这种情况；`ag irc-compare` 在同一例子里已经正确保留 unknown，两个命令的口径应当一致。
- 资料：`docs/research/rdkit-inference-risk.md` 的 R2 一节；`ag/src/ag/topology.py`（`fragments`、`_check_fragments_and_mapping`、`compare_minimum`）；`ag/src/ag/irc_compare.py`（`_pairs` 的状态划分）；`ag/tests/test_inference_risk.py` 中 R2 的 strict xfail。

## 允许改动的路径

- `ag/src/ag/topology.py`：只改片段数比较和顶层状态汇总；`fragments()` 的默认输出（`ag fragments` 在用）不变。
- `ag/tests/test_inference_risk.py`：R2 的 strict xfail 改为正常通过的断言；其余 xfail（R1）不动。
- `ag/tests/test_topology.py`：新增用例。
- `docs/research/rdkit-inference-risk.md`：在 R2 一节末尾追加“已由 T73 修复”及修复后的口径（不改原有记录）。
- `ag/README.md`：topology 一节补一句状态含义。
- `docs/redesign-tasks/T73-topology-uncertain.md`：本任务单。
- **不改 `irc_compare.py`、`geometry.py`、`fragments.py`**。需要改就停下询问。

## 要做的

1. **两种处理各算一次片段数：** 对提交结构和最终结构，分别把不确定接触当作“相连”和“不相连”计算片段数（确定相连的边两种处理都保留）。可以给 `fragments()` 加一个内部可选参数，但不带参数时输出与现在逐字节一致。
2. **判定：**
   - 两种处理下片段数都发生变化（且方向一致）→ `changed`，原因写明片段数；
   - 两种处理下都不变 → 按原来的逻辑继续（不改变现在不涉及不确定接触的结果）；
   - 其余情况（是否变化取决于不确定接触怎么算）→ 没有已确定的键变化时顶层为 `unknown`；若 `compare_endpoint` 已因确定的 `bond_differences` 返回 changed，则保持 `changed`。两种情况都在原因中追加相关的不确定接触（原子编号、元素、距离、比值），并说明“片段数是否变化取决于这些接触是否算作成键”；两个新增字段照常输出。
3. **报告字段：** `fragments` 下保留现有的 `submitted`、`final`（确定相连边的结果，含义不变）；新增 `fragments_if_uncertain_bonded`（两个结构的片段数），以及 `fragment_change_depends_on_uncertain_contacts`（布尔）。Markdown 摘要相应加一行。
4. **不改变的结果：** 没有不确定接触的结构，JSON 输出除 `ag_version`、`ag_provenance` 外与 main 逐字节一致（用现有夹具对比）；`same_connectivity_graph` 的同元素互换检查逻辑不变。
5. 与 `irc-compare` 口径核对：在 T68 的 B–O 2.2 Å 例子上，两个命令都给出 unknown。

## 不允许

- 不改不确定区间的阈值（0.6 / 1.2 / 1.5）。
- 不改 `ag fragments` 的输出；不改 `irc-compare` 的结果。
- 不回写任何已有的 topology 报告或已签证据。

## 测试

- T68 的 B–O 2.2 Å 例子：顶层 `unknown`，原因列出 B–O 接触；原 strict xfail 改为正常断言并通过。
- 确定断键（例如 B–O 拉到 3.5 Å，比值 > 1.5）：仍为 `changed`。
- 确定质子转移（片段数 delta=0）或确定断键，并存影响片段数的不确定接触：保持 `changed`，原因同时保留确定键变化与不确定接触；正、反方向均覆盖。
- 两种处理下片段数都变化：`changed`。
- 无不确定接触的现有夹具：输出与 main 一致（哈希对比，排除版本字段）。
- 开发中跑 topology 和 inference-risk 相关测试；推送前本地跑一次全量 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，之后以 CI 为准。敏感扫描与 `git diff --cached --check`。

## 真实环境验证

- 纯本地分析，不需要集群，不作为合并前条件。
- **合并后（研究 A 主会话，在计算机上，只读）：** 对研究 A 中已有 topology 报告的每个 Attempt，用新版本重跑 `ag topology`，`--out` 写到 study **以外**的临时目录；列出顶层状态与原报告不同的 Attempt（编号、原状态、新状态、涉及的接触），交监督方判断。不覆盖、不改写原报告和已签清单。

## 停止条件

- 需要改 `irc_compare.py`、`geometry.py`、`fragments.py` 或不确定区间阈值。
- 无不确定接触的夹具输出发生变化。

## 合并前审阅与交付

- 需要监督方审阅：是。
- PR 描述第一行：`Task: T73`；附 B–O 例子修复前后的顶层状态和无关夹具的哈希对比。
- 合并只由负责人操作。

## 版本记录

- T116 脱敏：研究标识、编号与环境字面量改为泛称；原工单结构和结论不变。
