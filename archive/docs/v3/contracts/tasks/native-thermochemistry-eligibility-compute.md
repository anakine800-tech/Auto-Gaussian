# Auto-G16 原生热化学第二包合同 r2（提案）

任务：NATIVE-THERMO-ADAPTATION-02 / ELIGIBILITY-AND-COMPUTE。
状态：PROPOSED_FOR_CONTRACT_FREEZE，未实现；r1独立审阅的两项P1及一项P2已修订，待增量复审。Owner已批准合同准备、参数候选表，以及合同确定后的离线实现/验证；不再次请求一般开发授权。
基线：main `12a4a5ca30c40f795f05824e3a59a8f545cc2d22`，tree `6d871d42bcdf402c370dd1c4d59187a8b00373bd`。OWNER-GUIDED、non-BUS、L2。

## 1. 结果与范围

为既有完整原生Opt/Freq来源增加唯一私有编排入口，在完整来源重放、既有SamplingProfile派生资格、显式计算政策齐全时，返回新的内存ConformerEnsemble修订及绑定它的ThermodynamicEnsemble。复用现有GoodVibes 4.3.0函数内核和稳定logsumexp汇总；不另建科学对象体系。

支持域沿用首包：中性闭壳层单重态非线性n-butane，14原子、36正有限模式，恰好两个已注册且顺序固定的canonical成员，完整successor minimum /2、parser `auto-g16-v3-gaussian-job` / `1.2.0`、wB97XD/Def2SVP、gas、restricted_closed_shell、UltraFine、Tight_MaxCycle128。方法、频率、电子能必须来自同一已绑定Freq结果，Opt/Freq方法一致。仅用于明确标识的有限采样流程验证，不声明穷尽或全局最低。

不修改历史r4、原SamplingProfile、source-adapter事实schema、旧reader返回值、Result/parser或公共导出；不保存、注册、安装、运行真实材料、改HTTP/UI或接通final_integration。真实r4只有在以后批准的独立计算窗口中才可能被读取/派生；本轮测试全为合成来源。

## 2. 拟冻结的入口和请求

新私有入口 `auto_g16/conformer/_successor_thermochemistry.py::build_native_thermodynamic_ensemble(readout, *, request)`。readout必须为exact FreqReadout；不接受已导出的facts mapping、任意原文路径、手工GoodVibes表或直接声称eligible的成员表。

request为闭字段mapping，字段恰为：
- `schema`: `auto-g16-native-thermochemistry-request/1`。
- `purpose`: `bounded_workflow_validation`。
- `source_ensemble`: `{conformer_ensemble_id,payload_sha256,revision}`，等于本次重放原始refined。
- `sampling_profile`: `{sampling_profile_id,payload_sha256}`，等于本次重放profile。
- `source_member_ids`: 长度恰为2、无重复的canonical完整成员tuple；必须等于全部注册及refined成员，不能挑选子集。
- `coverage_scope`: `{kind,rationale}`；kind仅 `frozen_profile_nonexhaustive_scope`，rationale非空规范文本。它解释使用范围，不能覆盖SamplingProfile或coverage/blocker结果。
- `method_binding`: 闭字段恰为 `program=gaussian16`、`method=wB97XD`、`basis=Def2SVP`、`dispersion=intrinsic_wB97XD`、`solvent=gas`、`reference=restricted_closed_shell`、`charge=0`、`multiplicity=1`、`integration_grid=UltraFine`、`scf_policy=Tight_MaxCycle128`；charge/multiplicity须为exact int。逐成员等于已重放authority.method_binding。明确不包含 `route_contract_version`；Opt/Freq各自路由版本继续由既有完整重放验证，不能把Opt METHOD的11字段直接拿来比较。该绑定不授予研究方法科学认可。
- `thermochemistry_policy`: 全量复用当前 `_service._POLICY_KEYS` 和 `_normalize_policy`，闭字段、无默认。支持方案固定为已有adapter v2、GoodVibes4.3.0、Grimme熵/Head-Gordon焓、alpha4阻尼、Gaussian原文对称数、禁自动缩放/翻转/额外SPC/额外溶剂自由体积；温度、标准态、两cutoff、两缩放因子仍必须逐次显式给定。
- `member_policies`: 完整canonical tuple；每项字段恰为 `{member_id,degeneracy,degeneracy_rationale,symmetry_rationale}`。degeneracy必须exact正整数，拒绝bool/float；两个rationale均非空。不能推断镜像简并或重复计入已由转动对称数计入的因子。

request规范化后用现有canonical `_identified_payload` 机制在新域 `native-thermochemistry-request` 得到ID/hash；不自称人工批准token，不引入新审批/能力框架。外部真实操作授权仍必须在调用前由既有流程完成，配置完整本身不授权真实计算。

## 3. 唯一来源路径及生命周期

单独获取既有process-wide Opt读锁一次，保持现有30秒等待。进入既有 `_replayed_frequency`，重放完整profile/原始与Opt/Freq历史；复用首包事实生成逻辑，核对Core Observation/Result、ParseOutcome、36正频、所有span/section/方法、已保存revision pair。不得通过伪造V30身份接入旧入口。

为复用首包逻辑，仅将 `_successor_thermo_source.read_native_thermo_inputs` 内部已审阅成员事实循环抽为私有 `_native_input_facts_from_replay(profile, refined, opts, freqs)`；只由保持上述资源的入口调用，该helper不获取锁、不自行构造来源。旧入口返回schema、顺序、兼容拒绝及resource lifetime均不变。新入口不嵌套调用会再次拿锁的旧入口。

请求完整性和所有来源/资格拒绝必须在GoodVibes调用前完成。读取pins、原库只读连接、snapshot、receipt上下文和锁保持到新记录构造结束；全部退出核验成功后才返回。异常关闭所有资源、传播错误且不返回任何部分集合/计算结果。无retry，无传出原文路径/store/fd/可执行权。

## 4. 派生资格与新修订

资格必须从同一profile和重放证据派生：profile.thermodynamic_eligibility_policy的require_post_dft_minimum必须为exact True；coverage.status必须为 `sufficient` 且在其required_coverage_statuses中；independent_review_blockers必须为空。coverage闭字段恰为 `{status,scope,global_minimum_claim,exhaustive_coverage_claim,obligations,observed_count,valid_count}`；scope固定 `closed-crest-imtd-gc-profile`，两个claim须为exact False，observed_count/valid_count须为exact int且均为2，与完整重放得到的观察和有效成员数一致。obligations闭字段恰为 `minimum_observations_met`、`minimum_valid_met`、`maximum_observations_respected`、`fragment_association_semantics_complete`、`independent_review_resolved`，各值必须exact True；缺键、额外键、空mapping、整数1代替True均拒绝。必须按既有profile预算、fragment约束和独立审阅证据核对这些结果，不能仅凭布尔映射通过。原始审计、Opt身份/连接/立体化学检查及后DFT去重必须经现有完整重放匹配，而非只信status字段。

全部canonical成员须为validated_minimum、保留完整正面 /2 authority、无negative Opt/Freq authority、无identity rejection、无duplicate-of、无未解决审计；任一不合格拒绝整个包，不把合格方便子集归一化。source/model与现有SamplingProfile政策任何偏差停止，不改profile补通。

创建独立ConformerEnsemble内存修订：revision=source.revision+1，supersedes=source ID；保留source Project/CalculationPlan/profile、members、sampling observations、negative evidence、dedup、clusters、coverage、blockers。`thermodynamic_eligible_members`为已派生的完整canonical集合；`ts_seed_members`保持原值（本域要求原值为空）。不升级TS资格。

仅追加一条闭字段audit记录：`stage=native_thermochemistry_eligibility`、`source_ensemble`、`sampling_profile`、`request_id`、`request_payload_sha256`、`request_payload`（完整规范化request）、`derived_member_ids`、`purpose=bounded_workflow_validation`。字段名与形状在本提案接受后冻结；不伪造minimum authority、不改成员来源。

对于当前真实材料，这是拟议的r4→r5派生语义；本轮不实际产生真实r5。相同source/request重建身份确定；温度/简并度等请求变化影响新修订身份，旧revision不变。

## 5. 原生方法归一化、内核与输出

新增 `auto_g16/thermochemistry/_native_service.py` 的唯一私有service签名为 `_build_native_thermodynamic_ensemble(*, source_ensemble, qualified_ensemble, profile, native_facts, request)`。前两项必须为exact ConformerEnsemble，profile必须为exact SamplingProfile；native_facts为当前受保护重放内生成的完整首包facts，request为完整规范化请求。该service不作为独立可信来源入口，不接收外部导出facts来替代来源重放。

首次GoodVibes调用前，重验三个模型的canonical ID/hash、源/profile/facts/request四者的身份、方法、完整两成员映射及第4节资格；重验qualified.revision恰为source.revision+1、supersedes恰为source ID，source的eligible和TS投影均为空。以下保留字段逐项完全相同：schema_version、project_id、calculation_plan_id/revision、sampling_profile_id/payload_sha256、species_binding、stereochemistry_binding、sampling_observations、negative_evidence、dedup_decisions、independent_review_blockers、clusters、members、coverage、ts_seed_members。qualified.audit_evidence必须等于完整source.audit_evidence原前缀加恰好一条第4节规定记录，qualified.thermodynamic_eligible_members必须恰为已派生全员canonical tuple；仅自洽hash不能替代这些比较。保持旧 `_normalize_method` / `_validate_member` 的legacy范围，不往旧支持表塞入wB97XD或parser1.2。

native `method_compatibility_binding`闭字段恰为：`schema=auto-g16-native-thermochemistry-method/1`、`method`（第2节准确10字段stage-independent mapping）、`minimum_authority_schema=v31-conformer-successor-two-stage-minimum-authority/2`、`parser_name=auto-g16-v3-gaussian-job`、`parser_version=1.2.0`、`energy_source=frequency_result_final_scf`、`symmetry_source=gaussian_reported_rotational_symmetry_number`。用既有identified_payload机制的新域 `native-thermochemistry-method`产生兼容性ID；全部成员完全相同。

每成员调用既有 `_goodvibes.functional_thermochemistry`，电子能、36频率、质量、Gaussian转动对称数、三转动温度来自首包已验证facts；政策数值全部来自显式request，标准态转换复用既有 `_standard_state_binding`。不调用GoodVibes CLI/QCData/calc_bbe，不自动读取额外文件或升级依赖。

normalized member保留现有统一外层字段：member_id、source_refined_conformer_ensemble_id/revision（新qualified修订）、two_stage_minimum_authority_id、method_compatibility_id/binding、source_provenance、temperature_k、standard_state、raw_rrho、treated_qrrho、degeneracy/rationale、inclusion_status。native source_provenance闭字段为：`schema=auto-g16-native-thermochemistry-provenance/1`、`source_ensemble`（原refined）、`sampling_profile`、`native_source`、`native_result`、`minimum_authority`、`thermo_facts`、`request_id`、`request_payload_sha256`。后六种输入对象的事实形状沿用首包/上述request，不能用摘要反造Core对象。对称审阅理由可经完整request_payload追溯。原始Gaussian reported值与重算raw_rrho/treated_qrrho分别保留，不互相覆写。

将 `_service._build_thermodynamic_ensemble` 中已有normalized成员后的稳定分区/归一化/模型构造代码提取为私有 `_finish_thermodynamic_ensemble(*, ensemble, policy, standard_state, normalized_members, gas_constant, joule_to_au)`，eligible取自ensemble.thermodynamic_eligible_members，由旧builder和native service调用。常数参数只能来自同一既有GoodVibes固定内核加载结果；helper不成为独立来源入口。仅机械提取，不改变常数、极值处理、tie-break、容差、degeneracy log处理、字段及身份算法；禁止复制第二套Boltzmann公式或额外加混合熵。旧fixture输出及完整identity逐项不变。

输出exact tuple `(qualified_conformer_ensemble, thermodynamic_ensemble)`，均为现有不可变公共类；后者source_member_ids必须等于前者派生eligible，有且仅有这些成员。无新公共类/导出/持久化记录类型。final_integration仍不新增原生消费能力，不将这对内存对象描述为已登记或可在原生页面消费。

## 6. 拟允许改动路径

新增：`auto_g16/conformer/_successor_thermochemistry.py`、`auto_g16/thermochemistry/_native_service.py`。
限定修改：`auto_g16/conformer/_successor_thermo_source.py`（上述共享facts循环提取）；`auto_g16/thermochemistry/_service.py`（上述共享finish提取，不放宽legacy验证）。
测试：`tests/v31/conformer/test_successor_freq.py`、`tests/v31/thermochemistry/test_core.py`；如需要native合成跨层案例，扩展已有 `tests/v31/integration/test_v31_offline_end_to_end.py`，不改原成功断言/削弱旧链。
治理：新 `docs/v3/contracts/tasks/native-thermochemistry-eligibility-compute.md`、`OWNER_DECISIONS.md`（真实Owner接受后才记录）、`config/context-map.toml`及 `config/validation-selection.json`（只追加该合同到现有控制文档路径；不降低selector）。

禁止改动：公共__init__/models、首包facts/parser、_goodvibes内核/依赖、旧_gaussian_thermo_facts、旧successor Opt/Freq政策或registry、final_integration生产代码、Core/Execution/Transport、CLI/HTTP/UI/真实数据/安装。若上述接口无法在这些路径保持语义，报告准确缺口，先修订合同。

## 7. 验收与证据选择

A. 合成完整原生来源→facts→派生r+1→ThermodynamicEnsemble，独立复算稳定权重、总体G及政策/方法/来源身份；不使用真实样例算结果。
B. 完整source/request匹配：错ID/hash/profile/order、缺member、重复、方便子集、任一来源/authority跨成员自洽拼接拒绝；即使重新计算了合法ID/hash，qualified的members/coverage/保留字段篡改、审计前缀改变/多追加/少追加均拒绝。
C. 资格失败：negative/zero/missing、duplicate、coverage非允许、字段类型/计数错误或obligations缺/额外/空/false/整数1、blocker、state/stereo/geometry/method漂移、部分Freq、/1拒绝，且GoodVibes零调用。
D. 参数失败：None/漏/额外字段、bool/float/非正degeneracy、空理由、非有限/非法T/cutoff/scale、混标准态/方法、方法漏字段/额外Opt route字段/值漂移；合法synthetic 1atm/1M显式政策与不同T验证。
E. 数值：复用PR #137迁移后的极端能差/大简并度、1:3等能0.25/0.75、独立G检查；新增native编排身份关联，不能重复抄核算法当oracle。
F. 旧入口兼容：旧reader/首包新facts输出不变；legacy ThermodynamicEnsemble完整payload/ID不变；历史部分/负频查询继续允许；无需native_compute时不加载GoodVibes。
G. 生命周期：计算期间pins/slot仍持有；normal/exception/exit失败释放资源，pin漂移使整体无输出；并发/30秒等待沿用旧锁、无嵌套，无原库写入。
H. preflight、静态/CI/Python contract、diff/敏感扫描、selector决定focused/affected及唯一complete owner；变更治理映射可能保守选择legacy-release，不能人工绕过。固定4.3.0 wheel与14项GoodVibes差分按现有资格流程验证；不升级到当前网上latest。
I. 独立L2实现审阅及冻结候选后一次完整证据。生产可达来源/锁/SQLite与新内核持锁消费的准确本地验收，在合并分类时另准备并明确授权；#196五次facts读取不能替代本包计算消费证据。合同本身不启动真实库读取/真实计算。

## 8. 本次需冻结的准确决定

接受上述新增native入口、闭字段request、同profile派生qualified修订、native method/provenance及机械共享finish边界和路径。此前对三项的批准继续覆盖合同确定后的离线实现、验证、独立审阅；本次不要求Owner提前选择任何真实T/标准态/cutoff/scale/简并度。

开发合同接受不自动接受PARAMETER-DECISIONS.md的真实候选数值。该表及scientific-decisions.pending.json保持未选定，真实计算/资格派生/保存/安装另需对应准确操作窗口。commit/push/PR/merge/清理不在本轮三项范围。
