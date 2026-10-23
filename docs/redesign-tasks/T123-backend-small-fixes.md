# T123：后端小修合集——监控容错、Slurm 本人内存、catalog 锁名与类别、扫描文档

版本：v1（监督方，2026-10-24）。**开发机做。** 后端出一个 PR，PR 描述第一行写 `Task: T123`。

## 分支与目标

- 分支：`codex/t123-backend-small-fixes`。
- **开工条件：** 以后端 main（不早于 `8d2afb0`）为基线。和 T117 并行（不改同一个源文件）。
- **来源：** T114、T116、T119、T118 审阅中记下的非阻塞问题，负责人 2026-10-24 同意放进 B 批一起修。
  - K1（T114 审阅 #2）`AllocMem` 解析或查询失败时，现在整个 `hardware` 都被清空。改为只把 `mem_allocated_gb` 写成 null，核数等已经拿到的值保留，原因写进 `hardware.error`。
  - K2（T114 审阅 #3）分区 `squeue` 失败时，现在整轮 Slurm 采样失败，本人数据也一起丢掉。改为：本人作业照常采样，`ok` 不受影响；`job_summary` 中的分区汇总和 `others_*` 写 null；新增 `cluster.job_summary_error`（字符串或 null，经 `redact_stderr` 处理）。**本人的 `squeue` 失败仍然让本轮失败**，这一点不变。
  - K3（T114 审阅 #4）Slurm 本人作业的内存：作业关联到本机 Attempt 时，取该 Attempt manifest 记录的档位内存（GB）作为 `mem_gb`，并新增 `mem_source = "manifest"`；没有关联的写 null。**不改**现有 `squeue` 命令的格式（submit 和 status 都依赖它）。PBS 作业的 `mem_source` 写 `"scheduler"`。
  - K4（T119 审阅 #3）catalog 的锁文件从 `catalog/submit.lock` 改名为 `catalog/catalog.lock`，读锁和写锁同步改。旧文件不删也不读。
  - K5（T118 复审）`ag catalog report-kind` 的可选类别加上 `coverage`、`ts`、`nci`，与前端报告类别保持一致；同步更新 `docs/ag-catalog-1.md`。
  - K6（T116 审阅）`docs/DEVELOPING.md`、`README.md`、`.github/pull_request_template.md` 里提到旧扫描命令 `ag/tools/scan_sensitive.py` 的地方，改为 `scripts/scan_public.py`（`--staged` 用法照新脚本的实际参数写）。旧工单副本是历史记录，**不改**。旧脚本保留，在文件开头注明"已由 scripts/scan_public.py 取代"。
  - K7（T114 审阅 #5）**只读核对**：验证时如果 default 或 newhpc 上恰好有真实作业在运行，读一次 `qstat -f`，确认 `start_time`、`stime`、`qtime` 的格式（是文本还是 epoch、带不带时区），把**格式**写进 PR，不写数据。只有文本时间时，本单不改代码，由监督方另行决定。没有真实作业就写"本次未遇到运行中的作业"。
- **资料：** `ag/src/ag/monitor.py`（`slurm_partition`、`slurm_observation`）、`ag/src/ag/slurm.py`、`ag/src/ag/catalog.py`；前端仓库 `docs/ag-monitor-1.md`。

## 允许改动的路径

- `ag/src/ag/monitor.py`：K1–K3。
- `ag/src/ag/slurm.py`：只在 K1、K2 需要时改。
- `ag/src/ag/catalog.py`：K4、K5。
- `ag/tools/scan_sensitive.py`：只在文件开头加一行说明（K6）。
- 测试：`ag/tests/test_monitor_all_jobs.py`、`ag/tests/test_catalog.py`（加用例）。
- 文档：`docs/ag-catalog-1.md`、`docs/DEVELOPING.md`、`README.md`、`.github/pull_request_template.md`、`docs/LESSONS.md`；本单 `docs/redesign-tasks/T123-backend-small-fixes.md`、`docs/redesign-tasks/open-tasks.txt`。
- 前端文档补丁：`cluster.job_summary_error`、`mem_source` 两个新字段的说明写在 PR 描述里，由 T122 合入前端 `docs/ag-monitor-1.md`。

## 要做的

- K1–K7 逐条照上面的写法实现。快照只做加法，原有字段的含义不变。
- K3：从 manifest 取内存时，必须用关联到的那个 Attempt 的精确记录，不按作业名去猜。manifest 里没有记录内存（旧 Attempt）就写 null，不从当前配置的档位反推。
- K4：改名前后各有一个进程时，不能出现两边各自加锁的情况。直接改名即可，因为锁文件只在命令运行期间存在，不需要兼容旧名。

## 不允许

- 不改任何远程命令，不放宽白名单。
- 不改提交、取消、状态流程，不改 `squeue` 的输出格式。
- 不改 catalog 日志的格式和已有事件；不修复或重写日志。
- 不改旧工单副本。

## 测试

| 场景 | 预期 |
|---|---|
| `sinfo` 成功、`AllocMem` 失败 | 核数保留，`mem_allocated_gb=null`，`hardware.error` 写原因 |
| 分区 `squeue` 失败、本人 `squeue` 成功 | `ok=true`；本人作业照常；汇总为 null；`job_summary_error` 有值 |
| 本人 `squeue` 失败 | `ok=false`（行为不变） |
| Slurm 本人作业关联 Attempt | `mem_gb` 等于 manifest 档位内存，`mem_source=manifest`；`own.mem_running_gb` 能算出来 |
| Slurm 本人作业没有关联 | `mem_gb=null` |
| catalog 写入 | 锁文件为 `catalog/catalog.lock`；读锁用同一个文件 |
| `report-kind --kind coverage|ts|nci` | 接受；旧日志回放不受影响 |
| 文档 | 不再把旧扫描脚本写成当前用法 |

推送前本地跑一次全量 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，之后以 CI 为准；同时运行 `python scripts/scan_public.py` 和 `git diff --cached --check`。

## 真实环境验证（合并前，开发机；不提交作业）

- 用配置副本和临时 `studies_root` 临时启动一次监控（`--watch 30`，运行 5 分钟），确认四个入口的新字段正常。**不替换常驻监控。**
- 按 K7 只读核对 PBS 的时间格式。
- PR 里只写结果和格式，不贴快照或作业内容。出现异常就停下汇报。

## 停止条件

- K3 需要改 `squeue` 格式，或者需要按作业名匹配 Attempt；需要改动范围外的文件；同一问题修两次仍未解决。

## 合并前审阅与交付

- 需要监督方审阅：**是**（监控和 catalog）。合并只由负责人操作。
- PR 描述包括：K1–K7 各自对应的改动、新增字段说明（给前端）、全量测试结果、真实验证与 K7 的核对结果。
- **合并后：** 开发机同步，常驻监控重启一次。

## 版本记录

- v1（2026-10-24，监督方）：汇总 T114、T116、T118、T119 审阅中的非阻塞问题起草。

## 实施补充（2026-10-24）

- 范围补充：负责人在本任务会话批准“允许这一处测试同步”。允许在 `ag/tests/test_monitor.py` 的 `test_snapshot_exact_association_and_no_study_mutation` 预期字典中增加 `mem_source='scheduler'`，不作其他修改。该测试原来精确比较整条字典，新增字段使其失败。
- K4 源码核对：锁文件本身会保留，命令结束时释放的是 `flock`。本单仍按要求直接使用 `catalog/catalog.lock`，旧文件不读取、不删除；升级前等待所有旧版 catalog 命令退出，防止新旧进程持有不同锁。没有改全局提交锁或增加旧锁兼容路径。
- K6 基线核对：`docs/DEVELOPING.md` 已使用新扫描器，本单保持其内容；README 修正旧命令，PR 模板补明实际 `--staged` 用法，旧脚本仅加替代说明。

## 真实验证结果（2026-10-24，合并前）

- 使用配置副本、空的临时 studies_root 和本分支代码调用正式监控入口（watch=30），运行 300 秒。原常驻监控及研究目录未修改，没有提交/取消作业；现场缓存留在仓库外。
- 四入口均成功：两个 PBS 入口各 10 次、两个 Slurm 入口各 5 次；Slurm 按现有 60 秒最短间隔采样。新增字段类型和局部错误字段正常，未遇到连接、解析或快照异常。
- K7：两个 PBS 入口均遇到运行中的作业；复用首次相应正式 `qstat -f` 查询核对格式。`start_time`、`qtime` 均为“星期缩写 月缩写 日 HH:MM:SS 年”的文本，无时区；`stime` 缺失。不记录值，不改时间解析代码。
- 临时 studies_root 无真实 Attempt，Slurm manifest 内存来源由合成绑定测试验证；现场只验证无关联时保持 null，不能据此声称已验证真实 Attempt 内存绑定。
- 执行源码 SHA-256：monitor.py 为 `7f3ec0b371ac200b31bebfa2975cc0fa65cfc69f1c549215b4054738db6986ab`；catalog.py 为 `98a6450ab317759d92a61de7fdff063917e57282c9474cdbd701b813ee6f1c9b`。

## 离线验证结果（2026-10-24）

- Python 3.11.15；全量仅执行一次 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`：4605 passed、19 skipped，384.30 秒，退出码 0。18 项 Linux 专属检查由 Linux CI 覆盖，1 项私有日志测试未启用。
- 定向回归初次为 197 passed、1 failed；失败仅为上述获批同步的旧整字典预期。全量测试已覆盖修正后的断言。
- `python scripts/scan_public.py`：1786 文件、0 错误；暂存内容加本地私有词表扫描：11 文件、0 错误；`git diff --cached --check` 通过。
- 无实现或环境阻塞；监控和 catalog 待监督方按 PR 当前 head 审阅，合并与合并后常驻监控重启由负责人安排。
