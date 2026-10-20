# T102：取回改按传输进度判断、取消后取回日志、确认框按钮文字

版本：v1.1（监督方，2026-10-20；末尾记录获批测试范围补充，v1 要求保留）。**开发机做。** 一个后端 PR，PR 描述第一行 `Task: T102`。

## 分支与目标

- 分支：`codex/t102-fetch-stall-cancelled-confirm`。
- **开工条件：** 后端 main 为 `76d5d15`（T101）或其后；T102 编号未被占用；没有与本单路径冲突的未合并 PR。
- **目标（负责人 10-18 定下的下一轮修复第 2、4 项，以及 10-19 新增的第 7 项）：**
  1. 取回单个文件不再固定 60 秒超时，改为**一段时间内没有任何进展**才判定超时。
  2. 由 `ag cancel` 取消的作业，也可以用 `ag fetch --incomplete` 取回已有输出（HSS 024 就是这个情况）。
  3. 提交和取消两个确认框的按钮改成不会混淆的文字。
- **资料：** `AGENTS.md`（尤其第 3 节第 4 条、第 5 节）、`docs/LESSONS.md`、T52/T62/T65/T66 任务单；`transport.py`、`fetch.py`、`status.py`、`cancel.py`、`confirm.py`、`state.py`。

## 背景（main `76d5d15` 的代码现状）

1. `SSHTransport.download()` 调用 scp 时写死了 `timeout=60`。在 RTwin 中继上（约 30–70 KB/s），几 MB 以上的文件必然超时，而且超时被归类为连接错误，触发"停下汇报"。`upload()` 也是 60 秒，但上传的只是小输入文件，本单不改。
2. 每次重试都写到新的临时目标；取回结束后逐个文件核对哈希。这个设计要保留。
3. `_incomplete()` 要求 Slurm 作业处于 `finished`、PBS 作业处于 `interrupted`，`cancelled` 一律拒绝。024 是负责人确认后用 `ag cancel` 取消的 PBS 作业，状态为 `cancelled`，日志至今取不回。
4. `cancel.py` 会写 `.cancel-claim`，并在 journal 里记一条 `cancel … succeeded {job_id}`，然后把状态置为 `cancelled`。
5. `confirm.py` 两个框共用同一个模板，不安全一侧的按钮固定叫"取消"；取消作业的框里，另一个按钮叫"取消作业"，两者容易点混。默认按钮和 Esc 都落在安全一侧，这一点没问题。

## 允许改动的路径

- `ag/src/ag/transport.py`：只改 `download()` 的执行和超时判断，以及相应的日志记录。
- `ag/src/ag/fetch.py`：`_incomplete()` 和 `_end_evidence()` 接受符合条件的 `cancelled`。
- `ag/src/ag/status.py`：只在第 2 节选"由 status 记录观察"时才改，并且只为 `cancelled` 增加与 `interrupted` 相同的只读观察。
- `ag/src/ag/confirm.py`、`ag/src/ag/cancel.py`：只改按钮文字、图标和提示文字。
- `ag/tests/test_fetch.py`、`ag/tests/test_incomplete_fetch.py`，新建 `ag/tests/test_confirm_labels.py`。
- `docs/LESSONS.md`（加一条）、`README.md`（已知限制里删去 60 秒的说明）。
- `docs/redesign-tasks/T102-fetch-stall-cancelled-confirm.md`（本单）、`docs/redesign-tasks/open-tasks.txt`。

## 要做的

### 1. 下载按进度判断超时

- 用可轮询的方式运行 scp，至少每 5 秒检查一次本地临时目标文件的大小。**连续 60 秒大小不变**（包括建立连接、还没收到第一个字节的阶段）就判定超时：先发终止信号，还不退出就强制结束。错误类别与现在的超时相同，"停下汇报、不自动重试写操作"的规则不变。
- 只要还在持续收到数据，就不设总时长上限。为防止进程永远不退出，设一个兜底上限：24 小时。
- 60 秒和 24 小时写成 `transport.py` 里的模块常量，不新增配置项。
- 不做断点续传。每次重试都从头传到新的临时目标，最终仍逐文件核对哈希。原因：续传需要 rsync 之类的新远程命令，不在白名单内。PR 里写明这一点，作为以后可选的改进。
- 本地 SSH 日志在"超时"的细分原因里区分 `stalled`（无进展）和 `hard_limit`（到兜底上限），并记录已传字节数。这两项都不含敏感信息。
- `upload()` 保持不变。

### 2. 已取消作业的不完整取回

- `--incomplete` 在以下条件**同时**满足时接受 `cancelled`：
  - 存在 `.cancel-claim`；
  - journal 中有本 Attempt 的 `cancel succeeded` 记录，且其中的 job_id 与当前绑定的作业一致；
  - `submission.verified_job()` 校验通过。
- **Slurm：** 沿用现有证据——精确作业不在 squeue 中，sacct 返回唯一一行，且为受支持的终态（应为 `CANCELLED`）。
- **PBS：** 用精确作业号查 qstat，作业不存在，或作业状态为 `C` 且作业名一致；不存在 `ag-exit.json`。另外，输出文件的大小和修改时间要观察两次、间隔至少 300 秒、两次结果相同。观察可以由 `ag status` 写进 `incomplete_observations`（规则与 interrupted 相同），也可以在 fetch 内部完成并显示进度。两种方式选一种，PR 里说明理由。两种都必须满足：至少两次观察，间隔不少于 300 秒。
- 如果 `ag-exit.json` 存在，就拒绝，并提示改用普通 status/fetch。
- 取回后的记录、`.partial` 暂存、不覆盖已有输出等行为，与 interrupted 的不完整取回完全相同。**状态仍然是 `cancelled`**，不新增状态转换。如果确实需要新增，先停下申请。
- 只取回 manifest 声明的输出文件，不新增远程命令。

### 3. 确认框按钮文字

- **取消作业框：** 两个按钮改为「**保留作业**」和「**终止作业**」；默认按钮和 Esc 都是"保留作业"；加警告图标（`with icon caution`）。提示最后一行改为："点「终止作业」将停止 `<集群>:<作业号>`，不会自动重提；点「保留作业」或按回车保持运行。"
- **提交框：** 安全一侧的按钮从"取消"改为「**不提交**」；动作按钮仍叫"提交"；默认按钮和 Esc 是"不提交"。
- `confirm()` 的调用方式和返回值不变；仍只接受这两种动作；超时 300 秒视为未确认。不增加任何绕过确认的参数、环境变量或配置（AGENTS.md 第 3 节第 4 条）。

## 不允许

- 不改上传、提交、取消的流程和核数检查；不改状态转换表（第 2 节说明的情形除外，需要先申请）。
- 不新增远程命令或远程写入；不做续传；不放宽哈希核验。
- 不自动重试写操作；不把 `stalled` 当作可以自动恢复的情况。
- 不碰 HSS 数据。024 的取回放在合并后，由负责人另行授权 HSS 会话执行。

## 测试

只用合成数据和假 Transport，不连接真实集群。

| 场景 | 预期 |
|---|---|
| 假 scp 缓慢但持续写入，总耗时超过 60 秒 | 成功，哈希一致 |
| 假 scp 写到一半停住超过 60 秒 | 判为 `stalled`，进程被终止，临时目标不发布 |
| 连接阶段 60 秒无任何字节 | 判为 `stalled` |
| 到达兜底上限 | 判为 `hard_limit` |
| 重试 | 使用新的临时目标，旧的残片不被复用 |
| cancelled，有 claim 和 succeeded 记录，Slurm sacct 为 CANCELLED | 允许不完整取回 |
| cancelled，缺 claim 或缺 succeeded 记录，或 job_id 不一致 | 拒绝 |
| cancelled PBS，两次观察间隔 <300 秒，或输出有变化 | 拒绝 |
| cancelled PBS，存在 `ag-exit.json` | 拒绝，提示改用普通 fetch |
| cancelled PBS，qstat 显示作业仍在运行 | 拒绝 |
| 取回成功后 | 状态仍为 `cancelled`，记录格式与 interrupted 一致 |
| 两个确认框 | 按钮文字、默认按钮、Esc 按钮、图标与本单一致（检查 AppleScript 文本），只接受两种动作 |

开发中只跑相关测试；推送前本地跑一次全量 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，之后以 CI 为准。只暂存本单文件；运行 `python ag/tools/scan_sensitive.py --staged` 与 `git diff --cached --check`。

## 真实环境验证（合并前，开发机，非研究体系）

涉及远程取回，按 AGENTS.md 必须在合并前完成。每一次提交和取消，都由负责人亲手点击确认。

1. **大文件取回：** 在 default 上提交一次能产生较大输出（目标 ≥20 MB）的非研究作业，例如水分子 Multiwfn IGM 的 medium 格点。正常结束后取回，核对哈希，报告耗时和平均速率。开发机直连很快，在真实环境里可能证明不了"超过 60 秒也能成功"，这种情况如实写明，由离线回归覆盖。
2. **取消后取回（PBS 必做，Slurm 选做）：** 提交一个预计运行 ≥10 分钟的非研究小分子作业（具体作业由开发机自定，在 PR 里说明）。作业开始写日志后用 `ag cancel` 取消（负责人点击"终止作业"）。按第 2 节收集证据，然后 `ag fetch --incomplete`，报告取回的文件、哈希、状态、记录。
3. **确认框：** 第 1、2 步中真实出现的提交框和取消框各截图一张（截图里不能有主机名和路径），确认按钮文字、默认按钮、图标都正确。
4. 有异常就停下汇报，不重试。

## 停止条件

- 需要改动范围外的文件；需要新增状态转换、远程命令或配置项。
- 同一问题修两次仍未解决。
- 真实验证中出现 SSH 错误、UNKNOWN、哈希不一致。

## 合并前审阅与交付

- 需要监督方审阅：**是**（涉及取回证据和确认框）。合并只由负责人操作。
- PR 描述：三项改动分别说明；PBS 观察方式的选择和理由；全量测试结果；真实验证的提交号、作业类型、哈希与截图说明。
- 用 `gh pr view <编号> --comments` 读取 `<!-- ag-review head=... -->` 评论，逐条处理。
- **合并后（负责人安排）：** 开发机同步 main。HSS 计算机同步前，先确认没有进行中的提交、取回或 reparse。024 是否取回、何时取回，由负责人另行授权 HSS 会话执行。

## 版本记录

- v1（2026-10-20，监督方）：依据下一轮修复清单第 2、4、7 项起草。
- v1.1（2026-10-20，监督方在开发会话批准）：追加下述测试范围，不改变其他实现与验收要求。

## v1.1 范围补充（监督方 2026-10-20 批准）

- `ag/tests/test_core.py`：只改旧的确认按钮断言（不提交 / 保留作业 / 终止作业及默认按钮和图标），以及下载模拟（改为可轮询进程）。
- `ag/tests/test_ssh_log.py`：只把下载模拟改为可轮询进程，并相应断言超时细分 `stalled` / `hard_limit` 和已传字节数。
- 不删除测试，不放宽无关断言；保留日志脱敏、新临时目标重试、哈希核对等原有含义。
- 假进程只在测试代码中；生产代码不新增测试开关或环境变量。
- PR 必须注明“监督方 2026-10-20 批准的范围扩展（test_core.py、test_ssh_log.py）”，并说明两文件各自的调整。
