# T47：只读取回被强杀作业的已有输出，并允许从中断作业复用 chk

## 分支与目标

- 分支：`codex/t47-incomplete-fetch`；基于最新 main，一张任务单一个 PR。
- 期限：必须在 HSS 第一批 TS 提交前合并（预计 3 天内）。
- **防的事故（已真实发生，或即将发生）：**
  1. **PBS 被 walltime 强杀。** `_guard.sh` 只在程序自行退出时写 `ag-exit.json`。作业被强杀后没有这份回执，`status` 判为 `interrupted`，而 `fetch` 只接受 `finished`（`fetch.py:27`），`parent_chk` 只接受 `finished/fetched`（`parent_chk.py:13`）。结果是日志、chk 和中间几何都留在服务器上取不回来，也无法接续。RCFC 验证中已经遇到这个缺口。
  2. **Slurm TIMEOUT。** sacct 给出终态后，状态会写成 `finished`（`status.py` 的 `check_slurm`）。但 `fetch` 要求全部声明的输出都存在：被杀的作业缺少 `ag-exit.json` 或最终产物，取回在核对元数据时就失败。
  3. HSS 马上要跑长 CREST，之后是 84 个原子左右的 TS 优化。MaxCycles 已证实不能保证不超 walltime，一旦被杀就丢掉几十个核时的结果。
- **目标：**
  - 对已确认结束、但不完整的作业，提供显式的“不完整取回”：只读下载服务器上实际存在的声明输出，记录缺失项，结果明确标为不完整；
  - 允许从这类作业复用 chk 给新的 Attempt（沿用现有的专用复制操作）；
  - facts 能识别 PBS 和 Slurm 两种 walltime 终止。
- **不变的东西：** AGENTS.md 硬内核全部不变。不自动重提；不在服务器上删除、覆盖或截断任何文件；每个 Attempt 只提交一次；接续必须新建 Attempt，并经人在 Mac 上确认后提交。

## 允许改动的路径

- `ag/src/ag/fetch.py`：新增不完整取回。
- `ag/src/ag/parent_chk.py`：放宽父作业状态的检查，只限下文规定的条件。
- `ag/src/ag/status.py`：只在“结束证据”门槛需要复用或补充观察时改动，并在 PR 中说明。
- `ag/src/ag/_parse_outputs.py`、`ag/src/ag/facts.py`：只改 walltime 识别（加入 Slurm 的 `DUE TO TIME LIMIT`，Slurm 读 `job.slurm.err`／`job.slurm.out`），以及不完整输出下的 facts 来源标注。
- `ag/src/ag/cli.py`：只在 fetch 选项注册需要时改动。
- `ag/tests/` 下的 fetch、parent_chk、status、facts 相关测试，以及新增的 `test_incomplete_fetch.py`；`ag/tests/test_smoke.py`、`ag/tests/test_review.py` 仅在受影响时同步（在 PR 中说明）。
- `README.md`（命令表）、`docs/DEVELOPING.md`（状态表、模块地图）、`docs/LESSONS.md`（新增一条：walltime 强杀与不完整取回）。
- `skills-next/auto-g16-recipes/cards/failure-diagnosis.md`：补“作业被强杀”的处理步骤；`skills-next/auto-g16-recipes/cards/ts.md`：只在第 7 节补一句，指向接续做法。
- `docs/redesign-tasks/T47-incomplete-fetch.md`：本任务单。

## 要做的

### 负责人批准的范围扩展（2026-10-15）

工单漏项：原只读观察的 `test ! -e` 会把无法进入父目录误报为文件不存在，已用本地合成文件和目录权限 000 复现。
负责人批准增加 `ag/src/ag/remote.py` 和 `ag/tests/test_core.py`（仅白名单测试）。
只新增供 `fetch --incomplete` 使用的只读命令构造函数，复用 `path_checks`/`quote`，仅处理声明文件、拒绝符号链接；不改 `output_observation` 等现有函数。
父目录存在且可进入才可确认不存在；存在文件必须可读并返回大小/mtime；权限、命令或 SSH 失败均无法核实并拒绝整次发布。
白名单测试断言完整命令文本和坏参数拒绝；功能测试包含目录权限 000。PR 描述记录本次批准及工单漏项。

1. **只有结束证据充分才能取回**，以下全部满足：
   - **PBS：** 当前状态为 `interrupted`，并且至少两次 `ag status` 观察（间隔不少于 5 分钟）都显示作业不在活跃队列（不在 Q、R、E 状态，或调度器给出完成记录）；两次之间 `output_observation` 的大小和 mtime 完全一致；没有 `ag-exit.json`。优先复用现有的 `awaiting_second_observation` 机制。
   - **Slurm：** sacct 给出终态（TIMEOUT、CANCELLED、FAILED、OUT_OF_MEMORY、NODE_FAIL，或 COMPLETED 但缺少声明的输出），并且活跃队列里没有这个作业。
   - `unknown`、`submitting`、`running`、`submitted`、`stalled` 一律拒绝。`cancelled` 是否允许，由 Codex 判断并在 PR 中说明理由；默认拒绝。
2. **显式调用：** `ag fetch <attempt> --incomplete`。不加这个选项时，现有行为完全不变。这个选项只用于只读下载，不涉及提交或取消，不违反硬内核第 4 条。
3. **下载规则：**
   - 只处理 `remote.output_names()` 声明的文件，不遍历目录、不用通配符；可以额外加入 manifest 绑定的 chk 名，用于记录它的哈希，但不默认下载 chk。
   - 每个文件下载前后都核对大小和 SHA-256。存在的照常下载，不存在的记为缺失，并区分“确认不存在”和“无法核实”。“无法核实”（SSH 失败、权限问题）时整个操作失败，不能当作缺失。
   - 本地输出独占创建，不覆盖已有文件。另外独占写一份记录 `fetch-incomplete-<UTC 时间>.json`，内容包括存在的文件及其哈希、缺失项、结束证据（两次观察的时间和调度器状态，或 sacct 行）、ag 版本。
   - 中途出错时，保留已暂存的证据，不发布任何文件，和现有的 `.partial` 做法一致。
4. **状态：** 首选不新增生命周期状态，保持 `interrupted` 或 `finished` 不变，用记录文件标识“已不完整取回”。如果 Codex 认为必须新增状态，先写清楚它防哪个事故，并列出 monitor、cancel、前端等所有受影响的地方，交监督方决定，不要直接实现。
   - 不完整取回后，普通 `ag fetch` 必须拒绝（文件已存在），`--add-missing` 的行为也要定义清楚并测试。
5. **facts：**
   - 对不完整输出照常运行 `ag facts`。`termination` 应为 `incomplete`（或在有错误时为 `error`）。
   - PBS 的 `walltime ... exceeded limit` 和 Slurm 的 `DUE TO TIME LIMIT` 都要识别为 `error_hint=walltime`。
   - 最后一个几何结构和 `final_input.xyz` 照现有规则导出，`opt_converged` 不能被推成 true。
   - 下游工具必须把它当作未完成：`thermo` 和 `profile` 照现有规则拒绝，因为 termination 不是 normal。请补测试证明。
6. **复用父 chk：** `parent_chk` 额外接受“已有不完整取回记录”的 Attempt。其他检查全部保留：同一集群、Gaussian 模板、manifest 绑定的 chk 名、复制前后的哈希、独占创建、父文件只读。
   - chk 在被杀那一刻可能只写了一半，接续能不能读，要靠真实验证说明。工具只负责安全复制，不保证 chk 可用。
   - 取向规则沿用 #240：坐标用 `final_input.xyz`。
7. **卡片：**
   - failure-diagnosis 卡片补“作业被强杀”一节：先看 status 的证据，再 `fetch --incomplete`，再 facts，然后由人决定是从中断处接续（新 Attempt，RCFC 或从最后几何重新开始），还是延长 walltime 重来。
   - ts 卡片第 7 节加一句指向这一节。

## 不允许

- 不改提交、取消、预算、核数检查，也不改 `_guard.sh` 和模板。不在服务器上写任何文件；chk 复制仍走现有的专用操作，目标是新的 Attempt 目录。
- 不自动接续、不自动重提，也不提供跳过结束证据门槛的选项。
- 不放宽 `unknown` 的处理。
- 不修改上述范围外的文件；不使用研究数据或真实日志做测试。

## 测试

- PBS：只有一次观察、两次观察之间输出有变化、作业仍在 Q 或 R、存在 `ag-exit.json`、状态为 unknown：全部拒绝。证据充分时只下载存在的文件，并正确记录缺失项。
- Slurm：TIMEOUT 加缺失输出时允许；仍在 squeue 中时拒绝；COMPLETED 且输出齐全时，`--incomplete` 应提示改用普通 fetch。
- 下载中途远程文件变化、哈希不一致、SSH 失败：整体失败，不发布任何文件，保留暂存证据。
- 无法核实与确认不存在分开报告。
- 重复执行 `--incomplete` 时拒绝，不覆盖已有输出和记录。
- facts：PBS 和 Slurm 两种 walltime 文本都识别为 walltime；不完整的 Opt 日志 `opt_converged` 不为 true；thermo 和 profile 拒绝。
- parent_chk：有记录才允许，没有记录的 interrupted 仍然拒绝，跨集群拒绝。
- 不加 `--incomplete` 时，现有 fetch 测试全部原样通过。
- 后端：`PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`；记录通过数和跳过原因。
- 暂存精确文件后运行敏感扫描与 `git diff --cached --check`。

## 真实环境验证（合并前，在计算机上；每个作业提交前都由负责人在 Mac 上确认）

### 负责人补充的执行分工和前置条件（2026-10-15）

开发机仅做离线开发和 PR，停用默认集群配置；不连接集群、不读取计算机上的 study。以下作业全部由计算机上的验证会话提交。
等待对象是 OPS-3 作业 1 和作业 3；作业 2 的 RCFC 路径已判定不适用于该无 Freq 的中断优化，不重跑，不当作环境故障。
负责人在计算机上确认：作业 1/3 均为 finished 或 fetched，无 submitted/running/unknown 作业；OPS-3 报告已写好，作业 3 的通过或不通过结论明确。
作业 3 验证 final_input.xyz 几何加父 chk 波函数的 Guess=Read 接续；若未通过，T47 第 2 项的验收标准先与负责人核对。
HSS 可以同时运行，核数由 ag 按集群核验；为避免两个会话同时提交，T47 验证安排在 HSS 两次提交之间。离线开发和 PR 不等待以上条件。

用一个专门的验证 study，最多 3 个作业：

1. **PBS 强杀：** 在组里集群提交一个小分子 Gaussian 优化，预计耗时远超 walltime（例如 walltime 5 分钟，作业设计成每步就要数分钟，由 Codex 提出方案并估算），必须能在被杀前写出至少一个优化步的几何和 chk。被杀后：
   - 两次 `ag status` 判为 interrupted，满足证据门槛；
   - `fetch --incomplete` 成功，记录正确；
   - facts 的 error_hint 为 walltime，`final_input.xyz` 已导出。
2. **从中断作业接续：** 用第 1 步的 chk 和 `final_input.xyz` 新建 Attempt，走 `Guess=Read Opt=(TS,CalcFC) Freq` 的波函数接续路线（具体结构、方法和完整输入在计算机上由负责人确认），正常 walltime。不能把无 Freq 中断优化的 RCFC 当作此项验收路径。验证复制操作的哈希一致，并记录 chk 能否被 Gaussian 读入。读不了要如实报告；若 OPS-3 作业 3 未通过，先与负责人核对验收标准。
3. **Slurm TIMEOUT：** 在 SCNet 上用 `--time 00:05:00` 提交一个必定超时的小作业。sacct 给出 TIMEOUT 后 `fetch --incomplete` 成功，facts 识别 walltime。

结果写进 PR 描述，不写主机、账户和路径。出现 UNKNOWN、哈希不一致或 SSH 报错时，立即停下报告。

## 停止条件

- 需要新增生命周期状态，或需要改动 `_guard.sh`、模板、提交或取消逻辑：先停下说明。
- 证据门槛无法在不改 status 核心判定的前提下实现：停下说明方案。
- 真实环境出现任何意外；同一问题修了两次仍未解决；需要改范围外的文件。

## 合并前审阅与交付

- 需要监督方审阅：是。贴近硬内核第 1–3 条，从严审。
- 修改 AGENTS.md：无。
- PR 描述第一行：`Task: T47`。写清证据门槛、下载与记录规则、状态的处理方式、真实验证结果，以及“防的事故”一节。
- 用 `gh pr view <编号> --comments` 读取评论，逐条处理并回复；冲突本地 rebase；合并只由人操作。
