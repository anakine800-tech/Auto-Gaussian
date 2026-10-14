# T16 — 多集群支持与 Slurm（目标平台 SCNet）

范围依据：负责人给出的 T16 任务及核时预算、到期、存储、程序版本追加要求。
改动范围：`ag/`、本任务单、`AGENTS.md` 硬内核第 6、9 条。真实环境验证在合并后单独授权；合并前等待监督方审阅，AGENTS 修改须负责人同意。

## 防止的具体事故

- 切换默认配置或不同集群出现同号作业后，查错、下载错或取消另一个集群的作业。
- sbatch 响应丢失、队列清除或自动 requeue 后，同一 Attempt 被重复运行/收费，或无证据地被标为成功。
- 漏算网页、数组、非 ag 作业，导致超出核数额度；丢失回复或本地台账后重复支出预算。
- 将不同 Gaussian 修订版的能量混入同一 profile，掩盖数值来源差异。

## 配置与绑定

旧单集群配置自动视为 `default` PBS；旧配置添加 `[clusters.batch]` 时仍保留旧配置为 default。
也可采用 `ag/config.clusters.example.toml` 的纯多集群结构。不要同时提供旧集群和 `clusters.default`，避免目标歧义。
命名 PBS 集群使用 `scheduler = "pbs"` 和 `queue`；Slurm 使用 `scheduler = "slurm"`，可选 `partition/account/qos/expires`。
每个集群独立配置 SSH、远程根、程序与四个资源档位。Slurm 的 `max_committed_cores <= max_cores`，提交采用 `max_cores` 严格模式。

`ag prepare --cluster batch ...` 把集群与调度器写入不可变 manifest；缺省为 default。
后续 submit/status/fetch/cancel 根据该绑定选连接，monitor 分集群采样并只关联对应集群的本地 Attempt。
混合集群的 submit 批次在任何远程操作和确认前拒绝；每个集群独立确认，以免额度与目标混淆。

负责人已同意解决“prepare 后 manifest 不变、作业号提交后才有”的冲突：
一次性 `submission.json` 是提交 manifest，记录 `<集群>:<作业号>`、集群及 manifest.json 哈希。
取消和后续状态核对与 status.json 交叉验证；取消确认后再次验证。
历史无 cluster 字段的 PBS Attempt 固定为 default，保留原先的确切 PBS ID、状态逻辑与脚本字节。

## Slurm 行为

所有远程构造仅在 remote.py。`sbatch --parsable job.slurm` 的数字 ID 和可选集群后缀分别解析；本地集群别名与后缀不混用。
脚本使用 Attempt id 作业名、单节点/单任务、档位 cpus/mem/time、固定目录内 stdout/stderr 和 `--no-requeue`。
不支持 `--exclusive` 或任意额外调度器参数。Gaussian 环境只接受 g16root、module_init 路径、modules 名称列表；scratch 私有。
复用 guard 的 ag_run 回执，Slurm 回执使用 `job_id`；PBS 回执和渲染结果保持原样。

squeue 全用户统计包括非 ag 作业；`-r` 展开数组，计入每个元素与异构组件；未知状态/核数/歧义拒绝推断额度。
活动作业消失后读取 sacct；无记录为 unknown。六类要求的终态均记录 scheduler_state、exit_code、exit_signal、elapsed、allocated_cpus。
本地 finished 表示调度器终态，可取回可用声明文件；FAILED 等绝不表示科学成功。科学判据仍须 facts 和人审阅。
UNKNOWN 按 Attempt 名和 owner 查 squeue/sacct，显式从创建日期查询历史，唯一匹配才绑定；永不重提。

## 核时与维护信息

Slurm `resources.budget_core_hours` 可选。每个集群在本地配置目录维护 `budget-<cluster>.json`：
提交前检查已用+预留+本次，原子持久化核数×walltime 的预留后才允许远程写。
确定的提交前失败释放预留；sbatch 超时/255/无法解析继续保留；取消请求本身也不释放。
`ag status` 取得 sacct 终态后按 manifest 核数×Elapsed 结算；支持 `D-HH:MM:SS`，重复观察不重复扣算。
monitor 只读提醒需要 status 核对，不能仅凭队列消失释放预算。
跨 submit 调用仍未出现在 squeue 的本地预留也计入核数，避免调度器读回延迟绕过严格额度。
有提交声明却缺台账记录时拒绝把消费归零，须人工核对。台账不含平台实际余额、网页外部消费或存储费；本地预算应给外部消费留余量。

确认摘要包含目标集群、估算核时、本次最多、累计已用/预留/预算；预算采用整数核秒计算。
doctor/monitor 在 expires 前 14 天起提示先 fetch；过期继续提醒，不删除远程文件。
Slurm doctor 检查 SSH、调度器工具、历史作业、分区、根目录 test -w、程序路径，并通过 `du -s -k` 显示 ag_root KiB 占用。
没有历史记录时报告未验证且 doctor 非零退出，不能声称 accounting 已验证。
SSH 255/连接超时提示“密钥可能已过期，请到网页重新下载”；该提示不等于确定失败原因。

## facts 与 profile

Gaussian 版本从日志的产品号/Revision 或 G16Rev 标头读取为 `program_version`，缺失或冲突记为 null 并附说明，不保留主机信息。
profile 对所有构象、单点修正和物种检查同一程序版本；旧 facts 缺版本时要求重新运行 ag facts。
T14 合入 main 后在其实现上增加检查，不复制 T14 功能。

## 验证

离线假 Transport：提交返回值、响应丢失单次声明、各终态/信号/无记录、全用户额度、批次读回延迟、同号跨集群隔离、取消绑定、模板和回执、预算保留/结算/丢失、到期、存储与程序版本。
运行全部 ag 单元测试和现有 Skills 测试；提交前敏感信息扫描。
真实环境（SSH、Slurm、计费、模块环境、实际程序运行）均未验证；合并后另行授权。不得把离线测试当作 SCNet 可用或科学验收证据。

Slurm 字段语义参考官方 [squeue](https://slurm.schedmd.com/squeue.html)、[sacct](https://slurm.schedmd.com/sacct.html)、[sbatch](https://slurm.schedmd.com/sbatch.html)。
