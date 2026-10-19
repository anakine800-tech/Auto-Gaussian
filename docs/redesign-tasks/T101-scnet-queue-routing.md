# T101：SCNet 队列分工、同集群共享核数、取消核时余额拦截

版本：v2（监督方，2026-10-19）。取代执行会话起草的 v1；v1 的背景与证据继续有效，本版按负责人 10-19 决定改写范围。**开发机做。**

## 分支与目标

- 分支：`codex/t101-scnet-queue-routing`；一个后端 PR，PR 描述第一行 `Task: T101`。
- **开工条件（开工时核对）：** 后端 main 为 `25155a1`（v4.3.0）或其后；T101 编号未被占用；没有与本单路径冲突的未合并 PR。
- **负责人 10-19 决定（本单依据，逐条落实）：**
  - D1 队列分工只管 **SCNet 内部选哪个队列**：CREST 优先 `scnet-test`（`wzhctest`）；Gaussian **只能** `scnet`（`wzacnormal`）。default（PBS）与 SCNet 之间如何选择不在本规则内，保持各 study 的既有安排。
  - D2 `wzhctest` 只能运行 CREST，不能运行 Gaussian。`wzhctest` 不可用时，CREST **不自动**改投 `wzacnormal`，由负责人逐次决定。
  - D3 取消核时余额拦截：预算核时与实际消耗不一致，不再因余额不足拒绝提交；只提示本次最大消耗（核数 × walltime）。
  - D4 同一实际集群的全部作业合计不超过配置上限，不能通过另一个队列入口绕过（AGENTS.md 第 3.9 条）；授权修改第 3.9 条使其明确覆盖多入口情况。
  - D5 并入下一轮修复第 1 项（监控核数上限显示）的**后端部分**；前端显示另行处理。
  - D6 不再管理到期限制：由本机配置删除 `expires`，本单不改到期相关代码。
- **资料：** `AGENTS.md`、`docs/DEVELOPING.md`、`docs/LESSONS.md`、T19/T50/T51 任务单；`config.py`、`budget.py`、`submit.py`、`attempt.py`、`monitor.py`、`render.py`；`skills-next/auto-g16-study/`。

## 背景（已核对的代码现状，main `25155a1`）

1. **远程统计已跨队列：** 提交时用 `squeue -u <用户>`，不带 `-p`，所以本人在所有 partition 的作业都已计入。
2. **本地预留按入口隔离：** `budget.unobserved_cores()` 只读所选入口的台账。入口 A 刚提交、squeue 尚未显示，或者 A 的结果为 UNKNOWN 时，紧接着经入口 B 提交会漏算 A。提交锁是配置目录级的（`<config_dir>/submit.lock`），两个入口本来就共用一把锁，但台账不共享。
3. **上限按入口各自判断：** 两个入口的 `max_committed_cores` 不同，就可能从上限较高的入口放行。
4. **核时余额拦截：** 只要配置写了 `resources.budget_core_hours`，`budget.check()` 就会在"已用 + 预留 + 本次"超过预算时拒绝；`reserve()` 在提交路径中调用它。
5. **Gaussian 无法靠"不配置程序"拦住：** `render.py` 对所有模板都会读取 `programs.gaussian.g16root`，所以 `scnet-test` 必须带 Gaussian 配置才能渲染任何模板。D2 需要一个显式的入口级模板白名单。
6. **监控显示：** `monitor.py` 的 `core_cap` 是单作业上限 `max_cores`，`committed_cap` 才是运行加排队上限。`sample()` 失败或初始快照只写了 `core_cap`、没有 `committed_cap`；前端在缺少 T51 三个字段时，会退回把 `core_cap` 当总上限显示。另一个可能原因：开发机本机配置仍是旧值（SCNet 32/32，default 可能还是 88）。两者都可能导致"显示 88/32"。
7. 2026-10-19 的正丁烷 CREST（`wzhctest`，8 核 17 s，COMPLETED，取回和解析通过）只作为队列可用的基线，不替代本单的合并前验证。

## 允许改动的路径

- `AGENTS.md`：**只改第 3 节第 9 条**，在末尾加一句（负责人 10-19 授权，原文见"要做的"第 1 节）。其余条款一字不改。
- `ag/src/ag/config.py`：派生同集群入口组；新增可选的入口级键 `allowed_templates`；`budget_core_hours` 改为接受但不再参与拦截。
- `ag/src/ag/budget.py`：跨同组入口汇总未观测预留；`check()` 不再因余额拒绝；摘要文字改为只显示本次最大消耗。
- `ag/src/ag/submit.py`：确认前和确认后两处核数检查都改用组内共享口径和有效上限；确认框显示目标入口与 partition。
- `ag/src/ag/attempt.py`：prepare 时执行 `allowed_templates` 检查；准备摘要显示入口、partition 和本次最大核时。不改 manifest 格式和已有 Attempt。
- `ag/src/ag/monitor.py`：所有快照路径都写出有效 `committed_cap`；同组入口加 `own.shared_with`；over-cap 告警用共享口径。
- `ag/tests/`：`test_slurm.py`、`test_mixed_clusters.py`、`test_clusters.py`、`test_monitor.py`，以及新文件 `test_shared_cluster_caps.py`。
- `skills-next/auto-g16-study/SKILL.md`、`references/study-md-template.md`、`references/confirmation-summary.md`；`skills-next/auto-g16-recipes/cards/crest-screen.md`；`skills-next/auto-g16-structures/references/conformer-workflow.md`：只写 D1/D2 的选择规则和显式 `--cluster` 示例。
- `skills-next/tests/test_card_consistency.py`：确有必要时才改。
- `ag/config.clusters.example.toml`、`README.md`、`docs/LESSONS.md`（加一条）：只用合成连接信息。
- `docs/redesign-tasks/T101-scnet-queue-routing.md`（本单）、`docs/redesign-tasks/open-tasks.txt`。

确需改动其他路径时，先停下申请。

## 要做的

### 1. AGENTS.md 第 3.9 条（负责人 10-19 授权）

在第 9 条末尾追加一句，原文如下：

> 同一实际集群（同一调度器、同一登录账号）配置多个队列入口时，视为同一集群合并统计：远程作业只计一次，各入口的本地预留全部计入，总上限取各入口 `max_committed_cores` 的最小值，不得通过另一个入口绕过。

PR 描述注明"负责人 2026-10-19 授权修改 AGENTS.md 第 3.9 条"。

### 2. 同集群共享核数（D4）

- **识别同组：** scheduler 相同、规范化后的 SSH 配置文件相同、SSH host 别名相同，三者都满足才算同一实际集群。partition、account、qos 不同不拆组。不凭名称猜测不同别名是否指向同一账号；配置里出现疑似情况时，在 doctor 中提示"未合并"，不自动合并。
- **核数口径：** 远程可见的本人作业只计一次（现有 squeue 查询已覆盖全部 partition）。另外加上组内**所有入口**台账中、远程还没有出现的 reserved / UNKNOWN 预留，在现有提交锁内读取。认领作业用各自的 manifest 与 submission/status，不只按作业号或目录名。批内还没读回的作业也要计入。
- **有效上限：** 总上限取组内各入口 `max_committed_cores` 的最小值；数值不一致时，摘要写明采用哪个值、涉及哪些入口。单作业上限仍按目标入口自己的 `max_cores`。确认前和确认后用同一规则。
- **台账不合并：** 各入口的 `budget-<cluster>` 台账照常各自结算，不迁移、不重写历史。组内某个入口的台账缺失或损坏时拒绝提交并给出可定位的错误；无关集群的台账损坏不影响本次检查。
- 不新增远程命令、远程写入或后台进程。

### 3. 取消核时余额拦截（D3）

- `check()` 不再抛错。配置里有 `budget_core_hours` 时，config 照常接受，但不参与任何拦截；doctor 提示一行"budget_core_hours 已不参与提交检查，可删除"。
- 准备摘要和确认框只显示：`本次最多消耗 X 核时（核数 × walltime；实际以平台计费为准）`。不再显示"预算 N 核时"或剩余额度。
- 本地台账保留，用于核数预留与结算，计算逻辑不变。`public_summary()` 不再输出预算额度：返回 `None`，或去掉 `core_hours` 字段，二选一，选哪种要在 PR 里说明，并确认前端读取空值不报错。
- PBS 行为不变。

### 4. 入口级模板白名单（D2）

- 新增可选键：`allowed_templates = ["crest", ...]`。不设置时允许全部模板，旧配置行为不变。
- prepare 时，模板不在目标入口的白名单里就拒绝，报错写明入口名与允许的模板。已经准备好的 Attempt 不受影响，不追溯检查。
- 部署时由负责人给 `scnet-test` 配置 CREST 所需的模板，具体模板名以代码为准，PR 里列出。独立 xTB 是否允许由负责人另定，本单默认不加入。
- 不靠删除 Gaussian 程序配置来实现拦截。

### 5. 研究 Skills 的队列选择（D1、D2）

- 只在"本次决定使用 SCNet"时适用：CREST 用 `--cluster scnet-test`，Gaussian 用 `--cluster scnet`。default 和 SCNet 之间的选择不由本规则决定，study 有既有安排的，按既有安排执行。
- `wzhctest` 不可用、无权限或额度满时，不自动改投 `scnet`；停下来报告原因，由负责人决定。
- 准备前读取本机配置，核对入口存在、partition 正确。不把队列名当 `--cluster` 别名，不改 CLI 的默认值，不在渲染器里硬编码队列名。
- 确认摘要写明实际入口与 partition。"赠送 / 正式专项"属于负责人核对过的使用说明，不代表实时余额；资金来源不明时写"未知"。

### 6. 监控核数上限（D5，下一轮第 1 项的后端部分）

- **先诊断，再动代码：** 在开发机记录三项——本机配置值、`latest.json` 中的 `core_cap` / `committed_cap`、前端实际显示。把"显示 88/32"的原因归为三类之一或几类：配置旧值、快照路径缺字段、前端回退逻辑。写进 PR。
- **后端修复：** 所有快照路径（含失败和初始快照）都写出 `committed_cap`，值为第 2 节的有效共享上限；`core_cap` 仍表示单作业上限，含义不变。同组入口的快照增加 `own.shared_with`（组内其他入口名），over-cap 告警用共享口径。`ag-monitor/1` 只做加字段，旧字段含义不变。
- 前端回退逻辑与同组作业去重显示**不在本单**，在 PR 里列为前端后续项。

## 不允许

- 不改第 3.9 条以外的 AGENTS.md 内容；不改已有 Attempt、manifest 语义、上传前后哈希核验、Mac 确认流程。
- 不自动提交、重提、取消、改投付费队列、扩容；不把一次临时额度授权当长期授权。
- 不改 PBS 的渲染字节和默认行为；不改 CLI 的 `--cluster` 默认值。
- 不改到期提示代码（D6 只做配置删除）；不改前端仓库。
- 不混入 CREST facts 元数据补全、账单抓取、新程序接入。
- 不提交真实主机、用户名、作业号、账号或订单号、绝对路径、余额、私人配置、研究数据。

## 测试

只用合成配置、临时 study 和假 Transport，不连真实集群。

| 场景 | 预期 |
|---|---|
| 同组两个入口；A 有 24 核预留未出现在 squeue；B 申请 16 核；有效上限 32 | 拒绝 |
| A 的作业已出现在 squeue | 只计一次 |
| A 为 UNKNOWN、未绑定作业号；B 新提交 | A 的预留计入，不归零 |
| 两次独立 `ag submit` 先后经 A、B，第一次后 squeue 未反映 | 第二次计入第一次 |
| 确认框打开期间远程占用变化 | 确认后的检查仍含远程加全组本地预留 |
| 同组上限 256 与 128 | 用 128，摘要说明 |
| 不同 host 别名或不同 SSH 配置文件 | 不合并；不串账；相同作业号不误去重 |
| 组内台账损坏 / 无关集群台账损坏 | 前者拒绝；后者不影响 |
| 配置含 `budget_core_hours` 且已用 + 本次超过预算 | 不拒绝；摘要只显示本次最大核时；doctor 提示可删除 |
| 无 `budget_core_hours` | 行为与现在一致（不检查） |
| `scnet-test` 设 `allowed_templates` 不含 Gaussian，prepare Gaussian | 拒绝，报错含入口名 |
| 同一入口 prepare CREST | 通过 |
| 未设 `allowed_templates` | 所有模板照旧 |
| 已有 Attempt 在新代码下 status/fetch | 绑定、脚本、哈希不变 |
| monitor 失败快照 | 含 `committed_cap` |
| 同组两个入口的 monitor 快照 | 都含 `shared_with`，`committed_cap` 为有效上限 |
| 只有 PBS 配置 | 渲染字节与 monitor 字段不变 |

开发中只跑相关测试；推送前本地跑一次全量 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，记录通过数和跳过原因，之后以 CI 为准。只暂存本单文件；运行 `python ag/tools/scan_sensitive.py --staged` 与 `git diff --cached --check`。

## 真实环境验证（合并前，开发机，非研究体系）

**前置（负责人或经负责人授权的开发机 Codex 做本机配置，不进 PR；先备份）：**
- `scnet`、`scnet-test` 两个入口都改为 `max_cores = 64`、`max_committed_cores = 256`（D4，符合第 3.9 条的 4 倍约束）；default 核对为 44/132。
- 删除两个 SCNet 入口的 `expires`（D6）。
- `budget_core_hours` **验证完成后再删除**，以便验证"有预算字段也不拦截"。
- 给 `scnet-test` 配置 `allowed_templates`。
- 开工前先只读汇报三个入口的上述字段，以及 `scnet` / `scnet-test` 是否同 SSH 配置文件、同 host 别名（只答是 / 否）。

**步骤：**
1. 用分支提交号建临时 worktree 和独立的正丁烷 study，不使用 HSS 或其他未发表研究。
2. 第 6 节的监控诊断，结果写进 PR。
3. 在 `scnet-test` prepare 一个 Gaussian 水分子单点：应被拒绝。在 `scnet` 上同样 prepare：应通过，摘要显示 `wzacnormal` 和本次最大核时，**不提交**。
4. 在 `scnet-test` prepare 正丁烷 CREST 快速初筛（8 核 / 12 GB / 30 min），摘要和确认框显示 `wzhctest`、有效共享上限、组内占用。负责人亲手确认后**只提交一次**；核对 status、fetch 哈希、facts、构象数、台账结算。
5. 账号上若有其他作业（包括 HSS 作业），只记录被计入的核数，不读取、不操作这些作业。
6. 跨入口漏算、UNKNOWN、并发等边界由合成回归覆盖；真实验证只报告实际观察到的范围。
7. 验证结束后删除 `budget_core_hours`，读回配置确认。

异常（SSH 错误、UNKNOWN、哈希不一致、作业异常）按 AGENTS.md 第 5 节停下报告，不重试。

## 停止条件

- 需要改动范围外的文件，或者需要改第 3.9 条以外的 AGENTS.md 内容。
- 同组识别无法从配置明确判断，而需求要求跨不同别名合并。
- 需要迁移旧台账、改已有 Attempt、放松哈希或确认规则。
- 前端读到空的 `budget` 会出错，且后端无法保持兼容。
- 同一问题修两次仍未解决。

## 合并前审阅与交付

- 需要监督方审阅：**是**（涉及 submit 核数语义和 AGENTS.md）。
- 合并只由负责人操作。修改 AGENTS.md 已获负责人 10-19 授权。
- PR 描述：D1–D6 逐条对应的改动；监控诊断结论；兼容性（PBS、旧配置、已有 Attempt）；全量测试结果；真实验证提交号与范围；前端后续项。
- 用 `gh pr view <编号> --comments` 读取 `<!-- ag-review head=... -->` 评论，逐条处理。
- **合并后（负责人安排）：** 开发机同步 main；HSS 计算机的同步时间由负责人定，同步前确认没有进行中的提交、取回或 reparse；HSS 计算机的 SCNet 配置按需同样删除 `budget_core_hours` 和 `expires`（只改配置，不动已有 Attempt）。不要求为本单单独发版。
- 工程完成不等于任何科学结果的验收。

## 版本记录

- v1（2026-10-19，执行会话）：队列分工、跨入口核数预留、到期核对的初稿。
- v2（2026-10-19，监督方）：按负责人 10-19 决定 D1–D6 改写——限定只管 SCNet 内部队列；`wzhctest` 只跑 CREST，用 `allowed_templates` 强制；取消核时余额拦截；并入监控上限显示的后端部分；到期改为删除配置、不改代码；授权补充 AGENTS.md 第 3.9 条。

### v2 补充：范围扩展（监督方 2026-10-19 批准，负责人在执行会话转达）

允许修改 `ag/src/ag/doctor.py`，只增加两项提示：配置含 `budget_core_hours` 时提示可删除；scheduler 相同而 SSH 配置文件或 host 别名不同的入口提示“未合并”，列出入口名。
不改 doctor 的 ok 判定、退出码及现有字段含义，不输出主机、用户名、路径；测试放在 `ag/tests/test_shared_cluster_caps.py`。PR 注明该范围扩展。

监督方 2026-10-19 批准的范围扩展（空台账初始化、旧预算文案测试）：

- 只有台账文件不存在，且本机全部 studies 中没有绑定到该入口的提交痕迹（`.submit-claim`、`submission.json`、submitted 及以后的状态）时，才按空台账处理。文件损坏或读不出、文件不存在但有提交痕迹，仍拒绝。其他入口只在内存中按零处理，不写文件；目标入口继续由现有 `reserve()` 创建。
- 允许修改 `ag/tests/test_caps.py`，仅把一处旧预算文案断言换成“本次最多消耗 X 核时”，不删除测试、不放宽其他断言。
- 补充缺失且无痕迹、缺失但有痕迹、损坏三类回归；完整测试后开 PR。

监督方 2026-10-19 批准的范围扩展（test_parent_chk.py 夹具）：只给三个 Slurm 参数场景共用的 `bound_slurm_parent()` 补上预留与结算的 4 行，保留全部断言。T16 同时引入 Slurm 与台账；正常提交始终先 reserve 再 sbatch，夹具须符合此流程。PBS 继续使用现有 submitted 补计，不要求台账。

同日缺账处理决定：迁移 study 未带台账、切换配置目录、台账丢失仍拒绝，不自动重建、不当作零、不新增恢复命令。错误定位到入口并提示“从备份或原配置目录找回该入口的台账；找不到则停止并交给负责人核对”，不输出路径、主机或用户名。`docs/LESSONS.md` 追加迁移时必须携带各 Slurm 台账的经验。

## 实现与验证记录

- D1/D2：Skills 限定 SCNet 内部选择；配置 `allowed_templates = ["crest"]` 即覆盖普通 CREST、约束 CREST 和 mdopt，不默认开放独立 `xtb`。白名单只在 prepare 入口检查，已有 Attempt 不追溯。
- D3：`check()` 不再检查余额；`public_summary()` 选择返回 `None`，clusters 省略 budget，Slurm 快照写 null（旧缓存中的预算也清除）。台账预留/结算算法与分入口文件保留。实际前端 `validate_monitor` 已离线验证 null、缺字段及 shared_with 可读取；页面按 null 条件隐藏预算区域。
- D4：同 scheduler、规范化 SSH 配置文件、同 host 别名合组；partition/account/qos 不拆组。提交锁内两处读取全组台账、采用最小总上限；当前 Attempt 排除于重复计数，批内先前作业及未绑定作业号的 UNKNOWN 保留预留。作业关联核对 manifest、submission/status、bundle 和完整调度作业名。
- D5 开工诊断（2026-10-19）：本机 default 配置 44/88，两个 SCNet 入口 32/32；scnet 与 scnet-test 同 SSH 文件、同 host 别名。已成功的 latest 快照分别含 core_cap/committed_cap 44/88、32/32，测试入口暂无快照。实际前端显示总上限 88/32，与配置及成功快照一致，现场直接原因归为**配置旧值**。代码另确认失败/初始快照缺 committed_cap，前端缺完整 T51 三字段时回退 core_cap；这是另外两项潜在原因，不能写成当次成功快照的实际触发原因。
- D5 修复：所有快照路径写当前有效 committed_cap，保留 core_cap 单作业语义；同组增加 shared_with，over-cap 告警另计全组未观测预留，原远程运行/排队字段含义不变。前端回退逻辑与同组作业去重是后续项。
- D6：到期相关代码未修改。本机配置草稿已准备；实际配置变更、正丁烷单次提交及验证后删除 budget_core_hours 尚未执行，不以离线结果冒充合并前真实验证。

离线验证（2026-10-19，Python 3.11.15）：相关回归 202 passed；全量首轮 4038 passed、19 skipped、3 failed（324.64 s）。跳过包括 18 个 Linux GNU stat/procfs 专用测试和 1 个未启用的私人日志测试。三个失败均来自 `test_parent_chk.py` 同一父 Attempt 夹具：有 submission.json 与 finished 状态却没有台账，被本次缺失台账规则拒绝。

批准的夹具修复与缺账提示完成后：相关回归 288 passed（16.79 s）；全量 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs` 为 **4044 passed、19 skipped、0 failed**（287.57 s，退出码 0）。跳过原因同上；额外 `PYTEST_ADDOPTS` 仅指定仓库外缓存目录，不改变测试选择。敏感信息扫描与暂存差异检查通过。

本机 Slurm 台账只读核对（2026-10-19）：是；缺失入口：无。

当前阻塞：提交——合并前小分子真实验证尚待完整摘要确认与 Mac 人工点击。全部文件范围扩展均已获批；监督方尚未审阅本分支。
