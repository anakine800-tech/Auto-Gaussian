# Auto-G16 原生热化学原始事实只读合同 r2

任务：NATIVE-THERMO-REPORTED-FACTS-01。状态：PROPOSED_FOR_OWNER_DECISION，OWNER-GUIDED、non-BUS。当前仅获准准备和审阅合同；本文件不自行授予实施许可。

## 1. 本次提请接受的范围

将已经留存、经原生Freq来源重放确认的7项Gaussian热化学原始事实接入原生列表/详情及页面，形成可独立验收的第一个开发包。本合同是前一份热化学整体方案的第一步；successor热化学资格、qRRHO、布居、派生集合入库与新的科学参数仍属后续合同。

本包不需要选择温度、标准态、低频参数、缩放或简并度。原始输出记录可以被展示，但不被提升为可比较自由能或科学验收。已观察298.15 K/1 atm/C1/转动对称数1仍不是被选政策。

基线固定：后端e0d239e41529649e25610eef6312d69714cf44e5，tree212dd063cc00b6aad292c62e21bf611ffd8b9ec8；前端a9f62ca20dfbceac41fd56b0f7b4f6e877f96e98，tree1588426a1e1191696a514ee29eb6f0e39dc255be。开工前重核基线和工作区，任何变化先说明差异，不默默重设。两仓库分别创建新隔离工作树及唯一codex/分支，属于同一个后端/前端配套任务，原始工作台和共享checkout保持原样。

## 2. 来源和消费者闭合

唯一新数据来源为现有FreqReadout在完整原生receipt/Opt/Freq/修订前驱重放后取得的parsed.facts['thermochemistry']。继续require_pair校验既有Source/Result，保留parser1.2.0和全部现有来源检查。不从HTTP提供路径、额外日志、手工表格、legacy GoodVibes页或查询层直接读取私有表重建事实。

复用原生parser现有7项白名单和每项value_hartree/source_span。不得新增解析规则、改Result内容/ID、重导入事实、改变Gaussian source/parsed schema、修改r4或提升eligible。旧thermochemistry adapter仍按原合同拒绝successor，不在本包修复其方法/authority兼容性。

## 3. 精确只读响应增量

保持路由和外层auto-g16-native-query/1不变。新版后端每个原生Attempt列表项与详情的facts中必须追加thermochemistry（含早退/不可用响应）；已有字段、来源和独立执行/验证/人工审阅轴不变。此处明确提请接受这一增加可选事实字段的API变更，不能从本合同准备状态推断已经获准。

该字段复用现有Field：availability、reason、source、value、unit。unit固定hartree。available时reason必须为null；旧后端字段缺省仅是前端兼容分支，不是新版后端的可选省略。来源可用时source固定为同一FreqReadout的Result:<parsed_result_id>，与provenance.parsed_result.parsed_result_id一致。

value仅可为既有parser白名单的子集，键固定为：
- zero_point_correction_hartree
- thermal_correction_energy_hartree
- thermal_correction_enthalpy_hartree
- thermal_correction_gibbs_hartree
- sum_electronic_zpe_hartree
- sum_electronic_enthalpy_hartree
- sum_electronic_gibbs_hartree

每个出现项原样携带且仅携带value_hartree（有限数值）与source_span。span沿用既有7字段：artifact_kind、envelope_observation_id、logical_name、sha256、size_bytes、start、end；完整日志身份与合法job_section范围由现有Result owner验证。不增造数值、补span或做单位转换。严格区分0、负数和缺失，不能使用truthiness判断数值是否存在。

availability规则：
- 有效已解析Freq至少有一个热化学项：available；保留实际子集，不以0填缺项。
- 有效已解析Freq的mapping为空：missing，reason=thermochemistry-not-recorded，value/source均null。
- 没有注册FreqReadout、非本合同支持的来源或事实未解析：unavailable，reason=thermochemistry-unavailable，value/source均null。
- 来源冲突、hash/span/pair/资格重放失败：沿用原有拒绝/HTTP错误路径；不得吞掉该异常而显示可用热化学。

内部FreqReadout投影增加同名字段：成功解析保留原mapping（可为空）；未解析为None。查询层仅使用已确认的FreqReadout投影；Opt及其他来源不尝试调用新来源接口。前端面对旧后端没有该字段时，显示“热化学读取未连接（unavailable）”，其余结果保持可用。旧HTTP路由、注册文件/schema与文件hash保持兼容，无需注册表迁移。

## 4. 页面验收定义

在既有原生项目Attempt列表和详情显示“Gaussian热化学原始报告”表，固定7行，中文名称分别为：零点能校正、热能校正、热焓校正、热自由能校正、电子能与零点能之和、电子能与热焓校正之和、电子能与热自由能校正之和。出现项显示原数值及hartree；missing项逐行标明缺失，整个字段unavailable时显示不可用原因。

保留来源Result、parser版本、日志SHA/字节span可查看；不得显示本机数据库路径或其他私有路径。页面明确提示：这些是Gaussian原始报告值，未绑定本页的可比较热化学条件，未作qRRHO/集合布居或科学验收。温度/标准态的新结构化归属在后续包处理，不能填入298.15/1atm作为默认值。

页面不增加ΔG排名、布居、温度选择器、导入/计算/运行按钮或后台自动重算。不是ThermodynamicEnsemble。既有并发2、原生120秒/普通15秒期限、导航隔离、显式错误和手动重试保持原实现。

前端须校验热化学字段有限值、白名单、项/来源span结构；未知项、非有限值、类型错误或错误来源不展示成有效数值，在该卡片显示invalid-thermochemistry-fact，不伪装成missing或0。其他原生事实维持各自状态。

## 5. 允许变更位置（接受并授权后）

后端：auto_g16/conformer/frequency_readonly.py、auto_g16/query/native.py；针对性扩展tests/v31/conformer/test_successor_freq.py和tests/v3/query/test_native.py。只允许为登记已接受合同而更新OWNER_DECISIONS.md、config/context-map.toml，并新建唯一合同文档docs/v3/contracts/tasks/native-thermochemistry-reported-facts.md。config/validation-selection.json仅允许将该文档完整路径加入现有v3-control-docs.exact_paths；这是本合同明确提请接受的单路径验证归属登记，不得更改选择算法、lane、safety级别、自保护规则或其他路径归属。按现有控制文件验证规则检查该登记。不得另增未列明提案文档路径。

前端：web/src/native-panel.tsx、web/src/native.css；tests/test_native_http.py、web/tests/native-frequency.spec.ts、web/tests/native-navigation.spec.ts及必要的纯合成fixture；发布说明可记录本次新增事实。若发现必须修改新路径、API版本、依赖、存储模型或行为范围，先给准确差异并停止扩展。

禁止改动：Result parser及schema、执行/传输/审批/Core存储写入、Conformer身份与eligible、thermochemistry kernel/模型/旧方法边界、GoodVibes依赖、注册文件、当前安装文件/launcher、私有业务库。无SSH/PBS/Gaussian操作、无现有库迁移或清理。

## 6. 验证及证据复用

开工按仓库handbook完成只读preflight，验证按实际变更选择；PR/发布交接前运行适用audit_ci_contract。两仓库分别留存精确base/head/tree。未知路径或验证控制缺口不能用直接扩大测试/跳过校验绕过。

最小验收：
1. 对现有anti/gauche捕获只读重放，7项数值与span逐一等于现存Result；原库hash/物理身份、r4及eligible不变。已有捕获不触发新作业。
2. 合成已解析全量/部分/空mapping，0和负值；无readout/未解析，验证missing/unavailable稳定。
3. hash、Result来源、span、成员或前驱漂移必须沿用owner拒绝；查询不得绕过原replay。
4. HTTP列表与详情相等、无路径泄漏、写入方法拒绝；旧无字段响应、V30/Opt/其他原生来源回归。
5. 浏览器覆盖7行、标签、单位、来源、missing/unavailable、错误卡片与导航隔离；重用已有期限单测，仅有影响时补跑。源代码未变的GoodVibes内核不重跑、不安装。
6. 作者自审及独立只读审阅零阻塞；按selector完成必要验证，不把旧全量或合成UI当安装/真实页面新验收。

归类为只读Result投影/展示增量，不改变target执行、传输、调度或原生进程安全行为。是否需要新target证据仍按handbook做最终分类；本合同不授权target测试。真实工作台部署和页面验收等源码候选完成后另行形成精确安装包。

## 7. 自治、权限与停止条件

当前状态只到合同审阅。下一项可请求的Owner决定为“接受本合同并授权限定离线实现、验证与独立只读审阅”。这项决定若获准，仍不包含提交、推送、PR、合并、安装或真实计算；按实际后续授权一次登记并连续执行，不重复索取已授权限。

实施修复预算遵循当前默认4轮或30分钟活跃诊断/编辑，先到即停；等待测试/审阅不计。安全/科学边界、源身份变化、范围/依赖变化立即停止并说明。不存在以测试成功替代授权的路径。

## 8. 后续热化学闭环的独立交接

本包完成仅表示原始报告可读。后续仍须另行冻结successor authority/2与parser1.2适配、wB97XD方法兼容、资格/覆盖与精确前驱链、新不可覆盖ThermodynamicEnsemble记录及登记读取；复用现有内核和final_integration，而不是放宽旧schema。

温度、标准态、低频方案和两cutoff、缩放、对称性/简并度、覆盖、方法和实现环境仍待科学决定；scientific-decisions.pending.json保持null。本合同的接受不能被解释为这些参数被默认接受或允许对真实anti/gauche计算qRRHO/布居。

## r2 审阅修订

闭合r1独立只读审阅的P2：固定唯一合同文档路径并限定其验证归属登记；明确新版所有Attempt响应必有字段及available.reason=null。r1原件保留。该修订仍仅为待接受合同，不是源码实施或控制文件修改。
