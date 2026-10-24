# T124：PBS 调度器时区——把 qstat 的文本时间换算成准确时间

版本：v1.1（负责人实测更正 Z2，2026-10-24）。**开发机做。** 后端出一个 PR，PR 描述第一行写 `Task: T124`。

## 分支与目标

- 分支：`codex/t124-pbs-timezone`。
- **开工条件：** **T123 合并之后**再开工（两单都改 `monitor.py`）；以当时最新的 main 为基线。和前端 T121、T122 不冲突。
- **背景：** T123 的 K7 只读核对发现，default 和 newhpc 的 `qstat -f` 里，`start_time` 和 `qtime` 都是没有时区的文本（格式为"星期缩写 月份缩写 日 HH:MM:SS 年"），没有 `stime`。按 T114 的规则，这种时间不猜时区，所以现在开始时间和提交时间都是 null，已运行时间退回用 `resources_used.walltime`（会落后几分钟），排队作业按作业号排序。
- **负责人 2026-10-24 决定：**
  - Z1 每个 PBS 入口可以配置 `scheduler_timezone`（IANA 时区名）。配置了的入口按这个时区解析文本时间，再换算成 UTC；没配置的入口保持现在的行为不变。
  - Z2 负责人 2026-10-24 实测更正：default 的 `scheduler_timezone` 为 `America/New_York`，newhpc 为 `Asia/Shanghai`。原“两台均为 Asia/Shanghai”的确认已由本次更正取代；必须使用 IANA 时区名，不填固定偏移。**合并后**才更新开发机正式配置，先备份，再重启常驻监控一次。合并前只使用隔离配置副本验证。
- **监督方细化：**
  - Z3 解析不依赖本机 locale：月份和星期缩写用固定的英文表；日期允许用空格补齐（例如 `Oct  4`）；星期和日期对不上时，按解析失败处理，写 null。
  - Z4 防止时区填错：同一作业既有开始时间又有 `resources_used.walltime` 时，如果按开始时间算出的已运行秒数**比 walltime 少 120 秒以上**，或者**多出 1 小时以上**，就判定时区可能不对。这时该作业改用 walltime，在 `warnings` 里加一条 `kind="timezone-mismatch"`（每个入口每轮最多一条，不写作业名和用户名）。开始时间晚于采样时间超过 120 秒时，同样处理。
- **资料：** `ag/src/ag/pbs.py`（`timestamp`、`job_fields`）、`ag/src/ag/monitor.py`（`observation`、`job_sort_key`）、`ag/src/ag/config.py`（`validate_cluster`、旧式配置迁移那一段）；T114、T123 任务单。

## 允许改动的路径

- `ag/src/ag/pbs.py`：文本时间解析，`job_fields` 增加时区参数。
- `ag/src/ag/monitor.py`：把入口的时区传进去；Z4 的检查和警告；快照字段 `cluster.scheduler_timezone`。
- `ag/src/ag/config.py`：PBS 入口新增可选项 `scheduler_timezone`（用 `zoneinfo.ZoneInfo` 校验）；旧式配置迁移的键列表加上它；Slurm 入口不接受这个键。
- 测试：`ag/tests/test_monitor_all_jobs.py`、相关的配置测试（PR 中逐个列出）。
- 文档：`ag/config.clusters.example.toml`（示例写 `"Asia/Shanghai"`）、`README.md`、`docs/LESSONS.md`；本单 `docs/redesign-tasks/T124-pbs-timezone.md`、`docs/redesign-tasks/open-tasks.txt`。
- 前端文档补丁：`cluster.scheduler_timezone`（字符串或 null）和 `warnings` 新增的 `timezone-mismatch` 写在 PR 描述里，由前端下一张单（T122 还没合并时由 T122）合入 `docs/ag-monitor-1.md`。

## 要做的

1. **解析（Z1、Z3）**：`pbs.timestamp(value, tz=None)`：
   - epoch 和带时区的 ISO：照旧；
   - 文本格式：只有在 `tz` 不为空时才解析，先作为本地时间，再换算成 UTC。遇到夏令时导致的重复时间或不存在的时间，写 null（`Asia/Shanghai` 没有夏令时，但代码要能处理一般情况）；
   - 没有配置时区：文本时间照旧写 null。
2. **作业字段**：`start_time`、`qtime` 按上面的规则得到 UTC ISO；`elapsed_seconds` 优先用"采样时间 − 开始时间"，`elapsed_source="start_time"`；Z4 触发时退回 walltime。
3. **排序**：`job_sort_key` 不用改，拿到 `qtime` 后自然按提交时间排序。
4. **快照**：`cluster.scheduler_timezone` 写配置值或 null。只做加法。
5. **配置校验**：时区名无效 → 配置错误；写在 Slurm 入口上 → 配置错误；旧式单集群配置能被迁移。

## 不允许

- 不改任何远程命令，不新增 SSH。
- 不猜时区：没配置的入口保持现状。
- 不改开发机配置和常驻监控（合并后再做）。
- 夹具只用合成的 qstat 文本（虚构作业号、用户名和节点名），不出现真实数据。

## 测试

| 场景 | 预期 |
|---|---|
| `Sat Oct 24 09:12:00 2026`，时区 `Asia/Shanghai` | `2026-10-24T01:12:00Z` |
| 日期用空格补齐（`Sun Oct  4 …`） | 正确解析 |
| 星期和日期对不上 / 月份缩写不认识 | null |
| `America/New_York`，2026-11-01 回拨区间及相邻边界 | 01:00:00–01:59:59 均为 null；00:59:59、02:00:00 及之后正确转换 |
| 没有配置时区 | 文本时间为 null，行为与 T123 相同 |
| epoch、带时区的 ISO | 不受影响 |
| 有开始时间、时区正确 | `elapsed_source=start_time`，与 walltime 相差在阈值内 |
| 时区填错（算出的值比 walltime 少 120 秒以上，或多 1 小时以上） | 改用 walltime，`warnings` 有一条 `timezone-mismatch`，不含作业名和用户名 |
| 开始时间晚于采样时间超过 120 秒 | 同上 |
| 排队作业有 `qtime` | 按提交时间排序；`qtime` 相同时再按作业号 |
| 时区名无效 | 配置错误 |
| Slurm 入口写了 `scheduler_timezone` | 配置错误 |
| 旧式单集群配置带这个键 | 迁移后生效 |
| 快照 | 带 `cluster.scheduler_timezone` |

推送前本地跑一次全量 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，之后以 CI 为准；同时运行 `python scripts/scan_public.py` 和 `git diff --cached --check`。

## 真实环境验证（合并前，开发机；不提交作业）

- 复制一份配置，给 default 加上 `scheduler_timezone = "America/New_York"`、newhpc 加上 `scheduler_timezone = "Asia/Shanghai"`，把 `studies_root` 指向临时目录，临时启动监控 `--watch 30`，运行 5 分钟。**不替换常驻监控。**
- 确认：运行中作业的 `elapsed_source` 变成 `start_time`，并且与 walltime 的差在阈值内；没有出现 `timezone-mismatch`；排队作业有 `qtime`。
- PR 里只写"字段齐全 / 差值范围 / 有没有警告"，不贴作业内容和时间值。出现异常就停下汇报。

## 停止条件

- 真实输出的时间格式和 K7 记录的不一致；需要改远程命令；需要改动范围外的文件；同一问题修两次仍未解决。

## 合并前审阅与交付

- 需要监督方审阅：**是**（监控数据）。合并只由负责人操作。
- PR 描述包括：Z1–Z4 各自对应的改动、阈值说明、全量测试结果、真实验证记录、给前端的文档补丁。
- **合并后：** 开发机同步；在开发机配置里给 default 加上 `scheduler_timezone = "America/New_York"`、newhpc 加上 `scheduler_timezone = "Asia/Shanghai"`（改之前先备份），常驻监控重启一次，确认没有 `timezone-mismatch` 警告。研究用计算机在发版同步时一起加。

## 版本记录

- v1.1（2026-10-24，负责人实测更正）：Z2 改为 default=`America/New_York`、newhpc=`Asia/Shanghai`；同步隔离验证及合并后配置步骤，补充纽约夏令时回拨边界测试。解析实现、Z4 阈值和远程命令均不变。
- v1（2026-10-24，监督方）：依据 T123 的 K7 核对结果和负责人 10-24 决定 Z1、Z2 起草；Z3、Z4 为监督方细化。

## 实施与离线验证（2026-10-24）

- 基线为 T123 已合并的 main `8ab8b91`，分支 `codex/t124-pbs-timezone`。实现 Z1–Z4，未更改远程命令或作业操作。
- 时区检查仅在 PBS 入口显式配置后启用，未配置时保留旧行为。异常作业保留解析出的 start_time，elapsed_seconds 退回 walltime；walltime 缺失时 elapsed_seconds 和 elapsed_source 均为 null。阈值严格使用“超过”，相等不触发。
- 初始、成功和失败快照均补 scheduler_timezone；失败时该字段取当前有效配置，旧作业数据仍按 last_ok_at 判断，不重新解释或计算旧样本。
- 测试改动仅有 `ag/tests/test_monitor_all_jobs.py` 和配置相关的 `ag/tests/test_clusters.py`，使用合成数据覆盖文本、日期/星期、夏令时重复/缺口（含半小时）、阈值、匿名单条警告、排序、配置迁移和快照恢复。
- 首轮定向回归发现新增合成文本重复提供 start_time，已修正夹具；修正后 223 passed。补充兼容性与 locale 回归后一并进入全量测试。
- Python 3.11.15；推送前全量仅跑一次 `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs -p no:cacheprovider`：**4723 passed、19 skipped，387.15 秒，退出码 0**。18 项 GNU/Linux 专属检查交 Linux CI，1 项私有日志未启用。
- 全仓库扫描 1790 文件、0 错误；暂存区加本机私有词表扫描 9 文件、0 错误；`git diff --cached --check` 通过。提交者与作者身份均核对为 noreply。
- 前端字段说明放在 PR 描述；实际配置与常驻监控仍待合并后安排。没有研究数据或现场快照进入仓库。

## 真实验证停止记录（2026-10-24，未通过）

- 以配置副本、空的临时 studies_root 调用正式监控循环，watch=30，计划运行 300 秒。副本内为 default/newhpc 设置 Asia/Shanghai，原配置及常驻监控未改。
- **首轮 default 触发 timezone-mismatch，1.79 秒即按工单停止**，未重试；newhpc 及两个 Slurm 入口均未采样，不能声称完成五分钟验证。
- 已保存的本地快照中时间字段齐全；“采样时间减开始时间”与 walltime 的差值范围为 **+43,263 至 +43,263 秒**，超过 +3600 秒阈值。未出现开始时间晚于采样时间超过 120 秒的情形。快照中该作业已按设计退回 walltime。
- 仅离线读取已保存的本地快照形成上述汇总，未追加远程查询。原因尚未确定，不能把警告认定为已经证实的时区错误；没有放宽阈值或改动已确认时区。
- 执行前后原配置和源码哈希一致。pbs.py：`75a7111e0cb16060dcc30de40fa69b6a1e3dfcd384cf9bbbd611185374304187`；monitor.py：`e1b4788f7ac4a994511871b08b7f43918ac35960193a924f21422f5565febc00`；config.py：`0092637fa3932b526be9003a0c15d6a329fe7c2dc14d1a6134525638d1dd6cce`。
- 当时阻塞类别：**环境核对**。负责人随后于 2026-10-24 实测更正 Z2，并授权使用隔离配置副本重新验证；本段保留首轮未通过的历史记录，复验结果另记。


## Z2 更正后的复验（2026-10-24，通过）

- 按负责人当日实测更正，仅更新本单副本、示例注释及 `ag/tests/test_monitor_all_jobs.py`；解析实现、Z4 阈值和远程命令未改。
- 新增纽约 2026-11-01 夏令时回拨测试：重复小时内全部 3600 秒均为 null，回拨区间前一秒和结束边界及后一秒均正确转换。
- 定向测试 **152 passed**；本轮推送前全量 **4724 passed、19 skipped，349.72 秒，退出码 0**。18 项 GNU/Linux 专属检查由 Linux CI 补足，1 项私有日志未启用。
- 使用配置副本、空临时 studies_root，仅采样 default/newhpc。副本按更正后的 Z2 配置，调用正式监控循环，watch=30，完整运行 **300.00 秒**。两入口各完成 **10 轮**，运行中作业的时间字段齐全，`elapsed_source` 全部为 `start_time`。

| 入口 | 按开始时间所得耗时减 walltime 的范围（秒） | timezone-mismatch | 排队字段覆盖 |
|---|---:|---|---|
| default | +16 至 +86 | 无 | 观察到排队作业，qtime 齐全 |
| newhpc | -77 至 -3 | 无 | 窗口内无排队作业，该场景未覆盖 |

- 全部差值处于原 Z4 阈值内；两入口全部警告数均为 0，未出现采样、配置、硬件或连接错误。未提交、取消或修改远程作业，原始快照及连接记录仅存仓库外临时目录。
- 执行前后正式配置、常驻监控 plist 及三个实现源码文件均未变，常驻监控主进程未替换。源码哈希与上文首轮记录一致。
- 当前无开发或真实验证阻塞；监督方审阅、人工合并仍待完成。合并后再备份并更新开发机正式配置，常驻监控重启一次；本次未提前部署。
