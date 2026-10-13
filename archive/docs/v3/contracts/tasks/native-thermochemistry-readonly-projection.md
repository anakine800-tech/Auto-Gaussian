# Auto-G16 原生热化学第四包合同 r1

任务 NATIVE-THERMO-ADAPTATION-04 / READONLY-PROJECTION；feature，OWNER-GUIDED、non-BUS、L2。Owner 于 2026-10-09 以“批准两项”准确接受原始合同 SHA-256 `468275ff3ae413b745d2a40ee51c3a11f418104ab59b82c2cb4ac6e88a36ad45`。本文为其公开脱敏版本；该摘要指向接受的原始合同而非本文字节。授权覆盖隔离工作区、实施、合成/离线验证、L2 独立审阅、提交、推送、draft PR 和 CI，不包含合并、真实注册、安装、真实浏览器读取、新计算或清理。

## 1. 起点、依赖与授权衔接

后端仓库 `anakine800-tech/Auto-Gaussian`。第三包已完成60项离线测试、独立审阅及43.774秒真实保存/新进程回放验收；原始合同记录其发布前基线 `23da24c4ec240dc65a0c2333780af9b6ea5f193a`。发布后的准确后端起点为提交 `13a98229551df6a9baeaa9b7c830f06c713a2049`、tree `ab7a2b16f2f68386e711bf4f198211827196a3a8`，七文件内容与已接受候选逐项相同。依赖 PR #198 的准确 HEAD 上全部五项 required CI 通过后才编辑功能。第三包尚未合并时使用叠加分支 `codex/native-thermo-projection`、draft PR base=`codex/native-thermo-readback`，明确依赖 #198；后续 retarget 必须另做准确检查，不能自动合并。第四包后端从第三包通过发布检查后的准确提交建立独立工作树，实施前记录其HEAD/tree及与上述候选的逐文件一致性。尚未产生的提交不填造；第三包变更字节或验收适用性不再相同则停止重新核对。不能复制脏树冒称主线。

前端从已核对本地/远端 main fd0124d1c072977816626657d3c36899ab5ce7f1，tree baa8d5ac38824afccce2e7482630a91170837604 建立另一独立工作树。前端仓库 `Auto-G前端`；共享旧前端2ddb755a与其未跟踪文件不修改。

两仓库各一唯一 codex/ 分支和独立工作区；使用 Codex 工作区能力，实施前各自 preflight。准确合同接受后继续实现、合成验证、L2独立审查及安装候选准备；页面仓库的提交/推送/PR、实际安装/真实浏览器窗口仍按各自具体授权记录。第三包发布授权不自动传递为第四包发布或合并授权。

## 2. 可信启动注册

前端 registry 增加 autog-native-source-registration/4：顶层恰为 {schema,sources}；source 每项恰为 {source_id,database,snapshots,opt_readout,freq_readout,thermodynamic_readout}，前五项语义及上限沿用/3。新增项为 null 或恰为 {path,sha256} 的 descriptor，使用既有read_pinned读取至多1MiB注册文档后交第三包load_native_thermodynamic_readout。/1、/2、/3的闭字段保持不变，未知/缺少/重复字段拒绝。

后端 NativeSource 新增 thermodynamic_readout: NativeThermodynamicReadout|None，默认None。非空时要求exact类型、已有exact FreqReadout、两者readout字段完整相等（全部material/optimization_sources/frequency_sources）。保留既有源database与唯一snapshot/Attempt/parsed revision的绑定校验，Opt/Freq互斥规则不变。未匹配的reader不能挂到另一个source别名或数据库。

不新建数据库来源、不扩展第三包产物格式、不自动选latest、不从HTTP接受路径、摘要、参数或注册正文。应用启动时不读取热化学结果、不重算。

## 3. Query与HTTP

新增 NativeQueryService.get_thermodynamics(source_id,attempt_id) 及只读GET /api/v1/native/sources/{source_id}/attempts/{attempt_id}/thermodynamics。

先沿用标识合法性与source存在检查。无thermodynamic_readout时，只用现有QueryService只读机制确认Attempt确实属于该source数据库，不调用旧完整_attempt投影或Freq reader；存在则返回not-registered，未知则404。有registration时，仅接受该NativeSource唯一注册snapshot的Attempt，其他Attempt返回404；从该reader频率来源找到唯一member，调用第三包read()恰一次。全部锁、文件和来源退出核验成功后才构建DTO。禁止嵌套FreqReadout.read或再次调用计算/聚合函数。

错误采用现有HTTP error schema：非法ID=400 invalid-id；未知身份=404 not-found；OptReadBusy或源资源不可读取=503 store-unavailable；内容/hash/关联/格式不符=409 invalid-evidence；不可分类异常=500 internal-error。错误无本地路径与原异常正文。配置存在但漂移不能降级为not-registered或旧成功值。

list_sources/list_projects/list_attempts/get_attempt 原DTO不变，不因第四包增加热化学集合读取。新接口单独请求；复用原HTTP响应字节上限及访问控制，没有写入路由。

## 4. 响应闭字段与准确映射

新顶层恰为 {schema,kind,data}，schema=auto-g16-native-thermodynamics-query/1，kind=thermodynamics；既有auto-g16-native-query/1不变。

data恰为 {availability,reason,source_id,attempt_id,selected_member_id,result}。可用时availability=available、reason=null、member为唯一选中成员、result为下述对象。未登记时availability=unavailable、reason=not-registered、selected_member_id/result均null。

result恰为下表各键。以下q为第三包返回qualified对象，t为thermodynamic对象，a=q最后一项eligibility audit，request=a.request_payload。只投影已保存值，不生成新热化学数字或身份。

| 键 | 闭字段 / 来源 |
| --- | --- |
| artifact_sha256 | reader.artifact.sha256 |
| source_ensemble | {id,payload_sha256,revision}，取request.source_ensemble |
| qualified_ensemble | {id,payload_sha256,revision}，取q |
| thermodynamic_ensemble | {id,payload_sha256}，取t |
| sampling_profile | {id,payload_sha256}，取request.sampling_profile |
| request | {id,payload_sha256}，取a.request_id/request_payload_sha256 |
| parameters | 第5节闭字段 |
| members | 第6节闭字段，保存canonical顺序 |
| ensemble_treated_free_energy_hartree | t同名保存值 |
| population_normalization | t同名保存对象，键恰为population_sum/absolute_error/numeric_tolerance/status/tolerance_purpose |
| coverage_scope | request同名保存对象，键恰为kind/rationale；kind=frozen_profile_nonexhaustive_scope |
| scientific_acceptance | 字符串unavailable，不从eligibility或回放推导 |

所有ID沿用既有非空ID语法；摘要为64位小写十六进制。所有数字必须finite，bool不充当数字，revision为正exact int。前后端均拒绝额外/缺少字段；前端无效响应显示contract-mismatch，不能静默省略非法字段。

## 5. parameters

闭字段为temperature_k、standard_state、entropy_method、enthalpy_method、entropy_frequency_cutoff_cm1、enthalpy_frequency_cutoff_cm1、frequency_scaling_factor、zpe_scaling_factor、moment_of_inertia、degeneracy_excludes_rotational_symmetry、functional_kernel_implementation_id。

temperature_k、standard_state与implementation_id直接取t；entropy_method/enthalpy_method分别取t.thermochemistry_policy.qrrho_entropy_method/qrrho_enthalpy_method；其余同名字段取已保存policy。沿用第三包支持域与合法类型，不增加参数默认值或新的方法选择。单位由字段固定：温度K、频率cm⁻¹、能量Hartree、熵Hartree/K，布居无量纲。

## 6. members与来源白名单

members每项恰为 {member_id,is_selected,degeneracy,degeneracy_rationale,inclusion_status,raw_rrho,treated_qrrho,normalized_population,source}。除is_selected为member_id与选中成员是否相等，其余对应t.member_observations保存值；简并度为正exact int，布居[0,1]，成员数/顺序完全保持。is_selected恰有一个true。

raw_rrho恰为 electronic_energy_hartree、zero_point_energy_hartree、enthalpy_hartree、entropy_hartree_per_kelvin、gibbs_free_energy_hartree。treated_qrrho恰为 enthalpy_hartree、entropy_hartree_per_kelvin、gibbs_free_energy_hartree、entropy_treatment、enthalpy_treatment；处理名保持grimme/head_gordon。无相对自由能新计算、单位换算或布居再归一化。

source恰为 {optimization_attempt_id,frequency_attempt_id,optimization_parsed_result,frequency_parsed_result,optimization_result_source,frequency_result_source,two_stage_minimum_authority_id}。

- 两个Attempt取同member的reader.readout.optimization_sources/frequency_sources对应snapshot.attempt_id；各应唯一且与完整回放成员关联一致。
- optimization_parsed_result/frequency_parsed_result 各恰为{result_id,payload_sha256}，取observation.source_provenance.minimum_authority.optimization/frequency.parsed_result。
- optimization_result_source/frequency_result_source 各恰为{observation_id,payload_sha256}，取上述minimum_authority两阶段result_source。
- two_stage_minimum_authority_id取observation同名保存值。现有authority没有独立payload_sha256字段，不凭空增加该字段。

不返回path、transport_root、directory_chain、原日志、完整private provenance或未列明自由字段。可按需在页面展示白名单身份以支持追溯。

## 7. 页面行为

详情页增加“已保存的集合热化学结果”区域。先完成现有Attempt详情读取，再在该详情仍可见时触发一次新GET；路由或token变化沿用AbortController丢弃过期响应。列表页不触发该请求。复用requestJSON的native-scientific-read策略（120秒、全页并发预算2、不自动重试），不修改全局请求机制。

页面展示两个成员raw RRHO/treated qRRHO、treated G/布居、集合treated G、当前成员标识、参数、单位和有限采样说明。保留“Gaussian 原始热化学值”与facts.thermochemistry原样。新区域的加载、未登记与失败分开显示；新区域失败不抹掉已完成的旧详情，不显示0、成功空表或历史缓存兜底。不设参数编辑、计算、保存、批准按钮。数值显示不声称穷尽采样、全局最低或新增科学验收。

## 8. 允许文件与验证

后端：auto_g16/query/native.py；tests/v3/query/test_native.py及新增tests/v3/query/test_native_thermodynamics.py；冻结后纳入docs/v3/contracts/tasks/native-thermochemistry-readonly-projection.md、OWNER_DECISIONS.md及两项准确文档路由登记。禁止改第三包owner、计算内核、公共科学模型、数据库、执行/transport、原Result/parser及旧DTO。

前端：autog_frontend/native_sources.py、autog_frontend/api.py；web/src/native-panel.tsx、web/src/native.css、新增web/src/native-thermodynamics.tsx；tests/test_native_sources.py、tests/test_native_http.py、新增web/tests/native-thermodynamics.spec.ts；新增docs/native-thermodynamics-registration.md。无新依赖，不改全局requestJSON、包版本或安装锁；实际配套安装另准备准确wheel/hash方案。

验证顺序：preflight → 后端query focused/affected（含第三包合成fixture复用）→ 前端注册/HTTP tests → UI typecheck/build及合成Playwright → L2独立审查 → 冻结提交selector指定的完整证据与CI。合成覆盖/1–/4兼容、重复/未知字段、跨source/Attempt/member拒绝、零重算、读失败/忙锁、列表零新增read、旧报告不变、单次请求、过期响应、显示精度与窄屏溢出。共享候选未变时不重复整套第三包真实回放。

## 9. 后续安装与合并边界

新页面不能直接使用当前较旧安装后端。先形成前后端接受提交、可重现wheel和安装目录候选、准确注册diff、合成浏览器证据，再给出独立本地安装/真实只读浏览器验收方案。方案绑定本次已保存产物、源/参数身份、实际loader、端口、时限和回退保留策略；此前真实保存窗口已消费，不包含这些影响。

发布、合并、应用注册、安装和真实浏览器窗口各依准确授权；本合同接受不会批准新Gaussian/PBS/SSH、科学验收或清理。依赖身份与范围均不变时继续已授权步骤，不再请求重复的一般开发许可。
