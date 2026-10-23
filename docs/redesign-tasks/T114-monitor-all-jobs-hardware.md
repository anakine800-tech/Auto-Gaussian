# T114：监控采集全员作业、分配核数、已运行时间和硬件资源

版本：v1（监督方，2026-10-23）。**开发机做。** 后端出一个 PR，PR 描述第一行写 `Task: T114`。

## 分支与目标

- 分支：`codex/t114-monitor-all-jobs-hardware`。
- **开工条件：** 以当前最新的 main（不早于 `47aef3f`）为基线；T114 编号未被占用。可以和 T119 并行（两单不改同一个文件）。T115（前端）照本单第 6 节的字段并行开发。
- **负责人 2026-10-23 决定：**
  - M1 PBS 集群（default、newhpc）列出**所有人的作业明细**：用户名、作业号、作业名、状态、核数、内存、已运行时间 / walltime、队列。本人作业关联到 Attempt。
  - M2 Slurm 入口（scnet、scnet-test）**只列本人明细**；其他人按本入口的分区汇总成"运行 / 排队的作业数和核数"，**不取用户名**。
  - M3 运行中的作业给**实际分配的核数**，排队中的作业给**申请的核数**，并标明是哪一种。
  - M4 **已运行时间** = 采样时间 − 作业开始时间；拿不到开始时间时，PBS 退回 `resources_used.walltime`；两者都没有就记为 null。另记 walltime 上限。
  - M5 硬件：PBS 从 `pbsnodes`（和现在读核数是同一次查询）读每个节点的总内存和已分配内存；Slurm 用 `sinfo` 只查本入口配置的分区，取 CPU 已分配 / 空闲 / 其他 / 总数，以及内存总量和已分配量，按分区汇总，快照里不存单个节点。采不到的写 null，不当作 0。
  - M6 本人内存 = 本人作业申请内存之和，运行和排队分开记。
  - M7 scnet 与 scnet-test 是同一账号：每个入口按自己的分区采硬件；本人占用沿用现有共享组逻辑，只算一次。
  - M8 采样频率：PBS 入口每 30 秒，Slurm 入口每 60 秒；存储查询仍然每小时一次。
  - M9 硬件或存储查询失败时，只把对应部分标为未知，**不让整轮采样失败**（T112 遗留问题 1）。
  - M10 `mark_removed()` 读到损坏的 `latest.json` 时不抛异常（T112 遗留问题 2）。
  - M11 排队作业按提交时间排序，所以 PBS 需要记录 `qtime`。
- **资料：** `ag/src/ag/monitor.py`、`pbs.py`、`slurm.py`、`remote.py`、`status.py`、`config.py`；前端仓库 `docs/ag-monitor-1.md`；T103、T106、T112 任务单。

## 允许改动的路径

- `ag/src/ag/monitor.py`：采样、调度间隔、容错、快照字段。
- `ag/src/ag/pbs.py`：节点内存解析、单作业字段解析（内存单位、qtime、时间）。
- `ag/src/ag/slurm.py`：分区汇总和 `sinfo` 输出的解析。
- `ag/src/ag/remote.py`：**只新增**本单第 3 节列出的只读命令，不改已有命令。
- `ag/src/ag/config.py`：只新增可选配置项 `display_order`（整数），见第 5 节。
- 测试：`ag/tests/test_monitor*.py` 等相关现有测试（PR 中逐个列出），新建 `ag/tests/test_monitor_all_jobs.py`。夹具只用合成输出（虚构用户名 userA…、虚构节点名 node-a…）。
- 文档：`README.md`、`docs/LESSONS.md`；本单 `docs/redesign-tasks/T114-monitor-all-jobs-hardware.md`、`docs/redesign-tasks/open-tasks.txt`。
- 前端文档补丁：在 PR 描述里附上 `docs/ag-monitor-1.md` 的补丁，由 T115 合入前端仓库。本单不改前端仓库。

## 要做的

### 1. PBS 全员作业（M1、M3、M4、M6、M11）

- 现在 `observation()` 已经读取全员的 `qstat -f`。本单把全员作业写进新字段 `cluster.jobs`；`own.jobs` 的含义不变，只给它补充第 6 节列出的新字段。
- 每条作业：
  - 核数：运行中（R、E）的作业取 `exec_host` 的分配核数，复用 `pbs.slot_count`；排队中（Q、H、W、S）的作业取申请核数，与 `status.occupied()` 的预留口径一致。用 `cores_kind` 标明 `allocated` 或 `requested`。
  - 内存：取 `Resource_List.mem`，换算成 GB（支持 b、kb、mb、gb、tb 后缀，大小写不敏感，按 1024 进位），保留 1 位小数；解析不了就写 null。
  - 时间：优先用开始时间计算已运行秒数；qstat 的时间是文本时，**以真实 `qstat -f` 输出为准**确定格式和时区。时区不确定时不要猜，改用 `resources_used.walltime`，并在 `elapsed_source` 里写明来源。
  - `qtime` 写成 ISO 8601 UTC；拿不到就写 null。
- C 状态（已完成）的作业不列入。
- 条数上限 500：超出的部分不写入，记下 `cluster.jobs_omitted`（被省略的条数）。截断前先排序：本人作业在前，然后运行中按开始时间，排队中按 `qtime`。

### 2. PBS 节点内存（M5）

- `parse_nodes` 为每个节点补充 `mem_total_gb`（取 `resources_available.mem`）、`mem_assigned_gb`（取 `resources_assigned.mem`）和 `jobs`（该节点上的作业数）。Torque 风格的输出没有这些字段时写 null。
- 汇总写进 `cluster.hardware`（第 6 节）。任一节点内存未知时，集群内存合计写 null，不按部分节点求和。

### 3. Slurm 分区汇总与硬件（M2、M5、M7）

- 在 `remote.py` 新增只读命令。分区名来自该入口配置的 `partition`，用现有的 `slurm_token` 校验：
  - `slurm_partition_jobs(partition)`：`squeue -h -p <分区> -r --local -o '%T|%C'`，只取状态和 CPU 数，**不取用户名**。
  - `slurm_partition_hardware(partition)`：`sinfo -h -p <分区> -o '%C|%m|%D'`（CPU 的 A/I/O/T、每节点内存 MB、节点数）。
  - 已分配内存：先在 scnet 上只读确认 `sinfo` 是否支持 `AllocMem`（例如 `-N -O`）。支持就加一条命令，只在 ag 内存中汇总，快照里不存节点名；不支持就写 null，在 PR 里说明。**以真实输出为准**，不凭记忆写格式。
- 没有配置 `partition` 的入口：不查全集群，硬件和汇总都写 null，并写 `hardware.error = "未配置分区"`。
- 其他人的汇总 = 分区全部作业 − 本人作业（本人作业来自已有的 `slurm_jobs(user=…)`）。结果为负说明两次查询不一致：这时写 null，并在 `hardware.error` 里写明原因。
- 共享组：`own` 的共享上限逻辑不变；`cluster.hardware` 和汇总按入口各自计算。

### 4. 采样间隔与容错（M8、M9、M10）

- `--watch` 允许的范围改为 30–600 秒。实际间隔：PBS 入口 = watch，Slurm 入口 = max(watch, 60)。每个入口各自判断是否到期，循环的节拍取 watch。快照里的 `interval_seconds` 写**该入口的实际间隔**。
- 一轮采样超过节拍时，下一轮紧接着开始，不叠加、不并发。每份快照写 `sample_duration_ms`。
- `storage_sample()` 失败时只写 `storage_error`，不再向上抛出，`ok` 不受影响。
- 硬件查询（`pbsnodes` 的内存部分、`sinfo`）失败时，`hardware` 各值写 null，`hardware.error` 写原因（经 `redact_stderr` 处理），`ok` 不受影响。**作业查询失败仍然让本轮 `ok=false`**，这一点不变。
- `mark_removed()` 读不到 `latest.json` 或内容不合法时，写一份最小的合法快照（`ok=false`、`config_removed=true`、`error="缓存不可读，已按配置移除处理"`），不抛异常。
- `history.jsonl` 的摘要里**不写他人作业和用户名**，只写计数。

### 5. 显示顺序（供前端排卡片）

- 每个入口新增可选配置 `display_order`（整数），写进快照 `cluster.display_order`。没配置时写 null，前端按"PBS 在前、Slurm 在后，再按入口名排序"兜底。本单不改开发机的配置文件。

### 6. 快照新增字段（`ag-monitor/1`，只做加法；T115 照此开发）

```
cluster.jobs[]            # PBS：全员；Slurm：只有本人
  job_id, user, name, state, queue,
  cores, cores_kind ("allocated"|"requested"),
  mem_gb (number|null), elapsed_seconds (int|null), elapsed_source ("start_time"|"walltime_used"|null),
  walltime_limit_seconds (int|null), start_time (ISO|null), qtime (ISO|null),
  mine (bool), study (str|null), attempt (str|null)
cluster.jobs_omitted      # int，PBS 截断时省略的条数；没有截断写 0
cluster.job_summary       # 按本入口统计：running_jobs, running_cores, queued_jobs, queued_cores,
                          #   others_running_jobs, others_running_cores, others_queued_jobs, others_queued_cores（任一项可为 null）
cluster.hardware          # cores_total, cores_allocated, cores_idle, cores_other,
                          #   mem_total_gb, mem_allocated_gb, source ("pbsnodes"|"sinfo"), error (str|null)
cluster.nodes[]           # PBS 已有字段之外，加 mem_total_gb, mem_assigned_gb, jobs
cluster.display_order     # int|null
own.mem_running_gb, own.mem_queued_gb   # number|null，有任何一条作业内存未知就写 null
own.jobs[]                # 已有字段之外，加上与 cluster.jobs 相同的新字段
sample_duration_ms        # int
```

- 原有字段的含义一律不变。`cluster.cores_total` / `cores_used` 照旧；Slurm 入口在 `sinfo` 采到数据时，`hardware_capacity_known` 改为 true。
- 失败快照沿用上一次成功的 `cluster.*`，并照旧带"非最新"的语义；第一次就失败时，新字段全部写 null 或空列表。

## 不允许

- 不改已有的远程命令，不放宽白名单，不新增任何写操作或作业操作。
- Slurm 不取他人用户名，不查未配置的分区，不查全集群。
- 不把作业查询失败降级成"部分失败"；不把未知值写成 0。
- 不改开发机的配置文件和常驻 LaunchAgent（改间隔是合并后的事）。
- 夹具和 PR 里不出现真实用户名、节点名、分区名、队列名、主机名或作业号。

## 测试

| 场景 | 预期 |
|---|---|
| PBS 全员 qstat（合成：本人 1 条，他人 3 条运行、2 条排队） | `cluster.jobs` 6 条；本人 `mine=true` 并关联 Attempt；运行中 `cores_kind=allocated`，排队中 `requested` |
| `exec_host` 跨两个节点 | 分配核数为两段之和 |
| `Resource_List.mem` 为 `50gb`、`51200mb`、`52428800kb` | 都换算成 50.0 |
| 内存字段缺失或格式不认识 | `mem_gb=null`，`own.mem_*` 为 null |
| 有开始时间 | `elapsed_seconds` 正确，`elapsed_source=start_time` |
| 没有开始时间、有 `resources_used.walltime` | 改用后者，`elapsed_source=walltime_used` |
| 超过 500 条 | 截断到 500 条，`jobs_omitted` 正确，本人作业不会被截掉 |
| pbsnodes 有内存字段 | 节点和集群合计正确 |
| 某个节点没有内存字段 | 集群内存合计为 null |
| Slurm 分区汇总（合成） | 他人 = 全部 − 本人；没有用户名字段 |
| 他人汇总算出负数 | 写 null，并写明原因 |
| 入口没有配置 `partition` | 不发出 `sinfo`、`squeue -p`；`hardware.error="未配置分区"` |
| `sinfo` 失败 | `hardware` 全为 null，`ok=true` |
| 存储查询失败 | 只写 `storage_error`，`ok=true` |
| 作业查询失败 | `ok=false`，行为与现在相同 |
| `--watch 30` | PBS 入口每 30 秒采样，Slurm 入口每 60 秒 |
| 一轮采样超过节拍 | 下一轮紧接着开始，不并发 |
| `mark_removed` 遇到损坏的 `latest.json` | 写最小快照，不抛异常 |
| `history.jsonl` | 不含他人作业和用户名 |
| 命令白名单 | 新命令只能带校验过的分区名；注入字符被拒绝 |

推送前本地跑一次全量 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，之后以 CI 为准；同时做敏感信息扫描，并运行 `git diff --cached --check`。

## 真实环境验证（合并前，开发机；不提交作业）

1. 复制一份本机配置，把 `studies_root` 指向一个临时空目录（这样缓存也在临时目录里），用新代码临时启动监控 `--watch 30`，运行 10 分钟。**不替换、不停用常驻监控。**
2. 四个入口各确认一次：
   - 新字段齐全；
   - PBS 的全员作业条数与 `qstat` 一致；
   - Slurm 的分区汇总与 `squeue -p` 的计数一致；
   - 硬件数值合理；
   - scnet 的 `AllocMem` 是否可用（写进 PR）。
3. 记录每个入口实际的 `sample_duration_ms` 和采样间隔。
4. PR 里只写字段是否齐全、计数是否一致、耗时多少；**不贴快照原文**（其中有他人用户名和节点名）。截图一律用合成快照。
5. 出现 SSH 异常就停下汇报，不要重试。

## 停止条件

- 需要改已有的远程命令或放宽白名单；真实输出与本单假设的格式差别很大。
- 需要改动范围外的文件；同一问题修两次仍未解决。

## 合并前审阅与交付

- 需要监督方审阅：**是**（新增远程命令）。合并只由负责人操作。
- PR 描述包括：M1–M11 各自对应的改动、新增字段清单（与第 6 节逐项对照）、给前端的 `docs/ag-monitor-1.md` 补丁、全量测试结果、真实验证记录。
- **合并后：** 开发机同步；常驻监控的 LaunchAgent 改为 `--watch 30`（改之前备份 plist），重启一次，确认下一轮采样正常。研究用计算机等发版后再同步。

## 版本记录

- v1（2026-10-23，监督方）：依据负责人 10-23 决定 M1–M11 起草，包括 T112 遗留问题 1、2。

## 2026-10-23 实现口径与负责人补充

- 负责人在本任务会话明确选择“按 M3 统一作业明细核数（推荐）”：`own.jobs[].cores` 和 `cluster.jobs[].cores` 对运行作业均使用分配核数；`own.cores_in_use` / `cores_running` / `cores_queued` 保留原来的额度预留统计口径。此决定解决 M3 与“原字段含义不变”之间的冲突。
- 负责人明确回复“批准上述只读验证”：四入口只读查询和配置副本/空临时目录的 10 分钟监控，不提交或取消作业、不修改远程文件或常驻监控；SSH 异常即停止。
- 新固定命令复用已有的 `slurm_jobs` / `slurm_partitions` 只读操作类别，未修改原命令、Transport 白名单或提交路径。
- 真实格式核对确认 AllocMem 可用；分区总内存出现 `最小值+` 时不能计算准确总量，保留 CPU 数据与 AllocMem 合计，总内存写 null 并说明。
- 两个 PBS 入口格式核对时均为空队列，不能据此宣称已验证其时间文本/时区。解析只接受 epoch 或带时区 ISO 日期；其余退回已用 walltime，qtime 无法确定 UTC 时为 null。
- 现有 Slurm 本人查询未提供申请内存、开始时间、提交时间、walltime 上限；本单未获准扩展该命令，这些字段及非空作业组的内存合计为 null，耗时来自已有的 `%M`。

## 真实验证记录（2026-10-23）

- 基线 `47aef3f` 加本任务源码；五个变更源码在启动前保存 SHA-256，结束后复核字节未变。原始输出与快照仅留本地仓库外临时目录，不提交原文。
- 使用实际配置的副本，`studies_root` 指向临时空目录，`watch=30` 运行 600.01 秒；常驻监控未替换、未停止，原配置前后字节一致，没有提交、取消或远程文件写入。
- default / newhpc 各 20 次、scnet / scnet-test 各 10 次，共 60 次 `ok=true`。各入口新字段完整，首份 PBS 明细条数与同次 qstat 原文一致，Slurm 汇总与同次匿名分区 squeue 逐行计数/CPU 求和一致。
- PBS 节点总 CPU 与原文核对一致；Slurm A/I/O/T 与原文核对一致，AllocMem 可用且合计一致。Slurm 不保存节点行；异构最小内存不能推导准确总量，按约定为 null。

| 入口 | sample_duration_ms 最小–最大（中位） | interval_seconds | sampled_at 实测间隔秒 最小–最大（中位） |
| --- | --- | --- | --- |
| default | 922–1317（1107） | 30 | 30–30（30） |
| newhpc | 680–1009（839.5） | 30 | 30–30（30） |
| scnet | 7561–10851（7882） | 60 | 59–61（60） |
| scnet-test | 7473–10132（7847） | 60 | 57–62（60） |

间隔以秒精度的 sampled_at 计算；Slurm 实测起点受前序串行查询耗时影响。没有通过并发采样压缩耗时。两个 PBS 入口本次全程为空队列，真实作业时间文本/时区仍未验证；非空 PBS 作业行为由合成测试覆盖。

## 离线验证与交付

- 推送前全量：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs -p no:cacheprovider`，Python 3.11；4534 通过、19 跳过，耗时 829.48 秒，无失败。跳过为未启用的私有日志与 macOS 缺少的 Linux procfs/GNU stat 检查，后者由 Linux CI 执行。
- 敏感信息扫描与 `git diff --cached --check` 通过；额外按 AST 核对已有 remote 函数/类源文逐字未变，仅新增三个固定只读函数。
- 相关已有测试逐个列明：`ag/tests/test_monitor.py`、`ag/tests/test_slurm.py`、`ag/tests/test_clusters.py`、`ag/tests/test_resources_monitor.py`；新建 `ag/tests/test_monitor_all_jobs.py`。没有修改提交安全检查或测试阈值。
- 给 T115 的 `docs/ag-monitor-1.md` 增补补丁附于 PR 描述，并在临时文档副本执行 `git apply --check`；未修改前端仓库。
- 待监督方审阅新增远程命令；负责人决定合并。实际配置、LaunchAgent 和日常运行版本尚未部署本改动。

## 监督方审阅跟进（2026-10-23）

- 负责人转来的监督方审阅通过 `8405714`，并要求本 PR 修正无时间信息时的作业号排序。现将最后的排序键改为 PBS 序号的整数值，完整作业号仅作同序号的稳定次序；本人优先、运行/排队分组和有效时间排序保持不变。
- 合成回归分别覆盖 R/Q 两种状态：本人作业优先，其余无时间作业按 `999`、`1000` 排列。只改本地显示排序，无新增远程查询。
- 复测 `test_monitor_all_jobs.py`、`test_monitor.py`、`test_pbs_arrays.py`：266 通过，19.92 秒；首次全量已完成，此次按仓库规则仅重跑相关测试，最终全量以新 head 的 CI 为准。
- 建议 2–4 留待后续：AllocMem 解析失败时保留 CPU、公共分区查询失败的降级、Slurm 本人内存字段。本 PR 保持已审阅的失败语义及远程命令。
- 建议 5 待合并后下一次 PBS 有真实作业时补验证：只读核对 qstat 时间字段，仅把脱敏格式写入 PR 评论；若只有无时区文本，另开小单处理服务器本地时间显示。本次未新增真实查询或常驻监控改动。
