# T1：`ag` 核心（作业生命周期与传输）

分支：`codex/redesign-t1-core`（阶段 A）、`codex/redesign-t1b-crest`（阶段 B）　位置：**本地**（需要 macOS 和 SSH）　依赖：T0 已合并　预计：阶段 A 2～3 天，阶段 B 0.5～1 天

## 目标

实现硬内核：study 与 Attempt、状态机、prepare / submit / status / fetch / cancel / list / doctor / init、远程操作白名单、确认对话框、核数上限、三个作业模板。规格以方案第 4 节为准（4.1～4.8、4.10），本任务单只补充实现要求和验证步骤。

## 允许改动的路径

- `ag/src/ag/` 下：`cli.py`、`config.py`、`study.py`、`attempt.py`、`state.py`、`transport.py`、`remote.py`、`submit.py`、`status.py`、`fetch.py`、`cancel.py`、`doctor.py`、`render.py`、`confirm.py`、`gaussian_input.py`、`locks.py`、`journal.py`
- `ag/templates/`（`_guard.sh`、`gaussian.pbs/.toml`、`xtb.pbs/.toml`、`crest.pbs/.toml`）
- `ag/config.example.toml`
- `ag/tests/` 下对应的 `test_*.py`（不动 T2、T5 的测试和 `fixtures/`、`data/`）

## 不允许

- import 旧代码；改旧文件。旧的 `templates/g16_job.pbs.template` 只读参考，安全头逻辑改写进 `_guard.sh` 并注明来源。
- 任何绕过确认的途径：`--yes`、`--force`、环境变量、配置项、非 macOS 下的降级确认。
- 远程命令拼接自由文本；白名单之外的远程命令；任何 `rm`、`rmdir`、`mv`、截断。
- 自动重试 qsub、自动重新提交、自动 qdel。
- 把本地配置、ssh 配置、研究数据、主机名、用户名、绝对路径提交到仓库。

## 实现要求（补充方案第 4 节）

1. **配置**：`~/.config/ag/config.toml`，样例 `ag/config.example.toml` 全部用占位符。键：`ssh.config_file`、`ssh.host`、`remote.allowed_root`、`remote.ag_root`、`scheduler.queue`、`resources.max_cores`、`resources.tiers.<名>.{cores,mem_gb}`、`programs.gaussian.g16root`、`programs.xtb.root`（crest 同根）、`local.studies_root`。缺键或路径不合法时所有命令拒绝运行。
2. **传输**：`Transport` 接口，真实实现用 `subprocess` 调用 `ssh -F <config_file> <host> -- <命令>` 和 `scp -F`，每条命令有超时（一般 60 秒，qsub 120 秒）。远程命令只能由 `remote.py` 中的固定函数生成（每个白名单操作一个函数），参数全部 `shlex.quote`，路径先校验在 `ag_root` 之下且不含 `..`。测试用假 `Transport` 记录收到的命令，断言只出现白名单形式。
3. **远程用户**：`doctor` 和 `submit` 用 `id -un` 取远程用户名（只读白名单命令），用于在 `qstat -f` 中按 `Job_Owner` 统计核数。
4. **submit 流程**（每个 Attempt 依次）：取全局提交锁（`fcntl.flock`，锁文件在 `~/.config/ag/`）→ 状态必须是 `prepared` → 重新计算本地 bundle 哈希并与 manifest 一致 → 统计核数 → **弹出确认对话框**（批量时一次对话框列出全部）→ `O_EXCL` 创建 `.submit-claim` → 状态 `submitting` → 远程 `mkdir`（study 目录不存在才建；Attempt 目录必须不存在）→ 上传 → 远程 `sha256sum` 校验 → `qsub` → 解析作业号 → `submitted`。任何一步在 qsub 之前确定失败 → `failed_presubmit`；qsub 调用超时、连接中断、输出无法解析 → `unknown`（退出码 3），不再做任何远程写操作。
5. **确认对话框**（`confirm.py`）：用 `osascript`，对话框文本通过 `on run argv` 作为参数传入（不要拼接进 AppleScript 源码，防止注入），按钮“取消”/“提交”（cancel 用“取消”/“取消作业”），默认“取消”，300 秒超时视为取消。非 macOS 直接返回拒绝。确认函数只在这里实现一处，测试通过 monkeypatch 替换。
6. **status**：`submitted` 的 Attempt 用 `qstat -f <作业号>`；状态 `C` 或作业已不在队列且远程目录中存在 `job.pbs.out` → `finished`（记录 `exit_status`）；作业不在队列且没有输出文件 → 保持 `submitted` 并给出提示，不自行判断。`unknown` 的 Attempt 只读核对：在 `qstat -f` 中按 `Job_Name` 查找，或查看远程目录内容；找到作业 → `submitted`；找不到 → 保持 `unknown` 并报告给人。
7. **fetch**：只取模板声明的输出；每个文件先下载到 `outputs/.partial/`，校验大小和 SHA-256 与远程一致后，用 `os.link` 放到最终位置（目标已存在则失败，不覆盖）；全部成功后状态 `fetched`。
8. **cancel**：只接受 `submitted` 状态且有作业号的 Attempt；对话框确认后 `qdel <作业号>` 一次；成功后状态 `cancelled`，失败如实记录，不重试。
9. **prepare**：渲染模板（`_guard.sh` + 模板），校验模板参数白名单；Gaussian 输入校验见方案 4.7；生成 `manifest.json`、`status.json`（`prepared`），打印确认摘要的数据（JSON）和一段人读 markdown；追加 journal。
10. **doctor**（只读）：ssh 连通与延迟、`id -un`、`qstat -Q`、`allowed_root` 存在且非符号链接且可写（用 `test`，不创建任何东西）、g16 / xtb / crest 可执行文件存在、当前用户已占用核数。
11. **CLI**：`cli.py` 注册本任务的全部子命令，并保留 T0 的挂载点让 T2、T5 的 `register` 生效。所有命令支持 `--json`；退出码按方案 4.4。

## 本地准备（不进仓库）

1. 在 `chem` conda 环境中 `pip install -e "ag[test,chem]"`。
2. 按 2026-10-13 环境盘点报告填写 `~/.config/ag/config.toml`：使用 Mac 直连的专用 ssh 配置文件和主机别名；`allowed_root` 为集群上的 SDL 根目录；`ag_root` 为其下的 `ag`；g16 与 xtb/crest 的安装根；`max_cores = 44`；三个档位按方案 D19。
3. `local.studies_root` 由人指定（例如 `~/Research/ag-studies`），不在仓库内。

## 真实环境验证（阶段 A，每一步需要人在场）

1. `ag doctor` 全部通过，把结果概要（不含主机信息）写进 PR。
2. `ag init` 一个名为 `ag-smoke` 的 study。
3. 用 RDKit 生成正丁烷坐标，写一个 B3LYP/6-31G(d) 单点输入（`%nprocshared=8`、`%mem=10GB`），`ag prepare --template gaussian --tier simple --walltime 00:30:00`。
4. 人确认摘要后运行 `ag submit`，人点击“提交”。
5. 反复 `ag status` 直到 `finished`；`ag fetch`；确认日志里有 `Normal termination`。
6. 安全性现场检查（都不应产生远程写操作）：对同一 Attempt 再次 `ag submit` → 本地拒绝；在对话框点“取消” → 无任何远程操作、状态仍为 `prepared`；`%nprocshared` 与档位不一致的输入 → `prepare` 拒绝。
7. 可选、需要人明确同意：提交一个 walltime 较长的同类作业，运行后 `ag cancel`，确认 qdel 只执行一次、状态为 `cancelled`。

## 阶段 B（单独 PR）

在阶段 A 合并后，用正丁烷分别跑一次 `xtb`（`--gfn 2 --opt`）和 `crest`（`--gfn2 --quick`，simple 档），确认模板、环境变量和完成标记正确，`ag fetch` 取回声明的输出。

## 验收标准

- `pytest ag/tests` 通过；测试覆盖方案 4.10 列出的各项，尤其：确认函数不可绕过（检查不存在相关参数和环境变量）、生成的远程命令只来自白名单、`unknown` 后不再有远程写操作、`failed_presubmit`/`unknown` 不能再次提交、fetch 不覆盖。
- 阶段 A 的真实环境验证 1～6 全部完成并记录在 PR 中。

## 停止条件

- 真实环境中出现任何意外：`unknown`、哈希不一致、ssh 报错、作业异常结束、远程目录意外已存在。立即停下，在 PR 中报告，不做任何补救性的远程操作。
- 需要白名单之外的远程命令。
- 对话框无法弹出或无法取得点击结果。

## PR 要求

PR 描述第一行 `Task: T1`（阶段 B 为 `Task: T1b`）；附 `ag doctor` 概要和真实环境验证记录（不含主机名、用户名、路径、作业号以外的标识）。
