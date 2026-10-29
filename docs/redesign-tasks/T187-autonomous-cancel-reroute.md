# T187：有证据的自主取消及改投资格

## 分支与目标

`codex/t187-autonomous-cancel-reroute`，一单一 PR，V4.8 W1 取消路径及 2.6 改投。依赖已合并 T184、T185/T186 最终归属与路由接口。先读当前实现并独立完成证据核验和合成测试；不复制未合并上游代码。事故依据：把手动作业误取消、把短暂慢进展误判失败、qdel/scancel 回执不确定后重试、旧持锁会话继续取消、取消未完成就重复提交。

## 允许路径

- `ag/src/ag/cancel.py`、`cli.py`、`submission.py`：独立自主取消入口与精确作业绑定。
- `ag/src/ag/autonomy.py`、`_autonomy_store.py`、`autonomy_submission.py`：仅复用/扩展已定稿的归属、计数与原子暂停接口。
- 可新增 `ag/src/ag/autonomy_cancel.py`：条件和证据核验，不创建通用编排系统。
- `ag/src/ag/snapshot.py`、`status.py`、`route.py`：仅现有固定只读证据的绑定/读取与公共核验复用；不得新增任意远程命令。
- 2026-10-29 负责人补充允许 `ag/src/ag/remote.py`、`slurm.py`、`transport.py`：仅固定、精确作业绑定的只读 Slurm 身份/版本/历史查询及白名单解析；`status.py` 可接入这些已获准查询。详见下方范围决定，不扩展 PBS 或取消命令。
- `ag/tests/test_core.py`、`test_slurm.py`、`test_autonomy.py`、`test_snapshot.py`；可新增 `test_autonomy_cancel.py`，现有取消/状态专用回归若在其它文件可先报告准确路径。
- `ag/README.md`、`docs/DEVELOPING.md`、`docs/redesign-tasks/T187-autonomous-cancel-reroute.md`。

## 要做的

1. 人工 cancel 原确认行为不变。自主取消用独立入口或显式模式，不能借 submit 批准记录/参数取消，也不能核验失败后退回人工弹框冒充自主成功。
2. 仅同 study、当前授权轮次中经有效自主规则实际提交的 Attempt；从一次性归属、manifest、submission、status 交叉验证精确 job ID 与 cluster。人手提交、其它轮次或 study、UNKNOWN、损坏/矛盾绑定均不能自主取消。
3. 当前持锁会话、有效计划与规则、取消条件每次核验；每次唤醒最多取消两个，包括已发出但结果不确定的消费。重复调用、并发、崩溃和改规则名不能重置。失锁/暂停后不得使用早先的核验结果执行。
4. 计算异常须两个连续、不同唤醒的正式 snapshot 都支持无进展。模型给出科学判断和理由，代码核验确切 Attempt/作业/集群、文件哈希、快照来源/顺序和唤醒绑定；不把模型手写的“无进展=true”当作完整证据，也不写确定性科学阈值代替审阅。不能用同一快照两次、过期/缺失/变更快照或其它作业证据放行。
5. 改投须排队至少6小时、可证从未开始运行、无 chk 依赖、当前同一 T185 算法给出更高位可容纳候选。仅“本机没观察到 running”不证明从未运行；调度器/记账证据不足则拒绝。容量候选也不宣称调度器保证立即启动。每个原作业谱系最多改投一次，新编号不能洗掉次数。
6. 改投取消与再次提交是两个阶段。qdel/scancel 接受不等于作业已消失；只有正式只读证据核实原作业已终止/不再运行才可输出后续新 Attempt 资格。结果不确定立即暂停、不重试取消、不 prepare/submit 替代作业；复用既有不可复用 cancel-claim。后续新 Attempt 仍走 prepare 与 T186 全部核验，不在 cancel 内直接上传/提交。原科学输入必须有哈希联系，资源变化由新的 prepare 明确展示；父文件不改。
7. 对宽松输入中不能证明无 chk 依赖的情形，不自动授予改投资格。不能凭人工填的无依赖标签跳过检查。
8. 取消前先记录完整理由、证据与目标；发出后记录实际结果，并更新待负责人处理项。短本地互斥不包长网络 IO；边界与在途不确定状态有回归，不可伪称网络中途取消命令能撤回。

## 验证与交付

离线覆盖每个拒绝条件、精确绑定、两个唤醒与相同快照去重、每次上限、并发/接管/暂停、取消后失联、取消成功但仍在队列、运行后重新排队、共享入口身份、谱系改投上限及旧手动取消不变。全量 ag/Skills、当前 head CI、私有敏感词扫描、精确暂存。

敏感路径必须合并前真实验证。当前未授权集群操作；先准备非研究作业的确切输入、哈希、规则、命令及次数，与 T185/T186/T188 集中审阅后请负责人批准。至少实际自主取消一个本轮专用作业，核对确切归属与终止证据；其它人的/手动/错误轮次只做本地拒绝。改投验证若需要6小时等待和第二唤醒，应如实列出，不篡改时间或证据冒充完成；缺证据就保留待验证。

PR 首行 `Task: T187`。列实际接口、不可用条件、合成回归与真实缺口；开发对话不合并、部署、配置真实规则或启动定时任务。范围外、同问题两次未解决、真实意外均报告协调方。

## 开发核查与本次交付边界

以下为本次开发核查追加记录，不缩减以上验收要求。T185/T186 最终接口尚未收到，本次先交付可独立验证的证据部分：

- `snapshot.capture_for_run(...)` 复用既有正式快照捕获，并将 round/run、确切 Attempt/作业/集群、manifest/submission 与快照文件哈希登记到自主日志。普通 `ag snapshot` 保持原行为；捕获本身不授权取消。
- `autonomy_cancel.review_no_progress(...)` 为纯本地核验接口：检查连续两个不同唤醒的正式快照来源、顺序、字节及模型对每份快照给出的审阅理由。代码不设科学停滞阈值，也不把模型布尔标签当成来源证据；审阅结果不授予执行资格。
- `autonomy_cancel.checkpoint_free_input(...)` 从冻结 bundle 核验有限严格输入没有 chk 读取路径，返回输入哈希联系；Guess、IRC、读取/重启项、未知语法和放宽输入均拒绝证明。拒绝不等于认定存在依赖，也不改变 prepare 支持范围；结果始终不授予改投资格。
- `status.capture_slurm_evidence(...)` 通过获准固定只读命令保存正式调度器观察。必须使用 submission 原有实际集群名，版本限定仅是格式候选；保存原始响应、哈希和查询时间并严格解析，首次错误停止，不补建原始实例或授予资格。
- 本次没有实际自主取消、改投、替代 Attempt prepare/submit 入口，不复制未合并的 T185/T186 代码。原手动取消的 Mac 确认与不可重试声明保持原行为。

当前实际阻塞属于**提交**与**环境验证**：

| 缺口 | 核查结果与接入要求 |
| --- | --- |
| T186 实际自主提交归属 | 现有 submission/status/manifest 可核对确切作业，但不能证明由当前授权轮次的有效自主规则实际提交。必须接入定稿的一次性归属、有效规则及同轮身份，不能用手动 policy 或本地意图计数代替。 |
| 消费、暂停与在途取消 | T184 记录本地意图；取消前的原子消费、每唤醒最多两个、谱系改投最多一次、失败或崩溃不返还、失锁及结果不确定时原子暂停均待执行入口接入。短本地互斥不得包住网络 IO，已发出的取消不能宣称可撤回。 |
| 从未运行与排队六小时 | 新固定 Slurm 查询保存控制器与重复记账原始响应，原始实例绑定和最终资格判断仍待 T186 接入及真实验证。未见 running、当前排队、elapsed 为零或缺开始回执均不足；PBS 证据不足拒绝。 |
| 无 chk 依赖 | `checkpoint_free_input` 已独立实现严格冻结字节核验；缺 `parent_chk` 或人工标签均不构成证明。它支持有限 Gaussian/CP 语法及受支持的 XYZ/约束，未知、放宽输入仍拒绝；不是改投资格或科学验收。 |
| T185 当前路由与容量 | 必须调用与自主提交相同的定稿算法，核验本轮顺序、更高位候选、共享入口身份与当前容量，不另写取消专用排序。容量足够不保证调度器立即启动。 |
| 取消之后的终止证据 | qdel/scancel 接受及本地 `cancelled` 都不是终止证明。须核验取消之后、同一确切作业的正式只读证据；缺失或矛盾、仍在队列、查询失联均不能放行替代 Attempt。 |

离线回归仅证明本次证据接口与拒绝行为；完整取消/改投计数、在途故障及上游集成验收仍待实现。具体测试结果以本 PR 当前 head 的执行记录为准，不以设计矩阵代替测试通过。

### T186 组合适配（已核对开发接口，待最终 head）

- `autonomy_submission.verified_authorization(path, authorization)` 只恢复已在调度前绑定的原始归属；
  再与当前轮次、有效规则和 `state.submissions` 实际消费交叉核对。它不授权取消，也不建立缺失的调度器初始实例。
- `submission_guard` 的 consume/dispatch/abort 与 `boundary_failure` 服务于提交；取消须独立保存每次唤醒最多两次的原子消费、
  确切目标和不可重试 claim，不能复用提交次数或把 boundary_failure 当取消许可。未知结果立即保存后果并暂停。
- 组合保持配置提交锁 → 全机登记锁 → study 状态锁的顺序，短事务中重读归属、条件与当前租约，释放全机/study 锁后才做网络 IO。
  已发出的操作不能撤回；后续响应仅补结果，不能恢复动作资格。
- 手动 `cancel` 待接入 `manual_write_guard(..., action='cancel', attempt_ids=[...])`，仍保留逐次 Mac 人工确认。
  running 或有效 lease 时拒绝，paused 且无有效 lease 才可接管；不能仅依赖前端保护。fetch 写入归属由 T186 组合处理，
  本工单不新增 `fetch.py` 范围。上述接口仍在上游开发中，本分支未复制实现或提前声称接通。
- 负责人补充要求 IO/解析后在最终本地发布前锁内重验 owner 权限。T186 负责 status/fetch/snapshot/facts 的最小发布钩子；
  T187 的 `capture_for_run` 与新 Slurm 采集须接该钩子。当前 capture_for_run 的“失效后留普通快照但不登记”
  仍是待修复组合缺口：最终行为必须拒绝过期或被接管 owner 的本地发布，不能只阻止自主日志采纳。
  网络/解析保持锁外，最终发布才持短锁；此组合未完成前不启用自主计算。

## 合并前真实验证矩阵（未授权、未执行）

仅使用专用非研究 study。待 T185/T186/T188 接口定稿后，生成待负责人审阅的确切输入、输入及 bundle SHA-256、计划/规则哈希、完整正式 ag 命令和逐条执行次数；当前未生成这些最终值，不用占位哈希冒充已准备或获准。

| 场景 | 待准备对象与操作 | 必需证据及验收 | 当前状态 |
| --- | --- | --- | --- |
| 本轮专用作业自主取消 | 由本轮有效规则实际提交专用小分子作业；两次不同且连续唤醒通过正式接口捕获并审阅；核对后对确切作业发出一次取消 | 一次性自主归属与完整摘要、两份日志及哈希、每份审阅理由、取消前消费及目标记录、取消实际结果、取消后正式终止证据。至少一个真实本轮专用作业完成此链路。若快照不支持无进展，不为满足测试而伪造结论或取消。 | 未授权、未执行；确切命令与次数待接口定稿及场景审阅 |
| 错误归属拒绝 | 用本地合成绑定覆盖手动提交、其他 study/轮次、UNKNOWN、损坏身份和共享入口混淆 | 在发出任何远程写操作前拒绝；不对其他人的或错误归属作业试取消 | 仅离线验证；无真实取消计划 |
| 接受后尚未终止 | 对获准专用作业保留取消接受后的正式状态观察 | 接受回执不能产生替代 Attempt 资格；只有取消后的确切终止证据才允许进入下一阶段 | 未授权、未执行；现场能否观察此窗口未知，不能预称覆盖 |
| 结果不确定与失锁 | 先以假 Transport、并发及崩溃注入覆盖取消发出后的失联、暂停和接管；若确需现场异常场景，另列具体方法请求批准 | 原 claim 与消费保留、立即暂停、不重复取消、不 prepare/submit 替代作业；不宣称网络中途能够撤回已发命令 | 真实故障注入未授权、未执行 |
| 有证据的改投 | 保留真实排队至少六小时及两次连续唤醒；取得可证明从未运行的调度器证据、无 chk 依赖证明和 T185 更高位容量证据 | 先取消并核实原作业终止，再单独审阅新 Attempt 的原科学输入哈希联系、资源变更与 T186 全部核验；每个原谱系最多一次 | 证据接口缺失；未授权、未执行，不缩短或篡改等待时间 |
| 原手动取消兼容 | 离线确认原入口始终要求 Mac 人工点击，不消费自主资格；若合并前需要现场兼容对象，另纳入确切命令清单 | 手动授权、确切 job/cluster、不可重试 claim 均保持原语义 | 现场未授权、未执行 |

真实 SSH 报错、UNKNOWN、哈希或归属矛盾、异常结束立即停止并报告；不得以重试写操作补证据。公开 PR 仅记录脱敏结论与覆盖范围，原始输入、规则和现场证据保留在仓库外。

## 调度器证据研究与范围决定

2026-10-29 协调会话转达负责人明确决定：“允许补证据接口，缺证据拒绝。”
据此新增允许路径仅为 `ag/src/ag/remote.py`、`ag/src/ag/slurm.py`、`ag/src/ag/transport.py`，
用途仅限本节固定、精确作业绑定的只读 Slurm 身份/版本/历史查询和严格解析；回归复用原已允许测试路径。
仅完整证据且已核实支持版本才可能获得自动改投资格；PBS、未知版本或证据不足一律不授予资格。
必须与 T186 一次性归属保存的不可变原始实例绑定交叉核验，不事后补认旧作业。
本决定不授权连接真实集群、现场查询、修改真实配置或取消命令，也不允许新增其他路径。
PBS 正向支持及新配置方言不在本轮范围；下方 PBS 研究仅记录证据限制。

本节只读核查现有源码、官方调度器文档与官方源码，没有连接集群，也没有实施下列新查询。
事故依据是把重新排队的旧运行认作从未运行、把取消接受或强制 purge 认作执行节点已停止，导致重复计算。
实现须保留三态判断：证明成立、明确不成立、证据不足；不把缺字段补成零。

### Slurm 最小查询与绑定

建议增加一个固定控制器探针和两种固定作业只读操作；作业参数只能来自已绑定的实际 Slurm 集群和确切数字作业号。
本机入口别名不能直接用作实际 Slurm 集群名；原始响应含私有字段，只存私有 study。

```text
env -u SLURM_CLUSTERS -u SCONTROL_SIB -u SCONTROL_SIBLING LC_ALL=C TZ=UTC SLURM_TIME_FORMAT=standard scontrol --local show config
env -u SLURM_CLUSTERS -u SCONTROL_SIB -u SCONTROL_SIBLING LC_ALL=C TZ=UTC SLURM_TIME_FORMAT=standard scontrol --local --clusters=<CLUSTER> --oneliner --details show job <JOB_ID>
env -u SLURM_CLUSTERS LC_ALL=C TZ=UTC SLURM_TIME_FORMAT=standard sacct --local --clusters=<CLUSTER> -X --duplicates -n -P --jobs=<JOB_ID> --format=Cluster%256,JobIDRaw%64,JobName%200,UID%20,DBIndex%32,Submit%32,Start%32,End%32,State%64,Restarts%20,SLUID%64,OriginalSLUID%64
```

以上是已获准实现的固定命令形状，不是允许模型拼接命令的接口。需同时核对客户端与控制器兼容性，
版本不明、字段不可见或历史不完整时拒绝正向资格；不自动退回当前七列 sacct 解析。
控制器探针须严格提取唯一非空 `ClusterName`、`SLURM_VERSION`，失败、缺字段或格式异常即拒绝。
`show config` 经 RPC 返回实际控制器的集群名与服务端版本；`scontrol --version` 只读客户端版本，
不能代替它。客户端兼容性另用固定 `scontrol --version`、`sacct --version` 分别记录。
首次探针清除 `SLURM_CLUSTERS`，因为 `--local` 不阻止该环境变量选择其他集群；
后续查询及提交显式绑定已确认实际集群，并与 `sbatch --parsable` 返回值核对。
固定 scontrol 查询还清除 `SCONTROL_SIB`、`SCONTROL_SIBLING`，防止继承环境加入 sibling 视图；
实际集群选择拒绝 `all`（不区分大小写）。新的四类证据操作首次 SSH 错误即保存并停止，普通只读重试行为不变。
当前探针不能反向补认旧 `scheduler_cluster=None` 的历史归属，也不能证明 DBD/执行节点版本或历史完整。
源码依据：[客户端参数与 RPC 入口](https://github.com/SchedMD/slurm/blob/slurm-25-11-0-1/src/scontrol/scontrol.c)、
[控制器构造版本及集群字段](https://github.com/SchedMD/slurm/blob/slurm-25-11-0-1/src/slurmctld/proc_req.c)、
[配置响应和输出](https://github.com/SchedMD/slurm/blob/slurm-25-11-0-1/src/api/config_info.c)。

| 字段/来源 | 必须保留的语义 |
| --- | --- |
| 提交时的一次性实例绑定 | 实际 cluster、UID、JobID、JobName、原始 Submit 与支持版本下的初始 SLUID/DBIndex。不能六小时后把当前记录补认成初始实例；与 T186 最终归属记录一起确定保存位置。 |
| 控制器 Restarts | 必须显式且为零，并与全部相关重复历史一致；Requeue 只是可否重排的配置。当前 PENDING、零耗时或 StartTime 缺失都不足。 |
| StartTime / Submit | Pending 的 StartTime 可为预计启动时间；requeue 可清零 start 并重置 Submit。取消 pending 作业也可把 start=end 设为取消时间，不能据此反推运行。 |
| sacct --duplicates | 默认只返回同号最新记录；重复可来自 requeue、resize、federation 和 JobID 回绕。必须区分实例，不复用当前拒绝所有重复 JobID 的 parser。26.05.5 的 DBIndex 与 SLUID 是同一值的十进制/Crockford 编码，须核对一致；OriginalSLUID 全零保留为缺失，不补当前实例。 |
| 历史与时间 | 记账成功但无记录不能证明从未运行；消息可能延迟或丢失。六小时须有原始绑定时间及当前实例一致性，跨源冲突、未来时间、截断字段均拒绝。 |
| 取消后的终止 | 先取得匹配实例的取消后 CANCELLED 记录及结束时间，再读控制器，拒绝 RUNNING、COMPLETING、SIGNALING、重排队等活动状态。控制器无记录仍须匹配终态；任意查询失败不等于作业不存在。 |

依据：[sacct 的重复记录与字段说明](https://slurm.schedmd.com/sacct.html)、
[scontrol 的单集群/本地查询](https://slurm.schedmd.com/scontrol.html)、
[记账消息缓存与丢失边界](https://slurm.schedmd.com/accounting.html)、
[作业状态语义](https://slurm.schedmd.com/job_state_codes.html)。
DBIndex/SLUID/OriginalSLUID 的精确输出来自
[26.05.5 sacct 字段输出](https://github.com/SchedMD/slurm/blob/slurm-26-05-5-1/src/sacct/print.c)
与[SLUID 编码实现](https://github.com/SchedMD/slurm/blob/slurm-26-05-5-1/src/common/sluid.c)；
新建和 resize 时的区别见[作业实例更新](https://github.com/SchedMD/slurm/blob/slurm-26-05-5-1/src/common/job_record.c)。
初版应拒绝联邦、数组和 heterogeneous 作业；本地 REVOKED 或缺记录不排除其他 sibling 执行，
见[联邦机制](https://slurm.schedmd.com/federation.html)。

已核查的版本差异不等于目标服务器已通过：

- [24.05 sacct 源码](https://github.com/SchedMD/slurm/blob/slurm-24-05-0-1/src/sacct/sacct.c)没有 Restarts/SLUID 字段；
  [24.11](https://github.com/SchedMD/slurm/blob/slurm-24-11-0-1/src/sacct/sacct.c)已有。
- [25.05 scontrol](https://github.com/SchedMD/slurm/blob/slurm-25-05-0-1/src/scontrol/info_job.c)没有输出 SLUID，
  [25.11](https://github.com/SchedMD/slurm/blob/slurm-25-11-0-1/src/scontrol/info_job.c)的 details 路径已有。
- [26.05.4](https://github.com/SchedMD/slurm/releases/tag/slurm-26-05-4-1)与
  [26.05.5](https://github.com/SchedMD/slurm/releases/tag/slurm-26-05-5-1)修复过 requeue 历史字段/记录覆盖问题；
  其他分支的回移须按实际补丁版本核实，字段存在不等于历史可靠。
- 正常控制器状态恢复保存 restart count；丢弃状态、忽略恢复错误或已知历史损坏仍使证明失效。
  见[作业状态序列化](https://github.com/SchedMD/slurm/blob/slurm-25-05-0-1/src/common/job_record.c)与
  [slurmctld 恢复选项](https://slurm.schedmd.com/slurmctld.html)。

首版建议仅把控制器、scontrol、sacct 均为 **26.05.5** 的明确组合作为候选，
由合并前真实验证决定是否支持；不推断 `>=26.05.5` 或未知定制版本等价。
验证还须确认实际 slurmdbd 组合（优先同版）；控制器 probe 不能代替它，
因为[官方允许兼容窗口内的混合组件版本](https://slurm.schedmd.com/upgrades.html)。
只考虑该已验证组合下新建并留有原始实例证据的普通非联邦作业；旧绑定缺失、
跨升级存活或曾损坏的历史不能凭当前版本补正。不要求或执行集群升级。
这仍是待决定的支持范围建议，版本白名单不能代替逐次证据核验或消除执行竞态。

读完之后到取消之前仍可能启动。仅添加查询不能消除该竞态。后续若考虑
`scancel --ctld --state=PENDING` 与精确实例标识，须单独核实版本的服务端匹配语义；
仅 PENDING 过滤也不能排除间隙中运行后又重排。见[scancel 官方文档](https://slurm.schedmd.com/scancel.html)。
本节不授权修改取消命令；取消后历史变化仍必须阻断替代提交。

### PBS 方言与无法直接补足的证据

| 方言 | 最小正式观察 | 正向证据边界 |
| --- | --- | --- |
| Torque | 复用 `qstat -f <JOB_ID>`，或验证版本后固定使用 `qstat -f -1 <JOB_ID>` 避免折行 | `start_count` 在发送给 MoM 前增加，非零足以否定 never-started；新作业可因属性 unset 而不输出计数。不能用合成显式零 fixture 冒充真实正向接口。 |
| OpenPBS/PBS Pro | 已识别方言/版本下固定 `qstat -x -f <JOB_ID>` 获取保留历史 | `run_count` 默认零，但管理员/operator/hook 可修改；普通用户不能假定可读内部 run_version。缺字段不补零，迁移状态 M 不当作终止。 |

Torque 的 `-x` 在相应版本用于 XML，不能直接复用 OpenPBS 的历史选项。
见[Torque qstat](https://docs.adaptivecomputing.com/torque/6-0-3/adminGuide/Content/topics/torque/commands/qstat.htm)、
[Torque 发布说明](https://docs.adaptivecomputing.com/torque/6-1-0/releaseNotes/Content/topics/releaseNotes/resolvedIssues.htm)、
[PBS 历史查询说明](https://2019.help.altair.com/19.2/PBSProfessional/PBSUserGuide19.2.1.pdf)。

计数器证据必须落实到版本的全部启动、恢复、重排路径及实际字段可见性：
Torque 的[启动计数](https://github.com/adaptivecomputing/torque/blob/master/src/server/req_runjob.c)、
[初始 unset](https://github.com/adaptivecomputing/torque/blob/master/src/server/job.cpp)和
[省略 unset 属性](https://github.com/adaptivecomputing/torque/blob/master/src/lib/Libattr/attr_fn_l.c)
说明“缺计数”不能泛化为零；PBS 的可修改计数见
[管理员手册 §14.18](https://2021.help.altair.com/2021.1.2/PBS%20Professional/PBSAdminGuide2021.1.2.pdf)。
`qtime` 表示进入当前队列的时间，不能直接当作不可变首次提交时间；六小时证据须与原始实例绑定一致。
文本时间须有明确调度器时区，时间歧义、未来时间或迁移归属不明均拒绝；可复用现有 `pbs.timestamp()`。

PBS 完成记录也不能普遍证明 MoM 所管理的该作业进程已停止：
[Torque 删除路径](https://github.com/adaptivecomputing/torque/blob/master/src/server/req_delete.c)
可在终止信号回应后先答复客户端；
[OpenPBS force-delete](https://github.com/openpbs/openpbs/blob/master/src/server/req_delete.c)
可由 server 自行填写 obittime、退出状态和 finished history，MoM 后续才可能收到 discard。
Torque 的[job_force_cancel_time](https://docs.adaptivecomputing.com/torque/6-0-3/adminGuide/Content/topics/torque/13-appendices/serverParameters.htm)
也可在无法联系 MoM 时 purge 记录。因此 C/F、qdel 接受、Unknown Job、单独 E accounting 均不足。
需要确切作业/运行实例的可信 MoM 完成来源；或取消前后均可靠证明从未启动，
且取消后另有同实例的正式不可再调度终态/已取消证明。仍在 Q 且计数为零不能作为终止证明。
现有 `remote.session_processes` 通过当前 Transport 查询，不能假定它访问了实际执行节点。

当前不建议读取全局 server_priv/accounting、tracejob 或执行节点任意 ps：权限、实例归属、
历史完整性及路径范围未解决。证据不足时仍可实现正式保存和拒绝路径，但不得声称 PBS 自动改投已经可用。

### 所需范围增量与回归

| 文件 | 精确用途 | 原工单范围 |
| --- | --- | --- |
| `ag/src/ag/remote.py` | 固定控制器身份/版本探针、精确 Slurm 作业/重复历史查询；白名单参数，不接受 shell 文本 | 新增已允许，仅 Slurm |
| `ag/src/ag/slurm.py` | 严格解析实际 ClusterName/服务端版本及新作业格式、实例区分、字段存在性及截断/重复/状态冲突处理 | 新增已允许 |
| `ag/src/ag/transport.py` | 若增加 operation，仅登记新的固定只读类别；复用已有 jobs 类别时无需修改，不放宽取消重试 | 新增已允许，仅上述只读范围 |
| `ag/src/ag/pbs.py` | PBS 方言正向支持所需字段存在性；时间解析可先复用现有函数 | 未允许，本轮不推进 |
| `ag/src/ag/config.py` | 显式 PBS 方言/经过核验的版本边界 | 未允许，本轮不推进 |
| `ag/src/ag/status.py` | 独立正式证据采集，保存查询起止、原始响应/哈希、确切 owner/job/cluster；保留手动状态语义 | 已允许，含上述新增只读查询接入 |
| `ag/src/ag/submission.py`、`autonomy_submission.py` | 与 T186 定稿归属一起保存不可变原始调度器实例和时间，不补认旧记录、不先建另一套归属模型 | 路径已允许；等待 T186 定稿接口 |
| `ag/src/ag/autonomy_cancel.py` | 证据消费、六小时/从未运行/取消后终止判断及拒绝；实际消费调用 T186 | 已允许 |
| `ag/tests/test_slurm.py`、`test_core.py`、`test_autonomy_cancel.py` | 固定命令与参数、requeue/同号复用、历史缺失、读写间启动、COMPLETING、版本不支持、错归属 | 已允许 |
| `ag/tests/test_pbs.py`、`test_remote_observation.py`、`test_incomplete_fetch.py`、`test_pbs_arrays.py` | PBS 查询改变时的兼容回归 | 未允许，本轮不改 |

原始记录必须保留查询操作、版本/方言、完整身份、字段缺失状态、查询起止、退出码及 stdout/stderr 哈希。
代码中的正向资格仍需合并前非研究对象真实验证；官方文档和离线合成响应不证明实际集群已具备这些能力。
