# T130：入口可配置 SSH 连接超时

版本：v1（监督方，2026-10-25）。**开发机做。** 后端出一个 PR，PR 描述第一行写 `Task: T130`。

## 分支与目标

- 分支：`codex/t130-ssh-connect-timeout`。
- **开工条件：** 以后端 main（不早于 `v4.5.1` 发版合并提交）为基线；T130 编号未被占用。C 批顺延到 T131 起。
- **问题来源（研究用计算机 10-25 实测）：** 经转发连接某 PBS 入口时，每条 SSH 要 14–24 秒，建立连接经常接近或超过 ag 写死的 `ConnectTimeout=15`。日志中失败调用的耗时都是 15.1–15.5 秒、`exit 255`、`connection_timeout`。`ag doctor` 内置的单次重试有时也连续两次超时，导致 doctor 失败、部署中止。监控没有重试，会频繁失败。提交的第一次连接没有内置重试，同样会受影响。
- **负责人 2026-10-25 决定：**
  - S1 入口新增可选配置 `ssh.connect_timeout_seconds`，整数，范围 15–60，默认 15。不配置时行为与现在逐字节相同。
  - S2 对该入口**所有** SSH 和 scp 调用生效：监控、doctor、status、fetch、snapshot、submit、cancel、chk 复制、上传、下载。只延长建立连接的等待时间，**不改**任何命令语义、只读重试规则、UNKNOWN 处理和提交确认流程。
  - S3 每条命令的总超时自动加上多出来的连接时间：**实际总超时 = 原值 + (connect_timeout_seconds − 15)**。这包括 `remote.Command.timeout`（含存储查询 30 秒、提交 120 秒等）、scp 上传的固定 60 秒、下载的“无进展”判定阈值。默认配置下所有数值不变。
  - S4 部署值：两台电脑的 PBS 入口都设 40（直连时只是失败时多等一会儿，切换连接方式时不用改）；Slurm 入口不配置。**本单不改任何电脑上的配置。**
  - S5 不单独发版：合并后不改版本号、不写 CHANGELOG，留到 C 批完成后随 v4.6.0 发布。
- **资料：** `ag/src/ag/transport.py`（`SSHTransport.__init__` 的 `options`、`run`、`upload`、下载循环与 `DOWNLOAD_STALL_SECONDS`、`_perform`）、`ag/src/ag/monitor.py`（`MonitorTransport._execute` 复制了基类逻辑，见 T127 非阻塞建议 1）、`ag/src/ag/remote.py`（`Command.timeout`）、`ag/src/ag/doctor.py`（`storage` 的 timeout 参数）、`ag/src/ag/config.py`（`validate_cluster`、旧单集群合并）、`ag/src/ag/fetch.py`（`_IncompleteSSHTransport`）。
- **新增配置项防的事故：** 就是上面的问题来源。除此之外不加新检查。

## 允许改动的路径

- `ag/src/ag/transport.py`：从配置读取连接超时；生成 `-o ConnectTimeout=<值>`；统一在一个地方计算“额外连接时间”，并加到命令总超时、上传超时和下载无进展阈值上。
- `ag/src/ag/monitor.py`：只在 `MonitorTransport._execute` 需要跟随基类时修改；**推荐顺带消除它对基类 `_execute` 的复制**（改为调用基类并只附加失败分类），以免以后再漏改。若改动超出这一处，停下来问。
- `ag/src/ag/doctor.py`：只在 `storage` 的显式 timeout 需要加上额外连接时间时修改。
- `ag/src/ag/config.py`：**只新增** `ssh.connect_timeout_seconds` 的校验（整数，15–60；布尔值和字符串都拒绝）。如果 `ssh` 表有允许字段集合，就加进去；旧单集群配置也要支持。
- 测试：`ag/tests/test_transport*.py`、`test_monitor*.py`、`test_doctor*.py`、`test_config*.py`、`test_fetch*.py` 中受影响的用例（PR 中逐个列出）；新建 `ag/tests/test_connect_timeout.py`。
- 文档：`README.md`（配置一节）、`docs/OPERATIONS.md`（第 6、7 节各加一句：慢链路时 PBS 入口建议 40）；本单 `docs/redesign-tasks/T130-ssh-connect-timeout.md`、`docs/redesign-tasks/open-tasks.txt`。
- **不改** `remote.py` 里的命令文本和白名单、`submit.py` 的流程、`AGENTS.md`、`ag/templates/`、前端仓库、`CHANGELOG.md` 和版本号。

## 要做的

1. **配置**：入口的 `[clusters.<name>.ssh]`（旧单集群为 `[ssh]`）新增可选整数 `connect_timeout_seconds`。校验规则同 S1。`cluster_identity()` 不受影响：共享上限分组只看配置文件、主机和调度器，不看超时。
2. **传输层**：
   - `SSHTransport` 按配置生成 `ConnectTimeout`。其他 `-o` 选项和顺序不变（`BatchMode=yes`、`StrictHostKeyChecking=yes` 保持在前）。
   - 增加一个只读属性或方法，例如 `extra_connect_seconds = connect_timeout − 15`，**所有**固定超时都从这里取，不在各处重复计算：
     - `run()` 交给 `_logged_execute` 的 `command.timeout`；
     - `upload()` 的 60；
     - 下载的无进展阈值。
   - 只读命令“连接失败后等 15 秒重试一次”的规则不变：仍然只重试一次，等待时间不随配置变化。
3. **监控**：`MonitorTransport` 的连接超时和总超时与基类一致。按“允许改动的路径”里的推荐消除复制，并保留 T127 的失败分类行为（在脱敏前分类）。
4. **doctor 与存储查询**：`storage(..., timeout=30)` 这类显式超时同样加上额外连接时间。
5. **其他调用方**：逐个检查直接构造 `SSHTransport`（或其子类）、直接调用 `ssh`/`scp` 的位置（例如 `cli.py`、`attempt.py`、`fetch.py`、`parent_chk_remote.py`、`monitor.py`），确认都走同一个配置。`login_user` 的本机 `ssh -G` 不连接服务器，不在本单范围内。PR 里列出检查过的全部位置。
6. **文档**：README 写明字段、范围、默认值、“总超时自动顺延”和使用场景（经转发等慢链路）；OPERATIONS 第 6、7 节各补一句。

## 不允许

- 不改命令文本、白名单、提交和取消流程、UNKNOWN 处理、只读重试次数，不新增远程命令。
- 不把连接超时做成全局开关或环境变量，只能按入口配置。
- 不改任何电脑上的配置、服务和检出；不发版。
- 夹具和 PR 里不出现真实主机、用户名、端口、路径或转发方式。

## 测试

| 场景 | 预期 |
|---|---|
| 不配置 | 生成的 ssh/scp 参数与 main 逐字节相同；所有总超时不变 |
| 配置 40 | `-o ConnectTimeout=40`；`Command` 60 → 85、120 → 145；上传 60 → 85；下载无进展阈值 +25；存储查询 30 → 55 |
| 配置 15 / 60 | 合法；15 时与默认相同 |
| 配置 14、61、`true`、`"40"`、`40.0` | 配置错误 |
| 旧单集群配置写在 `[ssh]` | 生效 |
| 两个入口不同取值 | 各自独立，互不影响；共享上限分组不变 |
| 只读命令连接超时 | 仍然只重试一次、等 15 秒（不随配置变化） |
| 写操作（submit、upload）连接超时 | 仍然不重试，后续处理与 main 相同 |
| 监控 | 用配置的连接超时；T127 的认证、主机指纹分类不变；超时类失败仍按普通失败退避 |
| `MonitorTransport` 去除复制后 | 超时文案、返回结构、失败分类与原来一致（补上 T127 建议 1 要的测试） |
| fetch 的 `_IncompleteSSHTransport` | 继承相同的连接超时和顺延 |

推送前本地跑一次全量 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，之后以 CI 为准；运行 `python scripts/scan_public.py`（带本机词表）和 `git diff --cached --check`。

## 真实环境验证（合并前，开发机；不提交作业）

做法沿用 T127：复制本机配置，`studies_root` 指向临时空目录；在副本里给两个 PBS 入口设 `connect_timeout_seconds = 40`。**原配置、常驻监控和 8773 都不动。**

1. 用本分支对两个 PBS 入口各跑一次 `ag doctor`，记录每条调用的耗时、有没有 `connection_timeout`、有没有触发内置重试。
2. 用本分支在前台运行 `ag monitor --watch 30`，持续 10 分钟。和常驻监控（仍为 15 秒）**同一时段**的 `connection_timeout` 次数做对照。
3. 只读核对生成的 ssh 参数里含 `ConnectTimeout=40`（例如从 ssh-log 或调试输出中看到，不贴原文）。
4. **不做**提交、取消、上传、取回的真实验证，这些只做离线测试。
5. PR 里只写次数、耗时和对照结论；出现认证或主机指纹类错误时立即停。

## 停止条件

- 某个调用方绕过 `SSHTransport` 直接拼 ssh 参数，需要改动的范围超出上面列出的路径。
- 去除 `MonitorTransport` 的复制需要改动 T127 的失败分类逻辑。
- 同一问题修两次仍未解决；真实验证出现任何认证或主机指纹错误。

## 合并前审阅与交付

- 需要监督方审阅：**是，逐行审**（传输层、提交路径的超时）。合并只由负责人操作。
- PR 描述包括：S1–S5 各自对应的改动、检查过的全部调用位置、测试表逐项结果、真实验证对照。
- 合并后**不部署、不发版**（S5）。两台电脑的配置改动随 v4.6.0 部署时一起做。

## 版本记录

- v1（2026-10-25，监督方）：依据负责人 10-25 问答 S1–S5 起草；顺带纳入 T127 非阻塞建议 1（消除 `MonitorTransport._execute` 的复制）。
