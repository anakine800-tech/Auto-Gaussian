# 开发时查这份

本手册对应 `ag/` 与 `skills-next/` 新架构；操作示例中的尖括号均为占位符。
先读 [AGENTS.md](../AGENTS.md)、本次任务单和 [经验记录](LESSONS.md)；文档总入口见 [文档索引](README.md)，[改造方案](REDESIGN-PLAN.md) 只作历史参考。
当前代码是实现依据；遇到文档与实现不同，写明差异，不借文档修改扩大任务范围。

## 模块地图

以下均位于 `ag/src/ag/`，一个模块一行；模板在 `ag/templates/`，测试在 `ag/tests/`。

- `__init__.py`：包入口与 CLI 版本号。
- `cli.py`：参数解析、子命令挂载、配置选择与退出码。
- `config.py`：本机配置校验、集群选择及按 manifest 绑定目标。
- `clusters.py`：只读输出供前端发现的集群、档位和预算白名单字段。
- `study.py`：study 骨架、标识符和本地路径校验。
- `attempt.py`：prepare、不可变 manifest、输入哈希及统一的本地记录读取。
- `state.py`：允许的状态迁移和本地 status 原子更新。
- `journal.py`：追加本地动作记录。
- `locks.py`：提交串行锁和不可复用的独占声明。
- `confirm.py`：唯一的 macOS 人工点击确认入口。
- `submit.py`：批次核验、确认、上传、提交及不确定结果处理。
- `submission.py`：一次性提交绑定及确切作业身份交叉校验。
- `budget.py`：按集群预留、核对、结算本地 ag 核时预算。
- `cancel.py`：确认后取消记录中的确切作业，取消声明也只能用一次。
- `status.py`：PBS/Slurm 观察、程序完成证据及 unknown 只读核对。
- `fetch.py`：校验输出大小和哈希，以不覆盖方式发布到本地。
- `monitor.py`：只读采样集群，在本地缓存最新快照和历史。
- `doctor.py`：只读检查连接、调度器、目录和程序环境。
- `remote.py`：全部固定远程命令、参数白名单及路径检查。
- `transport.py`：SSH/scp、只读传输重试、脱敏及可注入的 Transport 接口。
- `pbs.py`：PBS 节点与容量解析，供提交和监控共用。
- `slurm.py`：Slurm 提交、队列和记账输出的严格解析。
- `render.py`：声明参数校验及 PBS/Slurm 程序脚本渲染。
- `gaussian_input.py`：Cartesian Gaussian、QST2/QST3 输入与资源校验。
- `crest_input.py`：CREST 约束输入的受支持子集校验。
- `parent_chk.py`：父 chk 声明、父子关联与提交时来源检查。
- `parent_chk_remote.py`：以固定描述符安全读取和独占复制 chk 的远端脚本文本。
- `cards.py`：读取实际部署卡片并保存文本、提交号和 dirty 状态。
- `review.py`：生成审阅骨架，检查判据完整性及 facts 是否过期。
- `_review_manifest.py`：签字前独占生成 study 证据清单，绑定文件字节与 ag 提交号。
- `facts.py`：本地 facts/final.xyz 输出入口，仅提取事实。
- `mode_review.py`：基于正常结束的频率段导出正负模式位移、指定原子对距离及全对排名，方向由人审阅。
- `_parse_outputs.py`：Gaussian/cclib、xTB、CREST 输出解析。
- `_irc.py`：Gaussian IRC 方向、路径点和完成事实提取。
- `geometry.py`：XYZ、显式能量单位、成键/立体标识及 RMSD 共用工具。
- `dedup.py`：能量窗口和对称性去重，记录排除原因。
- `cluster.py`：代表构象选择及可选镜像简并度。
- `graph.py`：只读展示 parents/relation 谱系和缺失父节点。
- `irc_compare.py`：保留原子编号的 IRC 端点几何比较，不代替科学验收。
- `topology.py`：本地比较提交与最终几何，报告拓扑/立体差异或指定 TS 原子对距离，独占输出 JSON 与 Markdown。
- `thermo.py`：GoodVibes qRRHO、单点修正和显式简并度布居。
- `_profile_sources.py`：反应曲线的来源、物种、方法和审阅检查。
- `profile.py`：守恒反应自由能曲线、能垒和敏感性分析。

## 提交流程：规范顺序

规范顺序与当前 `submit.submit` 实现一致，参见已合并 [#209](https://github.com/anakine800-tech/Auto-Gaussian/pull/209)、[#224](https://github.com/anakine800-tech/Auto-Gaussian/pull/224)：
锁内校验输入和集群 → 核数/预算预检 → Mac 确认 → 再校验字节 → 声明 → Slurm 预算预留 → submitting → 复查占用 → 建目录 → 上传并逐文件核对大小/SHA-256 → qsub/sbatch → submission.json → submitted。
这里“声明”指以 `O_EXCL` 创建 `.submit-claim`；有声明就不能再次提交该 Attempt。
声明放在确认之后，是为了让人在弹窗取消时 Attempt 仍保持 prepared、没有声明，之后可正常提交，不因取消而消耗一次提交机会。

核数统计包含该用户在目标集群的全部作业，不能只统计 ag 作业；还要计入已提交但尚未读回的占用。
PBS 每批确认前核验一次节点容量；每项声明后复查队列，沿用已确认的有效上限；核验不成立时严格计入排队核数。
Slurm 始终按 max_cores 严格计算运行加排队；核时预算在远程写入前预留，unknown 不释放。
预算只记录本地 ag 消费，不等于平台余额，也不含外部网页作业的消费。
父 chk 若已声明，在新目录中先专用复制并核对来源/目标哈希，再上传其他输入；不改变父文件。
上传使用确认后核验过的字节快照；脚本、输入和附件都不能在确认后被悄悄替换。

## 状态速查

完整允许迁移见 `state.TRANSITIONS`；状态描述执行证据，不能替代科学审阅。

| 状态 | 含义与下一步 |
| --- | --- |
| prepared | 本地准备完成；可请求人工确认提交。 |
| submitting | 已消耗单次声明，正在提交；中断后保留声明并人工核对，不手改回 prepared。 |
| submitted | 已取得并绑定作业号，尚无运行或完成证据。 |
| running | 调度器报告运行；继续只读观察。 |
| awaiting_second_observation | 首次证据不足；按 next_observation_at 等待第二次观察，至少相隔 60 秒。 |
| stalled | PBS 仍运行而声明输出至少 60 秒未变化；需结合进程/日志判断，不自动取消。 |
| interrupted | 无充分完成证据，且作业不活跃或报告异常；保留证据并诊断。 |
| finished | 程序退出回执、旧 PBS 完成证据或 Slurm 终态已确认；检查退出码，再 fetch/解析/审阅。 |
| fetched | 声明输出已取回校验；仍需 facts 和科学审阅。 |
| cancelled | 已发出经确认的取消；不据此断言程序科学失败或调度记录已经消失。 |
| failed_presubmit | 确定未提交成功，如提交前失败或 PBS 明确拒绝；该 Attempt 已消耗，不能再提交。 |
| unknown | 提交/状态证据不确定；仅只读核对，不能把无记录当作未运行。 |

unknown 经唯一、匹配的作业证据可回到已知状态；找不到或歧义时保持 unknown，交给人决定。
failed_presubmit 或计算失败的修复方式是提出新 Attempt，经人确认；不删除声明、不重用目录、不自动重提。
PBS 有退出回执时可 finished 并取回，即使队列仍显示 R（调度器残留）；清理只走确认后的 cancel。
旧 PBS 无回执时：完成标记 + 两次输出稳定；队列仍有 R/C 记录时还需会话进程证据，读取标记后再复核输出。
Slurm 从 squeue 消失仅触发 sacct 核对；终态中非零退出/信号以及 FAILED、TIMEOUT 等都不是科学成功。

## 集群绑定：读哪个记录

- `manifest.json`：prepare 后不改；记录目标 cluster/scheduler、相对远程目录、输入哈希、方法、父关联和可选卡片快照，不保存连接凭据。
- `submission.json`：提交后独占写入；绑定 Attempt、集群限定作业号和 manifest 原始字节的 SHA-256；与 status 交叉核验后才能取消或关联。
- `attempt.local_record`：函数，不是新文件；先读 manifest 并过滤集群，再按该调度器读取 status/submission，返回 manifest、状态和原始作业号。

扫描 monitor、预算、list/status 等时复用 local_record/local_records；别先用 PBS 解析器读取所有 status。
旧无 cluster 的 manifest 按 default PBS 解释；无前缀作业号仅属于 default PBS；有前缀也必须与 manifest 一致。
其他集群的 status 不参与当前扫描；本集群缺失/损坏绑定须报出具体 Attempt，不能静默跳过或用可变 status 代替。
核对案例见 [#229](https://github.com/anakine800-tech/Auto-Gaussian/pull/229)、[#235](https://github.com/anakine800-tech/Auto-Gaussian/pull/235)。

## 怎么加功能

### 本地命令

在 `ag/src/ag/` 写确定性模块；参考 dedup 的 `register(subparsers)` 并在 `cli.py` 挂载。
纯文件工具不加载远端凭据、不创建 Transport；只需 studies_root 时用现有 local_only 配置路径。
参数、JSON、错误及已有输出不覆盖都用合成数据测试；科学判据优先写卡片，不再建工作流框架。

### 远程命令

先说明具体要防或解决的事故，在 `remote.py` 增加固定 Command，参数经白名单和路径检查；不接受 shell 文本。
只读操作同步加入 `transport.READ_OPERATIONS`；写操作不进入该集合，不获得自动重试。
**白名单测试必须同步更新**：参考 `test_core.py::test_remote_allowlist_and_paths`、`test_slurm.py` 和相应功能测试，断言完整命令、操作集合及坏参数拒绝。
覆盖链接替换、越界、SSH 255 和响应丢失；远端助手兼容目标 Python，不能拿本机版本替代。

### 程序模板

新增受审阅的 `ag/templates/` 程序体和 `.toml` 参数/输出声明，并同步 render、prepare/CLI、配置校验及 facts 解析入口。
不是只把文件放进目录：`render.declaration` 的程序白名单也须显式更新。
复用 `_guard.sh`，私有 scratch、独占回执、只执行一次；不随意 source 平台环境脚本。
用假程序检查成功/非零退出、输出和回执；保持既有 PBS 渲染结果逐字节不变，不重写旧 prepared bundle。

### 调度器

沿 config、固定 remote 命令、纯解析、render、submit/status/cancel/doctor/monitor、预算和 submission 绑定逐处接入。
按集群选 Transport；核对属主、完整作业名和确切作业号；全用户占用含数组与非 ag 作业。
测试提交响应丢失、队列读回延迟、终态/缺失记账、跨集群同号、预算预留与取消目标；Slurm 保留 `--no-requeue`。
不要新增通用调度抽象来预留未知需求；参照 [T16](redesign-tasks/T16-slurm.md) 的具体接入点。

### 卡片

放在 `skills-next/auto-g16-recipes/cards/`，同步 Skill 索引和 `skills-next/tests/test_skill_format.py` 的卡片清单。
固定八个二级小节（保留编号）：
1. 适用范围
2. 前置条件
3. 输入模板
4. 资源建议
5. 提交前检查清单
6. 结果判据清单
7. 常见失败与处理
8. 常见坑

每卡最多 **285 行**，“常见坑”最多 **10 条**；超限先合并或删除，不随最长卡片重新抬高上限。
为防止已实现工具仍被卡片写成缺功能、复制的方法骨架继续漂移，CI 的
`skills-next/tests/test_card_consistency.py` 从实际 CLI 注册核对子命令和选项。
“待 Tn”只能引用 `docs/redesign-tasks/open-tasks.txt` 中的任务，完成时同 PR 移除记录与标记。
方法/基组只在 `acceptance-methods.md` 定义；骨架使用占位符，具体 route 仅限逐例标明的“流程验收示例”，且组合仍须在方法表中。

第 6 节写可逐项审阅的判据；prepare 保存实际卡片快照，review 使用保存的判据，不能追着最新版改旧 Attempt。
旧 manifest 可在 review init 时用 --card 补指定，明确标注审阅时来源，不补写 manifest；见 [#228](https://github.com/anakine800-tech/Auto-Gaussian/pull/228)。

## 测试与敏感信息

### 本地证据与签字

`parse_facts` 只返回内存中的事实和几何文本；thermo/profile/review check 不生成或改写 facts.json。
`ag facts` 比较新旧解析内容时排除 `ag_provenance`；解析内容相同则保留旧文件原始字节和 mtime，
不归档、不补写缺失的 provenance，升级提交号不会使既有证据失效。只有解析内容不同时才列出差异并拒绝；
人工核对后用 `ag facts <id> --refresh`，先保留原始字节为 `facts.<SHA-256前12位>.json`，再原子写入新版。
已有几何仍不得覆盖。新 facts 的 `ag_provenance` 记录解析器 checkout 的提交号与 dirty 状态；
review 快照绑定该来源，不能用当前 HEAD 或 Skills 提交号代替。旧记录缺版本时明确报告未知。

签字前运行 `ag review manifest --study <dir>`；它无需配置或网络，独占创建
`analyses/review-manifest-<UTC时间>.json`。清单包含 study.md、全部 facts.json/review.md，
以及从 study/review 和已引用分析文件递归发现的 analyses/ 输出，记录相对路径、字节数和 SHA-256。
文档用 Markdown 链接、反引号路径或显式 `analyses/文件名`；分析 JSON 支持相对文件路径，
包括 profile 的 `thermo` 引用。含空格路径用 Markdown 尖括号链接或反引号；二进制输出只哈希不解析。
缺失引用、符号链接、越界会拒绝；远程 URL 不下载。未被引用的分析输出不纳入清单，
因此签字前先在 study.md/review.md 写全依据。生成清单不是科学签字；向人展示清单后，
将清单路径和命令返回的清单 SHA-256 一起记入签字记录。旧清单保留，每次签字生成新的清单。

新测试只用合成配置、合成小分子和假 Transport/假 ag，不读取真实配置、研究数据或连接集群。
从现场问题改写脱敏样例时，虚构身份和值，但保留空格、截断、换行、列宽、返回码和缺字段的真实形态。
既有经审阅的小分子 fixture 留作回归，不把原始现场日志、chk 或私有研究 fixture 加入提交。
PBS 兼容性要比较渲染字节或固定哈希，不能只比较脚本语义；本任务没有模板变化。
从仓库根目录、已具备项目依赖的 Python 环境运行：

```sh
PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs
git diff --check
# 逐个暂存本任务文件后：
python ag/tools/scan_sensitive.py --staged
git diff --cached --check
```

不要设置私有日志 fixture 环境变量。macOS 跳过的 Linux 方言检查由 Linux CI 补足，报告跳过原因。
扫描器只覆盖部分常见模式；还要人工检查 diff、PR 正文和提交元数据中的主机、用户名、作业号、凭据及绝对路径。
提交前在本机核对 author/committer 都使用 GitHub noreply 邮箱；不要把身份检查的原始输出贴到 PR。
真实环境验证在合并后另行授权、单独记录执行版本、范围和结果；离线通过不等于实际提交或科学验收。

## 角色与审批

三方分工：负责人做决定、合并、签字和提交确认；监督方（Claude）写任务单、审阅 PR 并留评论，也可以提交文档 PR；执行方（Codex）按任务单开发，真实环境操作须经负责人授权。

| 事项 | 由谁决定 | 说明 |
| --- | --- | --- |
| 合并任何 PR | 负责人 | Codex 和监督方都不合并、不直接推 main |
| 修改 AGENTS.md | 负责人明确批准 | 在 PR 中写明批准记录 |
| 修改方法表（方法、基组、窗口、热化学设置） | 负责人确认 | 在 acceptance-methods.md 写明确认日期 |
| 涉及 remote、submit、cancel、status、fetch 的代码 | 监督方审阅通过后再合并 | 新增远程命令须写明防的是哪个事故 |
| 卡片与 Skills 修改 | 监督方审阅 | 卡片一致性测试必须通过 |
| 真实计算的提交与取消 | 负责人在 Mac 上亲手点击 | 任何人不得代点或绕过 |
| 科学签字（机理假设、结构、代表构象集合、最终结果） | 负责人 | 签字前先生成证据清单 |
| 计算平台与软件许可的科研用途认定 | 负责人 | 记入 study.md |
| 创建 tag 和 release | 负责人在 GitHub 网页操作 | 版本号与 CHANGELOG 先经 PR 合并 |

监督方审阅评论的首行为 `<!-- ag-review head=<短哈希> -->`，正文写“通过”或逐条列出需要修改的项；只发评论，不推送他人分支、不合并、不改 Issue、不碰集群。PR 更新后按新的 head 重新审阅。

## PR 与发布

一张任务单、一个 `codex/<任务名>` 分支、一个 PR；描述第一行写 `Task: Tn`，模板见 [TEMPLATE.md](redesign-tasks/TEMPLATE.md)。
只写改了什么、验证结果和实际阻塞（结构/提交/解析/科学审阅/环境）；不另造规章、合同或指标体系。
监督方评论首行是 `<!-- ag-review head=... -->`；用 `gh pr view <编号> --comments` 读取，逐条修改并回复。
涉及 `remote`、`submit`、`cancel`、`status` 或 `AGENTS.md` 的改动，合并前等监督方审阅；AGENTS.md 修改还需负责人明确批准。
有冲突在本地 fetch 后 rebase 到最新 main，检查差异并重跑受影响测试；不用网页编辑器解决冲突。
合并只由人操作；Codex 不合并、不直接推 main、不修改分支保护。

发布任务同步 `ag/pyproject.toml` 与 `ag/src/ag/__init__.py` 的版本号，并在新架构 `CHANGELOG.md` 写变更、兼容性和验证。
版本取发布任务指定值，核对包元数据与 `ag --version` 一致；若尚无新架构 CHANGELOG，在发布任务中创建，不改 `archive/CHANGELOG.md`。
版本/CHANGELOG 经 PR 审阅、测试、人工合并后，由人在 GitHub 网页创建对应 tag 和 release；文档 PR 不顺带发版。

## 合并后同步本机运行版本

每次合并后，本机的后端 main 检出和前端 main 检出都执行 `git pull --ff-only`。
先确认分支是 main、工作区干净；若快进失败，报告本地分叉/改动，不强制重置。
后端在该 main 检出的 `.venv` 中维护依赖；真实计算只调用该检出的 `.venv/bin/ag`，
并核对版本和 Python 导入位置。清除临时 `PYTHONPATH`，不能用开发 worktree 或 PATH 中的旧 ag 执行真实计算。
Skills 软链接指向后端 main 的 `skills-next`；合并 PR 本身不会更新本机检出。
前端始终从本机约定的固定 main 检出目录运行，停止旧实例后从该目录重启，
核对其调用的后端也是上述 `.venv/bin/ag`；不从临时 worktree 启动日常前端。
固定目录的具体值只记在本机配置，不写进公开仓库；同步检出不授权提交或取消计算。
