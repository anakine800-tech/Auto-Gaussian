# T223 严格输入校验 GaussView 连接表

## 分支与目标

从最新 `origin/main` 建独立工作树与 `codex/t223-strict-gaussian-connectivity` 分支。先读 AGENTS.md、本任务单、docs/DEVELOPING.md 和 docs/LESSONS.md。

普通 Gaussian 严格校验会拒绝带完整连接表的显式几何，删去 route 指定的表后却可通过。

## 允许改动的路径

- ag/src/ag/gaussian_input.py、ag/src/ag/gaussian_relaxed.py：在可复用处共享连接表语法，分别保留各模式原有适用范围。
- ag/src/ag/attempt.py、ag/src/ag/autonomy_policy.py：仅处理标准 prepare 与原有冻结/方法重验的必要衔接。
- ag/tests/test_gaussian_input.py、ag/tests/test_gaussian_sections.py、ag/tests/test_gaussian_relaxed.py、ag/tests/test_relaxed_attempt.py、ag/tests/test_autonomy_policy.py、ag/tests/test_core.py：针对本单的回归。
- ag/README.md：严格与放宽路径的实际支持范围。
- `docs/redesign-tasks/T223-strict-gaussian-connectivity.md`：本单及实施、验证摘要。

## 验收标准

1. 普通单段显式坐标加 Geom=Connectivity 与合法连接表走严格 prepare，冻结原字节；同一输入删表应报缺表。读入合法多原子表，含孤立原子的单索引行。
2. 覆盖缺行、重复/乱序行、超界索引、缺少成对的键级及非有限数。一般严格输入没有连接表时保持原行为。
3. 复用已审阅的解析逻辑。与已支持的 ModRedundant 顺序组合有明确测试；尚无支持的组合准确拒绝。不能通过误吞未声明附加段接纳 Gen、Link1 或改变既有科学口径。
4. 冻结包复验与 prepare 一致；严格输入不获得 relaxed 标记。保留 QST、放宽连接表及旧文件阅读回归。

## 验证与交付

- 先用合成数据重现问题、运行定向回归，再于首次推送前执行 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`。使用本工作树源码与现行隔离机制。
- 精确暂存本单文件，运行仓库的暂存敏感扫描和 `git diff --cached --check`，核对提交身份。PR 第一行 `Task: T223`，列出测试结果、跳过原因、现场证据覆盖范围及真实阻塞。监督按实际 head 复审。

## 真实环境验证

默认只涉及本地受限语法。使用合成小分子在正式 prepare 和本地冻结复验路径验收；如发现必须改变真实提交行为，按开发手册在绑定 head 的非研究样例上补验证。

## 协作顺序与停止条件

可先准备独立红灯样例；与 T222 改动重叠处在其受审版本上对齐，合并顺序在 T222 之后。 越界、同一问题两次修复仍失败、真实环境异常时依 AGENTS.md 停止并报告。研究数据、真实连接和原始输出仅留私有位置。

## 实施与本地验证（2026-11-25）

- 在基线 `6bd8384f908ca6e457238623a7779c7035d07d43` 使用合成水分子复现双向错误：带完整表被当成额外段拒绝，声明相同而删表却通过。
- 从放宽模式抽出既有逐原子行校验。严格模式按显式原子数读第一个附加块；后续扫描或冻结使用原有 ModRedundant 解析器。QST 与连接表的组合、Gen 基组段、Link1 及未声明附加块拒绝。标准 prepare、冻结包复验及严格方法复查共用此入口。
- 在仓库 HOME 隔离机制中，使用合成 H₂ 与孤立 He 从 CLI 执行 `ag init`、`ag prepare --template gaussian`。已写齐资源、含 CRLF 的输入返回 0，磁盘 manifest 经 `verified_files` 复核，冻结字节与源文件逐字节相同，包内无放宽标记。删除连接表后 prepare 返回 1，提示缺表，Attempt 目录及编号预留均无新增。
- 使用本工作树 `ag/src` 与 Python 3.11.15 对 `test_relaxed_attempt.py`、`test_gaussian_input.py`、`test_gaussian_relaxed.py`、`test_autonomy_policy.py` 运行定向回归，986 项通过，退出码 0。包含重复、乱序、缺行、索引越界、缺少键级、非有限数、孤立原子、非顶层伪声明、扫描段顺序、合法旧格式及哈希自洽的历史缺表包复验。
- 本地证据覆盖输入语法、冻结字节和方法规则复查。未运行 Gaussian 或调度器；键级的化学合理性与现场运行结果保留给单独的科学或现场验收。

### 已消费的历史缺表包

按监督补充的验收场景，在假 PBS 中复现旧缺表包只派发一次、提交响应丢失、稍后出现开始回执。首次回归的两个分支均被新语法提前拦下。现对有永久 claim 且已离开 prepared 状态的旧包保留原有缺表布局解析；原有资源、哈希、脚本、科学摘要及回执归属校验继续执行。普通 prepare、未消费旧包的提交前核验与严格方法判定仍要求连接表。

- 使用合成回执核对，UNKNOWN 经迟到开始回执绑定原作业及 bundle，再由结束回执判定 finished。原输入、claim、manifest 和授权摘要逐字节相同。重复提交在本地被拒绝。
- 模拟远端输入增加一个换行，回执核对拒绝，状态仍为 UNKNOWN，未生成作业绑定。两条用例均只发生最初的一次模拟派发。
- 加入历史回执兼容后重跑上述四个定向文件及 `test_unknown_start_binding.py`，共 1055 项通过，退出码 0。
- 对监督指定的既有非研究输入另作本地重放：先核对原文件长度、SHA-256 与历史 manifest，再将相同字节交给隔离的默认严格 prepare。新 manifest 从磁盘读回，`verified_files` 返回的输入与原件逐字节相等，无放宽标记。实际文件与研究标识保留在仓库外，最终提交的复核结果见 PR。

监督更新合并排期：T222 与 T223 各自独立验收，先通过的一单可先集成；后合者在最新 main 复用同一个“已永久声明”判据。T224 在两单之后整合。

全量验证中首次发现安装冒烟的子进程枚举正式检出虚拟环境的 bin 目录，被 HOME 隔离明确拒绝。改用临时目录的独立虚拟环境，离线安装同一工作树的 CLI、沿用现成化学依赖，保持原隔离策略。在该环境中单跑 `test_smoke.py`，26 项通过。
首次完整运行 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs` 得到 8933 通过、1 失败、26 跳过（退出码 1）；唯一失败为上述安装入口。按监督排期对齐 origin/main 的 T228 文档更新后，在临时安装环境重新执行全量。
