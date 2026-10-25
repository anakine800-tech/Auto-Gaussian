# T127：监控容错、手动重试与硬件信息修正

版本：v1（监督方，2026-10-25）。**开发机做。** 后端出一个 PR，PR 描述第一行写 `Task: T127`。

## 分支与目标

- 分支：`codex/t127-monitor-resilience`。
- **开工条件：** 以后端 main（不早于 `725bead`，v4.5.0）为基线；T127 编号未被占用。前端 T128 按本单第 7 节的字段并行开发；**本单先合并**，两单都合并后发 v4.5.1（T129）。
- **问题来源（已在开发机证实）：**
  - 某一个入口失败时没有退避，每轮照常重新连接。v4.5.0 也不区分认证失败：一旦认证失败，每 30–60 秒就会向服务器发起一次失败登录。原先用本机包装脚本兜底，靠“任一入口失败就停整个监控”，结果把单个入口的问题放大成全部入口断线（开发机 10-23 至 10-24 共 56 次停机，其中 53 次来自 Slurm 入口，认证失败和主机指纹失败都是 0 次）。
  - stdout 每轮打印完整快照，约 1.5 MB/小时，没有轮转。
  - PBS 快照没有 `cluster.scheduler`，前端显示“未知”。
  - 两个 PBS 集群的 `pbsnodes` 是 Torque 格式，没有 `resources_available.mem` / `resources_assigned.mem`，节点内存全为 null，也没有报错。
  - Slurm 入口“异构节点总内存未知”是正常的局限说明，却写在 `hardware.error` 里，前端因此把已采到的核数也作废，并多计 1 条警告。
- **负责人 2026-10-25 决定：**
  - D1 **退避**：同一入口连续 k 次采样失败（`ok=false`）。k ≤ 2 时间隔不变；k ≥ 3 时，下次间隔 = min(600, 基础间隔 × 2^(k−2)) 秒。成功一次就清零，恢复基础间隔。硬件查询、存储查询失败不让 `ok=false`，所以不计入退避（现行口径不变）。
  - D2 **认证 / 主机指纹失败只暂停该入口**：在快照里写明原因，其他入口照常采样。以下三种情况恢复：该入口的配置发生变化；监控重启；手动重试并带上“已修复”确认后成功一次（D3）。
  - D3 **可以手动立即重试**：任何状态都可以，包括正常、退避中、因认证暂停。因认证或主机指纹暂停的入口，必须显式带 `--auth-fixed`（前端二次确认后才传），否则拒绝；带上后只试一次，失败就继续暂停。
  - D4 **手动重试不限频，但同一入口同时只有一次采样**：该入口正在采样，或已有一个待处理请求时，新的请求合并进去，不另起一次。手动重试成功，效果与自动采样成功相同（清零、恢复基础间隔）；手动重试失败，不改变连续失败数，也不改变下次自动采样时间。唯一的例外是失败类别为认证或主机指纹，这时仍按 D2 暂停该入口。
  - D5 **每个入口可配置采样间隔**：入口新增可选整数 `monitor_interval_seconds`，取值 30–600。不填时与现在相同：PBS 用 `--watch` 的值，Slurm 用 max(`--watch`, 60)。本单不改任何电脑上的配置，实际值在 T129 按 SCNet 统计填写。
  - D6 **stdout**：默认每个采样循环输出一行摘要，加 `--json` 才输出完整快照（第 4 节）。
  - D7 **PBS**：快照写 `cluster.scheduler = "pbs"`。Torque 节点总内存取 `status` 里的 `physmem`（不含 swap）。已分配内存只在该节点上所有作业都申请了内存时，按申请值加总，否则为 null。**不得**用 `physmem − availmem`：那是实际使用量，而且 `availmem` 含 swap。PBS Pro 字段继续支持。
  - D8 **局限说明与错误分开**：新增 `hardware.notes`（字符串列表）；`hardware.error` 只放真正的查询失败。
  - D9 **常驻方式**：仓库新增监控 LaunchAgent 的 plist 样例（全用占位符）。认证检测进了后端以后，常驻服务直接运行 `ag monitor`，本机包装脚本在 T129 部署时备份后删除。
  - D10 **手动重试的实现**：`ag monitor --retry <入口>` 在本机缓存里登记一个请求文件，由正在运行的监控进程读取并执行。前端只调用这个命令，自己不发 SSH（第 3 节）。
  - D11 Slurm 每轮的 4 条查询这次**不合并**成 1 次 SSH。
- **资料：** `ag/src/ag/monitor.py`（`run_clusters`、`sample`、`entry_interval`、`pbs_hardware`、`slurm_partition`、`publish`）、`ag/src/ag/pbs.py`（`parse_nodes`、`memory_gb`）、`ag/src/ag/config.py`（`display_order` 的合并与校验方式）、`ag/src/ag/cli.py`（monitor 参数）；T112、T114 任务单；前端仓库 `docs/ag-monitor-1.md`。
- **新增检查防的事故：** 退避和暂停防的是第一条（连锁断线、反复失败登录）；“暂停时手动重试须带 `--auth-fixed`”防的是人没修好密钥或隧道就连点重试，又产生失败登录；重试“合并”防的是连点时对同一网关发起并发连接。除此之外不加新检查。

## 允许改动的路径

- `ag/src/ag/monitor.py`：调度、退避、暂停、重试、快照字段、stdout 输出。
- `ag/src/ag/pbs.py`：Torque `status` 中 `physmem` 的解析；按节点汇总作业申请的内存。
- `ag/src/ag/config.py`：**只新增**入口可选键 `monitor_interval_seconds`（照 `display_order` 的方式：旧单集群配置合并列表、Slurm 允许字段集合、类型和范围校验）。
- `ag/src/ag/cli.py`：只改 `monitor` 子命令的参数（`--retry`、`--auth-fixed`、`--json`）和分派。
- 测试：`ag/tests/test_monitor.py`、`test_monitor_all_jobs.py`、`test_pbs.py`、`test_resources_monitor.py`（只改受影响的用例，PR 中逐个列出）；新建 `ag/tests/test_monitor_resilience.py`。夹具全部合成，写在测试里或 `ag/tests/fixtures/` 下的新文件中。
- 新建 `docs/ops/launchd/local.autogaussian.monitor.plist.example`。
- 文档：`README.md`（监控一节）；`docs/DEVELOPING.md` 第 306–307 行（见第 6 节）；`docs/LESSONS.md`（可选）；本单 `docs/redesign-tasks/T127-monitor-resilience.md`、`docs/redesign-tasks/open-tasks.txt`。
- **不改** `ag/src/ag/remote.py`、`transport.py`、`slurm.py`、`status.py`、`submit.py`、`AGENTS.md`、`ag/templates/`、`archive/`、前端仓库；不改 `CHANGELOG.md`（T129 统一写）。

## 要做的

### 1. 调度与退避（D1、D5）

- 每个入口单独记录：基础间隔、当前间隔、连续失败数、状态、下次采样时间。**基础间隔** = `monitor_interval_seconds`；没配置时沿用 `entry_interval()` 的现行规则。
- 主循环改为按“最早到期的入口”和“重试请求”唤醒：没有到期也没有请求时最多睡 2 秒，然后检查重试请求。**不要每 2 秒写一次文件，也不要每 2 秒打印输出。**一个入口采样超时，下一个紧接着开始，不叠加、不并发（T114 口径不变）。
- 退避按 D1 计算。快照 `interval_seconds` 的含义不变，仍是该入口的**基础间隔**；退避后的间隔写进新字段 `sampling.current_interval_seconds`。
- 该入口配置变化时（`run_clusters` 已有“配置变了就重建 transport”的地方），状态全部重置：清零、解除暂停、立即采样一次。
- 旧单集群配置（没有 `clusters` 表）的路径也照此执行。**调度只能有一份实现**，两条路径复用它。
- 一次性采样（不带 `--watch`）没有退避和下次时间：`sampling.state = "normal"`，`current_interval_seconds` 和 `next_sample_at` 为 null。

### 2. 认证与主机指纹失败（D2）

- 采样失败后，按错误文本分类：
  - `auth`：匹配 SSH 认证失败 `Permission denied (` 后接 `publickey`、`password`、`keyboard-interactive`、`hostbased` 或 `gssapi`（逗号分隔组合也算）。**单独出现的 `Permission denied`（例如远程命令读文件被拒）不算。**
  - `host_key`：`Host key verification failed`，或 `REMOTE HOST IDENTIFICATION HAS CHANGED`。
  - 其他都是普通失败，进入退避。
- 分类在进程内做，写入快照的只有类别，错误文本仍按 `redact_stderr` 处理后写入。分类用的模式不得包含主机名或用户名。
- `auth` 或 `host_key` 时：本轮快照照常写入（`ok=false`），`sampling.state = "paused"`，`pause_reason` 为对应类别，`next_sample_at = null`。之后不再自动采样该入口，直到满足 D2 的恢复条件之一。暂停期间不重复写快照。
- 监控重启后暂停状态不保留，第一轮照常采样（D2 选定的口径）。

### 3. 手动重试（D3、D4、D10）

**命令行契约（T128 依赖此契约，字段名不得更改）：**

```
ag monitor --retry <入口名> [--auth-fixed] [--json]
```

- `--retry` 不能和 `--watch` 同时使用。入口名必须是当前配置里的入口；旧单集群配置的入口名是 `default`。
- `--json` 时 stdout 只输出一个 JSON 对象：

```
{"entry": "<入口名>",
 "result": "queued" | "already_queued" | "in_progress" | "refused",
 "reason": null | "monitor_not_running" | "auth_confirmation_required" | "unknown_entry",
 "requested_at": "<ISO 8601 UTC>" | null}
```

  `queued`、`already_queued`、`in_progress` 的退出码为 0；`refused` 的退出码为 1。不带 `--json` 时打印一行中文说明。配置读取失败等其他错误，沿用 CLI 现有的错误输出。
- 各结果的含义：
  - `queued`：新建了请求。
  - `already_queued`：该入口已有待处理请求，本次合并。
  - `in_progress`：该入口正在采样，本次合并，结果见下一份快照。
  - `refused` + `monitor_not_running`：没有正在运行的 `--watch` 监控，**不留下请求文件**。
  - `refused` + `auth_confirmation_required`：该入口因 `auth` / `host_key` 暂停，且没有带 `--auth-fixed`。
  - `refused` + `unknown_entry`：入口名不在配置里。
- **请求文件**：放在该入口的缓存目录（`cache_dir()` 的结果）下，用 `O_EXCL | O_NOFOLLOW` 独占创建，内容为 `requested_at` 和 `auth_fixed`。监控开始处理请求时删除它；这只是本机缓存文件，不涉及服务器。监控启动时，遗留的请求文件按“没有请求”处理并删除，在 stdout 摘要里记一次。
- **判断监控是否在运行、是否正在采样**：做法由开发方定（推荐在 `.ag-monitor/` 根下放一个状态文件，记 PID、心跳时间、正在采样的入口；心跳至少每 30 秒更新一次，并在每次采样开始和结束时更新）。要求如下：
  - 不发 SSH；
  - 心跳超过 90 秒或进程不存在，就判为没有运行；
  - **不得在 `.ag-monitor/` 下新建子目录**（前端把每个子目录当作一个入口）；
  - 新文件和缓存一样拒绝符号链接。
- **执行**：监控读到请求后，在下一个空闲时刻（不打断其他入口正在进行的采样）对该入口采样一次。`sampling.trigger` 写 `manual`；带 `--auth-fixed` 时写 `manual_auth_fixed`。结果按 D4 处理。
- 同一个监控进程里，采样始终是串行的，所以同一入口不可能有两个 SSH 采样同时进行。

### 4. stdout 与历史（D6）

- 默认输出：只在本次循环至少采样了一个入口时，打印**一行** JSON：

```
{"schema": "ag-monitor-line/1", "at": "<ISO UTC>",
 "entries": {"<入口>": {"sampled": bool, "trigger": "scheduled"|"manual"|"manual_auth_fixed"|null,
                        "ok": bool, "state": "normal"|"backoff"|"paused",
                        "consecutive_failures": int, "jobs": int, "warnings": int,
                        "next_sample_at": "<ISO UTC>"|null, "error": str|null}}}
```

  - `jobs` 是本人作业数。
  - `error` 是已脱敏的错误文本，截断到 200 字符。
  - **不得包含他人作业和用户名。**
- `--json`：多入口时，和现在一样打印 `{"clusters": {...}}` 完整快照；一次性单入口时打印完整快照。
- `history.jsonl` 的每行摘要新增 `sampling_state`、`consecutive_failures`、`trigger`，原有字段不变。

### 5. 硬件信息（D7、D8）

- **PBS 写 `cluster.scheduler = "pbs"`**。
- **Torque 节点内存**：
  - 节点记录有 `status` 属性时，按逗号分隔的 `key=value` 解析，取 `physmem`，用现有的 `memory_gb` 换算（1024 进位），写入 `mem_total_gb`。`totmem`、`availmem` 不使用。
  - 节点同时有 `resources_available.mem` 时，以 PBS Pro 字段为准。两者都没有时写 null。
- **Torque 节点已分配内存**：
  - 按 `parse_nodes` 已采用的节点–作业对应关系，找出该节点上的全部作业。每个作业取 qstat 的 `Resource_List.mem`。
  - 全部作业都能解析，才加总；节点上没有作业时是 0.0。
  - 写 null 的情况：任一作业没有申请内存或无法解析；作业跨多个节点；节点上的作业号对应不到 qstat 记录（包括作业号格式不同）。**不猜，不按核数比例分摊。**
  - 为 null 时，在 `hardware.notes` 里写一条中文说明，例如“已分配内存未知：节点上有作业未申请内存”。
  - 以真实输出的格式为准：开发前先在开发机只读核对一次（见真实环境验证），**夹具只用合成文本**。
- **notes 与 error 分开**：
  - `hardware.notes`：字符串列表，没有时为空列表。现有 `'sinfo 内存为异构节点最小值，总内存未知'` 改放到这里；`slurm_partition` 里“两次作业查询不一致，他人汇总出现负数”也改放到这里（不影响硬件数据本身）。
  - `hardware.error`：只放查询失败，例如 `pbsnodes` 或 `sinfo` 执行失败、`AllocMem` 失败、未配置分区。
- 旧缓存（被保留的上一次成功数据）没有 `notes` 时，补一个空列表，不编造内容。

### 6. 常驻样例与文档（D9）

- 新建 `docs/ops/launchd/local.autogaussian.monitor.plist.example`：
  - 运行 `<AG_EXECUTABLE> monitor --watch 30`；
  - `RunAtLoad=true`，`KeepAlive=true`，`ThrottleInterval=60`；
  - stdout / stderr 写到 `<LOG_DIR>/monitor.stdout.jsonl` 和 `<LOG_DIR>/monitor.stderr.log`；
  - 只设最小 `PATH`（含系统 ssh 所在目录）；
  - **所有路径和账户都用尖括号占位符**，不得出现真实路径或用户名。
  - 用 `plutil -lint` 检查（把占位符替换到临时副本里再查，不加载到 launchd）。
- `README.md` 监控一节：写清退避和暂停的规则、`monitor_interval_seconds`、`--retry`/`--auth-fixed`、默认一行摘要与 `--json`、plist 样例的位置，以及“常驻服务直接运行 ag monitor，不再需要包装脚本”。
- `docs/DEVELOPING.md` 第 306–307 行改为：前端使用前端仓库自带的 `.githooks` 和扫描器，在前端检出执行 `git config core.hooksPath .githooks`。其余内容不变。

### 7. 快照新增字段（`ag-monitor/1`，只做加法；T128 照此开发）

```
sampling                          # 顶层对象；一次性采样也写
  state: "normal" | "backoff" | "paused"
  consecutive_failures: int ≥ 0
  current_interval_seconds: int | null    # 退避后的实际间隔（30–600）；一次性采样为 null
  next_sample_at: ISO UTC | null          # 暂停或一次性采样时为 null
  pause_reason: null | "auth" | "host_key"   # 只在 state = "paused" 时非 null
  trigger: "scheduled" | "manual" | "manual_auth_fixed"
  retry_pending: bool                     # 写快照时该入口是否还有待处理请求
cluster.scheduler                 # PBS 写 "pbs"；Slurm 照旧 "slurm"
cluster.hardware.notes            # [str]，可为空列表
cluster.nodes[].mem_total_gb      # Torque 来自 physmem（原字段，含义不变）
cluster.nodes[].mem_assigned_gb   # Torque 按 D7 口径（原字段，含义不变）
```

- `interval_seconds` 仍是基础间隔（30–600 或 null），含义不变。
- `state = "backoff"` 的条件是 `consecutive_failures ≥ 3` 且没有暂停。连续失败 1–2 次时 `state` 仍是 `normal`，但 `consecutive_failures` 如实记录。
- 原有字段的含义一律不变。v4.5.0 的前端读新快照时必须仍能正常显示（它会忽略未知字段，这一点要用测试证明）。
- 给前端的 `docs/ag-monitor-1.md` 补丁附在 PR 描述里，由 T128 合入。

## 不允许

- 不新增、不修改远程命令，不放宽白名单，不改 `transport.py` 的重试行为，不开 SSH 连接复用。
- 不新增任何提交、取消、写服务器的路径。监控仍然只读。
- 不把未知值写成 0；不用 `physmem − availmem`；不按比例分摊内存。
- **不改任何电脑上的 ag 配置、常驻 LaunchAgent、包装脚本，也不更新常驻服务正在用的检出**（部署属于 T129）。
- **不在真实环境故意制造认证失败或断开连接**，失败路径一律离线测试。
- 夹具、PR、截图里不出现真实用户名、主机、节点名、队列名、分区名、作业号或路径。

## 测试

| 场景 | 预期 |
|---|---|
| 某入口连续失败 1、2 次 | 间隔不变，`state=normal`，`consecutive_failures` 为 1、2 |
| 连续失败第 3、4、5 次（基础 60） | 下次间隔 120、240、480，`state=backoff` |
| 连续失败很多次（基础 30 和 60） | 间隔封顶 600 |
| 退避中自动采样成功 | 清零，恢复基础间隔，`state=normal` |
| 一个入口退避 | 其他入口按各自间隔照常采样 |
| stderr 含 `Permission denied (publickey,password).` | `paused`，`pause_reason=auth`，此后不再自动采样 |
| stderr 含 `Host key verification failed` 或 `REMOTE HOST IDENTIFICATION HAS CHANGED` | `paused`，`pause_reason=host_key` |
| 远程命令输出 `cat: x: Permission denied` | 不算认证失败，按普通失败处理 |
| 暂停后该入口配置变化 | 解除暂停，立即采样 |
| 暂停的入口，`--retry` 不带 `--auth-fixed` | `refused`，`auth_confirmation_required`，退出码 1，不留请求文件 |
| 暂停的入口，带 `--auth-fixed`：成功 / 再次认证失败 | 恢复 `normal` / 仍然 `paused`，只尝试一次 |
| 退避中的入口 `--retry`：成功 | 立即采样，清零，`trigger=manual` |
| 退避中的入口 `--retry`：失败（普通错误） | 连续失败数和下次自动时间都不变 |
| 连续两次 `--retry` | 第二次 `already_queued`；只多采样一次 |
| 采样进行中 `--retry` | `in_progress`，不另起采样 |
| 没有运行中的监控 / 心跳超时 | `refused`，`monitor_not_running`，不留请求文件 |
| 入口名不在配置里 / 名字带路径字符 | `refused`，`unknown_entry` / 被拒，不创建文件 |
| 请求文件位置是符号链接 | 拒绝，不跟随 |
| 监控启动时有遗留请求文件 | 删除，记录一次，不触发采样 |
| `monitor_interval_seconds = 90` / 不配置 | 该入口间隔为 90 / PBS 用 watch、Slurm 用 max(watch, 60) |
| `monitor_interval_seconds` 为 20、601、`"60"` | 配置错误 |
| 默认 stdout | 每个采样循环一行；不含他人作业和用户名；空闲的 2 秒唤醒不打印 |
| `--json` | 输出与 v4.5.0 相同结构的完整快照 |
| 合成 Torque `pbsnodes`（含 `status`，有 `physmem`、`availmem`、`totmem`） | `mem_total_gb` 取 `physmem` 换算，不受另两项影响 |
| Torque 节点上的作业都申请了内存 / 其中一个没申请 | 已分配内存为加总 / null，并写 notes |
| Torque 节点无作业 | 已分配内存 0.0 |
| 作业跨两个节点 | 相关节点已分配内存 null |
| 合成 PBS Pro `pbsnodes` | 行为与 v4.5.0 相同 |
| PBS 快照 | `cluster.scheduler="pbs"` |
| Slurm 异构内存（合成 `sinfo`） | `hardware.error=null`，`notes` 含说明，核数照常 |
| `sinfo` / `AllocMem` 执行失败 | 写入 `hardware.error`（行为不变） |
| 他人汇总为负 | 写 notes，不写 error；汇总仍为 null |
| 旧缓存没有 `notes` / `sampling` | 补空列表或默认值，不报错 |
| 用 v4.5.0 前端的 `validate_monitor` 校验新快照（测试内复制该函数或用等价夹具） | 通过 |
| `plist` 样例 | 替换占位符后的临时副本通过 `plutil -lint`（只在 macOS 运行；Linux CI 上跳过并写明原因） |

推送前本地跑一次全量 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，之后以 CI 为准；运行 `python scripts/scan_public.py` 和 `git diff --cached --check`。

## 真实环境验证（合并前，开发机；不提交作业）

做法沿用 T114：复制一份本机配置，`studies_root` 指向一个临时空目录，用本分支代码在前台运行 `--watch 30`，持续 30 分钟。**不替换、不停用常驻监控，原配置前后字节一致。**

1. **开发前的格式核对（只读，一次）**：用现有的 `pbsnodes -a` 查询（已在白名单）各看一次 default、newhpc 的节点输出，确认 `status` 的格式和作业号的对应方式，再写解析和合成夹具。原文只留在本机仓库外的临时目录。
2. 四个入口都 `ok=true`。PBS 两入口 `scheduler="pbs"`，`mem_total_gb` 非 null，并与原文的 `physmem` 换算值一致；`mem_allocated_gb` 有值，或者为 null 并带 notes，要写明是哪种情况、为什么。Slurm 两入口 `hardware.error=null`，`notes` 有异构说明，核数非 null。
3. 在配置副本里给 scnet 设置 `monitor_interval_seconds = 90`，确认它的间隔变成 90，其他入口不变。
4. 手动重试，每一步都用配置副本：
   - 对一个空闲入口执行 `--retry`，记录从发出到新快照出现的秒数；
   - 连续执行两次，确认只多采样一次；
   - 停掉临时监控后再执行 `--retry`，确认 `monitor_not_running`，并且没有留下文件。
5. 记录 30 分钟内 stdout 的行数和字节数，换算成每小时增长量。
6. **退避和认证暂停不在真实环境里验证**，只靠离线测试。
7. PR 里只写字段齐不齐、数值是否一致、耗时和增长量；**不贴快照或 `pbsnodes` 原文**。SSH 出现异常就停下汇报，不重试。

## 停止条件

- 需要改远程命令、`transport.py` 或白名单；Torque 输出与本单假设差别很大，或者节点作业号无法与 qstat 对应。
- 需要改范围外文件；同一问题修两次仍未解决。
- 真实验证中出现任何 SSH 异常或意外快照：停下报告。

## 合并前审阅与交付

- 需要监督方审阅：**是，逐行审**（监控远程读取路径、重试请求文件、认证分类）。合并只由负责人操作。
- 修改 AGENTS.md：无。
- PR 描述包括：
  - D1–D11 各自对应的改动；
  - 第 7 节字段逐项对照；
  - 给 T128 的 `docs/ag-monitor-1.md` 补丁；
  - 全量测试结果；
  - 真实验证记录（不含原文）；
  - plist 样例的 lint 结果。
- 用 `gh pr view <编号> --comments` 读取 `<!-- ag-review head=... -->` 评论，逐条处理并回复。
- **合并后不部署**：两台电脑的同步、配置填写、替换包装脚本，都在 T129 做。

## 版本记录

- v1（2026-10-25，监督方）：依据负责人 10-25 三轮问答决定 D1–D11 起草；原草案中 `.pnpm-store/` 一项属于前端仓库，移到 T128。

## 实现与离线验证（2026-10-25）

- 基线 `725bead`，实现提交 `f4f3621`；交付和真实验证记录见 [PR #329](https://github.com/anakine800-tech/Auto-Gaussian/pull/329)。D1–D11 及第 7 节字段逐项对照、给 T128 的文档补丁均在 PR 描述中。
- 旧单集群与多入口复用同一串行调度循环；入口配置变化独立重置。CLI 默认摘要，`--json` 保留完整快照；既有 Python `run_clusters()` 调用仍默认完整输出，兼容已有调用方。
- 本地 `watch.json`、`watch.lock` 与入口 `retry-request.json` 实现心跳和请求合并；锁内原子完成领取请求与标记采样，避免连点产生额外采样。同一缓存拒绝第二个存活监控，防止多个采样者争用请求状态。心跳线程只写本地文件，远程查询仍串行。
- 认证类别在 MonitorTransport 脱敏前提取；固定 Command、只读白名单、原传输参数和超时保持不变。未修改 remote.py、transport.py、模板或提交路径。
- 开发前只读核对确认两个 PBS 入口均为逗号分隔 status、physmem 可解析、槽位范围受支持，节点作业号可与 qstat 精确对应。合成夹具未包含现场身份或原文。
- 相关原有测试 299 项、新增 T127 测试 54 项通过；复制前端 v4.5.0 校验函数验证新快照。旧 Python 调用兼容修正后复测 90 项通过。
- 最终全量：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs -p no:cacheprovider`，4778 通过、19 跳过，272.69 秒。跳过为私有日志未启用及 macOS 不支持的 Linux procfs/GNU stat 检查；实现提交的 Linux CI 和 CodeQL 均通过。
- `python scripts/scan_public.py`：1797 个文件、0 错误；`git diff --cached --check` 通过。占位符替换后的临时 plist 通过 `plutil -lint`，未加载到 launchd；前端文档补丁在临时副本通过 `git apply --check`。
- 现有测试仅调整 test_monitor.py、test_monitor_all_jobs.py、test_resources_monitor.py 中受影响的内存、notes、stdout 和合成时钟用例；新增 test_monitor_resilience.py。其余测试文件未修改。
- 负责人已在本会话批准“限定的只读核对与验证”，并批准记录已知 SSH post-quantum 能力提示后继续。原配置、常驻监控、主检出均未替换；合并、部署和包装脚本替换仍由后续任务处理。

## T128 接入发现的拒绝路径补修（2026-10-25）

- 负责人明确批准：“保持零新增文件，允许另开后端修复 PR”。补修分支 `codex/t127-retry-refusal-no-files`，基于已合并的 #329（`ead920d`）；不扩展远程或部署范围。
- 合成复现：旧监控缓存无心跳、无锁时，`monitor --retry default --json` 正确拒绝，但创建了空的 `watch.lock`。原测试只检查请求文件不存在，遗漏了该副作用。
- 修复：重试只打开监控已有的锁，不创建缓存目录或锁；缺失时直接返回 `monitor_not_running`。锁存在时仍在锁内检查心跳及登记请求，独占请求创建、符号链接拒绝及并发合并保持不变。
- 合成回归：缓存不存在、无心跳、心跳过期、进程消失、缺锁五种拒绝情形，对比全部目录及文件字节；并保留成功、合并、认证确认和符号链接测试。相关测试 58 项通过。
- 真实验证限 T128 已授权的临时前端及一次本机拒绝请求；常驻监控仍为 v4.5.0，不启动新采样或连接集群。完整结果补入补修 PR。
- 修复后的真实拒绝验证：T128 临时前端使用本补修检出，在 18773 对 default 仅点击一次，返回 `refused / monitor_not_running`、requested_at=null；页面文字正确。缓存目录前后零新增、零删除路径，控制文件保持不存在；配置、LaunchAgent、常驻进程及原端口监听不变。临时前端已停止，无真实截图或快照进入仓库。
- 全量初跑：4781 通过、19 跳过，唯一失败为新增 open-tasks 登记行格式；仅将说明改为注释后，Skills 全量复验 509 项通过。后端代码测试均通过，覆盖结果为 ag 单元测试 4273 项及 Skills 509 项；19 项跳过为未启用私有日志及 macOS 不支持的 Linux 方言检查。
