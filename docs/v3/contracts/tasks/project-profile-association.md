# Auto-G16 bounded Project profile association

Owner accepted the private r2 contract (SHA-256 `874f692ceebbe067276daf7883d612737b1a1bc8d4fa74dbc667ea28792472f4`) on 2026-09-30. This is its implementation boundary; concrete production identities remain in the private reviewed package. Offline implementation/validation/review only.

## 唯一新增行为

1. 由 Execution 的现有 Project provisioning owner 提供一个私有、封闭的 profile-association 入口，只用于本次同一 Project 的 Q7 Opt→Q8 Freq 后继。不是任意目录 adoption、通用 rebind 或新 Project 创建接口。
2. 来源必须为真实、可只读重放的原 journal，包含同一 Project 的完整 intent、成功创建结果和 durable binding。重新验证原 profile/runtime/provisioning authority、journal 实体身份及所有关联。任何 UNKNOWN、缺成功回执、无绑定既有目录、身份冲突均拒绝；旧 UNKNOWN 不在接受域内。
3. 目标必须是独立审阅、精确接受和安装读回通过的新 Q8 Freq profile。对新旧 profile 进行闭合等价核对：允许 profile_revision 增加、Q7 qualification 被 Q8 qualification 替换、加入精确 Freq bootstrap；其他字段和既有 runtime bytes 必须一致，包括 transport、target、remote user/root、SSH topology/config、Python/Gaussian 身份和资源 dialect。具体目标 profile/Q/source 哈希在新源码冻结后的安装包中绑定，不在实现中固定为本次将被替代的 commit/Q。
4. 目标原生 authority 只执行一次 `OBSERVE_PROJECT`，核对同一目标、根、Project 路径、完整父链和目录物理身份，与原创建来源完全一致。异常、缺证据、身份漂移即拒绝；不能调用 PROVISION、创建 Attempt 目录、qsub、删除或自动重试。离线测试的 synthetic seam 不能发行生产关联。
5. owner 生成版本化、不可变的 `project-profile-association/1` 证明：绑定原 journal 的物理身份/摘要、原 intent/result/binding 的身份和摘要、旧 profile/runtime/provisioning identity、新 profile/runtime identity、精确允许差异、真实观察来源及时间、Project/父链身份和 owner schema/version。证明不是“又一次成功创建”记录。
6. 证明保存到精确审阅的独立本地路径，通过 no-follow、排他创建和 fsync 发布；原 journal 只读，不迁移 Core schema，不向原唯一 binding 行写入第二绑定。相同精确请求重读已完整证明可以幂等；相同目标但不同来源/物理身份/内容拒绝；部分发布留下证据并拒绝，不自动覆盖或继续。
7. 采用下文的版本化有效 Project binding 分支，原 binding 完整保留。Snapshot 顶层继续使用既有 project_physical_binding_id 字段，不额外插入 loader 未识别的 Snapshot 字段。新有效 binding 的身份覆盖完整关联证明摘要；Snapshot/effect intent、prebinding、scheduler、receipt 和批准链沿既有 binding ID 字段逐级绑定。恢复/Collection/结果来源读取重放同一关联而不重新观察或发行权限；prepare 仍要求新鲜原生观察。Project ID 保持相同，因此 Opt/Freq 两阶段的同 Project 科学关联不放松。
8. fresh Attempt/no-overwrite、单次 intent、三批准/Live Gate、程序 input/route/resources 和 exact-Q 安装校验保持。关联接受仅解决 Project→profile 身份，不给予运行权限。

## 证明字段、发行与历史重放（闭合规则）

关联 envelope 仅含 `schema, association_id, payload_sha256, payload`，schema=`project-profile-association/1`。payload 仅含 `project_id, source, old_profile, new_profile, allowed_delta, observation, issuer`。普通 SHA-256 使用既有 canonical JSON；association_id 使用既有 semantic_id 函数和全新 domain `project-profile-association/1`，输入为完整 payload；payload_sha256 不纳入自身输入。

- `source` 仅含 `journal, intent, creation_result, original_binding`。journal 是既有 no-follow 文件绑定（绝对路径、父链、device/inode、SHA/size）加真实 journal_identity；其余三个对象分别为从该 journal 唯一匹配行读取的完整闭合 payload 及其原 identity/digest。必须由原 provisioning journal owner 的只读验证入口重放列/payload/identity一致性及真实成功结果，不接受调用者拼出的替代成功记录。只支持含完整成功结果的 recoverable journal，不扩大旧 UNKNOWN 接受域。
- `old_profile`、`new_profile` 各仅含 `profile_file, resolved_profile_payload, runtime_authority_id, provisioning_authority_id`。profile_file 沿用既有 no-follow 文件绑定；resolved payload 必须由固定已安装 profile 原文离线解析得到。新旧 runtime/provisioning identity 按原生 owner 算法分别重算，不取任意输入字符串。
- `allowed_delta` 仅含 `contract_version, old_revision, new_revision, removed_runtime, added_runtime`。contract_version=`gaussian-opt-q7-to-freq-q8/1`；removed_runtime 只允许 Q7 文件名及原 bytes SHA/size，added_runtime 只允许 Q8 和 Freq bootstrap 的文件名及目标 bytes SHA/size。其余字段必须逐项完全相同；禁止放宽为“相同主机名即可”。新 revision 必须大于旧 revision。
- `observation` 仅含 `request, capture, decoded_result, observed_window`。request 保留 native Project 请求的完整 canonical bytes 及既有文件绑定；capture 保留完整原始 stdout/stderr、returncode/state/EOF/caps/request_sha256，字段沿用 project-wire-diagnostic/1；decoded_result 仅含 `state,parent_physical_identity,project_physical_identity`；observed_window 是现有闭合 UTC 起止窗口。request/capture 文件必须由同一固定生产 Project attestor 在该次 OBSERVE 调用中排他落地，不接受调用者传入 raw 字节替代；发行前验证 exact request SHA、完整 frame、protocol/operation/status、exit0、空stderr、完整EOF、输出上限及全部目录token。诊断本身仍不是创建回执，原创建权威只能来自 source journal。
- `issuer` 仅含 `owner_schema, source_commit, source_tree, installed_source_manifest, target_runtime_authority_id`。owner_schema=`project-profile-association-owner/1`；其余均来自固定受审安装和该次真实 attestor。当前 prepare 只消费此私有发行入口产生并登记的证明，不能通过解析任意 canonical JSON 取得生产权限。

请求/捕获/关联记录的固定只读位置和父链/文件身份由受审 installation/binding packet 登记，不由 HTTP、Q 或运行调用者选择。历史 detached reader 只读重放原 journal、两份原 profile、固定源定位和完整 request/capture/frame→result；核对这些文件与发行/安装清单的物理绑定，再验证关联语义。该 reader 不调用当前 effect driver、不发SSH、不发行新授权；只有 hash 自洽但没有登记来源的证明必须拒绝。同UID本地恶意伪造不在既有受审Controller信任域的抵抗声明内，不能因此把任意未登记文件视为权威。文件缺失或变化返回 unavailable/拒绝，不补造。

## 有效绑定与现有身份链的精确兼容方案

新增一个由上述 owner 独占构造、不可公开构造的 ProjectPhysicalBinding 版本分支，`provisioning_contract_version=v31-project-profile-associated-binding/1`。语义字段是历史 binding 字段集合加 `project_profile_association`；该字段为完整关联 envelope。仅此分支允许 location 的 `provisioning_disposition=PROFILE_ASSOCIATED`、`evidence_identity=association_id`，其目标profile为新profile，目录物理身份来自原binding与新观察的一致结果，Project ID不变。`provisioning_authority_id` 必须是新profile下既有 journal/runtime 算法重算的 authority。新 `project_physical_binding_id=semantic_id("project-profile-associated-binding/1", 完整关联分支identity payload)`。历史无关联分支保留全部旧字段、版本、domain和字节。

这不是原 journal 的第二条创建 binding：原 journal 仍只加载原binding；关联服务从固定独立证明还原新有效binding并检查其来源。旧 `_assert_owned_binding` 路径继续要求 journal 原binding与target完全一致；新增分支须完整关联重放，不得跳过旧创建来源。所有通用 journal append/provision/reconcile 入口必须拒绝关联版本，避免把关联记录写成创建成功。专用关联入口与 Snapshot prepare 不执行 PROVISION。

Snapshot 的原顶层闭字段集合与 `program-effect-intent` / `program-execution-snapshot` domain 保持；既有 `project_physical_binding_id` 值换为上面的新ID，故 proof任何身份变化都会改变effect/snapshot。`_approval_semantics.project_physical_binding` 内显式保存完整版本化关联分支；decoder只能按已知binding version选择闭字段，不能允许任意extra。Snapshot identity验证、准备、原始来源恢复、Collection、approval语义重放、Conformer两阶段reader及Query owning reader都必须贯通此分支。纯解析无权发行关联或效果。新身份必须通过 scheduler/prebinding 的现有binding ID、effect/snapshot ID及完成receipt关联一路闭合，篡改测试须证明。

生成源是否可保持字节不变必须用当前精确Q8逐项比较及完整loader重算/receipt回放验证；不得用新增未绑定字段、抛弃association字段或临时改ID替代。若现有wire/prebinding闭集不能承载既有ID而必须新增字段或改变生成字节，则本补充未授权猜测新的adapter/Q/material版本；停止并提交确切tuple增量设计。

## 实施与验证边界

接受后允许在现有 Freq worktree 离线实施与独立只读审阅。预计路径：`auto_g16/execution/project_provisioning.py`、Execution program snapshot/restore/identity consumer、Transport Project attestor及严格必要的 snapshot consumers、对应 `tests/v3`、Owner/boundary/acceptance/context-map。若需要改变目标等价接受域、旧 journal/Core schema、增加远端变更操作或两阶段科学标准，先返回 Owner，不扩大本合同。

复用已完成 Freq 实现和测试；新增检查必须覆盖：真实原 journal＋精确旧新 profiles 的离线前置重放；成功的显式新关联；未关联的跨profile拒绝；错误 target/root/config/bootstrap/runtime、假/缺成功回执、UNKNOWN、旧新 binding冲突；目录/源替换和symlink；proof篡改/串用；并发/重复/部分持久化；新 Snapshot 对关联的身份绑定、恢复只读以及两阶段结果来源；旧 Q7/历史 Snapshot 和生成源兼容。不能用只检查schema或自造原创建来源的测试代替端到端消费者覆盖。

修复后重新冻结 commit/tree 并重审受影响安装绑定。若 wrapper/loader/bootstrap 字节确实未变，按完整 source delta 和证据映射复用本次 Q8 10/10 native inert 结果，不重复运行同一包；新增 Project 关联所需目标证据应使用受审原生只读 OBSERVE，明确单次操作和留存，不执行计算。新的精确 Q 仍按既有合同接受，不覆盖本次已安装候选。

本次请求的新增授权仅是接受上述关联语义、离线实施、验证及独立审阅。之后准备精确的目标只读验证与安装差异包；已授权动作继续按其原范围执行，新增语义或不同精确候选不由旧接受代替。真实 anti/gauche Freq 仍需最终准确 Snapshot、资源、输入、目录和运行窗口审批。
