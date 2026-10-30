# Auto-Gaussian CLI

`ag/` 是独立 Python 项目，负责安全的作业生命周期和确定性本地工具。
当前候选版本为 **4.7.1（发布准备）**，配套前端同号；版本与范围见 [CHANGELOG](../CHANGELOG.md#v471发布准备)。
**自主运行尚未启用**：T184 仅提供本地记录，研究会话不得据此尝试自主提交、取消或改投。普通人工工作流保持；发布准备不代表已发布或部署。
按[根目录安装步骤](../README.md#安装)为当前 worktree 创建独立 `.venv`，
从仓库根目录在 Python 3.11+ 环境运行 `python -m pip install -e 'ag[test,chem]' 'rdkit==2026.3.3'`，
然后用 `ag --version` 和 `ag --help` 检查安装。
RDKit 与 CI 固定为同一精确版本；平台包边界见上述安装步骤，固定版本不保证跨硬件数值逐位一致。
整体架构、常用命令和 Skill 部署见[根目录 README](../README.md)；
规则见 [AGENTS.md](../AGENTS.md)，设计见[改造方案](../docs/REDESIGN-PLAN.md)。

本文计算命令描述当前手动模式；T184 的 `autonomy` 仅保存本地计划和状态。[自主运行规则](../AGENTS.md#自主运行)须待相关工具实现、敏感路径合并前验证、非研究试点及本轮显式启用全部完成；旧长期规则不提供自主权限，现有 cancel 仍须 Mac 人工点击。当前实现与后续要求见[开发手册](../docs/DEVELOPING.md#自主运行的实现边界)。

## 提交阶梯与整节点（T185）

旧 `ag route --template gaussian --tier general --walltime 04:00:00 --json` 继续提供本地快照建议。
新 `--job-class main|small` 模式要求 `--study`、`--round-id`、`--run-id`、`--object-id` 和 `--walltime`，
当前可信记录适配尚未完成而拒绝给出候选；T186 负责核对 T184 稳定接口后接通读取与 CLI，不接受人工传入“已通过”或占用 JSON。
两种模式均不运行 SSH、不创建目录、不写文件。T186 的提交时重算尚未接入。

`routing.ladder` 是按顺序排列的本机配置表，格子写明 `id`、`cluster`、`classes`（main/small）、
`tier`、`condition`、`max_placements`；具名入口另设有序 `nodes` 和 `node_fraction`。
`empty` 要求批次起点全空；`free` 要求 `min_free_cores` 且同一节点内存足够；
`jobs` 要求对象已等待一次真实唤醒，且该实际集群中全本机自主作业的运行加排队少于 `max_jobs`（SCNet 类上限为 4）；
`queue` 每节点或入口最多排一个，全本机自主排队/预留记录合计最多两个，同一实际资源的多个入口不能多占名额。
两项上限跨本机全部自主 study/round，包含不同配置目录和 studies_root，旧轮仍活跃的作业继续计入；非自主作业不占这两项自主名额，仍计入原有全部账号核数限制。
`round_id` 标识整个自主轮次，`run_id` 只标识一次唤醒运行；改变 study、round 或 run 均不重置上述活跃作业名额。
每个格子在同一 round/run 批次内最多放一至两个作业，`jobs` 和 `queue` 每次最多一个。合成配置见 [配置示例](config.clusters.example.toml)。

`ag.route.select_ladder` 是无 I/O 的共用选格函数。它接收配置、快照、作业类别、时限、必需的 `study_key`、显示用 `study_id`、`round_id`、`run_id` 和对象身份、
经本地适配核验的提交/预留记录及唤醒历史，可选父集群和 `batch_inputs` 保存的首次选格完整输入，返回候选、拒绝原因及配置/证据哈希。
输出同时保留 round/run 身份。哈希只标识输入，不能证明调用者提供的记录真实；适配必须核对 manifest、submission、声明/台账及运行事件，
不能使用 T184 状态中仅代表意向的提交计数。当前只有纯函数与合成回归，尚无实际记录到函数的完整接线。
T186 须从全本机记录核验真实自主归属，按共享账号及确切作业身份去重，保留尚未观测到的预留与 UNKNOWN 占用；
证据不明不能按零处理。T186 须接通跨配置目录的共同注册与共同锁，并在共同锁内重新收集、核验记录、快照及选格结果；
现有各配置目录的 submit.lock 不覆盖全本机，不能把先前建议缓存为提交许可。

供后续接线复用的参数以现有测试为例：`snapshots` 按入口传入完整 `ag-monitor/1` 数据；
`placements` 每项必须有 study_key、study_id、scheduler_job_name，以及 cluster、attempt_id、job_id（原始或限定号；reserved/unknown 可为空）、state（reserved/unknown/queued/running/finished）、cores、mem_gb，
以及 round_id/run_id/object_id、cell_id、target_node/capacity_node、manifest_sha256、record_sha256。
适配核验 manifest 后，PBS 的 scheduler_job_name 取 pbs_job_name，Slurm 取 attempt_id，再与快照比对。
`study_key` 为必填的 64 位小写 SHA-256；T186 可信适配须按安全校验后的本机绝对 study 目录生成，并持久绑定目录身份。
选择器请求、placements、wakeups、批次 request 与本地去重均使用此 key；study_id 仅作显示，缺 key 不回退到同名标识。
不同 studies_root 的同名 study_id/attempt_id 不合并；物理作业仍按共享账号和确切作业身份去重，矛盾归属拒绝。
纯算法只校验传入 key，不访问路径；真实目录绑定、共同注册和跨配置锁仍待 T186 接线。
同批成员另带首次选择的 config_sha256、selected_at、batch_input_sha256；无自主归属的本地预留仍需计入账号额度。
`wakeups` 每项有 study_key、study_id、round_id、run_id、object_id、started_at；waiting_since 来自该 study 对象等待事件，不能由模型自行填写。
`batch_inputs` 以 evidence.input_sha256 为键，保存首次完整 snapshots、placements、wakeups、request 和 selected_at；
request 包含 study_key、study_id、template、job_class、walltime、round_id、run_id、object_id、waiting_since、parent_cluster。
这些是选择器输入，不是新增授权记录；后续适配必须从不可变文件与重放事件构造，并核对选择与 manifest 资源一致。

`select_ladder(..., evaluate_from=None)` 可对已核验原 reservation 评估更优候选；可选字典只接受
`study_key`、`attempt_id`、`record_sha256` 三项，等价读取/共享别名去重后须恰好匹配一条原绑定且哈希一致；冲突或多个物理绑定仍拒绝。
原格子由 T186 的不可变 recommendation 填入 placement，cell、节点、资源和配置身份须一致；不能调用 `exclude_ownership` 删除原记录。
仅这条确切来源豁免“同对象已放置”的快捷拒绝，原占用继续参与全部核数、名额和节点容量检查，其他同对象记录仍按原规则阻断。
候选必须与来源不同 cell 且严格更优，复用 main/small 现有排序；省略参数时原行为和输入哈希不变。
结果带 `evaluation_only=True` 及 `evaluate_from`，仅供评估；首个组合不启用取消、停止核验、后继或改投入口，不等待 T187。后续接入评估时，薄适配须独立透传该参数，普通 reservation 消费必须拒绝评估结果；T187 复用此结果，不复制选格算法。
T187 仍须核验立即可运行、从未运行且排队至少六小时、无 chk 依赖、归属与租约、取消次数及消费等改投资格；本接口不授权取消或再提交，也不新增 CLI 参数、警告界面或真实操作。

两份半节点任务通过首次选格的完整输入重放同一算法，确认批次起点满足全部选格条件，再逐次核对当前剩余容量；
只保留一张原始快照不足以证明首次选格合格。已读回的作业不重复计入，
未读回预留仍计入，外来占用可阻止第二份放置。快照须成功、采样间隔有效且不超过三倍间隔，未知资源不作空闲。
CPU 和精确内存必须在同一节点满足；全部本人作业、共享入口最小额度、单作业上限和时限限制继续生效。
父 chk 候选仅限父入口，无合规空位时只能在该入口限额内排队。小体系在配置入口顺序内优先使用已有占用且有容量的节点。
主体系仅支持 Gaussian；gaussian-cp、multiwfn 排除具名节点入口，multiwfn 仍仅支持 default PBS；CREST/xTB 沿用旧建议模式。

具名 Gaussian 的 `prepare --node-fraction 1` 使用整节点，核数等于注册 slots，内存为每核 2 GB，
仍须精确匹配档位、max_cores 与节点总规格。默认 `1/2`、可选 `1/4` 和旧脚本/bundle 字节保持不变。
选择必须先于 prepare；prepare 后入口、节点与资源不可变，路由建议不授权提交。
`ag nodes` 可列出整节点；`ag clusters` 比例元数据复用 `node_targeting.FRACTIONS`，依次返回 `1/2`、`1/4`、`1`，默认仍为 `1/2`。本单不扩展前端工作。
合并前仍缺整节点、半节点、非指定入口三个独立小分子 Attempt 的批准与真实验证；离线通过不代替这些证据。

## 在新 Mac 上重建直连 SSH 配置

当前传输方式是 Mac 通过专用 OpenSSH 配置直连集群。准备本机可用的 `ssh`、`scp`，
以及由本人或管理员提供的连接资料、私钥和经可信渠道核验的服务器主机公钥。
这些资料只保存在本地，不能放进仓库、PR 或可分享的 study 记录。

### 1. 准备专用 OpenSSH 文件

在仓库外创建专用配置文件。下面**所有值都是占位符**，必须先按下表替换；
路径填写本机绝对路径，不使用另一台机器的原路径。

```sshconfig
Host <SSH_ALIAS>
    HostName <REMOTE_HOST_OR_IP>
    Port <SSH_PORT>
    User <REMOTE_USER>
    IdentityFile "<ABS_PRIVATE_KEY_FILE>"
    IdentitiesOnly <YES>
    StrictHostKeyChecking <YES>
    UserKnownHostsFile "<ABS_KNOWN_HOSTS_FILE>"
    BatchMode <YES>
    ConnectTimeout <TIMEOUT_SECONDS>
    ProxyJump <NONE>
    ProxyCommand <NONE>
```

| 字段 | 替换规则 |
| --- | --- |
| `Host` | 本地自选别名，与下文 `ssh.host` 完全一致；使用字母、数字、点、下划线或连字符，以字母或数字开头 |
| `HostName` | 管理员提供的真实集群地址，只填在本地 |
| `Port` | 管理员提供的 SSH 端口 |
| `User` | 实际远程账户名，不从 Mac 账户名推断 |
| `IdentityFile` | 本机私钥文件的绝对路径，不是公钥文件；对应公钥应已获远程账户授权 |
| `IdentitiesOnly` | 将 `<YES>` 替换为 `yes`，限制认证使用配置的身份 |
| `StrictHostKeyChecking` | 将 `<YES>` 替换为 `yes`，拒绝未信任或改变的主机密钥 |
| `UserKnownHostsFile` | 保存已核验服务器公钥的本地文件绝对路径 |
| `BatchMode` | 将 `<YES>` 替换为 `yes`，不在命令中等待密码输入 |
| `ConnectTimeout` | 将 `<TIMEOUT_SECONDS>` 替换为 `15`；`ag` 也会在调用 SSH 时指定此值 |
| `ProxyJump` / `ProxyCommand` | 将 `<NONE>` 替换为 `none`，保持直连，不沿用旧中转链路 |

使用独立文件，避免从旧配置 `Include` 不明的代理或身份设置。`ag` 会使用
`ssh -F <SSH_CONFIG_FILE> <SSH_ALIAS>`，并强制 `BatchMode=yes`、
`StrictHostKeyChecking=yes` 和连接超时 15 秒；不会通过交互式密码或自动接受新主机密钥来补齐配置。

如果私钥有口令，先在本机通过可信的密钥管理方式将它解锁并加入 SSH agent，
使后台 SSH 可用；不要把私钥口令写入配置。

### 2. 建立可信主机记录并设置权限

将可信渠道提供且已核验指纹的服务器公钥写入 `UserKnownHostsFile` 指向的本地文件。
记录必须匹配实际 `HostName` 和端口；非默认端口的 OpenSSH 主机标识形式为
`[<REMOTE_HOST_OR_IP>]:<SSH_PORT>`。仅收集到一个主机公钥不等于已经确认服务器身份。
不要通过关闭主机密钥检查、盲目信任扫描结果或删除旧信任记录来消除报错。

在占位符替换后，为已创建的配置、私钥和主机记录文件设置仅本人可读写权限：

```bash
chmod 600 '<SSH_CONFIG_FILE>' '<ABS_PRIVATE_KEY_FILE>' '<ABS_KNOWN_HOSTS_FILE>'
```

这些是本机文件操作，不需要连接服务器。配置文件及私钥的父目录也应仅允许本人管理。
可以用下面的命令只查看 OpenSSH 的最终配置，不发起连接；输出含私密机器信息，留在本地：

```bash
ssh -G -F '<SSH_CONFIG_FILE>' '<SSH_ALIAS>'
```

检查输出中的地址、账户、端口、身份文件、known-hosts 文件、主机密钥检查和代理设置。

### 3. 在 config.toml 中引用

将 [config.example.toml](config.example.toml) 复制到本机固定入口
`~/.config/ag/config.toml`；若已有配置先检查，不能用样例覆盖。
保留样例的全部节和四个资源档位，然后替换所有占位符。
下面是需要填写的机器相关字段示意，**不是可单独使用的完整配置**：

```toml
[ssh]
config_file = "<SSH_CONFIG_FILE>"
host = "<SSH_ALIAS>"

[remote]
allowed_root = "<ABS_REMOTE_SDL_ROOT>"
ag_root = "<ABS_REMOTE_SDL_ROOT>/ag"

[scheduler]
queue = "<TORQUE_QUEUE>"

[resources]
max_cores = <MAX_CORES_INTEGER>
max_committed_cores = <MAX_COMMITTED_CORES_INTEGER>

[programs.gaussian]
g16root = "<ABS_GAUSSIAN_EXECUTABLE_DIRECTORY>"

[programs.xtb]
root = "<ABS_XTB_CREST_INSTALL_ROOT>"

[local]
python = "<ABS_CHEM_PYTHON_EXECUTABLE>"
studies_root = "<ABS_LOCAL_STUDIES_ROOT_OUTSIDE_GIT>"
```

- `ssh.config_file` 填前一步创建的专用 SSH 文件绝对路径；`ssh.host` 填其中的 `Host`
  别名，不能把 `HostName` 的地址误填为一个未定义的别名。
- `remote.allowed_root` 填已存在的 SDL 根目录；`remote.ag_root` 必须严格等于它加上
  `/ag`，不填末尾斜杠。实际作业目录为 `<ABS_REMOTE_SDL_ROOT>/ag/<STUDY_ID>/<ATTEMPT_ID>`。
  远程路径不能包含空格、`..` 或符号链接，根目录需有访问和写入权限。
- `programs.gaussian.g16root` 的当前含义是**直接包含 `g16` 可执行文件的目录**。
  doctor 检查 `<ABS_GAUSSIAN_EXECUTABLE_DIRECTORY>/g16`，不是再向下一层找程序。
- `programs.xtb.root` 下应有 `bin/xtb`、`bin/crest` 和运行时所需的 `share/xtb`。
- `local.studies_root` 必须在任何 Git checkout 之外；`local.python` 记录所选化学环境的
  解释器。该字段不会自动切换当前 shell 的 Python，运行 `ag` 前仍需激活正确环境。
- `resources.max_cores` 限制单个作业和各资源档位；PBS 为 1–44，Slurm 为正整数。
  保留 `mini`、`simple`、`general`、`complex` 四档定义；`queue` 填管理员确认可用的队列。
- `resources.max_committed_cores` 是运行加排队的总额度，必须为整数，介于
  `max_cores` 和 `4 × max_cores` 之间；省略时等于 `max_cores`，保持原有额度。
  上面两个整数占位符替换后不要保留尖括号。单个作业仍受 `max_cores` 限制。
- PBS 和 Slurm 都按该用户在该集群上的全部运行及排队作业（含挂起、其他电脑和非 ag
  作业）检查总额度；Slurm 另计本地台账中尚未被调度器显示的预留。提交不读取 `pbsnodes`，
  `qstat` / `squeue` 无法统计时仍拒绝。确认期间每个作业提交前重新检查占用。
  确认对话框及终端摘要显示运行、排队、提交后合计和上限。ag 不限制运行中的核数：
  集群空闲时，排队作业可能同时运行，运行中的核数可能达到总额度。
- 每次 SSH/scp 调用（含只读重试）追加到配置目录内 `ssh-log/<集群名>-<YYYY-MM>.jsonl`。
  日志只含 UTC 时间、集群名、工具、操作类型、尝试序号、结果、返回码、耗时和错误类别，
  不含连接信息、命令、路径或 stderr 原文。文件权限为 0600，拒绝符号链接；
  写入失败仅警告，不改变原操作或重试规则，不自动删除历史日志。
- `ag monitor` 的 `ag-monitor/1` 输出在 `own` 中增量提供 `cores_running`、
  `cores_queued`、`committed_cap`；`core_cap` 表示单作业上限，`over-cap`
  按 `committed_cap` 判断。旧缓存可以缺少这些增量字段。

### 4. 用 ag doctor 验证

完成本地替换和主机信任准备后，在选定的 Python 环境中运行：

```bash
ag doctor --json
```

这是一次真实的**只读 SSH 环境检查**，会读取身份和作业清单、查询 `qstat -Q`、
检查允许根目录的访问/写权限及非符号链接条件，并检查 Gaussian、xTB、CREST 文件是否可执行。
它不会创建远程探测文件、提交作业、运行计算程序或清理服务器。

通过时退出码为 0，JSON 中 `ok`、`ssh`、`identity`、`scheduler`、`allowed_root`
为 `true`，并列出 `programs`、`occupied_cores`、`max_cores`、`max_committed_cores` 和 `inventory_seconds`。
`occupied_cores` 用于展示当前用户作业占用；提交时仍会重新核算容量。

doctor 通过只说明上述环境检查通过；它不验证科学方法、真实计算成功或研究完成，
也不替代提交授权核对或手动取消的人工对话框。可执行文件检查不会启动程序验证版本或运行依赖。

配置校验不通过时通常返回 1，SSH 或远程检查错误通常返回 2。
遇到错误，先保留脱敏信息，交由人核对相应配置或环境；不要运行提交来“试连接”。
当前只读传输对 SSH 连接失败/超时最多间隔 15 秒重试一次；这不允许重提作业，
真实环境意外仍须按 [AGENTS.md](../AGENTS.md) 停下来报告。

## 运行中日志快照：snapshot

`ag snapshot <ATTEMPT_ID> [--study <study>] [--max-bytes 20000000] [--json]`
只读复制已提交、有绑定作业号且尚未取回的 Attempt 的主程序日志。Gaussian 的日志名
由输入 stem 决定，xTB 为 `xtb.out`、CREST 为 `crest.out`，均取模板声明的第一项输出；
不接受远程路径。已取回（含不完整取回）的 Attempt 请直接看 `outputs/`。

每次独占创建 `<Attempt>/snapshots/<UTC时间戳>/`，包含原始日志字节和 `snapshot.json`：
读取时间、读取前远程大小/mtime、实际字节数、截断标记、本地 SHA-256、作业号及最近
本地状态。默认最多 20,000,000 字节；超过上限只保留读取前文件末尾的指定字节数。
读取使用 Linux `/proc/self/fd`、GNU `stat`/`tail`/`head` 和 `base64`，无远程临时文件；
拒绝链接、非普通文件、文件替换和短读。正在写入的日志不是原子文件系统快照。

Gaussian 摘要列出片段中的 SCF 次数/末次能量、Step number 记录数/末次步号、末次
四项收敛表原文、末次正常/错误终止标记及是否看见 Freq 输出标记。截断后仅统计片段，
丢弃开头可能不完整的一行；未见标记不代表相应阶段未开始。xTB/CREST 只保存主日志。
**运行中快照，不是结果，不能用于签字或分析。** 快照不写 `outputs/`，不更新状态、
journal、取回标记或 facts；不主动调用 `ag status`。后续 fetch/facts/证据清单不消费
这些快照。SSH 经现有 transport 记录到脱敏 ssh-log，操作类别为 `output_observation`。

## 取回输出：fetch

`ag fetch <ATTEMPT_ID> --json` 成功后自动在本地调用 `build_facts(refresh=False)`，
`--incomplete` 成功后也会解析，并保留不完整结果标记及原状态。新增的 `facts` 字段报告
`written`（首次写入）、`unchanged`（已有内容相同）、`conflict`（差异拒绝写入）、
`failed`（解析异常）或 `skipped`。可用 `--no-facts` 跳过；`--add-missing` 始终跳过，
缺少化学依赖也跳过，reason 分别为 `no-facts`、`add-missing`、`dependency-unavailable`。
每次成功取回后向 study journal 追加 `action=facts`、`result=auto`、`detail=facts` 记录，
包括跳过结果；补取原有记录不变。失败摘要仅保留首行、至多 300 字，study 内路径相对化，
其他绝对路径截去。冲突或解析失败会在 stderr 提示，但不回滚取回、不改变状态，退出码仍为 0。
已有 facts 内容相同时保留原字节和修改时间；不同时绝不自动覆盖。请人工核对差异后才使用
`ag facts <ATTEMPT_ID> --refresh`。journal 写入失败也只提示，请保留 JSON 输出以供核对。

## 弛豫扫描与 TS 初猜

Gaussian 的 Cartesian 输入后可使用 `Opt=ModRedundant` 扫描段，B/A/D 为键长、
键角、二面角，F 冻结行照旧；不得与 TS/QST 混用。一条 S 行保持原有 1–50 步、
摘要、facts 和 `scan-peak` 行为；xTB `$scan` 继续只允许一行（1–100 点）。
一维行为不变的唯一例外：Gaussian 一维、二维 S 行的步长都必须含小数点，
例如 `5.0`、`-5.0`、`.5`、`0.04`；整数写法 `5` 在准备时拒绝并提示改为 `5.0`。
这是提前拦截真实验证中 Gaussian L101 已会拒绝的输入，不自动改写输入字节。
Gaussian 两条 S 行表示二维网格：每维 1–20 步，包含起点，
`(n1+1)×(n2+1)` 不超过 144 点。两坐标不能共用全部原子（包括反向和重排）。
准备摘要分别显示两维起点、步数、步长、终点、单位和总点数；每点都是一次约束优化。
两维扫描的耗时约为把一个一维扫描重复另一维点数次，需相应估算 walltime。

`manifest.json` 的 `science.scan` 一维格式不变；二维格式如下（坐标顺序与 S 行一致）：

| 字段 | 含义 |
| --- | --- |
| `dimensions` | 固定为 `2`。 |
| `coordinates` | 两个定义；每个含 `coordinate`、`start`、`steps`、`step_size`、`end`。 |
| `coordinates[k].coordinate` | `kind`（B/A/D）、`atoms`（1-based 原子编号）、`elements`、`unit`（angstrom/degree）。 |
| `expected_points` | 两维各自 `steps + 1` 的乘积。 |

取回后 `ag facts <attempt>` 的 `scan` 保留这些定义并新增：

| 字段 | 含义 |
| --- | --- |
| `points` | `(n1+1)×(n2+1)` 的嵌套数组；`points[i-1][j-1]` 为网格点 `[i,j]`，缺失为 `null`，不插值。 |
| 每个非空点 | `point: [i,j]`（1-based）、`target_values`、`coordinate_values`（两维实测值）、`energy_hartree`、`converged`、`geometry_frame`（1-based XYZ 帧号）。 |
| `energy_kind` | Gaussian 为 `scf`；未报告能量为 `null`。 |
| `saddle_candidates` | 候选网格编号列表，如 `[[2,2]]`；仅作初猜提示，不是 TS 判定。 |
| `geometries`、`geometries_sha256` | `scan_points.xyz` 及其 SHA-256；无几何时前者为 `null`，后者不出现。 |

只将有 `Optimization completed/stopped` 证据的二维点定位；未结束的最后一次优化
不作为完成点，其格子保持 `null`。已完成优化但取不到几何的点则无法定位，
会保守地使整个扫描报错，不作为未完成点填入 `null`。
按各点几何实测两个坐标，各自唯一对到最近目标，
偏差必须严格小于半步长；半步边界按坐标的十位小数精度保守拒绝。
二面角以 360° 周期比较，因此跨 ±180° 可定位；周期别名无法唯一定位则拒绝。
无几何、无法匹配、重复占格或点数超出声明都使整个扫描报错。
网格编号不依赖 Gaussian 遍历顺序；XYZ 帧保留输出顺序，以 `geometry_frame` 关联。

鞍点提示要求内部点自身及上下左右四点都有能量且收敛，沿一个方向严格极大、
另一方向严格极小；边界和有缺失/未收敛邻点的点不列出。

```bash
ag scan-peak <attempt> --point 2,2 --out <new-seed.xyz> --json
```

二维必须人工指定候选，未指定或指定非候选均拒绝并列出全部候选；一维仍默认导出
最高严格局部峰，可用 `--point <序号>` 选择其他局部峰。导出仍为 XYZ，报告仍包含
`peak`、`relative_energy_reference`、`neighbors_before/after`、`warnings`、`jumps`、
`warning_thresholds`、`note`、`out`；二维另注明 `dimensions: 2`，使用 `coordinates` 和
`saddle_candidates` 替代一维的 `coordinate` 和 `local_maxima`。候选含相对能，
以全部已收敛点最低能为零（kcal/mol）；before/after 分别为两维负/正方向的紧邻点。
跳变检查沿网格边进行。已有输出拒绝覆盖，XYZ 哈希须与 facts 相符。
完整科学判据见 [TS 卡片](../skills-next/auto-g16-recipes/cards/ts.md)：初猜仍需 TS 优化、
频率方向审阅和双向 IRC。

## 本地审阅与旧 Attempt

`ag review init <ATTEMPT_ID> --json` 从准备时保存的卡片生成审阅骨架，
`ag review check <ATTEMPT_ID> --json` 检查判据、依据、结论和 facts 新鲜度。
两者只需要配置中的 `local.studies_root`；多集群配置里无关的 SSH 或程序环境字段
不会阻止本地审阅，远程操作仍使用完整配置校验。

旧 manifest 没有卡片记录时，可以明确补指定：

```bash
ag review init <ATTEMPT_ID> --card opt-freq --json
ag review check <ATTEMPT_ID> --json
```

生成的 `review.md` 会注明“卡片为审阅时补指定，非准备时记录”，保存当时的 Skills
完整提交号、dirty 标记和卡片内容。后续 check 使用保存的内容，不随当前卡片更新而改变。
manifest 保持原样；准备时已有卡片的 Attempt 不接受替换，已有 review.md 也不会被覆盖。
完整性检查通过不表示科学审阅通过或 study 完成。

## 签字证据清单：review manifest

```bash
ag review manifest --study '<STUDY_DIR>' --json
# 签字人逐条核对 unresolved_references 后：
ag review manifest --study '<STUDY_DIR>' --accept-unresolved --json
```

也支持位置参数 `ag review manifest '<STUDY_DIR>'`。命令无需配置或网络，
独占创建 `analyses/review-manifest-<UTC时间>.json`，记录 study.md、全部 facts.json/review.md
及递归引用的 analyses 文件的大小和 SHA-256；已有清单、签字及证据不改写。
生成清单不是科学签字，签字仍须绑定清单路径及返回的 SHA-256。

Markdown/文本中的显式 `analyses/` 前缀保留 T62 的 study 根目录语义。其余文本
和普通 JSON 引用先按源文件目录解析，非绝对且不以 `./`、`../` 开头
的路径允许回退到 study 根目录；两处存在且不是同一文件时拒绝，根目录回退记录
`resolved_from: study_root`。目录引用展开成员，记录 `expanded_from`。
普通 JSON 描述文字不推断成文件；远程 URL 不下载。

引用分成以下四类，按每次出现的位置记录，不按目标去重：

| 类别 | 处理 |
| --- | --- |
| `missing` | 无法解析的路径；裸文件名在源目录和根目录都找不到、但 analyses 任意位置有同名文件时也属此类，不猜测选择该文件。 |
| `escapes_study` | 字面规范化后越出 study；不访问外部目标，也不检查外部路径的符号链接。 |
| `outside_analyses` | study 内存在但在 analyses 外的显式引用，不新增收录；保存在信息性 `referenced_outside_analyses` 列表。 |
| `unqualified_name` | 不含 `/` 的裸名，源目录、根目录都找不到且 analyses 下无同名文件；不收录，保存在信息性 `unqualified_names` 列表。 |

前两类进入 `unresolved_references`，包含相对源文件 `source`、行号或 JSON 字段
`location`、原文 `value`（绝对路径替换成 `<absolute path>`）和 `reason`。
列表非空时终端逐条列出，退出码 **4**，不写清单；核对后显式加 `--accept-unresolved`
才写入，并保存完整列表、`unresolved_accepted: true`、UTC 确认时间
`unresolved_accepted_at`。每次重新运行重新收集，不沿用上次确认。
信息性条目无需确认，不改变退出码；终端每类只显示条数（JSON 中为
`outside_analyses_count` / `unqualified_name_count`），详情保存在清单中。

study 内符号链接、歧义、非法显式路径、空分析目录、收集期间证据哈希变化仍是硬错误，
不能用接受参数绕过。JSON 的 `thermo`、`frozen_evidence` 保留原解析基准，
缺失或越界仍硬拒绝，不获得普通 JSON 回退或裸名豁免。
已签 `ag-review-manifest/1` 只哈希、不展开；schema 名保持不变。
没有上述新分类条目时清单格式不变。

## 本地自主运行记录：autonomy

`ag autonomy` 在已有 study 的 `autonomy/` 内保存计划、运行租约和日志，
只加载本地配置，不连接集群、不运行量化程序，也不修改 Attempt、facts、签字或 `study.md`。
本模块尚未接入 `ag prepare`、`ag submit`、`ag cancel`；计划确认和资格检查都不是提交批准，
这些记录本身不能启用自主计算。所有子命令默认输出 JSON，接受 `--json`。

先准备计划正文 JSON，再依次执行；尖括号内容须替换为实际值：

```sh
ag autonomy init --study '<STUDY>'
ag autonomy plan --study '<STUDY>' --input '<PLAN_JSON>'
ag autonomy confirm --study '<STUDY>' --plan '<PLAN_ID>' --sha256 '<PLAN_SHA256>' --quote '<负责人确认计划的逐字原话>'
ag autonomy begin --study '<STUDY>' --plan '<PLAN_ID>' --quote '<负责人明确开始新授权轮次的逐字原话>'
ag autonomy start --study '<STUDY>' --plan '<PLAN_ID>' --owner '<SESSION_ID>'
ag autonomy status --study '<STUDY>'
```

`plan` 返回新 `plan_id`、完整计划和 SHA-256，创建不会自动确认。
`confirm` 核对原计划字节、哈希、版本和有效期后追加原话；CLI 不能验证说话者身份，
会话须核对负责人确已确认。已有计划文件从创建起即不覆盖；修改计划须先结束当前唤醒运行，
再创建、审阅和确认新计划，旧确认不转移。

计划、授权轮次和一次唤醒运行分别记录：`begin` 只在 `phase: ended` 时接受明确原话，
核验已确认且仍有效、版本一致的计划后创建新的 `current_round`，历史保留在 `rounds`。
`begin` 输出的 `state.current_round` 是本轮 ID，结束时须用它明确指定目标轮次。
`start` 只在该轮 `running` / `paused` 时取得一次运行租约，不另开授权轮次。
同轮可以有多次唤醒；唤醒间采用新确认的修订计划也保留本轮已用计数。
`begin` 保留之前的暂停标志；新轮若处于 `paused`，取得唤醒租约后仍须显式 `resume`，新预算不自动撤销暂停。

`<PLAN_JSON>` 只含下列字段；版本和创建时间由命令从实际运行环境取得，不能由输入替换：

| 字段 | 值与含义 |
| --- | --- |
| `goal` | 非空目标文本 |
| `comparison_groups` | 非空字符串列表，列出比较组 |
| `method_policy` | 非空方法口径文本 |
| `mechanism_scope` | 非空机理范围文本 |
| `system_rules` | 只含 `main`、`small` 的对象，两项均为非空判定规则文本 |
| `estimated_hours` | 正的有限数，耗时预估（小时） |
| `attempt_limit` | 正整数，当前授权轮次的本地 Attempt 意图上限 |
| `valid_until` | 晚于创建时间的 Unix 时间戳（UTC 秒） |

保存的 `versions` 包含 `ag_version`、完整 `git_commit`、`dirty` 和实际安装的
`rdkit`、`goodvibes` 版本。创建计划要求 ag 源码检出干净、提交可核验且两项依赖版本可读，
避免同一提交号下不同未提交源码沿用旧计划。确认、开始及动作检查核对当前版本与计划一致；
版本改变须创建并重新确认计划，不硬编码历史依赖版本。

`start` 返回本次唤醒的 `run_id` 和 `token`，持有者后续命令须同时提供。令牌只在开始结果中返回，
状态查询不公开令牌哈希。单次运行从开始起严格少于 60 分钟；到 60 分钟时旧持有者不能再写入或通过动作检查，
租约仍保留至 90 分钟，不能借恢复或续期延长本次唤醒。正常结束应在 60 分钟内执行 `finish`。
`finish` 仅关闭本次唤醒和租约，授权轮次继续保持 `running` / `paused`；`end` 才明确结束整个授权轮次。

```sh
ag autonomy check --study '<STUDY>' --run '<RUN_ID>' --token '<TOKEN>' --sha256 '<PLAN_SHA256>' --for-action prepare
ag autonomy update --study '<STUDY>' --run '<RUN_ID>' --token '<TOKEN>' --input '<UPDATE_JSON>'
ag autonomy pause --study '<STUDY>' --reason '<暂停原因>'
ag autonomy resume --study '<STUDY>' --run '<RUN_ID>' --token '<TOKEN>' --reason '<明确恢复原因>'
ag autonomy finish --study '<STUDY>' --run '<RUN_ID>' --token '<TOKEN>' --reason '<本次唤醒结束原因>'
```

`<UPDATE_JSON>` 只含 `summary`（字符串）、`pending`（非空决定事项的字符串列表，可为空列表）、
`objects`（对象 ID 到动态内容的映射）。它不接受计划、租约、计数等生命周期字段。
`pause` 无需持有者令牌，只等待短文件事务；发布后检查拒绝新的准备、提交、补救、取消和改投动作。
暂停时当前持有者仅可检查 `observe`、`fetch`、`organize` 并整理记录或结束，仍受原期限、计划及版本核验约束。
`finish`、租约恢复和接管不会清除本轮暂停，必须由当前持有者显式 `resume` 才能恢复；无回复或超时不视为恢复。

同一授权轮次中的两次唤醒和显式结束示例：

```sh
ag autonomy start --study '<STUDY>' --plan '<PLAN_ID>' --owner '<FIRST_SESSION>'
ag autonomy finish --study '<STUDY>' --run '<FIRST_RUN>' --token '<FIRST_TOKEN>' --reason '<第一次唤醒完成>'
ag autonomy start --study '<STUDY>' --plan '<PLAN_ID>' --owner '<SECOND_SESSION>'
ag autonomy finish --study '<STUDY>' --run '<SECOND_RUN>' --token '<SECOND_TOKEN>' --reason '<第二次唤醒完成>'
ag autonomy end --study '<STUDY>' --round '<ROUND_ID>' --reason '<明确结束授权轮次>'
# 此时再次 start 会被拒绝，必须先显式 begin 新轮次。
ag autonomy start --study '<STUDY>' --plan '<PLAN_ID>' --owner '<LATER_SESSION>'
```

每次 `end` 都须提供 `--round '<ROUND_ID>'`；命令在锁内核对当前轮次并写入日志，避免迟到的结束请求关闭较新的轮次。
如果该轮仍有当前租约，还须提供 `--run '<RUN_ID>' --token '<TOKEN>'` 并通过持有者期限核验；
无租约时可直接显式 `end --round '<ROUND_ID>' --reason '<原因>'`。新轮次须重新 `begin --plan --quote`，不会由定时唤醒自行产生。

90 分钟到期后，可显式接管仍有效的计划；日志记录被接管租约与原因，新运行生成新令牌，旧持有者不能写入、恢复或结束新运行：

```sh
ag autonomy start --study '<STUDY>' --plan '<PLAN_ID>' --owner '<NEW_SESSION_ID>' --takeover-reason '<接管原因>'
ag autonomy recover --study '<STUDY>' --reason '<关闭过期租约并保留记录的原因>'
```

上面两条是不同处理方式。无令牌的 `recover` 可在 90 分钟到期后记录并关闭旧租约，
即使旧计划已经过期，也可随后创建新计划；它只关闭唤醒，保留授权轮次状态与计数，不会开始运行或清除暂停。
未到期的租约不能这样关闭。

计数只追加本地意图，按请求、对象、失败类别、授权轮次和唤醒运行追溯：

```sh
ag autonomy count --study '<STUDY>' --run '<RUN_ID>' --token '<TOKEN>' --kind remedy --request-id '<REQUEST_ID>' --object-id '<OBJECT_ID>' --failure-class '<FAILURE_CLASS>' --evidence '<本地意图依据>'
```

`kind` 为 `attempt`、`remedy`、`cancel` 或 `reroute`。同一请求 ID 在同次唤醒以相同内容重试仅返回确认，不重复计数；
改内容或改运行复用请求 ID 会拒绝。`totals` 保留全部历史，`rounds` 保留逐轮计数，`runs` 保留逐次唤醒计数。
`attempt_limit` 按当前授权轮次计数限制新增 `attempt` 意图和 `prepare` 资格；`finish`、再次唤醒、接管或修订计划均不重置本轮消耗。
只有显式 `end` 后重新 `begin` 才开始新的轮次预算，旧轮次和全历史累计仍保留。
`submit` 检查不据计数拒绝已计数的最后一个 Attempt。
真实提交数仍须由后续集成核对不可变声明和绑定；JSON 明示 `submission_counts_verified: false`，
不能把人工增加计数当作实际提交或取消的证据。

文件均位于 study 的 `autonomy/`：`plan-<PLAN_ID>.json` 为不可变计划；`journal.jsonl` 为追加事件；
`state.json` 是含 `seq`、`journal_sha256`、`state` 的原子快照；`store.lock` 是不删除、不更换的短操作 OS 互斥文件。
状态保存授权轮次的 `phase`（`running` / `paused` / `ended`）、暂停标志、`current_round` / `rounds`、
当前计划、租约、`runs` 唤醒历史、
摘要、待决定、动态对象及计数；只读输出另给当前 `plan_sha256`、`versions`。
日志含序号、前项 SHA-256、时间、动作及数据；每次先追加并落盘日志，再原子发布状态并同步目录。
普通命令要求状态与完整日志一致，`status` 和 `check` 不创建文件或修复记录。

若进程在日志落盘后、状态发布前退出，普通操作拒绝继续；仅可显式恢复已核验的旧快照：

```sh
ag autonomy recover --study '<STUDY>' --run '<RUN_ID>' --token '<TOKEN>' --reason '<核验后的崩溃恢复原因>'
ag autonomy start --study '<STUDY>' --plan '<PLAN_ID>' --owner '<NEW_SESSION_ID>' --takeover-reason '<过期接管原因>' --recover
```

第一种仍要求当前持有者和 60 分钟内期限；第二种要求 90 分钟过期接管。
无租约的有效旧快照也可用无令牌 `recover` 发布。完整初始化事件是唯一允许恢复缺失初始快照的情形；
其他缺失状态、截断或修改的状态、部分日志、哈希不符均拒绝，计数不会退回零。
恢复追加新记录，保留旧日志与失败遗留文件；不要手工删除锁、截断日志或重跑初始化来清除错误。

供后续集成的 `action_guard(...)` 在同一短互斥内核对计划哈希、版本、持有者、期限与暂停，
只能包住短本地声明或决定，不能包住网络操作或完整运行，也不能嵌套调用其他 autonomy API（会再次获取锁）。
`check(...)` / CLI `check` 只表示检查当时的结果，
不能缓存为以后提交的许可证；后续入口须在各动作边界重新检查，并独立满足现有提交、取消及证据要求。
当前版本或计划哈希不符会拒绝本次检查，但尚未自动发布暂停。T186 接入时须扩展 guard，
在同一次 `store.lock` 动作事务内追加并发布暂停后，才处理后续动作；不能在持锁的 `action_guard` 内嵌套调用 `pause()`。

## 本地开发与验证

从仓库根目录运行 `python -m pytest ag/tests`，测试通过替身模拟远程操作。
提交前仅暂存本次改动，再运行 `python ag/tools/scan_sensitive.py --staged`。
不要把真实配置、SSH 输出、主机公钥记录、私钥或 study 产物用作公开测试数据。

CLI 子命令模块通过 `register(subparsers)` 注册，用 `set_defaults(func=handler)`
指定处理函数；确定性本地工具与远程作业控制分别维护，科学判据放在 `skills-next/` 的卡片中。

## 本地分析命令：结构比较（topology）

`ag topology <ATTEMPT_ID> --out <NEW_REPORT.json>` 中，片段数只有在不确定接触按
“相连／不相连”两种处理均同向变化时才据此判为 `changed`；若片段数结论依赖这些接触，
列出接触证据，并在没有已确定的键变化时保留 `unknown`，已有确定键变化则保留 `changed`。
两种处理都不变则继续原有连接/立体比较，状态不代替科学审阅。
`topology` / `irc-compare` 在含全部 H 的编号连接与逐片段总电荷相同时，双向枚举共振式：
等价时保留原始键级差异并记录 `resonance_check`、`resonance_equivalent` 和
`bond_differences_resonance_equivalent`；达到每向 1000 式上限或失败保留 unknown，立体比较独立进行。

## 本地分析命令：构象局部判别（dedup）

`ag dedup` 可按使用者指定的二面角分组保留局部不同的构象，避免局部转动被整体
RMSD 稀释。所有新选项均为可选；不加时保留原来的行为与输出格式。
分组组合相同后，仍按原来的 RMSD、能量差和能量窗口判断。

```bash
ag dedup conformers.xyz --charge 0 --out study/analyses \
  --dihedral-bins '1,2,3,4:-90,90@s-cis,s-trans' \
  --dihedral-bins '5,6,7,8:-60,60,180@rot0,rot120,rot-120' \
  --report-distance 9,10 --contact-atoms 9,10 --contact-cutoff 3.0 --json
```

编号是 XYZ 中从 1 开始的原子序号（不含前两行）。示例的 1–2–3–4 表示酰基
二面角，5–6–7–8 表示新键转子，9、10 可替换为要审阅的 B···O 原子对。
这些编号仅为示意，须按实际结构和已审阅的分组定义替换；不会自动推断构象家族。
跨来源模式 `--source A=route-a.xyz --source B=route-b.xyz` 支持同样的选项，
仍沿用已有的几何合并或 `--representative lowest` 同方法 Hartree 能量口径。
各来源须使用相同的原子编号含义；局部描述符按原始 XYZ 编号计算，不跟随 RMSD
的对称原子重排重新映射。

- `--dihedral-bins A,B,C,D:b1,b2,...[@name1,name2,...]` 可重复。
  分界必须在 −180° 到 180° 内严格升序，并在周期意义下互异（不能同时列 −180 和 180）。
  第 1 组为 `[b1,b2)`，依次递推，最后一组从最后分界跨周期到第一个分界；
  恰在分界的角属于从该分界开始的组。每个分界对应一个组名，省略时为 `bin1` 等。
  例如 `-90,90` 的第 2 组包含 +179° 与 −179°。
- `--report-distance I,J` 可重复，按定义顺序报告 Å 距离，不影响合并。
- `--contact-atoms I,J,K,...` 可重复，取所有编号的并集；
  `--contact-cutoff X` 默认为 3.0 Å，可为非负有限数，重复时最后一个值生效。
  接触包括至少一端在所选集合中、距离严格小于阈值的所有原子对，
  包括成键对和氢，排除自身，去重并按编号排序；它只供审阅，不影响合并。
  指定 cutoff 时须同时给 contact-atoms，避免误以为仅给阈值就会生成接触指纹。

JSON 仅在启用新选项时增加下列字段：

- 顶层 `descriptors`：`dihedral_bins`（atoms、boundaries、names）、
  `distance_pairs`、合并后的 `contact_atoms` 和 `contact_cutoff`。
- `kept` 与 `excluded` 各行及跨来源 `members`：`dihedrals`（有符号度数，
  范围 `[−180,180)`）、`bins`（从 1 开始的组号）、`distances`（Å）均按定义顺序排列；
  `contacts` 为排序后的 `[i,j]` 列表。
  `near_boundary` 在任一二面角距任一分界的周期差小于 5° 时为 true，供人工筛查，
  不调整分组。未请求的数组为空，未请求二面角时 near_boundary 为 false。
- 被合并行另有 `max_periodic_dihedral_difference`（与实际代表构象比较的最大周期差，
  单位为度，未请求二面角时为 null）；跨来源的被合并成员也保留此值。
- 顶层 `kept_by_bins`：最终保留代表中 RMSD 低于阈值但组号组合不同的所有配对，
  含原始全局 `indices`、`rmsd` 和双方 `bins`。此审阅列表不按能量差过滤，
  不表示每对都仅因分组而保留；不包含已被同组合代表合并或被能量窗口排除的帧。

重复或越界编号、错误分界/组名、共线或重合导致未定义的二面角均报错，
不会跳过坏定义或给它默认组号。所有帧先验证描述符再筛选，即使帧随后可能被能量窗口排除。

## 本地分析命令：构象集合清单

`ag ensemble` 汇总已保存的 dedup、Attempt facts 和可选热化学表，生成同名 JSON 与 Markdown。
相对路径在提供 `--study` 时相对 study 根目录；输出必须位于 `analyses/` 内、与 merged JSON
和它绑定的 XYZ 同目录，任一输出已存在就拒绝。

```bash
ag ensemble --study '<STUDY_DIR>' --merged analyses/group/merged.json \
  --out analyses/group/ensemble.json --label '构象集合' \
  --route crest=sample-001 --sp sp-001 sp-002 --opt opt-001 opt-002 \
  --thermo analyses/thermo.json
```

`--sp` 也可给一个只含本 study Attempt ID 的 JSON 列表。匹配保持输入原子顺序，
不对齐或改编号；多重匹配保留歧义。不同路线的 xTB 能量不可比较时，只列路线内相对能。
热化学数值直接复制，不重算布居、不选代表构象、不作科学验收。
字段与空值语义见 [ag-ensemble/1](../docs/ag-ensemble-1.md)。

需要在集合中查看局部构象时，可重复传入与 `dedup` 相同的定义：

```bash
ag ensemble --study '<STUDY_DIR>' --merged analyses/group/merged.json \
  --out analyses/group/ensemble-local.json \
  --dihedral-bins '1,2,3,4:-90,90@s-cis,s-trans' \
  --report-distance 5,14 --report-distance 1,4
```

原子编号与分组名称须按实际 XYZ 和已审阅定义替换。每个候选的 `local` 报告
二面角（度）、组名、距分界小于 5° 的标记和距离（Å），Markdown 同步展示。
`bin_summary` 按组合计数，在组内首个有能量的 thermo → opt → sp → xTB 层级中
选最低能候选；等能取最小编号，无可比能量时为 null。仅报告距离时组合为 `[]`。
此汇总不改变候选集合或科学验收状态；不支持 `--contact-atoms`。
不传上述参数时，保持原有 JSON/Markdown 输出，不自动继承 merged 的描述符。
新增字段仍属于 `ag-ensemble/1`，具体语义见上述字段文档。

## 本地分析命令：通道采样覆盖

`ag channel-coverage` 按明确填写的 CSV 通道表汇总 `ag-ensemble/1` 清单，
同时报告通道与产物分支的候选、路线、SP、Opt、热化学、歧义和未匹配记录数量。

```bash
ag channel-coverage --study '<STUDY_DIR>' --channels analyses/channels.csv \
  --out analyses/channel-coverage.json --imbalance-ratio 0.5
```

CSV 必须含 `channel_id,product_branch,ensemble_manifests`，可选 `note`；
清单相对 study 根目录，多个用分号分隔。CSV 和输出均位于 `analyses/` 下，
同名 JSON/Markdown 已存在就拒绝；只读本地已保存记录，无需集群。
阈值只提示候选、SP、Opt 数的相对不均衡，不判定覆盖是否足够。
最低候选依 thermo > opt > sp > xTB 的可用能量选择；多清单 xTB 零点无法比较时
保留各清单最低值并说明原因。字段及计数口径见 [ag-channel-coverage/1](../docs/ag-channel-coverage-1.md)。

## 本地分析命令：thermo / profile 输入一致性

`ag thermo` 只汇总同一组成、电荷、多重度且频率层方法/程序版本一致的构象集合。
单点修正必须全有或全无；全有时单点层的方法/程序版本也必须一致。
不一致时列出 Attempt 和差异字段，不生成布居表。
**分子式相同不等于同一物种，是否属于同一物种的构象集合仍由人审阅。**

`thermo` 与 `profile`（缓存 thermo、直接 Attempt 两条通路）共用频率证据检查：
`freq_step_converged is True`、`vibrational_modes_complete is True`，独立 Freq 同样适用。
明确失败时附收敛表或实际/预期模式数；未知值不按通过处理。
旧 facts 缺字段时提示先人工核对原日志，再运行 `ag facts <attempt> --refresh`，分析不改写 facts。
单原子只豁免模式完整性，并在 JSON/Markdown 注明无振动模式；仍要求频率阶段明确收敛。
thermo 的零虚频要求、profile 的唯一 TS 虚频及方向审阅要求保持不变。

profile 直接 Attempt 的 SPC（包括 TS 精化）复用 thermo 配对检查：
核对 manifest 绑定的 SP 输入字节、固定原子行序、全部原子的 proper Kabsch 对齐，
RMSD ≤ 0.001 Å；不做反射或原子置换，SP 输入不能是优化、IRC 或扫描。
JSON/Markdown 记录 RMSD、SP 输入及频率最终几何 SHA-256；缓存 thermo 保留其原有配对证据。

`protocol()` 增加 `basis_function_type`：显式 5D/6D、7F/10F 参与方案比较，
未指定记 `basis_default`，不推断与某个显式形式等价。
积分设置由 `integration_grid()` 单独读取 Int/Integral 写法，记录在每个构象的
`integration_grid.frequency/single_point` 中；未指定为 `program_default`。
同一集合、频率与 SP 层或整个 profile 的网格设置不同时，仅在 JSON/Markdown 警告；
不参与 `protocol()` 相等比较。默认网格依程序版本而异，不推断与显式网格等价。

电子能目前来自 `SCF Done`，因此 `protocol()` 只接受 `SCF_ENERGY_METHODS` 常量中的
HF/普通 DFT 名称（大小写不敏感，支持 R/U/RO 前缀及方法名中的连字符；前缀不在方案比较中消去）：

```text
HF LSDA SVWN SVWN5 SLYP BLYP BP86 BPW91 BPE BPBE G96LYP G96P86 G96PW91
PW91LYP PW91P86 PW91PW91 MPWLYP MPWPW91 MPWPBE PBE PBE0 PBEPBE PBE1PBE
B3LYP B3LYP5 B3P86 B3PW91 B1B95 B1LYP B1PW91 B98 B971 B972 B97D B97D3
MPW1PW91 MPW1LYP MPW1PBE MPW3PBE MPW3LYP MPW1B95 MPWLYP1M
O3LYP OLYP OPBE X3LYP CAM-B3LYP LC-WPBE WB97 WB97X WB97XD
M05 M052X M06 M06L M062X M06HF M08HX M08SO M11 M11L MN12L MN12SX MN15 MN15L
TPSSTPSS TPSSH REVTPSS REVTPSSH VSXC HCTH93 HCTH147 HCTH407 THCTH THCTHHYB
SOGGA11 SOGGA11X N12 N12SX HSEH1PBE HSE1PBE HSE2PBE OHSE1PBE OHSE2PBE
```

保留普通 DFT 的内置色散及显式 `EmpiricalDispersion` / `Em` 设置。
这份名单只界定能量提取能力，不替代科学方法表或程序自身支持范围。
`NON_SCF_METHOD_PREFIXES` 拒绝以下方法族及其派生写法：MP2/MP3/MP4/MP5、CC、QCISD、
CBS、G1/G2/G3/G4、B2（含 B2PLYP）、mPW2（含 mPW2PLYP）、DSD/DOD/revDSD/revDOD、
PBE0DH/PBEQIDH、PWPB95、XYG、wB97X-2、ONIOM、AM1/PM3/PM6/PM7、PDDG、MNDO、
CNDO/INDO/ZINDO、DFTB、UFF/Dreiding/Amber、CIS、EOM、BD、CAS、SAC、TD。
未知名称也拒绝并提示“当前只支持 SCF 能量的方法”，不将相关能、复合能或激发态能误当 SCF 能。
共享 `protocol()` 的 `ag asm` 与 T79 `ag irc-review` 同样受方法限制和基函数形式比较影响；
T79 若晚于此改动合并，需要 rebase 并验证其协议比较和测试。

## 本地分析命令：畸变–相互作用分析

`ag irc-review` 按 IRC 卡片四条判据分别核对 forward/reverse，并导出逐点电子能、
目标键长、日志行号与路径 XYZ。判据①只能给出工具部分的结论；仍需人工审阅连续性与化学身份。

```sh
ag irc-review --study '<STUDY_DIR>' --ts '<TS_ATTEMPT>' \
  --forward '<FORWARD_IRC>' --reverse '<REVERSE_IRC>' --pair 1-2 \
  --forward-reference '<EXPECTED_FORWARD>' --reverse-reference '<EXPECTED_REVERSE>' \
  --forward-endpoint '<FORWARD_OPT_FREQ>' --reverse-endpoint '<REVERSE_OPT_FREQ>' \
  --irc-compare analyses/endpoint-comparison.json --out analyses/irc-review.json
```

缺失 reference、端点或比对证据对应 `unknown`。默认降能阈值保持 3 kcal/mol；正降能不足阈值且
其他三项工具核对通过时记 `met_by_endpoint_optimization`，不改变实际降能。
四个输出文件均须不存在；签字 study 的只读核对可显式写到 study 外的新报告，输入仍限同一 study。
详见 [ag-irc-review/1](../docs/ag-irc-review-1.md)；`--energy-noise` 默认容许 0.01 kcal/mol 上升噪声。

`ag asm split` 按人工指定的原子编号导出片段 XYZ，保留 `original_atoms` 映射；
`ag asm summary` 核对已有 Gaussian 电子能、几何、电子态和方法口径后，汇总相互作用能、
可选参照下的畸变能及两个竞争体系的差值（b − a）。片段电荷与多重度由人指定。

```sh
ag asm split '<ATTEMPT>' --study '<STUDY_DIR>' --geometry input \
  --atoms 1-3 --name first --out analyses/first.xyz
ag asm summary --study '<STUDY_DIR>' --definition analyses/asm-definition.json \
  --out analyses/asm.json
```

`input` 取提交几何，`final` 取 `final_input.xyz`；坐标逐原子核对，不做对齐或重排。
所有文件限同一 study，输出独占创建。只用电子能，不含零点能、热校正或 BSSE 校正，
不判断选择性来源。定义、公式及几何哈希的间接证据绑定见 [ag-asm/1](../docs/ag-asm-1.md)。

## Multiwfn 非共价相互作用分析

`ag prepare --template multiwfn --analysis igm|igmh --grid low|medium|high --fragments <CSV>`
在 default PBS 运行固定版本 Multiwfn 2026.10.1。IGM 接收最多 50 帧 XYZ；IGMH 复用正常结束
Gaussian 父 Attempt 的 chk，作业内 formchk，fchk 留远程。片段 2–4 个，由人确认。
`ag fetch <Attempt> --no-facts` 后用 `ag nci-report <Attempt> --out analyses/<new>.json`，
输出原子/原子对贡献、片段汇总、版本与输入输出哈希；不代表相互作用能量分解。
配置、命令示例、格点与文件大小、完整输出名单和 JSON 字段见 [ag-nci/1](../docs/ag-nci-1.md)。
