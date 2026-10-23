# T44：解离端点的片段识别与导出 `ag fragments`

## 分支与目标

- 分支：`codex/t44-fragments-export`；基于最新 main，一张任务单一个 PR。
- 目标：新增本地只读命令。对一个已取回的 Attempt（IRC 端点或优化结果）或一份 XYZ，按共价半径规则找出连通片段，逐个导出成单独的 XYZ，保留原始原子编号的对应关系和各片段的分子式。各片段的电荷、多重度以及后续怎样计算，由人确认，命令不推断。
- 资料：
  - `ag/src/ag/topology.py` 中的 `_fragments`（T38，已合并）：按半径比 [0.6, 1.2) 的确定相连边统计连通片段，给出 Hill 顺序的分子式；
  - `ag/src/ag/irc_compare.py` 中的 `load_source`（读 IRC 端点 `irc_end.xyz` 或 `final.xyz`）；
  - 旧版知识来源（只读参考，不 import，提交说明注明来源）：`archive/skills/auto-g16-ts-irc/scripts/ts_irc.py:2341` 的 `propose_endpoint_components`；
  - irc 卡片第 132 行和 complex 卡片（T40）对断开片段的处理要求。
- 防的事故：IRC 走向分离产物时，端点是两个片段。现在只能手工拆坐标，容易弄错原子编号映射；或者直接把整个端点当成一个单分子去优化，得到无意义的“极小点”。

## 允许改动的路径

- `ag/src/ag/fragments.py`：新模块。
- `ag/src/ag/topology.py`：只允许把 `_fragments` 改成可供 fragments 复用的公共函数，行为和输出不变，现有测试不改。
- `ag/src/ag/cli.py`：只在本地工具元组中加入 `'fragments'`。
- `ag/tests/test_fragments.py`（新增）及合成数据。
- `ag/tests/test_smoke.py`：命令清单中加入 `fragments`（两处列表，事先批准）。
- `README.md`：命令表加一行。
- `docs/DEVELOPING.md`：模块地图加一行。
- `docs/redesign-tasks/T44-fragments-export.md`：本任务单。

## 要做的

1. **命令形式：** `ag fragments <attempt 或 xyz> [--study <dir>] --out <analyses/新文件.json> [--json]`。输入是 Attempt 时，IRC Attempt 读 `irc_end.xyz`，其他读 `final.xyz`（与 `irc-compare` 的 `load_source` 规则一致）。
2. **输出：**
   - JSON 和 Markdown 报告：片段数；每个片段的原始原子编号列表（从 1 开始）和分子式；判定规则和阈值；不确定接触（半径比 1.2–1.5）中跨片段的原子对，提醒可能存在弱键或配位。
   - 每个片段一份 XYZ：`<out 主名>.frag<N>.xyz`。注释行写明来源、片段序号、原始原子编号范围或列表。片段内的原子按原始编号升序排列，不重排、不平移、不旋转。
   - 所有输出都用独占方式创建，已存在就拒绝；限制在 study 的 `analyses/` 下，拒绝符号链接。
3. **不推断的内容（写进输出说明）：** 片段的电荷、多重度、身份，以及后续应该做分离物种计算还是复合物计算。报告里写：“片段电荷与多重度需人确认；片段电子能之和不是反应自由能”。
4. **只有一个片段时：** 照常报告，片段数为 1，不导出拆分文件（或只导出一份，二选一，在 PR 中说明）。

## 不允许

- 不改 facts、`irc-compare`、`topology` 的既有输出与行为。
- 不推断电荷、多重度，不自动准备 Attempt。
- 不使用研究数据或真实日志做测试；不连接集群。
- 不修改上述范围外文件。

## 测试

- 合成数据：两个分离的小分子（例如水加氟离子），片段数为 2，原子编号映射和分子式正确，导出的 XYZ 坐标与原始坐标逐行一致。
- 一个片段的情况。
- 不确定接触跨片段时，报告里出现提醒。
- 输出已存在、路径越界、符号链接：都拒绝，不留下部分文件。
- `topology` 的现有测试全部原样通过。
- 后端：`PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`；记录通过数和跳过原因。
- 暂存精确文件后运行敏感扫描与 `git diff --cached --check`。

## 真实环境验证

- 合并后由负责人另行安排：对 L3 的 IRC 端点（SN2 的产物侧是 CH₃F 和 Cl⁻，或者产物复合物）只读运行一次，核对片段数和原子编号。结果写在 PR 评论里，不含主机信息。

## 停止条件

- 复用 `_fragments` 必须改变它的行为：停下说明。
- 要改范围外文件。

## 合并前审阅与交付

- 需要监督方审阅：是（新命令）。不涉及 remote、submit、cancel、status、fetch。
- 修改 AGENTS.md：无。
- PR 描述第一行：`Task: T44`；写清改动、测试结果和参考的旧版文件。
- 用 `gh pr view <编号> --comments` 读取评论，逐条处理并回复；冲突本地 rebase；合并只由人操作。
- 研究 A 进入 IRC 阶段之前合并。

## 版本记录

- T116 脱敏：研究标识、编号与环境字面量改为泛称；原工单结构和结论不变。
