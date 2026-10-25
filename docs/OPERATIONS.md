# 本机运维：更新、监控与恢复

适用于后端与前端 v4.5.1。两个发布 PR 合并后，由负责人在各自确切合并提交上建 tag 和 release；建好两个 tag 后才进入部署。先部署开发机并观察通过，再部署研究用计算机。本页只提供通用步骤，具体本机值与负责人原话记录在仓库外的私用交接中。

尖括号均为占位符，执行前逐项替换；未替换的示例不能直接执行。`<ENTRY>` 是本机配置里的入口标识，`<UID>` 是 `id -u` 的输出，所有文件位置使用本机核对过的规范路径。命令输出只保存在私有记录中，不贴进公开仓库。这里只操作本机服务，不提交、取消或改动远程计算文件。

## 1. 标准更新步骤

1. 与当前研究主会话约定维护窗口，确认没有 `ag submit`、`ag fetch`、reparse 或 catalog 写入正在进行；有则等操作结束。记录两个检出的当前分支、HEAD、工作区状态、服务 PID 与完整启动方式。工作区有未保存改动或版本不明确时先停下核对。
2. 按第 2 节备份配置、现有 plist、包装脚本和所有前端启动方式/恢复脚本，记录哈希和开始时间。更改检出或依赖前卸载旧前端与监控 LaunchAgent，并确认包装进程及子进程退出；手工启动的旧实例按已备份方式停止，PID 与启动命令必须先对应。保留旧版本和依赖恢复信息，避免失败后旧服务指向新环境。
3. 两个检出分别同步到目标 tag；核对 tag 对应负责人确认的发版合并提交。下例在后端和前端各执行一次：

   ```sh
   git -C '<CHECKOUT>' status --short
   git -C '<CHECKOUT>' fetch origin --tags
   git -C '<CHECKOUT>' switch --detach '<TARGET_TAG>'
   git -C '<CHECKOUT>' rev-parse HEAD
   git -C '<CHECKOUT>' rev-parse '<TARGET_TAG>^{commit}'
   ```

   两个哈希必须相同；不以当时 main 的位置代替 tag。记录每步开始、结束和耗时。
4. 分别按 [后端 README](../README.md#安装) 与 [前端 README](https://github.com/anakine800-tech/Auto-Gaussian-Frontend/blob/main/README.md#run-locally) 更新各自依赖、构建前端。运行 `'<AG_EXECUTABLE>' --version`，v4.5.1 部署应返回 4.5.1；核对两个包元数据及网页包版本。前端运行时 `__version__` 的历史遗留值见 CHANGELOG，不用它确认部署版本。
5. 如需修改配置，先按第 2 节保留原件及变更记录，再按第 6 节设置采样间隔；其他具体配置只依据负责人私用指示。按第 9 节核对两个检出的 hook 和本机词表，全量扫描零命中。
6. 按第 3 节安装两个 LaunchAgent。先核对 plist 与路径，加载新服务并记录加载时刻；按配置入口逐一执行 `'<AG_EXECUTABLE>' doctor --cluster '<ENTRY>'` 并保存结果，同时开始第 4 节首轮快照计时。出现真实连接错误时停止并报告，不循环重试。
7. 按第 4、5 节观察当前电脑 30 分钟。开发机通过后，负责人再安排研究用计算机，后者也独立观察 30 分钟。记录“通过/未通过”，不得把 PR 合并或 tag 创建记为部署完成。

## 2. 私有备份与变更记录

使用带日期的新目录，权限为 0700，不放在任一 Git 检出或 study 证据目录里。先备份后改；每个原文件记 SHA-256，备份后再次核对哈希。示例逐文件执行，目标必须不存在：

```sh
umask 077
mkdir -m 700 '<PRIVATE_BACKUP_PARENT>/<DATED_BACKUP>'
shasum -a 256 '<SOURCE_FILE>'
test ! -e '<BACKUP_FILE>' && cp -p '<SOURCE_FILE>' '<BACKUP_FILE>'
shasum -a 256 '<BACKUP_FILE>'
```

备份至少覆盖 ag 配置、监控及所有前端 plist、本机包装脚本、手工前端的启动方式和恢复脚本，以及更新前后端 HEAD、依赖与构建恢复方法。恢复脚本已有时记录位置和哈希。运行中的服务先卸载并确认退出，才把退役的包装脚本、旧 plist 移入备份目录，使用不同文件名保留先前副本；不直接删除，不覆盖备份。

```sh
test ! -e '<RETIRED_BACKUP_FILE>' && mv '<RETIRED_LOCAL_FILE>' '<RETIRED_BACKUP_FILE>'
shasum -a 256 '<RETIRED_BACKUP_FILE>'
```

本机变更记录逐项写：日期时间、原因、负责人原话及出处、改前/改后内容、备份位置与哈希、执行版本、完整输出位置和耗时。具体值只留在私有目录；上述移动和复制仅针对本机运维文件，绝不用于远程 Attempt 数据。

## 3. 常驻服务及回退

每台电脑保留一个监控 LaunchAgent 和一个操作模式前端 LaunchAgent：

- 监控按 [后端 plist 样例](ops/launchd/local.autogaussian.monitor.plist.example)，直接运行 `ag monitor --watch 30`；旧包装脚本和旧 plist 移入带日期的私有备份目录，不另写包装脚本。
- 前端按 [前端 plist 样例](https://github.com/anakine800-tech/Auto-Gaussian-Frontend/blob/main/docs/ops/launchd/local.autogaussian.frontend.plist.example)，启用操作模式，`--ag` 指向目标 tag 的后端。按样例填写本机 Python、检出、已有 study 根目录与日志位置；只绑定回环地址。其他前端实例先备份启动方式和恢复脚本，再停用。只读模式仍可按需临时使用，不常驻第二个实例。

在临时副本中填写占位符并检查，日志目录事先在本机创建好。日志位置记作 `<MONITOR_STDOUT>`、`<MONITOR_STDERR>`、`<FRONTEND_STDOUT>`、`<FRONTEND_STDERR>`；监控样例虽把 stdout 命名为 jsonl，默认内容是逐行摘要，只有 `--json` 才是完整快照。

以下命令对两个已核对的 plist/Label 分别执行；仅卸载确实已加载的旧服务，首次安装跳过卸载：

```sh
plutil -lint '<NEW_PLIST>'
launchctl print 'gui/<UID>/<LABEL>'
launchctl bootout 'gui/<UID>' '<OLD_PLIST>'
```

确认旧进程及子进程退出，将旧 plist 移入备份后，确认安装位置空缺后放置新 plist 再加载，不覆盖旧文件：

```sh
test ! -e '<INSTALLED_PLIST>' && cp -p '<NEW_PLIST>' '<INSTALLED_PLIST>'
plutil -lint '<INSTALLED_PLIST>'
launchctl bootstrap 'gui/<UID>' '<INSTALLED_PLIST>'
launchctl print 'gui/<UID>/<LABEL>'
```

需要重启时，先 `bootout` 当前 plist，确认退出，再 `bootstrap` 同一文件。不要同时另开一个同缓存目录的 watch。前端重启后刷新已打开页面，以取得新令牌。

**回退顺序：** 触发第 5 节条件后停止本次部署，保存输出并报告；卸载新服务 → 将新 plist 移入另一个不覆盖的私有备份位置 → 恢复旧 plist、包装脚本和此次修改的配置 → 核对哈希及旧执行环境 → 重新加载旧服务。若旧 plist 的执行文件已随本次升级改变，先按备份恢复原 tag、依赖和前端构建，再加载；不能只恢复 plist 就宣称已回退。

```sh
launchctl bootout 'gui/<UID>' '<INSTALLED_PLIST>'
test ! -e '<FAILED_PLIST_BACKUP>' && mv '<INSTALLED_PLIST>' '<FAILED_PLIST_BACKUP>'
test ! -e '<INSTALLED_PLIST>' && cp -p '<OLD_PLIST_BACKUP>' '<INSTALLED_PLIST>'
# 先按上文恢复包装脚本、配置及原执行环境，核对哈希后再加载。
plutil -lint '<INSTALLED_PLIST>'
launchctl bootstrap 'gui/<UID>' '<INSTALLED_PLIST>'
launchctl print 'gui/<UID>/<LABEL>'
```

旧服务若依赖包装脚本，在加载前同样从备份恢复到已核对且空缺的位置；恢复后与记录哈希比对。手工前端按备份的恢复脚本恢复。回退是本机服务恢复，不重试计算、不改远程文件；恢复出现异常时停止并报告。

## 4. 部署观察标准

1. 记录每步开始、结束与耗时，不用固定秒级刷新窗口替代实际计时。以加载新监控为起点，所有已配置入口必须在 **180 秒内**写出首轮快照；记录各自写出时刻及相对耗时，超时停止部署并报告。
2. 核对 `.ag-monitor/watch.json` 中 `heartbeat_at` 的年龄不超过 **90 秒**，PID 与实际监控进程对应。心跳只说明本机进程存活；还要逐入口检查 `latest.json` 的 `sampled_at`、`ok`、`last_ok_at` 与 `sampling`。后续按 `state`、`current_interval_seconds`、`next_sample_at`、连续失败数判断正常等待、退避或暂停，不能把失败时保留的旧值当成新鲜数据。
3. 新快照应有 `sampling`，PBS 的 `cluster.scheduler` 为 `pbs`；硬件未知值保持 null，notes 是局限说明，error 才是错误。核对服务器卡片的标签、核数、内存和灰色说明，stdout 为每个有采样循环一行摘要。
4. 在操作模式任选一个入口点击一次“立即重新采样”，记录点击、开始采样、目标新快照写出三个时刻，以及请求文件是否已被消费。启动等待应对应当前入口剩余耗时，新快照还要加上目标入口的采样耗时；不要把界面“已请求”当成采样成功。拒绝或异常按原因停止核对，不反复点击。
5. 每台电脑观察 **30 分钟**，期间保持接电源、开盖。统计每入口采样轮数、ok 比例、相邻采样间隔中位数和最大值、心跳最大年龄、进入 backoff/paused 的次数；睡眠区间单独标记。
6. 判定“停更”前先查 `pmset -g log` 中的 Sleep/Wake，与空档时间对照。睡眠时停采、醒来自动恢复是正常行为；不要求防睡眠，不改电源设置。醒来后先区分网络恢复期与持续故障；前端可能显示已过去的下次采样时间，以新快照和心跳确认，不仅凭该文字判断。

旧单集群缓存的 latest.json 直接位于 `.ag-monitor/`；多入口位于 `.ag-monitor/<ENTRY>/`。核对时按实际配置选正确来源；缓存包含私有信息，只在本机查看。

## 5. 停止条件

出现以下任一情况，停止部署观察，保留本机输出，按第 3 节回退并向负责人报告，不擅自改配置或重试：

- 任一入口进入 `paused`，原因为认证或主机指纹；
- 监控进程退出或反复重启；
- 排除睡眠后心跳仍超过 90 秒；
- 快照字段异常，或首轮所有入口快照未在 180 秒内写出；
- PBS 入口在非睡眠时段连续失败至少 5 次。

Slurm 入口偶发普通失败并正常退避、醒来后的首轮普通失败，本身**不是**停止条件；仍记录失败并观察恢复。若同时符合上述暂停、进程、心跳或字段异常，仍按停止条件处理。doctor 或连接方式切换中的错误单独按对应步骤停止，不将此观察容忍条件扩展到其他命令。

## 6. 采样间隔建议

慢链路时 PBS 入口建议在该入口的 SSH 表中配置 `connect_timeout_seconds = 40`，命令总超时自动顺延；Slurm 入口沿用默认。

负责人确定的部署口径：PBS 入口建议 `monitor_interval_seconds = 60`，直连和经转发均适用；Slurm 入口不配置此项，沿用默认。该字段为入口级整数，允许 30–600 秒。在现有入口配置表内修改，不另建同名表，其他字段保留。

监控使用 `--watch 30` 时，未显式配置的 PBS 基础间隔为 30 秒，Slurm 为 60 秒。连续普通失败 3 次开始按倍数退避，最长 600 秒，成功一次恢复。配置间隔不是保证实际间隔：监控串行采样，经转发时单条 SSH 可能约 10–20 秒，一轮可能 100–150 秒。记录实测耗时，结合 `sampling` 判断，不靠缩短 watch 制造重复进程。

## 7. 连接方式切换（通用）

慢链路时 PBS 入口建议 `ssh.connect_timeout_seconds = 40`，直连时可保留该值，切换连接方式无需同步修改连接超时。

1. 直连不可用时，先确认没有 `ag submit` 正在运行，保存失败记录并取得负责人对本次切换的指示；按第 2 节备份配置。不要新建未经核对的连接方式。
2. 仅把受影响入口的 `ssh.host` 从 `<HOST>` 改为预先配置好的 `<HOST_FORWARD_ALIAS>`，其他值不变，变更记录写明原值、目标值和依据。具体工具、实际别名、端口和中转方式只在本机私用交接中描述。
3. 转发别名必须沿用原服务器已核对的主机密钥，例如使用 `HostKeyAlias` 关联原有核验记录；保持严格主机密钥校验与非交互认证，不关闭校验、不自动接受新指纹。出现指纹提示或变化立即停止，由负责人核验。
4. 对受影响入口先执行 `'<AG_EXECUTABLE>' doctor --cluster '<ENTRY>'`。通过后确认监控重新写出成功快照，再做其他操作；失败停止并报告。若因认证暂停，修复后按第 10 节处理。
5. 直连恢复后，先确认无提交、备份当前配置，将该字段改回原 `<HOST>`；再次 doctor 并确认快照恢复，记录耗时与结果。

## 8. 两台电脑的差异

公开仓库只记录允许存在的差异类别：**检出位置、连接方式、本机词表行数**。每台电脑的具体值、备份位置、服务启动信息和变更原因，只记在各自本机变更记录与私用交接里。部署顺序固定为开发机观察通过后再到研究用计算机；不同机器上的记录分别核对，不复制研究状态代替维护记录。

## 9. 公开仓库保护

按 [DEVELOPING.md 的公开仓库检查](DEVELOPING.md#公开仓库检查t116) 核对提交 hook 与本机私有词表；前端遵循其 README 的 hook 步骤。日常扫描必须确认词表存在且有效，“词表缺失、跳过”不能算带词表检查完成。每个检出分别执行：

```sh
cd '<CHECKOUT>'
git rev-parse --show-toplevel
git rev-parse HEAD
git config --get core.hooksPath
'<PYTHON>' scripts/scan_public.py --terms-file '<LOCAL_TERMS_FILE>'
git diff --cached --check
```

检出路径、HEAD、词表有效行数和完整输出记在本机，公开回报只给提交号、命中数量和结论。全量扫描不能替代人工检查；具体主机、IP、账号、路径、队列/分区、研究内容、转发工具与实际别名都不入库。备份、词表、配置、快照、原始运行输出也不进入 PR。两份发布 CHANGELOG 的旧版本段落保持原文。

## 10. 手动重试与暂停恢复

确认使用目标版本 ag、与常驻监控相同的本机配置和缓存。普通入口需要立即采样时：

```sh
'<AG_EXECUTABLE>' monitor --retry '<ENTRY>' --json
```

这只登记本地请求，不直接连接服务器。`queued` 表示已排队，`already_queued` / `in_progress` 表示已有请求或采样正在执行；不需要连点。监控会在当前入口采完后处理重试；成功才恢复基础间隔。普通手动采样失败不改自动失败计数与时间，不据此宣称故障消除。

认证或主机指纹暂停时，先修复密钥、连接通道或 known_hosts，并由负责人核对；确认修复后只请求一次：

```sh
'<AG_EXECUTABLE>' monitor --retry '<ENTRY>' --auth-fixed --json
```

`--auth-fixed` 表示已确认修复，不绕过认证或主机密钥校验。暂停也可因该入口配置变更或监控重启而解除，但先解决原因，不能用反复重启代替修复。部署观察中遇暂停先按第 5 节停止，本节供原因处理完成后获准恢复时使用。

返回 `refused` 时区分 `monitor_not_running`、`auth_confirmation_required`、`unknown_entry`，先核对服务状态、修复确认或入口标识，不自动重试。监控未运行的拒绝路径不会创建文件。请求由监控消费；启动 watch 会丢弃遗留请求并写入首条摘要，同一缓存目录只允许一个 watch。恢复后核对新的成功快照与心跳，记录结果。
