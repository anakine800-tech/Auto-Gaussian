# Auto-Gaussian CLI

`ag/` 是独立 Python 项目，负责安全的作业生命周期和确定性本地工具。
从仓库根目录在 Python 3.11+ 环境运行 `python -m pip install -e 'ag[test,chem]'`，
然后用 `ag --version` 和 `ag --help` 检查安装。
整体架构、常用命令和 Skill 部署见[根目录 README](../README.md)；
规则见 [AGENTS.md](../AGENTS.md)，设计见[改造方案](../docs/REDESIGN-PLAN.md)。

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
也不替代提交和取消时的人工对话框。可执行文件检查不会启动程序验证版本或运行依赖。

配置校验不通过时通常返回 1，SSH 或远程检查错误通常返回 2。
遇到错误，先保留脱敏信息，交由人核对相应配置或环境；不要运行提交来“试连接”。
当前只读传输对 SSH 连接失败/超时最多间隔 15 秒重试一次；这不允许重提作业，
真实环境意外仍须按 [AGENTS.md](../AGENTS.md) 停下来报告。

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

## 本地分析命令：畸变–相互作用分析

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
