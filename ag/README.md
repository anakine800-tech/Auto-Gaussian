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

## 本地开发与验证

从仓库根目录运行 `python -m pytest ag/tests`，测试通过替身模拟远程操作。
提交前仅暂存本次改动，再运行 `python ag/tools/scan_sensitive.py --staged`。
不要把真实配置、SSH 输出、主机公钥记录、私钥或 study 产物用作公开测试数据。

CLI 子命令模块通过 `register(subparsers)` 注册，用 `set_defaults(func=handler)`
指定处理函数；确定性本地工具与远程作业控制分别维护，科学判据放在 `skills-next/` 的卡片中。

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
