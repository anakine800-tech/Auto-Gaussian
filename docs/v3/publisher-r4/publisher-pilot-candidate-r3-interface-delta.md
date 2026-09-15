# Auto-G16 V31 首个 publisher pilot：R3 最小编排接口补丁

**候选，非激活、非生产权限；只读设计，无 repo 修改或测试运行。** R3 审阅包由本文件及 [R3 闭合 schema/版本附件](publisher-pilot-r3-schema-and-versions.md)组成，与 [R2](publisher-pilot-candidate-r2.md)合读；冲突以 R3 两文件的明确 delta 为准。本补丁替换 R2 对“现有 Controller 已核验来源、缺附件 driver 会拒绝”的不完整表述；附件替换其未闭合 Q 与混写的新建/重放规则。当前离线 prototype 已获开发授权，但其代码与 fixture **不承担生产授权**。

## 1. 经源码核对的真实缺口

- [execute_once:433–452](../../../auto_g16/execution/runtime.py)保持七参数接口（含 store）；只比较 `confirmed_execution_snapshot_id` 与 snapshot，并检查 profile/准备 port。它不接收或查找三批准对象。
- [validate_effect_authority:725–779](../../../auto_g16/approval/models.py)已经支持 `ProgramExecutionSnapshot`，检查当前 Core Attempt/plan、Scientific Approval、exact Batch member 和 Operational Confirmation，要求 Attempt 为 PLANNED。当前 `auto_g16` 中只有其定义/导出，没有实际 Controller 调用；现有 [测试专用组合:173–219](../../../tests/v3/transport/test_v30_a_synthetic_composition.py)才示范 validator→execute_once。
- [ExactOperationalConfirmation:574–605、610–629](../../../auto_g16/approval/models.py)支持 `confirmer_evidence`，并将其纳入 authority ID；`assert_current` 只核对身份、snapshot/current Core 与 APPROVED 决定，**不会解释 Q 附件或证明其来源**。所以仅把附件放进该 mapping 或把 snapshot ID 传给 execute_once，都不足以完成所需资格核验。

## 2. 命名一个单 pilot 编排入口，不新增 execution owner

拟议入口：`scripts/run_v31_publisher_pilot.py` 内 `_run_first_publisher_pilot()`，只处理一个预先受审的 pilot 部署/运行包，不做 daemon、任务队列、通用 Controller 或自动恢复。此脚本是**尚未实现的生产接入候选**，不属于当前仅 tests/候选外 prototype 的实施范围；记录这个实际接口缺口不需要再次请求原型开发授权。

受审运行包由已有部署/Live Gate 流程绑定：精确 code、Core/Approval/Transport 数据库及 profile/snapshot 身份、三批准 record IDs、固定 Q/证据路径、输入/script bytes、唯一 Attempt、有限 effects。包的根路径与身份由该次受信部署入口固定；不能从请求中任意指定另一个“已批准”数据库、Q、确认者或 Gate 文件。运行时只读取已存在的批准记录，**不调用 `for_snapshot(..., decision=APPROVED)`、不自行签发三批准，也不因其默认值为 APPROVED 推断用户批准。**

### `confirmer_evidence` 的一次 pilot 附件

通过既有人工确认/持久化流程，在 `confirmer_evidence["publisher_pilot"]` 中保存本次闭合映射，拟定字段：

`qualification_payload_sha256`、`qualification_file_sha256`、`qualification_size_bytes`、`qualification_path`、`qualification_parent_chain`、`qualification_file_identity`、`probe_evidence_manifest_sha256`、`deployment_readback_evidence_sha256`、`owner_q_acceptance_evidence_sha256`、`pilot_live_gate_evidence_sha256`。

字段语法见 R3 schema 附件，并增加单 pilot 的 `pilot_window`；path/parent chain/file identity 来自已批准的 create-new 安装与实际回读，不从 Q 自述提取。附件不含 `qualified/approved` 布尔值；Attempt/snapshot/profile 由既有 Confirmation 自身绑定，不重复签发新 token。它的 hash/reference 必须与受信部署包内的原件核对；附上一个自写的“Owner 接受”JSON 不等于取得 Owner 决定。材料的信任仍来自原有受审人工确认和安装流程，不由新脚本制造。

拟议纯比较 helper `_validate_pilot_qualification_evidence(...)` 核对附件完整性、安装原件/probe 清单/Owner exact-Q 接受引用、已读 Q canonical bytes、profile runtime identity、material/Q 和当前主机适用性证据。它返回正常或抛错，**不产生权限对象、不把返回值当授权开关**。该新增附件语义核验与通用 `validate_effect_authority` 各有职责，不能互相替代。

## 3. 精确调用顺序（一次新提交）

1. 绑定受审 pilot 包、当前代码与三库物理身份；从既有 `SQLiteApprovalStore.load_scientific_approval`、`load_batch_submit_approval`、`load_current_operational_confirmation` 读取指定记录；从 Core 读取其 exact Attempt/plan。snapshot 由已有受审准备步骤产生，不让编排入口临时选择科学参数或重建一个替代 Attempt。
2. 核对当前 profile/部署/Q 固定文件、原始 probe/安装/Owner 接受附件与 separately authorized 当前 Project/runtime/调度范围证据。调用 `_validate_pilot_qualification_evidence`；固定 Q 文件使用 no-follow 父链与保留描述符，内容/物理身份必须同时匹配。此阶段资格不满足即停止，不构造可用 production port。
3. 调用**现有** `approval.validate_effect_authority(runtime_store=..., attempt=..., plan=..., displayed_semantic_meaning=..., scientific_approval=..., batch_submit_approval=..., execution_snapshot=snapshot, operational_confirmation=confirmation)`，传入全部八项真实读取对象；异常则零 execute/claim/qsub。
4. 通过拟议私有 `_prepare_first_publisher_pilot_port(...)` 构造 exact `_RTWinProgramEffectDriver` 和既有 `_ProgramExecutionPort`；前者重新读取/核对第 4 节所述 Q/confirmation 依据。factory 不调用 effect 方法或 Core claim。
5. 在唯一 execution 调用前再次读取 current records 并调用同一 validator，复核本次 Q/附件/身份。正常返回后连续调用**现有** `execution.execute_once(...)`，`confirmed_execution_snapshot_id` 只取刚核验的 `confirmation.execution_snapshot_id`，原样传 input/script/current_profile 和 exact private port。不得传 caller 独立字符串充当确认。
6. Core claim、WINNER 分派、one-use continuation 只由 `execute_once` 现有代码承担。[runtime:476–493](../../../auto_g16/execution/runtime.py)及 [program_runtime:1345–1369](../../../auto_g16/execution/program_runtime.py)不重写。脚本不得调用 `record_submission_intent`、伪造 continuation、直接 `_execute_claimed_program` 或直接 `submit_qsub_once`。

两次 validator 都发生在 PLANNED 阶段，不能把它移到 Core WINNER 之后再调用。首次检查与最终检查之间不允许人工停顿、后台调度或改材料；任何等待/变更后从当前读/验证重新开始。未知/异常或进程中断保留证据；该入口不循环重试。再次启动看到非 PLANNED 即停止并转原有另行授权的 reconciliation/read 路线，不把 validator 的 PLANNED 限制改成通配状态，也不把本脚本包装成新的 replay owner。

## 4. Driver 如何取得固定部署 Q 依据

拟议在私有 `_RTWinProgramEffectDriver` 增加仅此 production 分支使用的显式依赖：`pilot_runtime_store`、`pilot_approval_store`、`pilot_confirmation_id`；均指向第 2 节固定部署包绑定的既有对象/ID，**不是新 bool、capability 或 accepted token**。strict 及旧 synthetic 构造行为不变；receipt production 缺这些依赖继续 `publisher-not-qualified`。这是一个必须明确审阅的私有接口增量，不暗称当前 constructor 已支持。

Driver 从该 ApprovalStore 重新 `load_current_operational_confirmation(id, snapshot)`，并显式调用 `confirmation.assert_current(pilot_runtime_store, snapshot)`。它从 `confirmer_evidence.publisher_pilot` 读取路径/安装身份/证据 hash，但不能仅信该 mapping：还要调用拟议 `_load_fixed_pilot_deployment()` 取得**独立安装的 expected 值**并逐字段比较，然后按那个已受信路径读 Q。

`_load_fixed_pilot_deployment()` 的输入位置是本次受审安装包预先绑定的唯一绝对路径/父链/文件身份；不接受 CLI/env/Q/confirmation 提供的替代位置。部署操作者负责先核验原始 probe、Owner exact-Q 接受、code/三库/窗口及固定 Q 安装回读，再把 expected 值写入一次性的安装附件并只读部署。实际路径及物理值仍 NOT_ACQUIRED，必须随该次部署工件一起审定；helper 缺少这个已安装绑定即拒绝，不能搜索“最近”文件。它与编排入口共享同一固定来源规则，不是现有 `_DeploymentAuthority` 已有的字段，也不是新长期 registry/token。

安装附件包含与 confirmation 子映射一致的 expected Q/path/证据 hash/窗口，以及本次代码/三库绑定。机器检查原件内容/hash、安装物理身份、与 Confirmation 的一致性及现有记录当前性；**人负责判断真实原始证据支持资格并接受 exact Q**，不能由机器把 `Owner` 文本或 hash 自动升级成人的接受。篡改 confirmation 内路径/Owner引用，即便重算合法 ID，也因不同于这个独立安装附件而在 constructor/final preclaim 检查拒绝。原件/expected 同被攻击者改写属于受信部署域被攻陷，依既有 threat model 不声称可防。

与同一 snapshot profile/material 中 Q bytes、固定 installation readback 和完整附件闭合后，保留 Q descriptor 与物理身份用于 `_authority` 的每次重新比对。任何运行时 Q/helper 都不签发新权限。

Constructor 与 `_authority` 都核对上述来源和 snapshot/current-profile，不因任意 dataclass 对象或 hash 相同就认定通过。首次生产调用由第 3 节三批准验证约束；提交后的 driver/current confirmation 身份比对不再调用要求 PLANNED 的三批准 validator。后续 collector/promotion 仍要此 exact pilot driver、durable job/workspace/receipt 前驱和合格 Q；旧 raw history 读取不依赖新 Q。

**信任限度必须说清：** 一份 ApprovalStore 记录或安装文件的 hash 不能自行认证人的身份。此单 pilot 的可信起点是已受审部署/人工批准流程对 code、数据库、固定路径与 original evidence 的绑定；driver 只是重放这个绑定。我们没有新增“所有任意 Python 调用都无法绕过 Controller”的 API 级权限防火墙，也不能声称现有 execute_once 自带三批准验证。任意未受审调用此库不能被纳入本 pilot 生产许可；保持原同 UID/受信组件威胁模型。若要求对不可信库调用者强制执行这条链，那是另一个 execution/security contract，不在本补丁中偷做。

## 5. R3 最小 delta、验证与 prototype 界线

| 相对 R2 的新增/纠正 | 精确范围 |
| --- | --- |
| 从口头 Controller 变成有限入口及真实调用 | 新候选 `scripts/run_v31_publisher_pilot.py`，只做第 3 节编排；不改 `execution/runtime.py` 的七参数接口/claim owner，不改 `approval/models.py` 或 public Approval schema。 |
| 从任意附件变成有语义的既有 confirmer_evidence | 一次 pilot 子映射、读取原件并核对的私有 helper；不新增 Q 接受/撤销日志或 token。 |
| Driver 资格来源可追溯 | `_program_rtwin.py` 的上述三个私有依赖及 current confirmation/Q 重新读取；factory 和证据 helper 可放同一私有模块，拒绝从纯 completion helper 反向 import Transport。 |
| 覆盖实际调用缺口 | 未来新增 `tests/v31/transport/test_publisher_pilot_orchestration.py`：任何三批准/附件缺失或错配都零 execute/claim；真实 validator 被调用，stub 掉它不算通过；只有验证后的 confirmation ID 传 execute_once；重复启动非 PLANNED 停止；driver 缺固定依据拒绝；成功惰性组合唯一现有 execution owner。 |

新脚本的验证 owner 映射需要在正式接入候选中明确补入 `config/validation-selection.json` 的精确路径路由；沿用已有 tests/v31/transport owner，不重命名 required checks 或更改 runner。**当前 prototype 要求 auto_g16/冻结合同/CI 全不变，故不能趁 prototype 写入这个 script/产品接口/路由变更。** prototype 可以用测试专用候选 helper 和惰性 harness 先验证上述顺序与反例；即使通过也不构成 Q 接受、production 接入、安装或 live 权限。

R2 两个真实难点不变：实际主机必须由受信调度范围与 production wrapper 本机 guard 闭合；旧 scheduler/material/B/source 配对原字节回放，新配对独立版本分派。R3 没有以编排脚本代替它们，也没有改变无覆盖、至多一次提交、UNKNOWN 不重试与所有历史保留要求。
