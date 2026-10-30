# T187：有证据的自主取消及改投资格

## 分支与目标

`codex/t187-autonomous-cancel-reroute`，一单一 PR，V4.8 W1 取消路径及 2.6 改投。依赖已合并 T184、T185/T186 最终归属与路由接口。先读当前实现并独立完成证据核验和合成测试；不复制未合并上游代码。事故依据：把手动作业误取消、把短暂慢进展误判失败、qdel/scancel 回执不确定后重试、旧持锁会话继续取消、取消未完成就重复提交。

## 允许路径

- `ag/src/ag/cancel.py`、`cli.py`、`submission.py`：独立自主取消入口与精确作业绑定。
- `ag/src/ag/autonomy.py`、`_autonomy_store.py`、`autonomy_submission.py`：仅复用/扩展已定稿的归属、计数与原子暂停接口。
- 可新增 `ag/src/ag/autonomy_cancel.py`：条件和证据核验，不创建通用编排系统。
- `ag/src/ag/snapshot.py`、`status.py`、`route.py`：仅现有固定只读证据的绑定/读取与公共核验复用；不得新增任意远程命令。
- 2026-10-29 负责人补充允许 `ag/src/ag/remote.py`、`slurm.py`、`transport.py`：仅固定、精确作业绑定的只读 Slurm 身份/版本/历史查询及白名单解析；`status.py` 可接入这些已获准查询。详见下方范围决定，不扩展 PBS 或取消命令。
- 同日第二次范围批准：负责人答复“允许按方案补齐（推荐）”，允许 `remote.py` 独立绑定提交、SLUID 精确实例取消构造器及固定 sbatch/scancel 版本查询；新提交路径明确 `--no-requeue`，按本单末尾固定清理清单防止环境覆盖。原手动/普通兼容路径保留，不授权真实连接。
- `ag/tests/test_core.py`、`test_slurm.py`、`test_autonomy.py`、`test_snapshot.py`；可新增 `test_autonomy_cancel.py`，现有取消/状态专用回归若在其它文件可先报告准确路径。
- 协调补充 `ag/tests/test_parent_chk.py`：仅同步 READ_OPERATIONS 完整枚举断言，增加四个获准 `slurm_evidence_*` 名称；保留集合全等，父 chk 逻辑与其他测试不改。
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

以下为开发核查记录，不缩减以上验收要求。无进展取消、改投候选、停止证明及 T186 后继组合已实现并通过实际 API 的隔离测试；现场验收仍未完成：

当前无进展和改投的自主取消均仅实现 Slurm 26.05.5 的原始 SLUID 实例链。版本限制来自本单已审阅的解析及固定取消命令，
不是无进展科学判断的固有条件；无进展取消不要求六小时、无 chk 或更高位路由。
现有 PBS 正式快照与 submission/status 交叉绑定仍只提供作业号及日志来源，本单未实现 PBS 原始实例登记、
按实例固定取消及停止证明。因此 PBS 手动取消保留，普通自主提交兼容性不能被写成所有入口自主取消可用。

- `snapshot.capture_for_run(...)` 复用既有正式快照捕获，并将 round/run、确切 Attempt/作业/集群、manifest/submission 与快照文件哈希登记到自主日志。普通 `ag snapshot` 保持原行为；捕获本身不授权取消。
- `autonomy_cancel.review_no_progress(...)` 为纯本地核验接口：检查连续两个不同唤醒的正式快照来源、顺序、字节及模型对每份快照给出的审阅理由。代码不设科学停滞阈值，也不把模型布尔标签当成来源证据；审阅结果不授予执行资格。
- `autonomy_cancel.checkpoint_free_input(...)` 从冻结 bundle 核验有限严格输入没有 chk 读取路径，返回输入哈希联系；Guess、IRC、读取/重启项、未知语法和放宽输入均拒绝证明。拒绝不等于认定存在依赖，也不改变 prepare 支持范围；结果始终不授予改投资格。
- `status.capture_slurm_evidence(...)` 通过获准固定只读命令保存正式调度器观察。必须使用 submission 原有实际集群名，版本限定仅是格式候选；保存原始响应、哈希和查询时间并严格解析，首次错误停止，不补建原始实例或授予资格。
- `status.slurm_submission_probe(...)` 已实现未提交冻结字节的可选版本/身份探针；只返回 canonical 记录及哈希，不发布文件。明确缺工具、固定选项不支持或版本不识别只使实例证据不可用，真实 SSH/身份/混合错误仍抛出并附 `.evidence`。
- `status.capture_slurm_origin(...)` 已实现提交之后的一次性实例捕获：独占 claim 在查询之前，观察与最终 origin 分别在新的有效 owner 短事务中发布。失败不重查、不抹掉已知 job，返回的 `initial_instance_recorded` 也不构成现场验证或改投资格。
- `autonomy._consume_cancellation` / `_record_cancellation_result` 已实现独立记账：每唤醒最多两次、同 Attempt 与改投谱系不可重用；结果不确定在同一事件中暂停。`cancel.autonomous_cancel` 在真实归属、有效规则及精确实例核验后，按 kind 验证两次无进展审阅或六小时/从未运行/无 chk/更高位候选，只发送一次固定取消命令。
- `cancel.verify_stopped` 使用只读 transport 和当前 owner 发布保护，交叉核验实际消费、接受账本、原始回执及取消后同实例终态，独占保存停止证明；不会再取消或 prepare/submit 后继。
- 不复制未合并的 T185/T186 代码；独立分支缺少上游接口时明确拒绝执行。手动取消保留 Mac 确认并接入 T186 manual_write_guard。没有连接真实集群。

当前待验收项属于**上游集成**与**环境验证**：

| 缺口 | 核查结果与接入要求 |
| --- | --- |
| T186 实际自主提交归属 | 已使用真实 prepare/submit/reservation/consume/dispatch API 隔离组合，包含无进展取回补救和改投后继；依赖合并及现场验证待完成。手动 policy 或本地意图计数不能替代归属。 |
| 消费、暂停与在途取消 | 实际入口已在消费前核验 T186 归属、当前规则与完整条件；覆盖未知响应、不可退款、接管后迟到结果。现场验证仍待完成。 |
| 从未运行与排队六小时 | 已组合原始/当前控制器及重复记账、无重启、运行时间与六小时条件并接入改投执行；控制器预测时间与记账实际时间分开处理。现场验证待完成；PBS 不支持正向。 |
| 无 chk 依赖 | `checkpoint_free_input` 已独立实现严格冻结字节核验；缺 `parent_chk` 或人工标签均不构成证明。它支持有限 Gaussian/CP 语法及受支持的 XYZ/约束，未知、放宽输入仍拒绝；不是改投资格或科学验收。 |
| T185 当前路由与容量 | 已调用与自主提交相同的定稿算法并完成后继组合，核验精确原记录、更高位候选、共享入口占用、当前容量和候选规则预算；没有取消专用排序。容量足够不保证调度器立即启动。 |
| 取消之后的终止证据 | 已实现正式同实例停止核验和独占证明，并通过完整实际 API 组合；接受或本地 cancelled 均不代替该证明。缺失或矛盾、仍活动、查询失联不能放行替代 Attempt。 |

离线回归覆盖证据、无进展及改投取消、停止和后继的正向与拒绝行为。最终合并组合及现场验收仍待完成；具体测试结果以冻结源码与本 PR 当前 head 的执行记录为准，不以设计矩阵代替测试通过。

### 执行器与后继的离线验证

生产源码冻结后的本地全量 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`：
**7775 passed, 35 skipped**（571.22 秒）。其中 9 项跳过要求未合并的实际 T185/T186，另 26 项为私有日志或 Linux 专用用例。
此后仅修正两份测试文件的共享夹具并增加一个真实 90% 预算用例；两文件重新执行为 **623 passed, 10 skipped**（39.81 秒），
全部 10 项跳过都是组合依赖缺失，不能把这些跳过计为独立分支已验证集成。
最终组合的 `test_core`、`test_autonomy_cancel`、`test_slurm`、`test_snapshot`、`test_autonomy` 五模块为
**1134 passed, 11 skipped**（93.01 秒）；跳过项为 Linux 专用快照验证。组合首轮的两个夹具问题已修复：
缺 T185 用例显式删除对应接口，临时测试包补齐原有相对日志 fixture；生产源码未改。缺 T185 单例在独立分支另复验通过。

冻结组合的实际 API 选择性测试 **19 passed**：本单 7 项完整改投/规则/占用/90% 用例、3 项真实读证据收据用例，
以及 T186 的 6 项无进展取消/完整或不完整取回/有界补救和 3 项改投后继用例。
另一 study 已确认停止后，当前 study 的路由、取消消费、一次命令、停止证明和新 Attempt prepare/submit 完整走通；
accepted 尚未停止及 UNKNOWN 均保留旧占用。实际 T185 选择器、T186 政策/消费/归属 API 未用替代实现。
HOME、配置、registry 和调度器响应均隔离，SSHTransport 执行入口硬失败；没有真实 SSH 或本机配置修改。

组合依赖固定 T185 `47ac89867132d5271c996f6d56183f1935011af8` 与 T186 `e5b2daa60570d139f222210de5da93c968e0ee51`。
组合源码摘要 `690c8078414a5c077394057a82bea44f7d0e67fe1ae4335a239c5988f87378eb`；
最终源/测试映射清单 v2 SHA-256 为 `3270402a843a7ca52c6b6942810c1f1833dfcc106ea0e1049e61c96b64af5e6f`；
先前清单 `e6aeaa549d5ecd2e758151ead3c77c7a4411975dc1c7c5d168c7c2076252b170` 和失败日志保留，不覆盖历史记录。
两个依赖的完整 `ag/src` 已逐文件核对固定 Git 对象；T187 使用完整冻结源码，没有拼接不同阶段的执行器。
本单实际回归已保存在 `ag/tests/test_autonomy_cancel.py`，仅缺集成接口时明确跳过。复现选择性入口（在已组合源码中）：

```sh
PYTHONPATH=ag/src python -m pytest ag/tests/test_autonomy_cancel.py ag/tests/test_autonomy_submission.py -q \
  -k 'real_reroute or stopping_read_receipt or actual_no_progress_cancel_and_bounded_successor or actual_reroute_stop_and_single_successor'
```

组合曾发现旧单元夹具手写归属却调用真实消费核验，以及已有自主上下文中构造反例字节被手动写保护拒绝。
修复仅隔离这些单元夹具的测试边界，生产归属和写保护不放宽；端到端用例继续使用真实 prepare/submit 与正式消费。
原始组合清单、完整日志、源码哈希及复现材料保存在仓库外；它们不是现场支持、科学验收或自主启用证明。

### 较早证据检查点（非本次执行器验收）

2026-10-29 较早检查点 `8465a385` 验证：`ag/tests skills-next` 共 **7347 passed, 26 skipped**（486.10 秒）；
跳过项为私有日志显式启用或 Linux/GNU stat/procfs 专用用例，后者仍须当前 head Linux CI。
T186 真实 API 临时组合另 **3 passed**：write_reservation → submission_guard.consume/dispatch_started →
submission.record → observation_publication_guard/verified_reservation → 本单 capture_slurm_origin。
成功登记、首个查询 255 保留已知 job/submitted、第二次调用 claim 拒绝且零新增查询均通过。
路由与调度响应为合成，未覆盖完整 submit、真实 T185 选择器或取消/改投，不作为现场验证。
组合以 T186 `25c51c9d88f8a680c7bc1cbda68a09e3dabff4c3` 加其当时工作树及本单冻结源码构成；
T186 输入树摘要 `b73cfb28f71999a8e039de03bbf5060c2aa56ae5ecc3d3f5ea6b9ca5d122bdae`，
组合源码/模板摘要 `2b6e8be19b07aa489649426cb5e7727cd7188bcbcfb5736d86c4564894a22f17`。
源工作树后续变化须重新组合，不能只以 T186 的旧 HEAD 复现这一结果。

### T186 组合适配（已通过冻结源码的隔离组合，待依赖合并）

- `autonomy_submission.verified_authorization(path, authorization)` 只恢复已在调度前绑定的原始归属；
  再与当前轮次、有效规则和 `state.submissions` 实际消费交叉核对。它不授权取消，也不建立缺失的调度器初始实例。
- `submission_guard` 的 consume/dispatch/abort 与 `boundary_failure` 服务于提交；取消须独立保存每次唤醒最多两次的原子消费、
  确切目标和不可重试 claim，不能复用提交次数或把 boundary_failure 当取消许可。未知结果立即保存后果并暂停。
- 组合保持配置提交锁 → 全机登记锁 → study 状态锁的顺序，短事务中重读归属、条件与当前租约，释放全机/study 锁后才做网络 IO。
  已发出的操作不能撤回；后续响应仅补结果，不能恢复动作资格。
- 手动 `cancel` 已接入 `manual_write_guard(..., action='cancel', attempt_ids=[...])`，仍保留逐次 Mac 人工确认。
  running 或有效 lease 时拒绝，paused 且无有效 lease 才可接管；不能仅依赖前端保护。fetch 写入归属由 T186 组合处理，
  本工单不新增 `fetch.py` 范围。上述接口仍在上游开发中，本分支未复制上游实现。
- 负责人补充要求 IO/解析后在最终本地发布前锁内重验 owner 权限。T186 负责 status/fetch/snapshot/facts 的最小发布钩子；
  T187 的 `capture_for_run` 与新 Slurm 采集须接该钩子。当前分支已给 snapshot.capture 增加最小 publication 工厂，
  capture_for_run 在 T186 已集成时使用 observation_publication_guard，全机登记锁先于 study 锁，失效 owner 不创建普通快照。
  独立 T184 证据用例继续使用已有 owner guard；不因此获得实际取消归属。
  网络/解析保持锁外，最终发布才持短锁；隔离组合通过不代表现场验证或自主启用。

提交时原始实例与 T186 按以下边界对齐（已进行真实提交 API 的合成组合；不以观察接口补认）：

1. 对可能取得自动改投资格的新 Attempt，dispatch 前由 T187 固定五次查询读取实际 ClusterName、控制器及 scontrol/sacct/sbatch/scancel 客户端版本。
   T186 在有效 owner 的短发布事务中把原始 probe 及哈希与 reservation、输入/bundle、轮次、规则及本次 dispatch 绑定。
   **这是改投资格条件，不是所有普通自主 Slurm 提交的新版本门槛。** 可预期的不支持版本只记录 origin/reroute 不可用，
   保持既有已审阅提交能力，不发送该版本不支持的后续实例查询。真正 SSH 失败或身份矛盾仍按停止/暂停规则处理。
   旧 Attempt 没有这份 dispatch 前证据时，不能事后创建。
   即使 `sbatch --parsable` 没有返回 cluster，也只能使用这份已绑定的实际集群名；若返回不同名称即拒绝归属并暂停。
2. 确定取得作业号后，T186 先独占保存确切 submission/status 绑定，再调用 T187 的一次性初始实例捕获。
   捕获只读 exact job 的历史与控制器，核对原始名称/UID/Submit/SLUID、当前版本与预先绑定集群；
   首次查询前须先原子声明，成功/失败/崩溃均不重用，不允许稍后重试把当前实例补成初始实例。
   原始响应和成功/不可用结果独占落盘，由 submission 预先引用的原始证据身份交叉核验。
3. 初始查询失败但 sbatch 回执确定时，仍保留已知作业号及已提交状态，记录初始证据不可用并禁止自动改投，
   不把已提交伪装成未提交失败，也不重提。只有提交响应自身不确定才进入 UNKNOWN；后续只读核对可恢复确切绑定，
   但不能生成迟到的初始实例资格。失效 owner 不得发布到 study，网络返回仅交有效 owner 按原一次性记录处理。
4. 查询侧最小签名与适配约定如下。它们不授予执行权限；当前 `capture_slurm_evidence` 只能观察已绑定作业，
   不承担任一原始注册步骤。第一份 probe 不写 ownership 哈希，避免 reservation 包含 probe 哈希而产生循环引用。

   - `status.slurm_submission_probe(cfg, path, transport)`（已实现）：仅接受尚无提交声明/绑定的 prepared Attempt，
     只读 config 与四个客户端版本，返回 canonical probe 记录及 SHA-256。记录包含 manifest/bundle 哈希、
     配置入口、实际集群、版本、查询起止、原始响应与哈希；无本地发布和远程写入。
     返回 `{'record': canonical_dict, 'sha256': SHA256(canonical_bytes)}`。T186 用有效 owner 的发布事务将原字节独占保存为
     `slurm-origin-probe.json`，并把 probe 哈希纳入原 reservation，随后才 dispatch。probe 本身不包含 ownership 哈希，避免循环引用。
   - `status.capture_slurm_origin(cfg, path, transport, *, probe_sha256, ownership_sha256, publication)`：
     job 从已独占保存的 submission 读取，不能由调用者另填；读取并复核原 probe、manifest/bundle、确切提交及 T186 已验证归属。
     `publication` 是 T186 的零参数 contextmanager 工厂，提供锁内复验的原始 state，不能是模型字典。
     查询前在该短事务内创建一次性 origin claim；查询在锁外；最终原始响应/身份或不可用结果再次经 publication 独占发布。
     claim 已存在则永不重查，含首次失败或崩溃。
     该接口读取真实 `state.submissions[Attempt].dispatch_started == {'at': timestamp}`，严格拒绝替代类型或额外字段；
     probe 完成不得晚于原 dispatch，当前 round/run/plan 与消费一致。初始 claim、观察发布、最终 origin 共三个短事务，
     版本不支持或缺实际集群时只用首尾两个事务且不发送作业实例查询。
     正常返回含 `origin_sha256`、`initial_instance_recorded`、`status`，`reroute_authorized` 和 `live_validated` 恒 false。
     真正查询/解析故障在可发布时保存不可用 origin，再抛原异常并附 `origin_evidence`（文件名、哈希、完整记录）；
     发布权限拒绝直接抛错，保留已存在 claim；不因本地记录缺失重试。
   - 申请原始实例资格的新 submission 额外绑定 `scheduler_probe_sha256`，并使用 probe 中已验证的实际名称填 `scheduler_cluster`。
     `ownership_sha256` 必须与原 reservation、`state.submissions` dispatch 消费及 submission.authorization 一致。
     初始记录同时引用这三个不可变哈希；旧 submission 缺 probe 引用时拒绝，不追加字段补认。
     普遍提交硬要求仍为既有确切 job/配置入口、manifest/输入字节与授权绑定；缺 origin/probe 引用只禁止自动改投，
     不追溯否定已有提交，也不把可预期版本不支持当成所有普通自主提交都失败。
   - probe 不支持的版本/不完整结果不能进入原始实例资格；这不自行改动其他提交规则或假称 DBD 历史已验证。
     T186 适配须区分“提交本身已知/未知”和“原始实例证据不可用”，后者永远不成为重提理由。

   T187 负责固定查询及一次性证据写入，T186 负责 reservation/dispatch/精确提交绑定和发布权限适配；
   上述签名已经实现并经过真实提交 API 的合成组合。最终参数只能从这些已验证源取得，不能用手写摘要或布尔标签替代。
   T186 最新开发源码已按 collect probe → reservation/consume 的顺序接入，避免循环引用；
   旧开发说明中“消费后采集”须同步。不能通过事后改写一次性 reservation 解决，组合结果以冻结源码及实际 API 测试为准。

取消后的后续动作需分别接通：

- **无进展补救：** T187 输出不可变的本轮确切取消归属/结果、理由、两份原快照哈希及已确认停止证据；
  T186 仅在取回（允许 `fetch --incomplete`）的文件/哈希与该记录、确切作业一致时接受相应 canonical 补救类。
  取消回执不确定、仍在运行或取回证据缺失均暂停拒绝；不能只要求普通成功 fetch 而把此合法分支堵死。
- **自动改投：** 只消费已验证 never-started、六小时、当前更优候选和确认停止的改投资格，保持原对象/谱系，
  每个原作业最多一次；新 Attempt 仍计本轮预算。它不等同于同对象的常规失败补救，不能清空次数或因旧作业已取消而一概拒绝。
- 这两条已通过冻结源码的实际 API 隔离组合；T187 负责上述取消/资格证据，T186 负责 canonical 补救适配、原始消费及全局资源计数。
  最终回归必须用真实实现组合“连续快照 → 取消 → 确认停止 → 不完整取回 → 新 Attempt”，模拟 Transport 不代表现场通过。

最初源码核查发现两个接线点（已由 T185/T186 补接口，最终组合见下方）：旧 T185 `select_ladder` 遇本对象未 finished 的旧作业即返回
`object_already_active_in_round`，不会计算候选。需由 T185 提供同算法的最小替代候选入口/参数，
仅对通过 study_key/Attempt/record_sha256 精确定位的原记录跳过同对象重复选择检查，原作业仍完整计入全部资源、作业数及本地预留。
不得删除旧 placement、伪造 finished 或更换 object_id 来获得候选。T186 适配须将原 reservation/路由位置与该只读选择结果交叉核验。
另 T186 `write_reservation` 当前无条件使用 `remedy_evidence`，已派发对象仅接受 fetched 的失败来源；
never-started 被取消作业可能没有输出，需该工单单独接受本单确认停止的 reroute_source，保持原对象与一次谱系，
新 Attempt 仍计轮次预算，不伪造程序失败或清空常规补救次数。以上不是本单复制另一套路由或修改 T186 源码的许可。

## 合并前真实验证矩阵（未授权、未执行）

仅使用专用非研究 study。待 T185/T186/T188 接口定稿后，生成待负责人审阅的确切输入、输入及 bundle SHA-256、计划/规则哈希、完整正式 ag 命令和逐条执行次数；当前未生成这些最终值，不用占位哈希冒充已准备或获准。

| 场景 | 待准备对象与操作 | 必需证据及验收 | 当前状态 |
| --- | --- | --- | --- |
| 本轮专用作业自主取消 | 由本轮有效规则实际提交专用小分子作业；两次不同且连续唤醒通过正式接口捕获并审阅；核对后对确切作业发出一次取消 | 一次性自主归属与完整摘要、两份日志及哈希、每份审阅理由、取消前消费及目标记录、取消实际结果、取消后正式终止证据。至少一个真实本轮专用作业完成此链路。若快照不支持无进展，不为满足测试而伪造结论或取消。 | 未授权、未执行；确切命令与次数待接口定稿及场景审阅 |
| 错误归属拒绝 | 用本地合成绑定覆盖手动提交、其他 study/轮次、UNKNOWN、损坏身份和共享入口混淆 | 在发出任何远程写操作前拒绝；不对其他人的或错误归属作业试取消 | 仅离线验证；无真实取消计划 |
| 接受后尚未终止 | 对获准专用作业保留取消接受后的正式状态观察 | 接受回执不能产生替代 Attempt 资格；只有取消后的确切终止证据才允许进入下一阶段 | 未授权、未执行；现场能否观察此窗口未知，不能预称覆盖 |
| 结果不确定与失锁 | 先以假 Transport、并发及崩溃注入覆盖取消发出后的失联、暂停和接管；若确需现场异常场景，另列具体方法请求批准 | 原 claim 与消费保留、立即暂停、不重复取消、不 prepare/submit 替代作业；不宣称网络中途能够撤回已发命令 | 真实故障注入未授权、未执行 |
| 有证据的改投 | 保留真实排队至少六小时；取得可证明从未运行的调度器证据、无 chk 依赖证明和 T185 更高位容量证据 | 先取消并核实原作业终止，再单独审阅新 Attempt 的原科学输入哈希联系、资源变更与 T186 全部核验；每个原谱系最多一次 | 接口已实现；未授权、未执行，不缩短或篡改等待时间 |
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

本节只读核查现有源码、官方调度器文档与官方源码，没有连接集群或在真实集群执行下列新查询。
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
| 取消后的终止 | 当前实现要求控制器与记账均返回匹配实例的取消后 CANCELLED 记录及结束时间，拒绝 RUNNING、COMPLETING、SIGNALING、重排队等活动状态。控制器无记录仍拒绝停止证明；任意查询失败不等于作业不存在。 |

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

## 已批准的 Slurm 写命令最小增量（实施中，未真实执行）

当前 `slurm_submit` 是 `sbatch --parsable job.slurm`，`slurm_cancel` 是 `scancel <数字作业号>`。
新只读 probe 清除了查询目标的环境覆盖，但没有改变这两个写命令；不能据此声称查询目标与实际动作已闭合。
本节方案经协调方审阅后，负责人已在 2026-10-29 明确答复：“允许按方案补齐（推荐）”。
批准问题原文：“是否允许 T187 扩展 remote.py 的固定写命令：提交绑定已核实的真实集群，清除会覆盖已确认资源的调度器环境选项，并在该新路径禁用自动重排；无进展取消绑定具体作业实例，补充 sbatch/scancel 版本查询？仅适用经验证的版本，保留原手动流程，不授权连接真实集群。”
本次新增授权覆盖以下独立固定构造器和版本查询；不包含真实执行、部署、配置修改或计算。
事故依据：环境将提交/取消转向其他实际集群、覆盖已批准脚本的资源/名称/输出，或数字 JobID 复用后取消另一个实例。

### 提交：固定环境与单一实际集群

新增独立的绑定提交构造器 `remote.slurm_submit_bound(cfg, manifest, *, scheduler_cluster)`，
由 T186 负责调用接线，本单独占修改 remote.py，避免重复实现。保留现有远程路径检查和 `cd`，随后使用下面固定形状。
尖括号只允许由已绑定 probe 的单一实际 ClusterName 填入；拒绝 `all`、逗号列表和其他非白名单值。
`job.slurm` 仍为已获授权、上传后核对过的原 bundle 文件，不重渲染、不追加脚本参数。

```text
env -u SLURM_CLUSTERS -u SLURM_HINT -u SLURM_HOSTFILE \
  -u SBATCH_IGNORE_PBS -u SBATCH_DEBUG \
  -u SBATCH_ACCOUNT -u SBATCH_ARRAY_INX -u SBATCH_ACCTG_FREQ -u SBATCH_BATCH \
  -u SBATCH_BURST_BUFFER -u SBATCH_CLUSTER_CONSTRAINT -u SBATCH_CLUSTERS \
  -u SBATCH_CONSOLIDATE_SEGMENTS -u SBATCH_CONTAINER -u SBATCH_CONTAINER_ID -u SBATCH_CONTAINER_TYPE \
  -u SBATCH_CONSTRAINT -u SBATCH_CORE_SPEC -u SBATCH_CPU_FREQ_REQ -u SBATCH_CPUS_PER_GPU \
  -u SBATCH_DELAY_BOOT -u SBATCH_DISTRIBUTION -u SBATCH_EXCLUSIVE -u SBATCH_EXPORT -u SBATCH_GET_USER_ENV \
  -u SBATCH_GRES -u SBATCH_GRES_FLAGS -u SBATCH_GPUS -u SBATCH_GPU_BIND -u SBATCH_GPU_FREQ \
  -u SBATCH_GPUS_PER_NODE -u SBATCH_GPUS_PER_SOCKET -u SBATCH_GPUS_PER_TASK -u SBATCH_HINT \
  -u SBATCH_JOB_NAME -u SBATCH_MEM_BIND -u SBATCH_MEM_PER_CPU -u SBATCH_MEM_PER_GPU -u SBATCH_MEM_PER_NODE \
  -u SBATCH_NETWORK -u SBATCH_NO_KILL -u SBATCH_NO_REQUEUE -u SBATCH_OPEN_MODE -u SBATCH_OVERCOMMIT \
  -u SBATCH_PARTITION -u SBATCH_POWER -u SBATCH_PROFILE -u SBATCH_QOS -u SBATCH_REQ_SWITCH \
  -u SBATCH_REQUEUE -u SBATCH_RESERVATION -u SBATCH_SEGMENT_SIZE -u SBATCH_SIGNAL \
  -u SBATCH_SPREAD_JOB -u SBATCH_SPREAD_SEGMENTS -u SBATCH_THREAD_SPEC -u SBATCH_THREADS_PER_CORE \
  -u SBATCH_TIMELIMIT -u SBATCH_TRES_BIND -u SBATCH_TRES_PER_TASK -u SBATCH_USE_MIN_NODES \
  -u SBATCH_WAIT -u SBATCH_WAIT_ALL_NODES -u SBATCH_WAIT4SWITCH -u SBATCH_WCKEY \
  -u SBATCH_ERROR -u SBATCH_INPUT -u SBATCH_OUTPUT \
  LC_ALL=C TZ=UTC sbatch --parsable --clusters=<ACTUAL_CLUSTER> --no-requeue job.slurm
```

清理名单来自 26.05.5 `early_env_vars` 与 `env_vars` 的完整固定名称集合，以及共享验证器的 `SLURM_HOSTFILE`，避免仅清 `SLURM_CLUSTERS` 而遗漏
`SBATCH_CLUSTERS`、资源、数组、作业名及输出位置覆盖；这里选择固定清理而不复制脚本全部参数到命令行。
该版本按脚本 → 环境 → 命令行处理，之后仍有站点 cli_filter/SPANK 处理，不能声称消除了管理员插件影响。
依据：[环境集合及处理顺序](https://github.com/SchedMD/slurm/blob/slurm-26-05-5-1/src/sbatch/opt.c#L154)。
共享 `_validate_nodelist` 在未设节点列表时读取 `SLURM_HOSTFILE` 并转为 arbitrary 分布，可能读取未确认的节点文件或与固定 nodes 参数冲突，
所以将该固定名称一并清除；不扩展为任意环境过滤。依据：[共享节点验证](https://github.com/SchedMD/slurm/blob/slurm-26-05-5-1/src/common/slurm_opt.c#L5398)。

单一 `--clusters` 仍依赖该站点数据库/配置可解析该实际集群；失败不回退无集群限定的写命令。
脚本里现有 partition/account/qos、核数、内存、walltime、名称和输出路径保留原冻结字节；回执 cluster 必须与 probe 一致。
`sbatch` 本身不会提前给出 SLUID，不能编造提交前实例；确定 job 回执先保存，再用本单一次性捕获登记 UID/SLUID。
不添加切换身份的 `--uid`/`--gid`；提交依赖已配置 SSH 身份及调度器认证，UID 在首次正式控制器/记账中交叉核验。
依据：[单集群选取、提交和 parsable 回执](https://github.com/SchedMD/slurm/blob/slurm-26-05-5-1/src/sbatch/sbatch.c#L246)。

不得把 26.05.5 证据候选变成所有普通提交的新版本门槛。此固定新路径需另存实际 sbatch 客户端版本证据，
与审阅版本相符且真实验证通过才可声称支持该绑定能力；旧/定制客户端或缺 probe 保留原提交能力说明，自动改投资格继续不可用。
`SLURM_CONF`、认证环境和站点插件不能随意清除：保留站点配置，实际 config/版本/回执冲突即停止；不以清环境代替真实集群核验。

### 取消：SLUID 可定位实例，但当前不能原子满足改投条件

新增独立精确实例构造器
`remote.slurm_cancel_instance(*, scheduler_cluster, uid, job_name, sluid, purpose='no_progress')`，现有手动 `scancel` 与 Mac 确认保持原行为。
候选命令如下；只传一个 SLUID，数字 JobID 留在本地绑定中，不作为第二个位置参数（第二个会增加取消目标）。

```text
env -u SLURM_CLUSTERS \
  -u SCANCEL_ACCOUNT -u SCANCEL_BATCH -u SCANCEL_CTLD -u SCANCEL_CRON \
  -u SCANCEL_FULL -u SCANCEL_HURRY -u SCANCEL_INTERACTIVE -u SCANCEL_NAME \
  -u SCANCEL_PARTITION -u SCANCEL_QOS -u SCANCEL_STATE -u SCANCEL_USER \
  -u SCANCEL_VERBOSE -u SCANCEL_WCKEY \
  LC_ALL=C TZ=UTC scancel --ctld --clusters=<ACTUAL_CLUSTER> --user=<UID> --name=<ATTEMPT_ID> <SLUID>
```

实际集群取原 probe，并与 submission/origin/当前正式 config 一致；UID、名称和 SLUID 取经 T186 归属绑定的
一次性 origin，再对照取消前正式 controller/history。所有参数是已验证记录的字段，不能直接采信模型自由输入。
拒绝缺原实例、数组、heterogeneous、联邦、版本未知或任何身份冲突。清理名单逐项来自
[scancel 的环境处理](https://github.com/SchedMD/slurm/blob/slurm-26-05-5-1/src/scancel/opt.c#L232)。

26.05.5 将 SLUID 原串送入 `slurm_kill_job2`，控制器在作业写锁内按 SLUID 定位并核验调用身份；
这可以避免只靠数字 JobID 取消已复用的新实例。
依据：[请求字段](https://github.com/SchedMD/slurm/blob/slurm-26-05-5-1/src/api/cancel.c#L47)、
[控制器锁与调用](https://github.com/SchedMD/slurm/blob/slurm-26-05-5-1/src/slurmctld/proc_req.c#L5725)、
[SLUID 查找与认证](https://github.com/SchedMD/slurm/blob/slurm-26-05-5-1/src/slurmctld/job_mgr.c#L5319)。

**该版本的 `--state=PENDING` 不是原子保障。** 源码推论是：SLUID 的数字占位为 NO_VAL，
`has_fed_jobs` 把它识别为需回退的路径，跳过批量服务端过滤；PENDING/UID/name 过滤在客户端，
随后请求只携带实例和信号，过滤之后仍可能启动。
依据：[SLUID 解析](https://github.com/SchedMD/slurm/blob/slurm-26-05-5-1/src/scancel/opt.c#L532)、
[回退判断](https://github.com/SchedMD/slurm/blob/slurm-26-05-5-1/src/scancel/opt.c#L153)、
[数值常量](https://github.com/SchedMD/slurm/blob/slurm-26-05-5-1/slurm/slurm.h#L106)、
[命令分派](https://github.com/SchedMD/slurm/blob/slurm-26-05-5-1/src/scancel/scancel.c#L329)。
即使后续版本修复这条分派，基础 PENDING 仍可能包含 COMPLETING，重排的 SLUID 更新也在收尾之后；
不能只凭 PENDING 过滤断言从未运行。取消后发现曾运行再阻止新 Attempt，不能补救已经误取消了运行中的作业。
因此当前命令不能提供该原子保证，不以额外远程脚本掩盖这一点。
依据：[基础状态过滤](https://github.com/SchedMD/slurm/blob/slurm-26-05-5-1/src/slurmctld/job_mgr.c#L4421)、
[重排计数/状态](https://github.com/SchedMD/slurm/blob/slurm-26-05-5-1/src/slurmctld/job_mgr.c#L17035)、
[收尾后实例更新](https://github.com/SchedMD/slurm/blob/slurm-26-05-5-1/src/slurmctld/job_mgr.c#L16024)。

probe 独立读取固定 `scancel --version` 和 `sbatch --version`，保存原文/哈希并核对命令版本，
不能以 scontrol 版本替代；这不改变普通提交的兼容边界。
一个 scancel CLI 内部对明确的 TRANSITION_STATE_NO_UPDATE 可能重试 RPC，需如实记录；ag 仍只消费一次并发出一次 CLI，
SSH/回执不确定不再次发出 CLI。依据：[内部有限重试](https://github.com/SchedMD/slurm/blob/slurm-26-05-5-1/src/scancel/scancel.c#L886)。

### 已批准的精确范围与待验收项

- 批准范围仅为 `remote.py` 的上述两个独立固定写命令构造器、已有版本查询白名单加入 sbatch/scancel；
  其余接线复用工单已允许的 submission/cancel/status/transport 及测试路径。不给任意 shell、批量目标或新的远程解释器入口。
- 保留逐 Attempt 的输入/bundle 哈希、上传后校验、一次性提交声明、T186 owner/规则/原始归属及本轮计数；
  取消另需对应 kind 的完整证据、独立消费和同一个不可重用 `.cancel-claim`。不回退成手动确认来冒充自主成功。
- 离线先验证环境覆盖清除、严格参数、单目标与旧手动行为；真实验证按专用非研究对象逐项批准，
  包括实际 client/controller/DBD 组合及命令目标。未知响应保留全部记录、暂停，不能以再次执行验证第一次是否成功。

构造器的 `purpose` 严格仅 `no_progress` 或 `reroute`；后者仅增加固定 `--state=PENDING` 客户端过滤，仍只有一个 SLUID。
改投资格同时核验取消前的完整排队证据、六小时、无 chk 依赖、同一 T185 更高位容量候选，以及取消后同实例的确切停止证据。
明确运行、重排、仍活动、UNKNOWN 或证据不足均不能放行替代 Attempt。

版本探针接线约定：原 `versions` 继续保留 controller/scontrol/sacct 三键；新增 `execution_versions` 保存 sbatch/scancel
的 raw/parsed 版本，避免更改已有 origin 的格式候选语义。`bound_submit_format_candidate` 仅在实际集群已知且
controller/scontrol/sbatch 均为审阅版本时成立；`instance_cancel_format_candidate` 还须已有观察格式候选与相同 scancel 版本。
这两个布尔值只说明格式候选，`live_validated` 和所有执行授权仍 false；调用方必须另外核验有效规则、完整归属、现场能力及动作边界。
配置工具缺失仍仅查询一次；其他正常 probe 为五次固定读取。可预期版本不支持只影响相关候选，不一概禁止普通提交。
T186 开发工作树的 `_slurm_probe` 已接入五次查询及新增字段核验，仍须使用冻结组合重新验证；
先前 3 项真实 API 组合只覆盖原三查询 probe，不能自动算作新增五查询/绑定写命令的组合通过。

### 当前执行接口接线

同一实际集群绑定的必要只读配套已实现：`slurm_jobs`、`slurm_accounting`、`slurm_find`、`slurm_history`
增加可选 `scheduler_cluster=None`。默认命令保持原字节；非空值只能由已核验 probe/submission 的实际 ClusterName 提供，
固定单集群、local 查询并清除官方源码列明的目标/过滤环境变量。账号容量查询仍带确切同一用户，并加 `--all` 纳入隐藏分区，
不会查询所有用户。没有增加 sinfo 行为、任意命令或配置方言。
来源：[squeue 环境解析](https://github.com/SchedMD/slurm/blob/slurm-26-05-5-1/src/squeue/opts.c#L166)、
[SHOW_ALL 与用户过滤](https://github.com/SchedMD/slurm/blob/slurm-26-05-5-1/src/squeue/squeue.c#L279)、
[sacct 环境解析](https://github.com/SchedMD/slurm/blob/slurm-26-05-5-1/src/sacct/options.c#L497)。

`verify_slurm_instance` 重读原 probe、claim、origin、提交绑定和两份观察的全部原文与哈希，重新解析固定响应；
原始 dispatch 与当前取消 wake 可以不同，但必须属于同一当前轮次和计划。取消前观察加入独立的当前 scancel 版本查询。
`_cancellation_guard` 提供锁内最新状态、重新核验和一次性消费；未收到结果的消费阻止新写动作，不能通过开始新 wake 或恢复清掉。

`cancel.autonomous_cancel` 和取消后停止核验已接线，完整三方正向/拒绝回归结果记录在最终冻结验证中。
T185/T186 已提供以下同算法接口，不使用 T187 的平行排序或删除旧预留替代：

- T185 `select_ladder` 的精确原作业参数：仅针对已验证的 study_key、Attempt、record_sha256 绕过同对象重复候选短路，
  旧作业的资源、作业数和全机预留仍全部计入；原始 cell 来自 T186 reservation，新候选严格高于原位置。
- T186 `reroute_source`：读取本单原取消消费、接受回执和确切停止证据，核对同对象/原谱系、输入哈希联系及当前计划，
  使从未运行、无输出的已取消排队作业走独立改投后继，而不是伪造普通程序失败。新 Attempt 仍消费真实提交预算，不能洗掉一次谱系限制。

停止核验结合取消前完整 never-started 观察、同实例最终停止和之后未发现相反运行证据共同判断。
pending 取消可能填入 start=end；它不单独证明从未运行，也不因其秒级时间精度而永久阻断所有正向改投。
明确运行、重排、活动状态、终止证据缺失、实例矛盾或 SSH 未知仍拒绝替代，消费保留；结果注明客户端过滤和时间精度限制。

最新三方接线约定：T185/T186 已提供 `evaluate_from={study_key, attempt_id, record_sha256}`，
T187 仅调用同一 `route.autonomous_selection`，读取其 `evaluation_only`、精确 source 及正式推荐，
不重复实现主/小体系排序。取消 request 保存完整 `routing_selection` 与 `reroute_queue`。
取消消费及 request 的 `lineage_sha256` 取原始 reservation/ownership SHA-256；T186 后继须核验该值等于
source 的 `record_sha256`，并拒绝原记录已经含 `reroute_source` 的再次改投。新 Attempt、换 wake 或换轮次均不能抹掉原谱系消费。
这是接口接线记录，最终行为以冻结组合回归为准。

停止证明的短锁接线已改为两段，避免解析跨过当前 wake 截止时间后仍发布，也避免大文件哈希持有全机锁：
`cancel._accepted_cancellation(path, ownership, reads)` 仅在锁外、T186 `_capture_reads()` 活跃期间读取和审计，
返回含 reservation 的 prepared 记录；`cancel._check_accepted_cancellation(path, current, ownership, prepared)`
在最终短事务内核验当前提交消费和 cancel/result 两条账本，配合 `reads.verify()`、最新版本及 `eligible(...)` 后发布。
T186 `_verified_stopped` 须适配这两个实际签名，不能继续使用旧 `(path, current, ownership)` 调用或将全解析搬回锁内。
只验证全机 registry 的目录身份及实际读取文件；无关 study 新建登记不使当前证明失效。inputs 的完整目录指纹仍核验，防止增加附件。

路由调用同时携带锁外 `ownership.prepare_stopped_reservations(cfg)` 产生的 `prepared_stops`，
避免另一 study 已有停止证明时在全机锁内解析，或错误保留已完成核验的旧占用。
accepted/unknown 尚无停止证明的旧占用仍保留。取消前还核对候选在当前 policy 的模板、集群、节点、单作业资源和预算范围内，
复用现有预算检查及完整 placements；防止先取消旧作业，随后新 Attempt 才因已知规则不允许而失败。
同样核对账号作业数上限及 `check_budget` 的 `pause_after_consumption`：若下一次提交消费将触发 90% 暂停，
取消前即拒绝该候选，避免旧作业已取消而后继注定无法派发。
