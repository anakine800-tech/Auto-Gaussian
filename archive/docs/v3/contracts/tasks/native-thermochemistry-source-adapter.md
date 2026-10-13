# Auto-G16 原生热化学来源与方法适配：首包合同 r2

任务：NATIVE-THERMO-ADAPTATION-01 / 第一包 SOURCE-ADAPTER。
状态：PROPOSED_FOR_OWNER_CONTRACT_DECISION；根据r1独立审阅修订，等待r2增量复审及Owner对修订边界的决定；未实施。
类别：v3 feature development；OWNER-GUIDED、non-BUS；至少L2合同/兼容性审阅。
后端基线：3f067d8b3e93af9cebd64b560b20cbda4c54a938，tree dd13c5194353d3b8646d7e7dd7c2fae8c3a8a33a。
隔离分支：codex/native-thermo-adaptation。Owner已指示从main继续适配；本提案请求具体首包边界的决定，不重新请求一般开发授权。

## 1. 首包完成后能做什么

从完整重放的原生Opt/Freq来源读取一套不可变、可追溯的热化学输入事实；接受现有successor /2最低点证据、Freq parser 1.2.0和精确wB97XD/Def2SVP方法域。来源身份、原文归属和旧接口兼容性可分别测试。

首包止于输入事实适配。它不调用GoodVibes处理真实分子，不创建ThermodynamicEnsemble，不改变ConformerEnsemble的eligible/ts_seed投影，不持久化新产品记录或增加HTTP/UI入口。这使本包不必猜测温度、标准态、低频策略、简并度、覆盖或存储协议。

这是后续热化学闭环的依赖包，不是完整热化学适配已经完成。后续资格与有序成员投影、集合计算、不可覆盖保存/登记、前端展示分别保留明确的合同与科学参数决定。

## 2. 支持域与兼容性

- 仅支持现有read_two_stage_authority可重放的中性闭壳层单重态n-butane域、14原子、36个模式；不泛化到其他分子、金属、开壳层、线性分子或TS。
- 新入口要求authority_schema精确为v31-conformer-successor-two-stage-minimum-authority/2，保留并核验tail_evidence；/1不自动升级，旧读取不受影响。
- Opt方法来自现有read_opt_authority的METHOD，Freq方法必须等于现有去除stage route字段后的闭合binding；保留输入route、Opt/Freq计划、SCF和basis输出的全部既有检查。方法适配只承认输入事实同源，不表示该方法已获研究用途或热化学科学认可。
- Freq来源为v31-gaussian-result-source/2及v31-gaussian-parsed-result/2，parser固定1.2.0；不放宽旧_gaussian_thermo_facts的V30支持表，不伪造V30 ParseOutcome身份或最低点authority。
- 既有7项Gaussian原始热化学事实及span原样保留。补充提取只生成私有输入事实，不修改parser、Result、历史数据或查询返回值。

## 3. 唯一来源入口及资源生命周期

新增私有编排函数auto_g16/conformer/_successor_thermo_source.py中的read_native_thermo_inputs(readout)，参数必须是exact type的现有完整FreqReadout注册对象，拒绝子类或鸭子类型替代。无原文路径参数、HTTP参数、任意dictionary作为已验收来源或历史手工GoodVibes表输入。

为避免复制读取栈，在frequency_readonly.py提取一个私有、上下文管理的完整重放helper，供现有FreqReadout.read和新入口共用。提取后的现有read响应、并发槽、等待/错误语义、数据库访问模式及registry schema保持不变。新入口的全员Freq、/2 schema、正频、最低点及补充事实完整性要求仅在新consumer施加，不能加入共享helper导致旧read拒绝原先允许的部分Freq、/1、负频/零频或补充事实缺失结果。

helper必须在返回值仍被消费期间持有原有文件pins、只读数据库、receipt来源上下文与原生读取槽；在正常返回前重新核验pin。异常时关闭资源并传播原有来源错误，绝不返回部分成功输入。不得把打开的store、descriptor或raw路径放入返回mapping。新编排在锁内直接使用helper，不嵌套调用FreqReadout.read以免重复获取同一锁。旧read保留read(store, attempt_id)调用形状、先获取原slot再校验selected Attempt的顺序、selected修订与调用方store完整serialize比较，以及对调用方store执行require_pair的约束。新consumer没有调用方query store，只对注册的各自destination执行require_pair；不得用省略store比较的分支替代旧read。内部helper可在受控with范围yield瞬态资源，公开给调用者的最终mapping只能在所有context成功退出、pin及只读快照退出检查完成后返回；退出异常使整个调用失败。

重放顺序沿用现有FreqReadout：

1. 注册材料hash/size与无重复key解码；精确重建profile、original、opt_refined、history、prior、refined身份。
2. 原始Core/Transport只读打开，已保存解析修订用Core.read_snapshot读取。
3. 重放全部Opt来源和Freq历史链；比较完整集合_identity_payload，不能只比较ID、当前member字段或36/0计数。
4. 每个成员再次使用gaussian_freq_result_source、parse_freq_source、require_pair取得本次重放的native Observation、native Result、ParseOutcome和日志bytes；与该成员完整minimum authority中的parsed_result/result_source/频率/span/方法逐项一致。
5. 将仍受保护的bytes和已确认的事实交给纯补充提取函数。所有注册成员必须在refined中按canonical顺序恰好出现一次；缺少任何Freq来源、存在未完成或非最低点成员都拒绝整个输入包，不产生方便子集。
6. 返回前完成所有pin检查；返回值不带存储句柄、读取权限或计算权限。

新入口以输入事实准备为目的，要求每个模式严格大于0且有限。零频可保留其既有最低点分类，但本入口拒绝热化学输入，不重新分类历史结果。

## 4. 私有事实mapping的精确形状

不新增公开导出类，不新增Core/Result schema。下面是私有、深冻结、可确定重建的mapping，不作为可独立信任的科学资格凭证。

顶层字段恰为：

| 字段 | 值 |
| --- | --- |
| schema | auto-g16-native-thermo-input-facts/1 |
| source_ensemble | {conformer_ensemble_id, payload_sha256, revision}，来自完整重放的refined |
| sampling_profile | {sampling_profile_id, payload_sha256}，来自完整重放profile |
| members | 按refined.members原顺序的非空tuple；精确全员，不叫eligible_members |

每个member字段恰为：member_id、minimum_authority、native_source、native_result、thermo_facts。

- minimum_authority：原样深冻结该成员已重放的完整successor /2 authority；保留Opt/Freq来源、method binding、tail evidence及身份。
- native_source：{observation_id, payload_sha256}；等于authority.frequency.result_source。
- native_result：{result_id, payload_sha256, parser_name, parser_version, result_kind}；前两项等于authority.frequency.parsed_result，后三项来自本次ParseOutcome。
- thermo_facts：下表中的闭合mapping；不包含temperature policy、standard_state policy、degeneracy、population或eligibility布尔值。

thermo_facts字段恰为：

| 字段 | 来源、单位与拒绝规则 |
| --- | --- |
| source_artifact | 原ParseOutcome的完整source_artifact，hash/size必须等于已验证日志bytes |
| job_section | 原ParseOutcome的job_section，span在完整日志内合法 |
| electronic_energy_hartree | {value, source_span}；等于原final_energy_hartree，并绑定该section中确定该最终值的最后一个SCF事实span；冲突/缺失拒绝 |
| frequency_blocks | 原频率block tuple，含每个原始span，不重新分组或缩放 |
| frequencies_cm1 | 原始36个有序有限正数，必须等于blocks展开值和authority.frequency.frequencies_cm1 |
| molecular_mass_amu | {value, source_spans}；该section恰好一条合法正有限Molecular mass记录 |
| rotational_symmetry_number | {value, source_spans}；正整数，至少一条明确记录，允许重复同值并保存全部span，冲突或默认值拒绝 |
| rotational_temperatures_kelvin | {value, source_spans}；恰好一条、恰好3个正有限数，沿用现有非线性域 |
| point_group_diagnostic | null或{value, source_spans}；可缺失，出现时同值一致，只作诊断，不据此生成对称数或简并度 |
| gaussian_reported_thermochemistry | 原parsed.facts['thermochemistry']完整子集及原span，空mapping保留为空；不补零、不重算 |

每个新source_span使用现有七字段：artifact_kind、envelope_observation_id、logical_name、sha256、size_bytes、start、end；start/end为原日志bytes的半开区间，包含该行原始行结束符（若有），不可使用解码字符串偏移。span必须在已验证job_section内且引用同一source_artifact。

不在首包结构化温度/压力观察，以免引入尚未需要的解析规则；它们不会被默认为298.15 K/1 atm。后续科学政策绑定及观察值结构化另冻结。

## 5. 补充提取与旧入口保持

新增auto_g16/thermochemistry/_successor_facts.py，提供私有纯函数extract_successor_thermo_facts。其参数为raw_gaussian_bytes、source_result、minimum_authority、native_source、native_result，均由上节来源编排在受保护上下文中提供。

参数类型冻结为：raw_gaussian_bytes为exact bytes；source_result为exact auto_g16.result.ParseOutcome；native_source为exact auto_g16.core.Observation；native_result为exact auto_g16.core.Result；minimum_authority为闭合字段mapping。这里的native_source/native_result是完整Core对象，绝不是第4节输出中的同名摘要，也不能用其摘要恢复或代替对象。

函数调用现有parse_freq_source(native_source.data, raw_gaussian_bytes, parser_version="1.2.0")作纯重建；重建的Observation及Result必须分别与完整传入Core对象相等，包括ID、Attempt、type和data；重建ParseOutcome的完整payload及result_id必须与source_result分别相等。不新增parser规则，不只比较facts、外部摘要或自称的schema。持久化native Result.result_id/data hash采用既有v2域，ParseOutcome.result_id属于内部carrier域，两者不得直接要求相等，也不得相互替代。

minimum_authority.frequency.result_source精确绑定Core Observation.observation_id及payload_hash(Observation.data)；frequency.parsed_result精确绑定Core Result.result_id及payload_hash(Result.data)。输出第4节的native摘要仅从上述已完整确认的Core对象生成，parser tuple从已重建匹配的ParseOutcome生成。再检查minimum authority完整身份、schema/2、parsed状态、频率/energy/span、方法与tail证据关联。仅靠自称validated_minimum不能通过。

这次纯重建仍不能证明Core对象来自原始存储或已完成原生执行；编排调用方必须完成第3节原始重放和require_pair，不得将纯函数暴露为跳过来源重放的替代入口。

沿用现有_gaussian_thermo_facts的质量/对称数/转动温度/点群行语法及LF/CRLF的byte行边界语义，保留D/E科学计数法；垂直制表、换页、Unicode分隔等不得制造新行。section外标记不参与。格式异常、非法数值、重复质量/转动温度、冲突对称数拒绝。纯新模块可引用旧模块中的冻结regex，旧入口及其支持表/返回mapping不变；如果为清晰所有权需要改旧提取函数，先提交准确差异，不能直接扩大首包。

首包不改变现有_goodvibes、_service、models、final_integration的产品代码。数值迁移测试只调用现有builder与当前合成fixture，按独立评估表补充断言。

## 6. 允许变更路径（本合同接受后）

- 新auto_g16/conformer/_successor_thermo_source.py。
- auto_g16/conformer/frequency_readonly.py，仅提取共享私有重放上下文、保持旧读取行为并供新编排调用。
- 新auto_g16/thermochemistry/_successor_facts.py。
- tests/v31/conformer/test_successor_freq.py，新入口与旧Freq只读行为/来源拒绝案例。
- tests/v31/thermochemistry/test_core.py，数值迁移案例和纯补充事实案例；复用现有测试模块所有权，不增加未登记模块。
- tests/v3/query/test_native.py，仅必要旧query投影回归。
- OWNER_DECISIONS.md、config/context-map.toml，登记本次被接受的合同和组件。
- 新docs/v3/contracts/tasks/native-thermochemistry-source-adapter.md，版本控制中的唯一合同文档。
- config/validation-selection.json，仅将上述唯一合同路径追加到既有v3-control-docs.exact_paths；保留控制文件自身保护及现有conformer/thermochemistry前缀归属。

禁止修改：公共导出、Result parser/schema、旧authority /1与/2形状、Conformer模型/eligible生成、GoodVibes内核/依赖/数值政策、聚合生产函数、最终集成器、Core/Execution/Transport实现、HTTP/前端/注册表、当前安装、真实库或历史修订。

若现有来源API不能在上述允许路径内安全实现，先报告精确缺口并修订合同，不复制执行权、不通过通用callback或任意路径参数绕开。

## 7. 验收及测试迁移

1. 成功的全员合成Opt/Freq来源：新事实等于已解析事实/原日志字节；canonical顺序确定；无句柄或私有路径泄漏。
2. stage/Attempt/Project/成员/方法/parser/schema/tail/前驱/材料/存储pair/hash/span任何漂移拒绝。明确覆盖各自ID/hash自洽、但来自另一成员/Attempt的Core Result或ParseOutcome交叉拼接，不能只测试坏摘要。
3. 任一成员缺失、未完成、负频、零频、不是36模式、对称数缺失/冲突、质量/转动温度异常时整个包拒绝，不输出部分包。
4. LF/CRLF、D/E、段外/非LF伪标记、byte span准确性；点群缺失为null，原始7项可为空/部分；不能按truthiness吞掉0或负的原始热化学校正。
5. 原FreqReadout及Query成功和失败DTO逐项不变。后端仍是当前单一进程级Lock及30秒等待；两个并发调用的竞争测试不表示允许两个持锁reader，更不新增并发槽。验收旧部分成员Freq pending、negative-frequency authority及忙锁同时传入无效Attempt的优先错误不变；覆盖超时、异常关闭、pin漂移、只读数据库hash/物理身份，禁止嵌套锁和隐式重试。
6. NUMERICAL-TEST-MIGRATION.md四项建议按当前fixture迁移；逆序确定性等已有测试复用。全部为合成科学参数，真实anti/gauche没有选定政策。
7. 真实已捕获材料的只读输入重放可作为后续单独绑定的本地验收，但不自动执行真实库读取/写入、不把本合同变为操作窗口；使用现有证据先准备精确清单。无新增Gaussian或网络目标测试。
8. 当前selector决定实际离线范围。新合同登记涉及self-protecting配置，不能为减少测试绕过selector；精确候选冻结后指定一个全量owner。preflight、适用静态/兼容性/CI合同检查、敏感扫描及独立审阅按handbook执行。

本包并发读取helper涉及本地文件/SQLite资源生命周期：在合并分类时单独审阅其no-follow与锁行为，并准备适用的明确授权本地原生读取证据。合成测试或旧只读安装证据不能自动覆盖改变后的helper。不需要为此新增远程SSH/PBS/Gaussian测试。

## 8. 权限与下一决定

待接受的具体决定：同意本首包限于“完整来源重放 → 私有热化学输入事实”的接口/路径/验收边界，以及四类数值测试迁移；据已给出的继续开发指令推进限定离线实现与验证。

r1独立审阅发现输入对象身份域的合同缺口；r2将完整Core对象、内部ParseOutcome和最终摘要分开，并冻结旧reader兼容边界。r2增量独立复审与Owner对修订接口的确认完成前，不开始依赖实现；一般继续开发授权仍保留。合同审阅不替代后续实现审阅。

真实温度、标准态、低频方案/两个cutoff、频率/ZPE缩放、对称性/简并度、覆盖、方法科学认可和GoodVibes运行环境仍未决定。保留已有scientific-decisions.pending.json的null；本文件不修改它。无需为完成本首包提前选定这些值。

提交/推送/新PR/合并、安装、实际科学计算、集合资格提升和入库均不包含在本首包决定中。无自动重试、删除或清理。


## r2 修订记录

- 修复r1 extractor参数类型不明确：exact Core Observation/Result输入与ParseOutcome内部carrier身份明确分离；现有parser纯重建比较完整对象后才生成输出摘要。
- 明确旧read兼容：新增全员/正频/schema及补充事实条件属于新consumer，旧read仍保留selected/store/pair/slot和错误顺序约束。
- 明确资源退出先于最终返回；原生来源重放与纯重建的证明范围分开。
- r1及其既有摘要保留，不改历史记录。无产品代码、依赖或科学范围扩大。
