# Auto-G16 publisher pilot R4：Controller/Transport 职责最小修正

**候选，非激活、非生产权限。** 只修独立 R3 复核发现的依赖越界；R1/R2/R3 原文件全部保留。与 [R3 接口补丁](publisher-pilot-candidate-r3-interface-delta.md)及 [R3 schema/版本附件](publisher-pilot-r3-schema-and-versions.md)合读，本文件对冲突条款优先。没有修改 repo、运行测试或连接服务器；不从 prototype 推导正式合同，也不宣布发现已关闭。

## 1. 明确撤回 R3 的三个 driver 依赖

撤回 `_RTWinProgramEffectDriver` 的 `pilot_runtime_store`、`pilot_approval_store`、`pilot_confirmation_id` 三个拟议参数及所有 driver 内 `load_current_operational_confirmation/assert_current` 操作。这违反 [boundary:27–32](../../../docs/v3/boundary-spec.md) 的 Transport 依赖方向；现有私有 successor composition 例外不能据此扩成 Transport 读取 Core/Approval。

**全部留在单 pilot Controller：** 读取三批准、Operational Confirmation load/assert、解释 `confirmer_evidence.publisher_pilot`、核验真实 Owner 接受/部署附件语义、`validate_effect_authority`，然后调用唯一 `execute_once`。Driver 不接收 Approval/Core 对象、confirmation ID、`approved` 标志、验证回调或所谓已接受 token。

## 2. Driver 只读一份固定 deployment basis

复用当前 `_driver._resolve_closed_profile_authority(...)` 及其 `_DeploymentAuthority` 结果，作为当前 resolved profile/effective config/bootstrap/manifest 的既有机械身份依据。[driver:109–110、387–421](../../../auto_g16/transport/_driver.py)

拟在 `_program_rtwin.py` 内增加私有 `_read_fixed_publisher_deployment(authority, snapshot)`；`authority` 是上述现有闭合结果，snapshot 是允许依赖的公开 Execution record。它只使用标准库读取/比较下面的单 pilot deployment basis 与 Q，不调用 Approval、Core、Observation 或科学评审。**不必改 `_driver._DeploymentAuthority` dataclass、原四键 runtime qualification 或 `_driver.py`。** 新内容是这个既有 authority 旁的有限部署附件，不是给通用 manifest 宣称它原本已有 Q 资格。

### 固定来源及安装 owner

- 已获 exact Gate 的部署操作者先核验 Owner exact-Q 接受、原始 probe 和本次 code/profile/snapshot，再在**既有受审 controller 部署目录** create-new 安装固定 basename `v31-publisher-pilot-deployment.json`、Q 和原始证据；保留无覆盖的安装回读。该目录/文件的词法路径及物理身份随本次已受审安装包固定，实际值当前 `NOT_ACQUIRED`。
- Reader 的唯一 locator 来自该已安装且受审的本地部署配置；不能来自 Q、Confirmation、caller 参数、`current_profile` 的任意路径字段、CLI/env 或“最近文件”搜索。目录/配置未被实际固定部署时，该 reader 不可用、production 继续拒绝。离线测试的固定临时根仅在候选 harness 中存在，不成为可配置 production root。
- Driver 在读取时验证这份已固定安装配置、父链/文件身份和对应 bytes；部署操作者/Owner 负责人工来源判断，reader 只比对已部署 expected 值。只改 Q/Confirmation 自述不能修改这个独立安装事实。可信安装域本身被恶意同 UID 攻陷仍按原 threat model 排除，不引入签名服务、权限平台或新的防回滚日志。

### 最小闭合 basis 内容

沿用 R3 附件的 `H/G/S/Path/Node/Window` 类型与 canonical grammar，basis ≤64 KiB，精确字段如下：

```
{
  schema: "auto-g16-v31-publisher-pilot-deployment/1",
  source_commit: G, source_tree: G,
  resolved_server_profile_id: S, effective_config_sha256: H,
  program_execution_snapshot_id: S,
  qualification_payload_sha256: H,
  qualification_file_sha256: H, qualification_size_bytes: P,
  qualification_path: Path,
  qualification_parent_chain: [Node], qualification_file_identity: Node,
  probe_evidence_manifest_sha256: H,
  owner_q_acceptance_evidence_sha256: H,
  pilot_live_gate_evidence_sha256: H,
  pilot_window: Window
}
```

`qualification_size_bytes` ≤1 MiB；链覆盖根至Q父目录，身份同时比较device/inode与另外的size/hash。schema未知/多键/缺键/不规范/超界拒绝。basis不含批准对象、decision、accept/revoke状态或自身hash。Q与原始证据文件在固定部署包中按安装清单查找，不能按文件内容改道。

它是**新且必要的有限部署来源附件**：现有 `_DeploymentAuthority` 只闭合profile/runtime/bootstrap，缺少已安装的expected Q路径/物理身份/来源hash；仅增加此机械数据，无新长期权限记录。basis中的 snapshot/profile IDs 与当前公开record/authority比较，Q与profile/material比较；源码与受审安装版本及内建source比较；时间窗口与当前可信时钟比较。Driver 对Owner/LiveGate证据只核对原件hash，不解析人的批准语义。

## 3. 与既有 confirmer_evidence 的无循环关系

Controller读取**同一份独立安装basis**与原始证据，再解释并核验 Owner接受、LiveGate及其具体范围。Operational Confirmation 的原11键 `publisher_pilot` 附件保留：其中 `deployment_readback_evidence_sha256` 在本 R4 明确定义为上述 **basis canonical文件的普通 SHA-256**（该文件包含Q安装回读的expected身份）。其他Q/path/来源hash/窗口必须逐字段等于basis；无必要增加公开schema或第12个字段。

顺序是 `Q → final profile/material/snapshot → 安装basis（含该snapshot ID）→ 人工Operational Confirmation（引用basis文件hash）`。basis不再被加入profile.runtime_contents或snapshot内，不引用Confirmation ID或自身hash，因此无循环。Q仍通过profile/snapshot进入原批准链；basis的精确身份由独立受审安装与Confirmation两处绑定。不能把basis自述hash当安装来源，也不能由driver确认“人已批准”。

## 4. 修正后的实际顺序与失败语义

| owner/入口 | 实际职责与顺序 | 失败边界 |
| --- | --- | --- |
| `_run_first_publisher_pilot` | 固定部署包/三库绑定→加载三批准与current Confirmation→`assert_current`→basis/Q/原件及附件**语义**核验→现有`validate_effect_authority`→准备port→紧邻execute再次读/核验三批准及附件→`execute_once`。 | Q来源、附件、批准或PLANNED检查失败：零execute、零claim、零外部effect。脚本不自签批准。 |
| `_prepare_first_publisher_pilot_port` | 使用原driver三个constructor参数 `snapshot,current_profile,program_transport_store`；不再传Core/Approval依赖。factory不进行claim/driver效果。 | constructor资格不符在进入execute之前拒绝。 |
| `_RTWinProgramEffectDriver.__init__/_authority` | 新production tuple才调用现有profile authority解析，随后固定basis/Q reader；只作source/身份/profile/material/窗口机械复核，保留descriptor，必要边界再次比较。旧strict/synthetic契约保持。 | before-claim失败零claim/effect；execute内prepare阶段仍在claim前。claim后漂移只停止后续效果并留存已有claim/receipt，不能声称回滚成零claim。 |
| `execute_once` / 既有program continuation | 原七参数公共入口只接受Controller刚验证的confirmation snapshot ID；它仍是唯一Core claim/WINNER/continuation owner。 | 不由新脚本或Transport直接claim/qsub，不自动retry。 |
| 后续生产collector/promotion | Controller核验该pilot剩余作用域/附件，组合层闭合durable前驱；driver重新核对同一固定basis/Q和当前profile。三批准的PLANNED专用validator不挪到已提交阶段。 | 缺失/漂移/超出窗口拒绝新效果/新promotion，历史状态与合法synthetic完成不改。 |

任何host资格事实仍由新production wrapper实际节点guard闭合；部署basis不能替代计算节点观察。所有首次显式选择/持久回放tuple、旧source bytes、Q逐层schema与P01–P08仍以R3附件为准；不因修依赖新增probe/长期机制。

## 5. 两个非循环细节的精确澄清

**profile basis 使用真实的 `_identity_payload`，不能混用 `semantic_payload()`。** [models:388、420–435](../../../auto_g16/execution/models.py)显示前者是保留的原始身份输入；后者额外携带最终 resolved ID，且没有 `ordered_config_content`。在 Execution 私有材料/身份验证中先调用 `resolved_profile.assert_identity_closed()`，从 `resolved_profile._identity_payload` 复制完整映射，要求精确键集为 `server_profile_id,profile_revision,transport_kind,target_identity,remote_user,remote_root,platform_paths,ordered_config_content,runtime_identities,effective_config_sha256`。仅删顶层派生 `effective_config_sha256`，并只从复制的 `runtime_identities` 删除唯一 `v31-publisher-qualification-v1.json`（制包前可尚不存在），其余项包括顺序化 config 内容及新revision全保留；对不可变 typed 投影调用现有 `semantic_sha256`。不修改原对象，不加入最终 resolved ID，不用散落属性手拼漏字段的摘要。

这个投影归 Execution 的私有 snapshot/material闭合验证；Transport 通过公开 `snapshot.assert_identity_closed()` 及现有 profile authority解析、Q/profile/material精确身份比对复用其结果，不新增对私有 Execution helper 的反向依赖。候选自洽Q+observation也必须与真实输入profile/runtime逐字段一致，不能互相自证。这里是落实R2/R3已有identity-payload规范意图；没有从prototype接受新的字段/算法。

**P08 必须是与最终 Q 无关的先验组合验证。** `Q.payload.controller_probe` 只引用已冻结摄入/编排源码在独立、预先固定的合成Q/部署/Confirmation fixtures上的惰性测试证据；不得依赖正在签发的最终Q、其最终profile/snapshot、实际安装basis或最终Confirmation。最终 exact-Q 的安装回读、真人批准和本次运行前的validator结果留在Q之外的deployment/Confirmation证据中，绝不反写Q或其P08 evidence hash。因此顺序是 `冻结源码+先验fixture/P08 → Q → final profile/snapshot → basis → Confirmation`，没有Q→自身验证hash的环。

## 6. 精确 delta 与复核状态

仅候选文档delta：删除 R3 driver 的3个Core/Approval依赖；将其load/assert及附件语义全部留在已有拟议单pilot脚本；点明在 `_program_rtwin.py` 复用现有 `_DeploymentAuthority` 再读取有限独立basis；精确澄清identity projection和P08无循环含义。产品拟改路径不新增 `_driver.py`、Core或Approval模块；之前已指出的单pilot脚本与精确验证归属仍属未来正式接入候选，不进入当前prototype。

独立reviewer已确认R3依赖P1；本 R4 是该发现的**待复核修正**，不是自判closed。production hard stops保持原样，真实目标/部署值仍NOT_ACQUIRED；现有授权的隔离离线prototype继续，但不承担生产授权。
