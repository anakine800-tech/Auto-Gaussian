# T227 人工核清 UNKNOWN 后的持续额度核算

## 分支与目标

从最新 `origin/main` 建独立工作树与 `codex/t227-resolved-unknown-accounting` 分支。先读 AGENTS.md、本任务单、docs/DEVELOPING.md 和 docs/LESSONS.md。

人工核清未绑定的 UNKNOWN 后，若此前的正式负向 status 证据超过十分钟，核算会重新占用额度，即使持续的新鲜监控记录仍能说明作业缺席。

## 允许改动的路径

- ag/src/ag/autonomy_submission.py、ag/src/ag/autonomy.py、ag/src/ag/route.py：人工核清后只读核算的延续、失效及调用边界。
- ag/tests/test_autonomy_submission.py、ag/tests/test_autonomy.py、ag/tests/test_route.py、ag/tests/test_t216_reservation_audit.py、ag/tests/test_t216_audit_cli.py：合成时间线、账本与命令回归。
- docs/DEVELOPING.md、ag/README.md：会重新计占的条件及人工核清边界。
- `docs/redesign-tasks/T227-resolved-unknown-accounting.md`：本单及实施、验证摘要。

## 验收标准

1. 首次人工核清仍要求既有有效账号绑定、正式 status、无作业匹配和无启动回执。只对相同人工核清记录下后续的额度计算评估延续证据。
2. 正例覆盖越过 600 秒后，同一实际账号、唯一可核对的作业身份和连续两份不同、完整、新鲜的正式快照持续缺席时维持释放。核对采样顺序、账户和时间线及本地开始/绑定证据；优先复用现有监控缺席核验。
3. 作业重新出现、同名或截断歧义、回执/绑定变化、缓存过期/损坏/轮转冲突、缺少连续样本或证据不可重放时恢复计占。新证据不得通过简单延长原 TTL 替代。
4. UNKNOWN 状态、claim、实际消费、暂停与人工处置语义保持；额度释放不能授权 UNKNOWN 补救、重提、取消或自动恢复。分别验证 accounting、audit 及 remedy 等已有调用方，别把额度用的负向证据扩为其他动作权限。

## 验证与交付

- 先用合成数据重现问题、运行定向回归，再于首次推送前执行 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`。使用本工作树源码与现行隔离机制。
- 精确暂存本单文件，运行仓库的暂存敏感扫描和 `git diff --cached --check`，核对提交身份。PR 第一行 `Task: T227`，列出测试结果、跳过原因、现场证据覆盖范围及真实阻塞。监督按实际 head 复审。

## 真实环境验证

冻结 head 后，使用开发机正式只读 audit-reservations，对既有合法非研究核算记录比对并记录覆盖范围；如有已人工核清的非研究样本，做原数据的只读时间线验证。合成时钟覆盖边界。不制造真实 UNKNOWN，不为取证取消或重提；若缺必要现场正例写明待补范围并由监督按手册核实。

## 协作顺序与停止条件

在 T226 的身份语义确定后开发核心改动；按 T226、T227 顺序验收集成。 越界、同一问题两次修复仍失败、真实环境异常时依 AGENTS.md 停止并报告。研究数据、真实连接和原始输出仅留私有位置。

## 离线证据判据

- 在合成 study 里实际登记消费、派发、UNKNOWN、暂停及人工核清。将时钟从正式 status 观察后的第 600 秒推进到第 601 秒，用 monitor 的正式发布函数轮转缓存，分别核对本地核算、路由使用的核数及只读体检。
- 核清记录绑定原消费、作业名和实际账号。越过时限后，最近两份不同的成功采样均须晚于核清，账号及本人作业列表完整一致，均排除该身份。缺份、过期、时间倒序、缓存更换、同名或截断名、开始回执及绑定变化均作反例。
- 逐字节核对旧 Attempt 与核清记录，检查消费次数与暂停状态。相同过期 status 与快照送入首次核清和补救入口时，仍须得到拒绝。

基线回归：`6bd8384f` 上定向执行 `pytest ag/tests/test_autonomy_submission.py -k resolved_unknown_`，扩充后的用例有 3 个预期失败、18 个通过。第 600 秒仍释放，第 601 秒仅一份新快照时计占；第 661 秒已有第二份完整快照，PBS、Slurm 和同账号别名三个正例仍返回 `unknown` 并计入 8 核。

## 冻结后现场核验方案（待监督协调）

在开发机记录受审 head 与实际导入的源码版本，使用同一份获准的本地既有证据，分别运行基线与受审版的 `python -B -m ag.cli autonomy audit-reservations --json`。先核验退出码、覆盖完整性及拒绝项；只从全机报告私下筛选经负责人确认的非研究对象。对其中已人工核清的未绑定 UNKNOWN，逐项核对消费归属、核清时间、原 status 两个哈希、同账号前后两张采样时间与本人作业清单、开始回执与绑定，以及新旧 `accounting_state`。记录原始文件核验前后的哈希、两次读取间有无缓存轮转；时间线已变化时不能作为同输入比较。对外仅记录脱敏计数与实际覆盖的证据类型。无合格样本时单列缺口，保留原记录。
