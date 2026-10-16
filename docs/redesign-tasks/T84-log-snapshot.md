# T84：`ag snapshot` 运行中作业日志的只读快照

## 分支与目标

- 分支：`codex/t84-log-snapshot`；基于最新 main，一张任务单一个 PR。**开发机做。**
- **开工条件：** 占用 T79 的那条线，T79 合并后开工（T79 合并前如有空闲线也可提前）。
- **来源：** HSS 主会话（10-16）需要查看运行中 Attempt 的 Gaussian 日志（例如优化进度、收敛表），负责人已授权读取；但现有 ag 没有这个入口，仓库规则又要求远程操作只能经 ag，不能自行拼 SSH/SCP。目前只能等作业结束再取回，或由负责人手动导出。
- **目标：** 新增 `ag snapshot`，对**已提交、尚未取回**的 Attempt，只读复制其程序日志的当前内容到本地快照目录，并给出简短的进度摘要。快照**不是取回**：不写 `outputs/`，不改 Attempt 状态、journal、取回标记和 facts，不影响之后的正常 `ag fetch`。
- **属于远程命令改动：** 必须审阅，并在合并前完成真实验证（DEVELOPING 规则；吸取 T62 教训）。
- 资料：`ag/src/ag/remote.py`（`path_checks`、`contained`、`attempt_dir`、`metadata`、`output_names`、`incomplete_output_observation` 的写法）、`ag/src/ag/transport.py`、`ag/src/ag/fetch.py`（取回范围和标记，作为“不能碰”的对照）、`ag/src/ag/status.py`。

## 允许改动的路径

- 新增 `ag/src/ag/snapshot.py`。
- `ag/src/ag/remote.py`：只**新增**一个只读命令构造函数（例如 `log_snapshot`），不改已有函数。
- `ag/src/ag/cli.py`：登记 `snapshot` 命令（按现有执行类命令的登记方式）。
- `ag/tests/test_smoke.py`：**已预先批准**，只在命令列表断言中追加 `snapshot`。
- 新增 `ag/tests/test_snapshot.py`（用假 Transport）。
- `ag/README.md`：命令一节；`skills-next/auto-g16-recipes/cards/failure-diagnosis.md`：只在“查看运行中作业”相关处补一句用法（如无合适位置，改为写进 `ag/README.md`，卡片不动）。
- `docs/redesign-tasks/T84-log-snapshot.md`：本任务单。
- **不改 `fetch.py`、`submit.py`、`status.py`、`transport.py`、模板。**

## 要做的

1. **命令：**
   ```
   ag snapshot <Attempt> [--study <study>] [--max-bytes 20000000] [--json]
   ```
   - 只接受本地记录为已提交（有作业号）且未完成取回的 Attempt；已取回的拒绝，提示直接看 `outputs/`。
   - 读取的文件只限该模板的主程序日志（Gaussian 为 `job.log` 或模板规定的日志名；xTB、CREST 为各自的主输出），文件名取自现有的输出名单（`output_names`），**不接受用户传入的路径**。
2. **远程命令（只读）：** 在 `attempt_dir` 下、经 `path_checks` 和 `contained` 校验；拒绝符号链接和非普通文件；先取大小与修改时间，再读取内容；超过 `--max-bytes` 时只取**末尾** `--max-bytes` 字节并标记 `truncated: true`。只用 `stat`、`tail -c`、`cat`、`sha256sum` 这类只读命令；不写远程任何文件，不在远程生成临时文件。
3. **本地写出：** `<Attempt>/snapshots/<UTC 时间戳>/` 下写日志副本和 `snapshot.json`（时间、远程大小、修改时间、读取字节数、是否截断、本地 SHA-256、作业号、`ag status` 的最近状态）。每次快照新建目录，不覆盖旧快照。`ag facts`、`ag fetch`、`ag review manifest` 都不读取 `snapshots/`（写测试确认）。
4. **进度摘要（打印，并写进 `snapshot.json`）：** 只做文本统计，不调用完整的 facts 解析：`SCF Done` 次数和最后一个能量；优化步数（`Step number`）；最后一个收敛表（四项 Converged? 原文）；最后一次 `Normal termination` / `Error termination`；Freq 是否已开始。明确标注“运行中快照，不是结果，不能用于签字或分析”。
5. **ssh-log：** 经现有 transport 调用，自动记录，不另写日志。

## 不允许

- 不写 `outputs/`；不改任何状态、标记、journal；不触发取回或 facts。
- 不接受任意远程路径；不跟随符号链接；不在远程写文件。
- 快照内容不进入证据清单，不作为任何签字依据。

## 测试

- 假 Transport：正常快照、超过上限时截断、远程文件是符号链接或不存在、Attempt 未提交 / 已取回时拒绝、路径越界被拒、连续两次快照生成两个目录。
- `ag fetch`、`ag facts`、`ag review manifest` 在存在 `snapshots/` 时行为和输出不变。
- 远程命令字符串只含只读命令且正确转义。
- 开发中只跑相关测试；推送前本地跑一次全量 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，之后以 CI 为准。敏感扫描与 `git diff --cached --check`。

## 真实环境验证（合并前，开发机）

- 在**非研究 study** 中准备一个会运行几分钟的小作业（例如小分子 Opt+Freq，少核数），由负责人确认提交，只提交一次。
- 运行期间做两次 `ag snapshot`：确认得到日志副本、摘要合理、第二次的大小不小于第一次；`ag status` 结果不受影响。
- 作业结束后正常 `ag fetch`：取回的 `outputs/` 和 facts 与没有快照时一致（与同类作业的预期一致，不出现快照文件）；ssh-log 有对应记录且已脱敏。
- 组里集群（PBS）和 SCNet（Slurm）各验证一次；时间不允许时至少一个，并在 PR 中说明。
- 结果写进 PR 评论，不写主机、路径和用户名。HSS 不作为验证对象。

## 停止条件

- 需要改 `fetch.py`、`status.py`、`transport.py` 或模板。
- 无法在不写远程文件的前提下实现截断读取。
- 真实验证中任何一次快照影响了作业状态或之后的取回。

## 合并前审阅与交付

- 需要监督方审阅：是（远程命令）。
- PR 描述第一行：`Task: T84`；附远程命令清单和真实验证结果。
- 合并只由负责人操作。
