# Auto-G16 V31 PBS/xTB publisher：首个有限 pilot 资格契约 R2

**候选，非冻结、非激活、非生产权限。** 基线仍为 `3116d1f1919eff164ef3593171d0ed7f42c778b5` / tree `32fe6df47c947988311497fbd4b2de75d97c1a34`。本 R2 是新的完整审阅文本，取代 R1 的长期接受/撤销日志、递增序号锚和“accepted-context”权限机制提议；R1 与其补充原样保留。仅限现有 PBS/xTB receipt v3 的一个明确 fresh Attempt；不扩其他程序/backend。

## 1. 首个 pilot 能复用什么，还确实缺什么

[冻结 boundary:5260–5276](../../../docs/v3/boundary-spec.md)要求 qualification record、可信摄入、actual target 与每个 eligible execution host 的资格，不要求另建权限平台。

可以复用：profile 的 runtime_contents 身份链、受审 deployment 的精确字节与安装证据、当前 Project/runtime attestation、Scientific Approval、有限 Batch Submit Approval、exact Operational Confirmation、现有 Live Owner Gate 和 WINNER/REPLAY 机制。Operational Confirmation 已覆盖 snapshot 的 profile/target、workspace、input/script、adapter 等，变化使确认过期；Controller 在效果前重放三项批准。[boundary:237–274](../../../docs/v3/boundary-spec.md)。私有 program port 明确不是 approval owner，现有 one-use continuation 仍由公开入口转交。[program_runtime:1267–1299、1345–1369](../../../auto_g16/execution/program_runtime.py)

**确实缺的只有两类接入证据/行为：**

- 当前 manifest/runtime qualification 没有证明 production wrapper 的 actual-host/mount 发布资格；需要私有 Q 和读取/比对它的窄实现。
- profile resolver 能给任意非秘密 runtime bytes 计算身份，却不证明这些 bytes 是谁采集、审阅和接受的。必须通过已受审的 deployment/批准流程核对 Q 的来源；Q 自己的 `PASS`、hash 或 caller JSON 不构成资格。

R2 不新增接受/撤销服务或权限 record。若已有 deployment 交接尚未记录 Q 的来源，只补**一次性的资格证据附件**：原始 probe 清单 hash、Owner 对 exact Q 的接受原话及身份/证据引用、安装操作者、固定摄入路径/物理身份和回读 hash。它是已有 deployment/Operational Confirmation 的审阅材料，不是可单独传入 driver 的授权 token；不改变公开 Approval schema。后续详细实现若发现现有审批接口无法附带或核对这份证据，应先指出具体接口缺口，不推导出新权限子系统。

## 2. 私有 Q 的最小身份与可信摄入

### 2.1 Q：资格事实，不是执行许可

信封只含 `payload`、`payload_sha256`；payload 闭合字段：

| 字段 | 内容 |
| --- | --- |
| `schema, contract_sha256, scope` | 拟定 `auto-g16-v31-publisher-qualification/1`；最终规范 hash；固定 PBS backend、xTB adapter v3/receipt mode、现有 single-point/optimize 操作范围。 |
| `implementation` | 经审阅的 source commit/tree，production wrapper 与有限 probe source 的 SHA/size。source 不含 Q 或其 hash。 |
| `profile_basis_sha256, runtime` | 无 Q 的 profile basis 语义 hash；manifest-v3、server_python、xTB executable、runtime-data manifest 的既有路径/内容身份。 |
| `execution_domain, hosts` | 已认证 PBS 范围观察的证据 hash、确切 queue 和有限 eligible host 集合；每主机唯一 machine/boot 身份、实际 namespace/mount/文件系统与 root 父链、Python/xTB/data 物理身份和该主机 probes 的证据 hash。Q 不含可执行命令。 |
| `observation_window, evidence_manifest_sha256` | 可信采集起止 UTC 和完整原始命令/结果/工具链/主机/scratch 身份证据清单。强制案例缺失、未知或跳过均不能签发有效 Q。 |

采用闭合 canonical JSON（UTF-8、排序键、紧凑编码、末尾一个 LF），`payload_sha256 = semantic_sha256(payload)`；整份 Q 的普通 SHA/size 另用于 profile runtime identity。拒绝额外/重复键、错误类型和隐含缺省。Q 无最终 profile ID、snapshot/Attempt/job/receipt ID，避免自引用。精确实机值和未取得字段当前全部为 `NOT_ACQUIRED`，这不是可实际加载的有效记录。

### 2.2 唯一有限的摄入流程

1. 获准的 qualification operator 用受审固定 probe 从真实 eligible hosts/实际 mount 采集原始证据；独立审阅后，Owner 明确接受 exact Q。采集/接受并不创建 live Attempt。
2. 受审 deployment 流程在现有受控本地证据区以 create-new 方式安装 Q，指定此次 pilot 唯一固定只读路径，记录 no-follow 父链/文件身份、内容 SHA/size 和回读结果。路径与安装记录由该 deployment packet 预先确定，不从 Q、执行请求或环境变量选择。原文件留存，不覆盖、替换或清理。
3. 首个 pilot Controller 将原始证据、Owner 接受和安装回读逐项核对；新增私有 Q reader 只读取该固定文件、保留描述符/身份并在使用边界复核，与 current profile 中 exact Q bytes/hash、snapshot 嵌入 material 一致。**这个 reader 只证明已选文件与记录相符，不签发新权限。** 准备 driver 不授权执行，所有效果仍走现有三批准/Live Gate/公开 execute_once 与 WINNER 链。
4. Operational Confirmation 向人展开 Q hash、来源附件、完整 profile/snapshot、一次 Attempt 范围与 probe 适用性。缺少来源附件的有效核验、固定路径身份不符、未获 Owner exact-Q 接受或失配，均维持 `publisher-not-qualified`；不能仅因 profile 含 Q 就放行。

这是同一受审 pilot Controller/deployment 信任域内的来源核验，不声称能阻止恶意同 UID 调用任意私有 Python 函数。沿用 [OD-18 范围:5277–5281](../../../docs/v3/boundary-spec.md)，不新增自签 JSON、用户资格开关、后台服务或持久授权上下文。

## 3. 非循环绑定和两个不能省略的技术边界

### 3.1 Q 如何进入已有批准链

先确定新 profile revision 和除 Q 外的完整内容。对 resolved identity payload 去掉派生 `effective_config_sha256`，并仅从 `runtime_identities` 排除拟定 `v31-publisher-qualification-v1.json`，计算 profile basis。冻结 source/真实 probes 后生成 Q，再把 Q 文件加入 runtime_contents，得到最终 profile ID。现有 resolver 已把这些 bytes 身份纳入 profile。[models:546–595](../../../auto_g16/execution/models.py)

顺序为 `source/资格事实 → Q → 完整 profile → material → B → script → snapshot → marker → receipt`。资格 hash 经 profile/snapshot 被 exact Operational Confirmation 绑定；Q 不反向绑定最终 snapshot。Scientific Approval 与 Batch Approval 维持原有作用域，不把 Q 伪装成科学参数或新的科学许可。

### 3.2 实际计算主机：不能只有一份名单

当前 receipt 无 execution-host 字段。候选最小闭合要求：认证 PBS 原始 queue/eligible-host 范围 → 各实际节点受信身份与 probe → Owner 接受 Q → **新增 production wrapper 在 child 启动前及 receipt 出版前本地读取 machine/boot/namespace/mount/runtime 并唯一匹配 Q** → exact source/snapshot/marker/job/workspace/receipt 发布链。不能信任 caller 节点 JSON、环境变量 hostname 或登录节点探针。Q 的 workspace 身份只约束已资格 root/mount；fresh Attempt 目录仍由现有独立 workspace binding/no-follow 链闭合，不能套用 probe scratch 的 inode。

提交前复核可信 eligible-host 全集；实际执行到未资格节点时 wrapper 拒绝，不启动/不出版。受信范围的采集命令、节点到达方式和本机身份读取语法尚须在精确 probe/source packet 填实；当前 `NOT_ACQUIRED`。receipt 在原信任模型内可证明“属于合格主机集合”，不直接记录具体是哪台。若 Owner 要求 receipt 直接记载确切主机，则需另审版本化字段增量，本 R2 不暗加该要求。

**保持 production source 原字节的替代方案目前不成立**：需另有贯穿 qsub 至 publication 的受信调度/namespace 强制保证，当前未取得。一次节点列表观察不够，因此推荐保留新增 production source 分支这一实质 Owner 决定。

### 3.3 旧 v3 source/快照/receipt 字节不变

当前 `_prebinding`、renderer 与 `_receipt_binding` 都读取全局 `_WRAPPER_SOURCE`，[completion:334–399](../../../auto_g16/execution/_program_completion.py)；直接替换会破坏旧身份。拟定封闭配对：

| 分支 | 固定配对与行为 |
| --- | --- |
| 历史 v3 | scheduler `/2` + material `/1` + B `/2` + 原 source **14181 bytes / SHA `58167de5436ec2d5ae9ef89dde458f386cdc2860f4f00a41c81c0a390f782333`**；所有字节/IDs 原样重建，生产资格仍禁止。 |
| 本 pilot 的新生产 v3 分支（待接受） | scheduler `/3` + material `/2`（原字段加 Q base64）+ B `/3` + 独立新 production source（待冻结）；必须 exact Q/profile 与新的 fresh snapshot。 |

所有 material/prebinding/render/receipt-expected helpers 按持久 artifact 的固定版本配对选择**内建受审 source**，不执行 artifact 任意代码，不依赖“最新 source”、当前 Q 或 receipt 自报 hash。未知、混合、降级均拒绝。旧 raw-read/identity replay 不需当前 Q；新效果/成功 promotion 必须走本 pilot 限定检查。旧 strict、旧 receipt `/1` raw-read/reject、`/2` consumer 隔离不变。

## 4. 一次 pilot 所需工作，与长期维护明确分开

**必须做：** 冻结新 source/分派与 Q 摄入方案；在所有实际适用 host/mount 上取得有限 inert no-follow/独占发布/subreaper-descendants/atomic-link/实际 runtime 及新 host guard 证据；Owner 接受 exact Q；完成受审安装/只读摄入及当前 Project/runtime/调度范围复核；为唯一 fresh Attempt 准备完整新 snapshot 和现有三批准、精确 Live Gate。实际探针不运行 xTB、不 qsub；到不了真实 namespace 就停，不能暗中提交探针作业。每个 probe 的有限进程、时间、scratch 与自有 PID 回收范围由其 packet 明确；无清理权限。FC06 既有证据仅按 exact source/环境复用，不重复测试。

**适用性与变化：** Owner 明确一个 pilot 的执行/取证边界和允许窗口，未指定时不得无限期复用。效果前复核固定 Q 文件、profile/runtime、当前观察和批准链；wrapper 负责实际节点 action-time 检查。任何 Q/source/profile/host/namespace/输入/资源等变化使相应旧 snapshot/批准不适用，必须停止并另审新的解析/snapshot/批准；已消耗 Attempt 不重签、不重试。UNKNOWN 保留，另行授权 reconciliation。

**不为此次 pilot 建设：** 接受/撤销服务、递增序号锚、自动轮换、资格续租、跨进程长期激活、分布式撤销。Owner 中止 pilot 时由现有 Controller 停止后续获准动作；已 qsub 的任务不会被自动召回/取消，必要 qdel 仍需精确 job 授权。重启 Controller 或离开此次有界流程不自动恢复生产资格；新的续行 Gate 复核同一不可变证据、当前状态和作用域。历史证据不删改。

## 5. 精确拟改范围与短决策

- 产品仍仅拟改 `_program_rtwin.py`、`_program_completion.py`、`_program_completion_wrapper.py`、`execution/program.py`、`execution/program_runtime.py`：增加窄 Q reader/比较、真实 driver/组合入口检查、新私有 source/version 分派与 host guard。pure completion helper 不读可信目录或反向 import Transport。pilot Controller 的来源/批准核验依照既有操作流程，专用资格/安装证据留在候选外；不新增常驻 Controller 服务。
- 测试仅扩既有 `tests/v31/transport/{test_program_completion,test_rtwin_successor_bridge,test_program_composition}.py`：未受信 Q/错路径/漂移零 effect；新 guard 错节点拒绝；旧 v3 黄金 bytes/IDs 跨新 Q 有无仍一致；新旧交叉配对拒绝。现有 owner 是 [v31-transport-tests:409–420](../../../config/validation-selection.json)。不改公开 Core/Approval/Result、Transport 七操作、store DDL 或原四键 runtime qualification；若确有接口缺口，先提交精确增量。
- 合同接受后才落地六份 authority 文件及 dossier。Owner 此次只需决定：**①是否接受复用现有批准/deployment + 固定只读 Q 摄入的单 pilot 信任链；②是否接受实际节点 guard 的集合成员证明及新私有版本配对；③指定真实 host/namespace/取证到达方式与一次 pilot 范围。** 这不同时授权实现、探针、部署或运行；各阶段仍绑定具体可审阅工件。

旧环境/模板起点沿用已读 rev12 环境回执 (external retained evidence; not versioned)和 strict v2 离线 packet (external retained evidence; not versioned)。它们不证明当前计算节点资格，也不能直接作为 receipt v3 的新 snapshot/批准。本 R2 不选择化学参数、不刷新旧环境；所有未取得事实继续 `NOT_ACQUIRED`。现有 production hard stop 未改。
