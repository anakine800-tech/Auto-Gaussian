# T51：按“运行加排队”统计核数上限，取消硬件核验；SSH 调用写本地日志

## 分支与目标

- 分支：`codex/t51-queue-caps-ssh-log`；基于最新 main（含 #268、#269），一张任务单一个 PR。
- **目标一：核数上限。** 负责人 2026-10-16 决定：
  - 组里集群（PBS）：运行加排队 ≤ 132 核，单作业 ≤ 44 核。
  - SCNet（Slurm）：运行加排队 ≤ 256 核，单作业 ≤ 64 核。
  - **ag 不再限制运行中的核数。** ag 只能在提交那一刻检查，作业何时开始运行由调度器决定。集群空闲时，运行中的核数可能达到运行加排队的上限，负责人已接受这一点。
  - 统计范围不变：该用户在该集群上的**全部**作业，包括另一台电脑、手动或非 ag 提交的作业，挂起和等待的作业都计入排队。
- **目标二：SSH 日志。** 2026-10-15 19:48，组里集群出现一次原因不明的“SSH 连接被拒绝”。排队量提高后，SSH 调用会变多。每次 ssh/scp 调用都在本机追加一行结构化日志，以后能按时间和错误类别排查。
- **要防的事故：**
  1. 现在的 PBS 严格模式要求“集群总核数 ≤ max_cores”才放宽排队。组里集群总核数大于 44，于是 `max_committed_cores` 永远不生效，HSS 的 8 个单点（64 核）和 6 个 TS（132 核）都排不上。
  2. Slurm 要求 `max_committed_cores ≤ max_cores`，要排到 256 核就只能把单作业上限也放到 256。
- 资料：`ag/src/ag/submit.py`（`capacity`、`submit`）、`ag/src/ag/config.py`（第 87–100 行校验）、`ag/src/ag/monitor.py`（第 113、264 行）、`ag/src/ag/transport.py`（`_execute`、`_perform`）、AGENTS.md 硬内核第 9 条。

## 新的配置含义

| 字段 | 含义 | 取值范围 |
|---|---|---|
| `resources.max_cores` | 单个作业及各档位的核数上限 | PBS 1–44；Slurm ≥ 1 |
| `resources.max_committed_cores` | 本人在该集群运行加排队的总核数上限 | 两种调度器都是 `max_cores` ≤ 值 ≤ `4 × max_cores`；省略时等于 `max_cores` |
| `resources.budget_core_hours` | 不变：可选，省略时不做核时预算检查 | 不变 |

负责人会在本机配置里写：组里集群 `max_cores = 44`、`max_committed_cores = 132`；SCNet `max_cores = 64`、`max_committed_cores = 256`。示例配置只用占位符，不写这些值。

## 允许改动的路径

- `ag/src/ag/config.py`：按上表修改 `max_committed_cores` 的校验（Slurm 也允许大于 `max_cores`）；档位核数校验改为不超过 `max_cores`（PBS 仍不超过 44）。
- `ag/src/ag/submit.py`：删除 `capacity()` 的硬件核验和严格模式，上限一律用 `max_committed_cores`；删除提交时的 `pbsnodes` 调用；改确认文本。
- `ag/src/ag/monitor.py`：PBS 和 Slurm 快照里 `committed_cap` 都取 `max_committed_cores`，`over-cap` 警告按它判断；`core_cap` 保留为 `max_cores`。PBS 快照仍读取节点（监控显示需要），但不再参与上限判断。
- `ag/src/ag/clusters.py`、`ag/src/ag/doctor.py`：输出里增加 `max_committed_cores`。
- `ag/src/ag/transport.py`：SSH 日志（见“要做的”第 4 条）。
- `ag/src/ag/pbs.py`：只在 `parse_nodes` 不再被 submit 使用时，更新模块文档字符串一行；逻辑不改。
- `ag/config.clusters.example.toml`、`ag/config.example.toml`：注释改为新含义，占位符不变。
- `ag/tests/test_queue.py`、`test_clusters.py`、`test_core.py`、`test_monitor.py`、`test_slurm.py`：修改与上限、严格模式、`pbsnodes` 假响应相关的断言。
- 新增 `ag/tests/test_caps.py`、`ag/tests/test_ssh_log.py`。
- 其他测试文件中**仅因**提交时不再调用 `pbsnodes` 而需要删除的假响应行：允许改，但要在 PR 描述里逐个列出文件和原因。
- `AGENTS.md`：只改硬内核第 9 条，文本见附录。**负责人已于 2026-10-16 批准方向，措辞以 PR 审阅为准。**
- `README.md`（第 52 行、已知限制里 PBS 数组作业号那一条）、`ag/README.md`（资源与上限一节、doctor 输出字段）、`docs/DEVELOPING.md`（第 64–65 行）、`skills-next/auto-g16-study/references/confirmation-summary.md`（第 16 行）：改为新的含义。
- `docs/LESSONS.md`：新增一条。
- `docs/redesign-tasks/T51-queue-caps-ssh-log.md`：本任务单。

## 要做的

1. **上限判断（PBS、Slurm 相同）：**
   - 单个作业核数 > `max_cores` 时拒绝。
   - 已占用（运行 + 排队，含挂起；Slurm 另加本地台账中已预留但调度器尚未显示的核数）加本批申请的核数 > `max_committed_cores` 时拒绝。
   - 确认期间每个作业提交前的重新检查（`fresh_used`）保留，上限同样用 `max_committed_cores`。
   - 不再有“严格模式”：`pbsnodes` 读不到、集群总核数多少、数组作业号能否解析，都不影响上限。
2. **确认文本**（终端和 Mac 确认框相同）：
   ```
   当前占用 N 核（运行 R、排队 Q；按集群上本人全部作业统计，含其他电脑和非 ag 提交的作业），
   提交后合计 T / 上限 C 核。
   ag 不限制运行中的核数：集群空闲时，排队作业可能同时运行，最多 T 核。
   ```
   Slurm 的核时一行保持不变（未设预算时显示“未设置”）。
3. **Slurm 预算：** 不改 `budget.py`。省略 `budget_core_hours` 时不做预算检查（现在已经这样），台账照常记录。
4. **SSH 日志：**
   - 每次 ssh 或 scp 调用（含重试的那一次）结束后，向 `<配置文件所在目录>/ssh-log/<集群名>-<YYYY-MM>.jsonl` 追加一行。
   - 字段只有：`at`（UTC ISO 时间）、`cluster`（配置里的集群名）、`tool`（`ssh` / `scp`）、`operation`（`remote.Command.operation`，上传、下载写 `upload` / `download`）、`attempt`（1 或 2）、`outcome`（`ok` / `exit` / `timeout` / `start_failed`）、`returncode`（整数或 null）、`duration_s`（保留 3 位小数）、`error_class`。
   - `error_class` 从**已脱敏**的 stderr 归类，只写类别，不写 stderr 原文：`none`、`connection_refused`、`connection_timeout`、`connection_reset`、`permission_denied`、`host_key`、`operation_not_permitted`、`name_resolution`、`network_unreachable`、`other`。
   - 不写主机名、用户名、路径、命令文本或参数。
   - 文件用 `O_APPEND | O_NOFOLLOW` 打开，权限 0600；目录或文件是符号链接就不写。
   - 写日志失败（任何 OSError）**绝不影响**正在进行的操作：打印一行警告，继续执行。
   - 不自动删除旧文件。
5. **monitor 与 doctor：** 快照仍为 `ag-monitor/1`，字段名不变（前端已支持 `cores_running`、`cores_queued`、`committed_cap`）。PBS 快照补齐这三个字段（如果还没有）。不要新增 schema 版本。
6. **保持不变的行为：** 提交锁、`.submit-claim`、确认期间输入变化的检查、parent chk 附件、Slurm 台账预留、批次同模板同方法的要求、`qstat` / `squeue` 读不到时拒绝提交。

## 不允许

- 不修改上述范围外的文件、已有 Attempt 或模板；不改脚本渲染结果。
- 不新增“运行中上限”的任何本地限流或常驻进程。
- 不改 `budget.py` 的预留与释放规则。
- 不自动重提、不绕过 Mac 确认、开发时不连集群。
- 日志和测试里不出现真实主机、用户名、作业号、绝对路径。

## 测试

- **上限边界**（PBS、Slurm 各一套，`test_caps.py`）：
  - 已占用 + 申请 = 上限：允许；= 上限 + 1：拒绝。
  - 单作业 = `max_cores`：允许；+1：拒绝。
  - 已占用里包含：本地 study 中没有的排队作业（模拟另一台电脑或手动提交）、挂起作业（PBS `H`，Slurm `PD` 且原因为 held）：都计入。
  - Slurm：调度器尚未显示、但本地台账已预留的核数计入。
  - PBS：`pbsnodes` 假响应缺失、出错或总核数大于 `max_cores` 时，上限仍是 `max_committed_cores`；提交流程不再调用 `pbsnodes`（断言调用列表里没有）。
  - 确认文本包含运行、排队、合计、上限和“ag 不限制运行中的核数”这一句。
- **配置校验：** PBS `max_cores = 45` 拒绝；`max_committed_cores` 小于 `max_cores` 或大于 `4 × max_cores` 拒绝（两种调度器）；Slurm 64 / 256 通过；档位核数大于 `max_cores` 拒绝。
- **monitor：** PBS 和 Slurm 快照的 `committed_cap` 等于 `max_committed_cores`；`over-cap` 按它判断。
- **SSH 日志**（`test_ssh_log.py`，用假 subprocess）：成功、非零退出、超时、启动失败各写一行，字段齐全；stderr 含主机名、用户名、路径时，日志文件里一个都不出现；`error_class` 归类正确（至少覆盖 connection_refused、operation_not_permitted、other）；日志目录是符号链接或不可写时操作照常完成；只读重试时写两行，`attempt` 分别为 1、2。
- 后端：`PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`；记录通过数和跳过原因。
- 用前端仓库现有的服务器页测试核对新快照（只读运行，不改前端）；PR 里写明结果。
- 暂存精确文件后运行敏感扫描与 `git diff --cached --check`。

## 真实环境验证

- 不另起验证 study。合并后，负责人在两台电脑上改本机配置并各运行一次 `ag doctor`（确认输出里有 `max_committed_cores`）。
- HSS 下一批真实提交时，由负责人在计算机上核对确认框里的运行、排队、合计、上限四个数和提示句，并确认 `ssh-log/` 下出现了新行，日志里没有主机名和路径。结果由负责人转给开发机，写进 PR 评论，不写主机和路径。

## 停止条件

- 需要改 `budget.py`、模板、`remote.py` 的命令文本或 `ag-monitor/1` 的字段名。
- 发现上限判断之外还有代码依赖“严格模式”或 `capacity()` 的返回值。
- 写日志需要改动 `_perform` 的重试或报错语义。

## 合并前审阅与交付

- 需要监督方审阅：是（submit、remote 传输、AGENTS.md）。
- 修改 AGENTS.md：是，只改硬内核第 9 条（附录），负责人已批准方向。
- PR 描述第一行：`Task: T51`；写明删除了哪些测试假响应、前端核对结果。
- 用 REST 读取 `<!-- ag-review head=... -->` 评论，逐条处理并回复。
- 冲突在本地 rebase 解决；合并只由负责人操作。

## 附录：AGENTS.md 硬内核第 9 条（拟）

> 9. 核数按集群分别统计，包括该用户在该集群上的全部作业（含其他电脑、手动或非 ag 提交的作业，挂起和排队都计入）。单个作业不超过 resources.max_cores；运行加排队的总核数不超过 resources.max_committed_cores（不超过 4 × max_cores）。ag 只在提交时检查，不限制排队作业何时开始运行，运行中的核数可能达到 max_committed_cores；这是负责人接受的取舍。
