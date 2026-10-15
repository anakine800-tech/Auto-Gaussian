# T38：优化前后成键与立体比对命令 `ag topology`

## 分支与目标

- 分支：`codex/t38-topology-check`；基于最新 main，一张任务单一个 PR。
- 目标：新增本地只读命令 `ag topology`，比对一个已取回 Attempt 的提交几何与最终几何，报告成键、断键、质子位置和立体中心的变化。它只报告，不阻止任何操作，也不修改 facts、manifest 或 review。opt-freq 卡片的人工比对步骤改为“运行 `ag topology` 并审阅其输出”。
- 资料：
  - `ag/src/ag/irc_compare.py:63–165`：`_pairs`（按共价半径比值分为相连、不确定、分离三档）、`compare_endpoint`（成键差异、不确定键、质子差异、立体差异，判不出时报 UNKNOWN）；
  - `ag/src/ag/geometry.py:89–105`：`infer_molecule`、`graph_key`、`stereo_key`；
  - `ag/src/ag/facts.py:70–116`：取回后写出 `final.xyz`、`final_input.xyz`；
  - `skills-next/auto-g16-recipes/cards/opt-freq.md:103`：目前要求人工比对，并注明 `ag graph` 不做结构比对；
  - 相关已合并 PR：#226（IRC 端点比较）、#240（final_input.xyz）。
- 防的事故：优化过程中发生质子迁移、配位转移、成环/开环或立体翻转（含硼、两性离子等电荷分离体系尤其容易出现），而结构仍被当作原构象计入系综或剖面。现在只能人工逐项比对，容易漏看。构象去重已经会拒绝立体变化的帧（`dedup.py:27`），但 Gaussian 优化结果还没有同样的检查。

## 允许改动的路径

- `ag/src/ag/topology.py`：新模块（命令实现）。
- `ag/src/ag/irc_compare.py`：只允许把 `_pairs`、`compare_endpoint` 等可复用部分移到共享位置，或改成可被 topology 调用；行为与输出一字不变，现有测试不改。
- `ag/src/ag/geometry.py`：如需放置共享函数。
- `ag/src/ag/cli.py`：只在第 153 行的本地工具元组中加入 `'topology'`。
- `ag/tests/test_topology.py`（新增）及 `ag/tests/fixtures/` 下的合成小分子文件。
- `skills-next/auto-g16-recipes/cards/opt-freq.md`：只改第 103 行所在条目。
- `README.md`：命令表加一行。
- `docs/DEVELOPING.md`：模块地图加一行。
- `docs/redesign-tasks/T38-topology-check.md`：本任务单。

## 要做的

1. **命令形式：** `ag topology <attempt> --study <dir> --out <analyses/新文件.json> [--pair i-j ...] [--json]`。
   - `<attempt>` 接受 Attempt ID 或目录，解析方式与 `irc-compare` 一致。
   - `--out` 已存在就拒绝；同时在同名位置写一份 `.md` 摘要，同样独占创建。
   - 原子编号一律从 1 开始（与 Gaussian 一致），并在输出里写明。
2. **几何来源：**
   - 提交几何取 manifest 中记录的输入坐标；最终几何取 `final_input.xyz`（同一取向、同一原子顺序）。
   - 缺少 `final_input.xyz` 时，退回用 `final.xyz`，并在输出里注明取向不同（不影响拓扑判断）。
   - 原子数或元素顺序不一致时，报 UNKNOWN，不做重排。
   - 电荷取 manifest 记录的值。
3. **极小点模式：**
   - 复用 `compare_endpoint` 的判定，输出 `status`（unchanged / changed / unknown）、`bond_differences`、`ambiguous_bonds`、`proton_differences`、`stereo_differences`。
   - 另外按元素列出 B、N、O 与其他原子之间处于“不确定”区间（共价半径比值 1.2–1.5）的接触，提交几何和最终几何各一份，用于审阅配位变化。
   - RDKit 无法给出键级或立体时，相应项报 UNKNOWN 并写明原因，不猜。
4. **TS 模式：**
   - facts 显示恰好一个虚频，且 route 含 `Opt=TS` 或 QST 时，不给出“相连”结论。
   - 只对 `--pair` 指定的原子对报告提交与最终几何中的距离及变化。没有给 `--pair` 时报 UNKNOWN，并提示需要声明成键或断键原子对。
5. **输出：** 每份报告写明 ag 版本与提交号、所用几何文件及其 SHA-256、判定阈值，以及这样一句话：“结构比较不代替科学审阅”。
6. **opt-freq 卡片第 103 行：** 改为先运行 `ag topology`，在 review.md 里引用它的输出，人工审阅 changed/unknown 项；原有的“结构改变时不能计入原构象集合”的规则保留。

## 不允许

- 不改 facts、thermo、profile、dedup 的既有输出与数值；不改 `irc-compare` 的输出。
- 不把结果接入 `review check` 作为强制项，也不阻止任何命令。
- 不修改上述范围外文件；不连接集群；不使用研究数据或真实日志做测试。
- 不推断“键级变化是否合理”这类科学结论。

## 测试

- 合成小分子（手工构造坐标，不用研究数据），每一类各一个正例：
  - 无变化：几何轻微扰动，期望 unchanged；
  - 质子迁移：如羧酸 O–H 的 H 移到另一个 O，期望 changed，并列出质子差异；
  - 断键或成键：期望 changed；
  - B–O 配位：距离从远到近，期望在不确定接触或成键差异中出现，判不出时报 UNKNOWN；
  - 立体翻转：期望 stereo_differences；
  - 原子数不一致：期望 UNKNOWN；
  - TS 模式：有 `--pair` 时报告距离，没有时报 UNKNOWN。
- `--out` 已存在时拒绝；`.md` 与 `.json` 都是独占创建。
- 现有 `irc-compare` 测试全部原样通过。
- 后端：`PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`；记录通过数和跳过原因（RDKit 不可用的环境如实报告跳过）。
- 暂存精确文件后运行敏感扫描与 `git diff --cached --check`，人工核对 PR 文本和 Git 身份。

## 真实环境验证

- 合并后由负责人另行安排：在计算机上用 L2、L3 已有的 Attempt 只读运行，不提交作业。结果写在 PR 评论里，不含主机信息。

## 停止条件

- 复用 `compare_endpoint` 需要改变它的行为或输出：停下说明。
- 要改范围外文件；同一问题修两次仍未解决。

## 合并前审阅与交付

- 需要监督方审阅：是（新命令、卡片修改）。不涉及 remote、submit、cancel、status、fetch。
- 修改 AGENTS.md：无。
- PR 描述第一行：`Task: T38`；写改动、测试结果、复用了哪些既有函数。
- 用 `gh pr view <编号> --comments` 读取评论，逐条处理并回复；冲突本地 rebase；合并只由人操作。
- 与 T37 共用 `cli.py`、`README.md`（不同行），后合并者 rebase。
