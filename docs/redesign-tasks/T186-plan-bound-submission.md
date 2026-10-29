# T186：绑定计划的长期规则与自主提交核验

## 分支与目标

- `codex/t186-plan-bound-submission`，一单一 PR；来源 V4.8 W2、W3 提交时一致性核对。
- 依赖 T184 的最终轮次/唤醒接口、T185 的阶梯选择器；从最新 main 开始，先做独立规则解析及核验，不复制未定稿上游实现。上游代码尚未合并时由协调方安排临时组合检出验证，不能据此合并本单。
- 目标：只有绑定本轮不可变计划和有效长期规则、持有当前唤醒租约且满足实际额度和路由证据的 Attempt 才能自主提交；旧手动流程保持可用。
- 事故依据：旧规则无到期/方法/总数限制，节点规则过宽；并发或调度器延迟使预算漏计；检查后暂停/失锁仍提交；改计划或规则后继续消费旧授权。

## 允许改动的路径

- `ag/src/ag/config.py`、`approval.py`、`submit.py`、`submission.py`、`attempt.py`、`cli.py`：规则、准备/提交入口和不可变归属记录。
- `ag/src/ag/autonomy.py`、`_autonomy_store.py`：仅已合并本地接口所必需的原子消费、暂停和边界检查扩展。
- `ag/src/ag/autonomy_policy.py`、`autonomy_submission.py`（可新增）：有明确职责的核验实现，不建通用调度框架。
- `ag/src/ag/route.py`：仅调用已审阅阶梯并核验输入/选择绑定的接入点，不另写路由算法。
- `ag/tests/test_approval.py`、`test_autonomy.py`、`test_route.py`；可新增 `test_autonomy_policy.py`、`test_autonomy_submission.py`。
- `ag/config.example.toml`、`ag/config.clusters.example.toml`、`ag/README.md`、`docs/DEVELOPING.md`、`docs/redesign-tasks/T186-plan-bound-submission.md`。

负责人追加批准（2026-10-29，协调会话转达原话）：
“允许补齐四处写入保护（推荐）”。精确新增范围为 `ag/src/ag/status.py`、
`fetch.py`、`snapshot.py`、`facts.py`，仅在状态、取回文件、快照、解析结果和相关
journal 的最终本地发布前，锁内复核当前会话权限。网络和重解析不得持全机或 study
锁；覆盖普通、补缺、不完整 fetch，以及 auto_facts 的异常与 journal。此批准不授权
真实环境或新远端命令。与 T187 共有源码需在最终临时组合检出核验。

## 要做的

1. 明确区分旧手动规则和完整自主规则：旧规则可按原有语义手动使用，缺新字段不能自主放行；自主核验失败不得回退聊天批准或弹框。保留 quote、set_at，任何配置修改产生新规则哈希。字段严格校验，拒绝未知键、空白/宽泛名单、布尔冒充整数、非有限值和矛盾上限。
2. 自主规则绑定 study、本轮身份与计划哈希、模板、集群/节点名单、单作业核数/walltime、各集群资源及作业数上限、到期时间、Attempt 总数、方法口径/网格、阶梯配置身份和是否允许放宽输入。具名 PBS 只能命中显式节点名单；不得无条件删除原政策禁令。
3. 普通 Gaussian 从实际冻结输入解析方法口径，复用现有 protocol/integration_grid 的适用逻辑但不改变 profile 行为：泛函、基组及基函数类型、色散、溶剂模型/溶剂、网格均核对。不锁完整 route，以便已批准范围内 SCF/Opt 调整。最终 Opt/Freq 不得降低收敛要求；不能仅相信模型填的“最终/预优化”标签规避。非 Gaussian 模板按实际支持的确定性参数核验，不伪造 Gaussian 口径。
4. 放宽输入能力尚未实现时，不因 allow_relaxed 为 true 就跳过普通输入检查。为 T188 留明确字段和集成位置；未来仅带不可变放宽标记、确切跳过清单且计划/规则均允许时例外，标“方法口径未核验”。本单不实现宽松解析器。
5. 提交使用 T185 同一算法、绑定的原始快照和本机全部 study/轮次的实际占用重算当前格；核对入口、节点、核数、档位/内存、walltime、模板及父 chk 集群。SCNet 自主活跃最多 4 个、兜底自主排队最多 2 个，旧轮及未读回预留继续计入；手动及非 ag 作业另计账号全部核数。拒绝伪造选择回执、过期快照、配置变化和第二份半节点占用漏计；保留对真实账号全部作业的现有即时额度检查。
6. 核对 T184 的当前轮/计划/有效唤醒租约；prepare 与 submit 的每个新动作边界都重新核验，拒绝手动会话在运行中绕过。正常唤醒结束不重置本轮预算，计划修订不擦除消费，新轮只能由显式确认开启。暂停/到期/版本变化/失锁后不能靠已读出的 check 结果继续。
7. 规则实际提交消费由不可变声明、submission-summary、submission 和 journal 交叉核验；明确成功、尚不确定的保留额度、已证明未提交三者，不把缺失/截断记录当零。把规则名/哈希、计划哈希、本轮、唤醒及精确 Attempt 归属持久保存，供后续取消核对。规则改名、哈希变化、进程重启或新唤醒不能擦掉本轮已发生消费。批次部分成功与 UNKNOWN 只读恢复都不得重复计数或再次提交。
8. 到达本轮上限 90%、计划/版本/规则失效、UNKNOWN、哈希不符等本提交路径可判定条件时，在可核验状态下原子记录暂停及原因。状态损坏只能拒绝并保留证据，不重建计数。SSH 连续失败、快照连续过期等跨唤醒统计明确交后续入口接入，不虚称全部自动暂停已完工。
9. 每个 Attempt 先留完整摘要和输入/bundle 哈希，再执行一次性提交，上传后再核验。保留父 chk、共享集群容量、独占声明、不可变绑定和 UNKNOWN 硬限制。短本地互斥不得覆盖长远程 IO；具体执行分界、暂停/失锁竞争和在途动作的处理必须有测试与明确说明，不能把旧 token 当长期通行证。
10. 不启用自主能力。文档说明当前实际字段、旧规则兼容、计数来源、暂停行为和取消仍由后续 T187 实现。

## 不允许

不改 profile/thermo 科学接受条件，不修改旧 Attempt/研究、真实配置或运行检出；不生成真实长期放行配置，不启动真实计算或定时任务，不部署、不自行合并。不新增任意远程命令或绕过确认的参数。

## 离线验证

每个新字段均有拒绝用例；覆盖与人工批准/旧规则的隔离、暂停后准备/提交拒绝、失锁/旧会话恢复、上传期间规则到期、同轮并发消费、共享账号入口、调度器延迟、批次部分提交、UNKNOWN 及恢复绑定、断电/截断、方法与网格变化、放宽标记伪造、资源和节点不符。核验拒绝发生在相应远端副作用之前。

测试使用合成 study、固定传输假对象及独立环境；全量 ag/Skills 按仓库要求通过，敏感扫描和差异检查通过。不要为重复实现编写空泛断言；重点验证额度、字节及副作用边界。

## 真实环境验证（合并前，须另行批准）

先交待验证 PR、最终提交、非研究小分子输入及 SHA-256、规则草案、精确命令和次数、预期结果/停止条件；协调方与 T185 整节点/半节点/非指定入口验证集中准备后，请负责人批准实际执行。至少一份计划绑定规则真实提交、读取确切绑定并完成取回核验；到期/口径/网格/节点/计划/上限拒绝均以该候选的真实配置做无提交拒绝检查。不能在无授权时先查询或操作集群；任何真实意外立即停止并报告，不重试提交。

## 交付与停止条件

PR 首行 `Task: T186`，列最终字段、消费来源、并发/崩溃测试、真实验证待办和明确局限。需要独立敏感路径审阅及合并前真实证据；协调方依本轮授权合并。范围外、同问题修两次未解决或无法解释事故依据时报告协调方，其余独立工作继续。


## 当前工作区接线进展与待验证（2026-10-29）

本 PR 保持待验证草案，基于已合并 T184 的 `8ff90e3`；本分支不复制 T185/T187/T188
实现，只在临时组合检出核验。已接入自主 prepare/submit、实际原子消费与暂停、
全机可信路由证据、只读 route CLI、观察发布保护，以及正式停止后的补救/改投后继。
分支全量、正式端到端定向和固定四源全量回归已通过；敏感路径现场验证和显式启用
尚未完成，不能作为自主能力已启用或合并验收完成的声明。

组合来源已固定为 T185 `47ac89867132d5271c996f6d56183f1935011af8`
（包含正式 `evaluate_from` 精确来源评估；早期功能基线为 `b4df7799`）
与 T188 `9bbebcc527d6864c79b7fd02a37599a332c3bdac`；完整组合另固定 T187
`80e959938c8888bf1aefe853be43ca276fd81439` 与 T186
`b8167ee74282ac3a28004969630574b8d31d5b2b`。该快照在只读配置身份入口补充前冻结，
不以旧全量结果冒充后续新增入口的验证；新增入口的定向结果另列。
以下行为已实现；验证结果及尚缺证据另列，不能替代真实环境验收：

- 从本地不可变 Attempt/提交归属及可追溯等待事件构造 placements、wakeups、batch_inputs；
  不接受模型手写 JSON 或仅声明哈希；使用 T185 同一选择器重算。
- 把每次消费绑定本轮、唤醒、计划、规则名/哈希、Attempt 和完整摘要字节；
  历史手动归属不足时拒绝推断，同轮跨唤醒/改名/计划修订不清零。
- T184 短锁内原子消费与暂停，prepare/创建远程目录/上传/调度提交边界重新检查；
  长远程 IO 不持短锁，明确已经越过边界的在途动作。当前纯核验结果不是授权令牌。
- 到期观察租约的本地路径已完成，版本/确认/完整性和 60/90 分钟限制保留；
  实际 status/fetch 通过最终发布保护，不让到期规则恢复 prepare/submit。
- 同对象同失败最多两次补救在实际新 Attempt 消费边界检查，不采用模型意图数替代。
- SCNet4/兜底排队2已确认按全部本机 study/轮次计数；取消额度交 T187。
- 并发消费、上传期间到期/暂停/失锁、批次部分成功、UNKNOWN 只读恢复、调度器延迟、
  阶梯第二份半节点占用、共享账号跨入口和崩溃恢复均有适配层回归，固定组合全量已通过。

### 离线验证记录（2026-10-29，未做现场验证）

- 实现提交 `e5b2daa6` 的独立 Python 3.11 环境，`pytest -q ag/tests skills-next`：7433 passed、144 skipped，
  538.59 秒；前后源码文件 SHA-256 一致。跳过包含本分支未集成的 T185/T187/T188
  实际接口以及原有平台/私有证据用例，不把这些跳过算作通过。
- 上述固定四源的 `pytest -q ag/tests skills-next`：8826 passed、26 skipped，669.32 秒。
  测试源码聚合 SHA-256 为 `8c90dbe3bc98e985bacb479e85644141c3253510fd62535e16c6678715282c17`，
  前后一致；实际 T186/T187 来源文件也无漂移。旧组合及完整复现包保留原样。
  全量包含九条完整/不完整取回补救、排队取消改投、跨 study 已停止占用以及第二后继拒绝；
  网络和时钟用合成替身，归属、取消消费、停止、准备与提交调用正式接口。
- 额外独立审阅证明 source 状态、已知输出和停止记录变更会使旧回执失效；缺停止
  证明仍保留占用。协调方独立组合子集另有 41 passed；所有离线结果均不替代现场证据。
- 只读配置身份入口实现提交 `dcf71f026ed9f35603803608185c1c22707d914e`：本分支
  `test_route.py` 为 143 passed、19 skipped；固定 T185/T187/T188 的新组合为
  237 passed、6.45 秒，无跳过。包含真实 T185 哈希变化/稳定性、无文件写入/传输、
  错误脱敏、缺模块、混用拒绝及旧模式兼容。新组合测试源码聚合 SHA-256 为
  `a00c4d59f0ca9ab1cc6e3cd85f3763ff3598f41946de415d31dd2b301ae79099`，前后一致，
  来源文件无漂移；协调方独立入口子集另有 24 passed。没有改动或重跑先前全量的冻结组合。
- 通用及私有词表敏感扫描：1910 文件、0 错误；扫描器自身 5 项测试通过，差异检查通过。

### 实际接线接口（开发中，供 T187/T196 组合核对）

- `autonomy.submission_guard(cfg, study, run_id, token, plan_sha256=...)`
  仅用于短本地事务；`.snapshot` 是重放后原始 state 的深拷贝。
  `.consume(record)`、`.dispatch_started(attempt_id)`、
  `.abort_before_dispatch(attempt_id, reason)`、`.pause(reason)`、
  `.waiting(object_id, record_sha256)` 写持久事件。它不允许持锁做远程 IO。
- `state.submissions[attempt_id]` 保存 `attempt_id/object_id/failure_class`、
  `ownership_sha256/round_id/run_id/plan_sha256/rule_sha256/max_attempts`，
  以及 `plan_id/at/dispatch_started/aborted_before_dispatch`。
  内部 `owner_token_sha256` 不进入公开状态。实际计数按 `round_id` 聚合此表，
  不读意图计数；abort 不退回本轮历史 Attempt 消费。
  prepare 不占提交次数；Attempt 上限与 90% 阈值只使用提交消费记录。
  这与原计划“按该规则实际提交的次数计数”一致，准备遵循随用随备。
- 原子消费达到 90% 即保存暂停；尚未 dispatch 的该成员停止并留下 abort，
  不将旧 guard 结果当成暂停后的通行证。已 dispatch 的在途请求不可撤回，
  响应丢失保留 UNKNOWN；晚到结果只能补确切绑定，不能恢复动作资格。
- `autonomy.boundary_failure(..., attempt_id, ownership_sha256,
  run_id=..., token=..., dispatched=..., reason=...)` 验证原消费归属，
  只记录既有后果及暂停，不发新动作。T187 必须另外核对实际取消条件，
  不能把此接口或待确认意图当取消授权。
- `autonomy_submission.write_reservation(..., verified_state=guard.snapshot)`
  保存完整摘要、输入/manifest/bundle 身份、规则/计划/轮次/唤醒和原始选择输入。
  `read_reservations` 双向核对共同登记、Attempt、summary、submission 与重放事件，
  返回可信 placements/batch_inputs；`verified_authorization(path, authorization)`
  用于既有调度响应的只读归属核验。模型输入的摘要或哈希不是替代证据。
- `study_key` 必填，来自逐段 nofollow 校验后的绝对 study 路径 UTF-8 SHA-256；
  共同登记另绑定目录 device/inode。规则、request、placement、wakeup、batch
  都核对此身份，`study_id` 仅作显示。换配置、同名根目录或移动目录不能清零。
- `manual_write_guard` 在 running 或仍有有效唤醒 lease 时拒绝；paused 且无有效
  lease 可接管写入，保留原轮次预算。实际操作期间保留专属 writer 登记，
  不长持全机或 study 状态锁；start/resume 与 writer 登记在同一短事务中互斥。
  到期接管须记录原 lease。这里只说明后端接口，前端投影由 T196 接入。
- 全机登记使用固定标准配置目录，与用户选择的配置路径无关。全机短锁为
  `autonomy-submit.lock`；既有每配置目录 `submit.lock` 继续保护旧提交/预算。
  自主动作固定按配置提交锁 → 全机登记锁 → study 状态锁的顺序执行本地核验、
  预留及消费，随后释放全机/study 锁才进行网络动作。其他状态操作只拿后两者。

### T187 原始实例接入点（2026-10-29，固定组合离线已通过）

容量与 UNKNOWN 找回的必要配套只需为三种既有固定只读构造器增加同名可选参数：
`remote.slurm_jobs(job=None, user=None, scheduler_cluster=None)`、
`remote.slurm_accounting(job, scheduler_cluster=None)`、
`remote.slurm_find(user, name, since, scheduler_cluster=None)`；实际签名保留现有
keyword-only 位置。None 保持手动旧命令；非空仅接收已冻结 probe/原始归属的实际
cluster，在固定命令中限定该目标，并清除会覆盖目标/筛掉账号作业的已核实环境项。
remote.py 由 T187 唯一实现，本分支不构造 shell 文本或新增配置方言。
T186 的 `status.inventory(..., scheduler_cluster=None)` 传该目标做三次提交额度
检查；`check_slurm` 从不可变原始归属取目标，传给队列、按名找回及确切作业记账。
UNKNOWN 找回时保存同一已发出固定命令的目标；不从未绑定的当前观察补认旧作业。
这是提交/额度/找回使用同一调度器的必要接线，不增加新的查询类别。
不完整 fetch 的两条既有终态查询也使用同一已核验目标，防止从另一控制器的同号
作业取得结束证据；其只读命令种类、人工路径及取回接受条件保持原有口径。

T186 已提供的准确边界是 `AutonomousSubmission.boundary(stage)`：在配置提交锁 →
全机登记锁 → study 锁内重新读取配置、规则、冻结字节、原始消费和当前租约；只有
`stage='dispatch'` 写入不可逆的 `dispatch_started`。远端调用在返回后执行。
原始归属摘要为 `run.reservation['sha256']`，原始记录为
`run.reservation['record']`，均已与 `state.submissions[attempt_id]` 交叉核对。
不得把调用者给的哈希或普通 `status` 当前观察当作原始实例。

实际接入使用 `status.slurm_submission_probe(cfg, path, transport)`，在 prepared 且
尚无 claim 时执行固定只读查询，返回 `{record, sha256}`，不自行发布到 study。
T186 在消费短事务里重新核验该原始字节、时间、manifest/bundle 与当前 owner，
把完整 envelope 存进不可变全机 reservation 的可选 `slurm_probe`，随后独占保存
Attempt 的 `slurm-origin-probe.json`（只含 canonical raw record），再 claim/consume。
旧记录没有该可选字段仍兼容；有字段的全局审计同时核对侧文件，缺失不能当未采集。
一次性 `submission.json` 保存 `scheduler_probe_sha256`，指向这份原始证据。

`autonomy_submission.verified_reservation(path, verified_state=raw_state)` 返回
`{record, sha256}`，核对共同登记、原始消费和摘要/绑定，只用于读取既有归属，不授新动作。
T187 真实 capture 签名为 `status.capture_slurm_origin(cfg, path, transport,
probe_sha256=..., ownership_sha256=..., publication=...)`。其零参数 publication factory
由 T186 observation_publication_guard 提供，并在 yield raw state 前重新调用
verified_reservation 核对原始归属。真实 `dispatch_started` 值为 `{'at': timestamp}`，
不是数字；初始采集必须严格读取这个已有事件，不改写 state 形状来迁就接口。

取得确切 job 后先保存 submission/status，额外采集失败保留已知绑定，不改为
未提交或再次提交。UNKNOWN 恢复不调用首次采集补认旧实例。T187 的独立
`remote.slurm_submit_bound` 只有在冻结 probe 的 bound-submit 候选成立时才使用，
固定实际 cluster 并禁用 requeue；回包省略 cluster 时只保存本次实际发出命令的
目标，不单凭 probe 推断。容量查询和 UNKNOWN 找回使用同一实际 cluster，
普通兼容路径继续保留原有行为。已知 job 后采集失败和负面资格已有定向组合回归；
上述固定完整组合离线已通过；现场验证尚未完成，未获现场授权。

26.05.5 候选格式与完整初始实例证据限制各自对应的固定目标提交、自主取消或改投
能力，不是所有普通兼容 Slurm 提交的新增准入条件。可预期的不支持版本须保存
对应新增能力不可用的结果，
不发送该版本不支持的后续查询，保留原已审阅提交能力。真正 SSH 失败或身份
矛盾仍暂停；额外证据缺失不得丢弃确切提交绑定或再次提交。

取消后的补救由 `autonomy_submission.remedy_evidence(cfg, verified_state,
object_id, exclude_attempt=...)` 接受 T187 正式消费/停止证据，并交叉核对确切
源归属、作业和取回文件；普通 fetch 与带明确来源的不完整 fetch 均须覆盖。
无进展的 canonical failure 不允许通过换猜测或省略 failure 参数重置次数。
已验证改投则单独保存原谱系及一次改投资格，仍消费本轮新 Attempt 预算，
不伪装成普通失败补救。上述正式接口的定向及固定全量组合已通过，现场验证仍待完成。

当前取消与停止接口分开（仅据组合源码，非现场结果）：`cancel.autonomous_cancel`
接受取消后返回 `stopped=False`。T187 提供 `cancel.verify_stopped` 和
`autonomy_cancel.verify_slurm_stopped`；定向组合已走正式 API 验证取消 → 确认停止 →
完整或不完整取回 → 补救后继准备/提交，以及排队取消后的独立改投准备/提交。
定向回归和固定源码全量的结果分别记录，均不替代现场证据。普通 numeric-job status 不能替代
确切实例停止证据，T186 不用取消回包直接开启新 Attempt。

已接入原范围内的独立改投后继：由 prepare/submit 的
`--reroute-source <原Attempt>` 指明唯一来源，与 `--failure-class` 互斥；实际证据
仍从 T187 不可变取消消费、接受回执、停止记录以及当前计划/对象读取。该参数不是
许可，也不能输入自由 JSON。新 reservation 保存独立 reroute_source；原来源若已是
改投后继，或全机归属已存在其后继，则拒绝，Attempt 改名不能重置谱系次数。
新资源由 T185 同算法精确来源参数重算，原提交消费保留；旧占用仅在正式停止证明
核验后释放，调度器仍报告活动时继续计入。
科学输入比较只允许已核验 Gaussian 的 `%nprocshared`/`%mem` 两项资源变化，
调度脚本由新 Attempt/资源重生成；其他输入与附件字节、程序参数和科学摘要均须相同。
不改写原输入、不接受放宽输入或父 chk 依赖，准备不消费预算，实际新提交仍消费一次。
以上已实现并通过定向及固定全量组合；尚未完成现场验收，也未启用自主运行。

停止记录参与全机名额核验时也不得在短锁内重解析调度器证据。准确配套接口是
`prepare_stopped_reservations(cfg, states=None)`（锁外，只读）返回内部
PreparedStoppedReservations；随后 `read_reservations(..., prepared_stops=receipt)`
及 `route.autonomous_selection(..., prepared_stops=receipt)` 在短事务中只核对
当前真实消费/取消结果与来源文件身份。存在 stop 文件但未提供 receipt 时拒绝，
不在锁内隐式解析、不按缺失当零。T187 的取消候选评估也须在自己的短事务前准备
该 receipt 并透传，以免早先已停止作业阻塞全机四个/两个名额；全机新增/变更证据
仍须在每个实际动作边界重查。prepare_stopped_reservations 不创建登记或执行网络。

此前 T187 单元夹具在隔离授权依赖前使用手写 authorization，触发 T186 正式核验；
另有缺少 T185 的场景未显式隔离已组合的接口。T187 已在所属分支修正，固定
`80e95993` 包含这两处隔离，组合全量通过。T186 没有弱化正式核验或改写上游测试；
九条端到端流程继续使用真实消费、停止及后继 API。

### 首次配置与本地整理入口（2026-10-29）

为解决首次计划/规则均需 `routing_sha256`、原 route 又先校验计划/规则的闭环，
新增 `ag route --config-identity --json`。它只读取本地配置并调用 T185 同一
`ladder_config_identity`，只输出精确哈希；无须 study、计划、规则、租约或模板/档位。
拒绝与选择参数混用，不查询远端，不创建 registry、锁或 monitor 文件，不输出
账号、主机、路径或入口名称；缺 T185 算法明确拒绝。该小入口在上列冻结全量后补齐，
采用新的临时组合做相关定向回归，旧组合及其证据保持原样。

另经只读核查：`study.md` 仅有 init 初次创建，没有受 owner 保护的正式文本更新入口；
独立 facts CLI 无 owner 参数，仅有手动 writer 保护，running 时拒绝；review init、
review manifest、mode-review 无 owner/manual/publication 保护。fetch 后 auto_facts
及 autonomy scientific-review 有 owner 最终发布，但后者不生成 mode 报告或更新
review.md/study.md。这些整理入口的补齐由协调方另行安排，不扩本单源码范围，
T190 卡片不得把它们写成已经支持的自主写入能力。

### 非研究真实验证草案（未执行、未获批准）

候选仅为合成水分子，电荷 0、多重度 1、无手性；方法为验证用兜底方法，
不构成研究结果。建议先审阅下列确切 UTF-8/LF 输入（末尾保留两个换行）：

```text
%nprocshared=8
%mem=10GB
%chk=water.chk
# B3LYP/6-31G(d) Opt=Tight Freq Int=UltraFine SCF=(XQC,Conver=8)

T186 water validation

0 1
O 0 0 0
H 0 0 1
H 0 1 0

```

输入 SHA-256：`734a7d6f671b18f236776856323c8ea671bab32aafd23fde262ae96a9e45faa5`。


候选资源为 8 核、档位内存 12 GB、Gaussian 内存 10 GB、walltime 00:30:00；
仅当最终阶梯确切选中该资源才使用。最终所选资源不同须另存新候选、重新计算输入及
bundle 哈希并审阅，不在执行时修改已批准字节。没有选定真实入口、节点或写入真实规则。

本地准备命令草案（各一次；须待最终接口确认后才纳入批准包）：

```sh
ag init water-validation
ag prepare --study water-validation --template gaussian --input water.gjf \
  --tier simple --walltime 00:30:00 --label plan-bound \
  --method-basis '兜底方法：仅合成水分子提交链路验证' --json
```

正式批准包须追加最终源码完整 HEAD、选定入口/节点/阶梯证据、最终 prepare 命令、
不可变计划和规则草案/哈希、Attempt ID、冻结输入和 bundle 哈希、完整摘要，
以及自主提交确切命令。当前已实现 `--autonomous-policy`、`--run`、`--token`、
`--plan-sha256`、`--object-id`、`--job-class`；批准包必须填入最终绑定值，
不能以旧 `--policy` 或占位符代替。
拟允许一次自主提交；只读 status/snapshot/fetch 按最终命令包逐项列次数，
最低一次读取确切提交绑定和一次取回核验。到期/方法/网格/节点/计划/上限六类
各一次无提交拒绝检查，均须在相应远端副作用之前失败。

预期：只有计划匹配的一个候选提交一次；摘要/声明/归属/journal 可交叉核验，
取回字节校验通过。拒绝测试无新远端目录、上传、提交或取消。
任何 UNKNOWN、哈希不一致、SSH 报错、异常结束或不确定结果立即停止并报告，
不重试提交、不取消或清理远程文件。当前未连接集群、未提交、未部署；
因最终组合、现场参数和规则尚未核验，本草案不是可执行批准包。

### 预算结算发布保护补充授权（2026-10-29）

负责人确认原话：**“允许补齐预算结算保护（推荐）”**。
据此新增允许改动 `ag/src/ag/budget.py` 的 `settle()`，仅增加可选的发布钩子，
并在已允许的 `status.py`、`test_autonomy.py` 接入和验证；预算算法、手动行为
及其他预算入口不因此扩展。

准确接口为
`budget.settle(cfg, m, elapsed=None, *, rejected=False, job_id=None, publication=None)`。
`publication` 是无参上下文工厂；`settle()` 先取得既有配置提交锁，再进入工厂，
在其内执行原有台账读取、绑定核验与写入。自主工厂使用
`autonomy.observation_publication_guard`，锁顺序保持配置提交锁 → 全机短锁 →
study 短锁；等待配置锁期间不持后两者，网络和调度结果解析均在这些事务外。
省略 `publication` 时保持原有手动结算语义。

Slurm 终态先用此接口完成结算，再以独立的发布事务重新核验观察资格，
写入状态和对应 journal。等待配置锁时超过 60 分钟或发生 90 分钟接管，
旧会话不能写预算或状态。两次事务之间失去资格时，已合法完成的结算保留，
最终状态拒绝发布；不回滚已确认的台账，也不把此前检查当作后续写入许可。

离线测试使用合成台账、固定时钟、Fake 调度器及真实本地配置锁，覆盖上述
等待期间到期/接管、正常两次发布，以及已合法结算后到期/接管的拒绝分界。
没有连接真实集群，没有修改真实配置或启用自主运行。
