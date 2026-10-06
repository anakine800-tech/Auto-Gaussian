# Auto-G16 原生 Freq 最小增量提案

状态：待 Owner 接受，审阅修订 r2。仅为离线设计候选，不是运行或安装批准。
基线：main b5f65f6c105a30c416e05dc88e57f7f84e573a08 / tree 5db62a11d7a091c4ca40a98dcacabda8401f0470。
任务范围：已留存 n-butane anti/gauche 两个原生 Opt 结果的纯 Freq 后继；OWNER-GUIDED、非 BUS。旧 UNKNOWN 保持封存。当前用户已授权离线候选和实际缺口分析；本提案的版本化执行/科学语义增量需另行接受。

## 1. 当前事实与缺口

1. execution/program.py:238–242、340、439–440：adapter6/Q7 明确仅 Opt；旧 /3–/5 虽支持 freq，419–420 拒绝资源 Link0。不得删资源、重标为 opt 或修改 /6 的历史语义来绕过。
2. execution/_gaussian_result_source.py:27–30：原生结果来源仅接受 Opt。当前 import_opt_result_revision 不能消费 Freq。
3. ScientificValidation 公共最低点分类要求同一 Result 内 Opt/stationary 证据；纯 Freq 不具备。1.2.0 的既有私有豁免仅是 Opt。
4. Conformer 旧两阶段最低点 authority 存在，但绑定旧 PreparedInputBinding/Result/SV/Review 且方法域不是当前 wB97XD；不可伪造旧代记录。
5. 当前 owning readout 固定重放 Opt；通用频率显示位置可复用，但需要真实 Freq/两阶段投影来源。

## 2. 科学候选保持不变

继承已显式选择的 loose 协议（协议含 minimum_optimization 与 frequency），不重新选方法：wB97XD/Def2SVP、restricted closed shell、气相、intrinsic dispersion、charge 0/multiplicity 1、Tight SCF/MaxCycle128、UltraFine、NoSymm。

纯 Freq 输入是同成员 freshly replayed Opt authority 的最终 Cartesian。14 原子及映射顺序逐项相同，坐标从输出保留的六位小数精确往返，无额外舍入。只将已选 Opt token 替换为 Freq。无 Link1、%oldchk、Guess=Read、Geom=Check/AllCheck、ReadFC 或环境文件依赖。

资源候选：Gaussian 12288 MiB/8 cores，PBS memory_mb=16384/8 cores，headroom_mib=4096；单并发，anti 验收后 gauche；每个 3600 秒作为有界试运行上限，不是 Freq 耗时预测。温度 298.15 K、1 atm、未缩放谐振频率与 RRHO 仅为原协议诊断范围，不执行 qRRHO、布居或热力学提升。

## 3. 版本化资源执行增量

拟新增且只接收 stage=freq 的 tuple：adapter7 / Q8 / material9 / prebinding10 / scheduler10 / deployment8 / v31-gaussian-freq-resource-bootstrap-v4.py。合同 domain 为 V31-GAUSSIAN-FREQ-RESOURCE-01/binary-MiB-explicit-headroom-v1 加 LF。新 source bytes、contract digest、Q/profile/material 身份在实现冻结后生成；本提案不虚构这些哈希。

program_data 闭集仍为 stage、completion_mode、gaussian_resources；stage 固定 freq，completion_mode 固定 receipt-on-absence-v1；gaussian_resources 严格是正整数 memory_mib、cores、headroom_mib。沿用逐层验证 input cores == scheduler cores、memory_mib + headroom_mib == scheduler memory_mb。

新路线闭集仅对应已选的 wB97XD/Def2SVP Freq SCF=(Tight,MaxCycle=128) Integral=UltraFine NoSymm。必需且唯一 Link0：%chk=gaussian.chk、%mem、%nprocshared，单位语义继承 Q7 二进制 MiB。拒绝额外关键词、坐标读取、组合 Opt/Freq、外部文件、额外 Link0、重复字段和无界输入。

复用既有 Project、fresh Attempt/no-overwrite、descriptor/no-follow、单次 effect intent、scheduler/receipt/capture、封闭环境、暂态传输及有界回收机制。不重建 Project、不重试 UNKNOWN。所有历史 adapter3–6/Q4–7 的输入接受域、生成字节及身份规则不变。

受影响生成源必须重新形成精确安装候选。未变传输/文件载体/回执资格按源码差异与证据映射复用；涉及新 tuple、资源和原生装载行为的安全声明需要相应明确授权的目标增量验证。离线模拟不能代替该证据。按 handbook 分类处理合并前证据；不得把待补目标证据伪称为通过。

## 4. 来源、解析与不可覆盖存储

Execution 增加明确的私有 Freq reader，限制上述新 tuple/stage=freq；复用原始 success proof、capture 和源 qualification。拒绝 mixed-generation、错 Attempt/Snapshot/spec/input/log、未知或拼接 tuple。Execution 不导入 Result、SV、Conformer，不推导科学结论。

新增私有 v31-gaussian-result-source/2：继承 /1 的全部封闭字段，仅新增 stage，值固定 freq。新增 v31-gaussian-parsed-result/2：沿用 /1 的封闭字段与语义，但 schema/来源必须精确指向 Freq /2；新语义 ID domain 分别为 v31-gaussian-result-source-v2 与 v31-gaussian-parsed-result-v2。旧 /1 不改变。

Result 复用 auto-g16-v3-gaussian-job / 1.2.0 / gaussian-job-facts 精确字节解析和 span；不新增平行 parser、不制造 V30 provenance。Result 不导入 Execution/Transport/SV。组合 owner 从 Execution 获取已验证 bytes；每次读取完整重放并比对所有 payload、事实、诊断、span，而非只信自洽 hash。

复用已接受的存储语义：原 Core/Transport/Opt 解析库只读；显式目标 Freq Core 快照必须有真实同一 Project/Task/Attempt/plan/spec/snapshot/intent 历史。仅在内存 append 新 source/parsed pair，然后独占发布新文件。对目标/source 的全记录和物理身份审计、别名拒绝、冲突拒绝、幂等与部分记录恢复规则保持；不得复制 Opt Attempt 冒充新 Freq 历史。无 Core schema 迁移。

## 5. Opt→Freq 联合科学证据

新增私有、非公共 V30 的 v31-conformer-successor-two-stage-minimum-authority/1。封闭顶层字段：authority_schema、source、method_binding、method_id、optimization、frequency、assessment、two_stage_minimum_authority_id。

source 复用既有 ensemble/member/species/map/stereochemistry 精确绑定。optimization 是完整的 freshly replayed v31-conformer-successor-opt-authority/1。frequency 闭集：calculation_plan、input、result_source、parsed_result、selected_geometry、frequency_blocks、frequencies_cm1、mode_count；相应 plan/input/source/parsed 结构沿用现有 Opt authority 的绑定结构，指向新 Freq 记录。assessment 闭集：classification、reason_code、validation_policy；policy 固定 v31-successor-two-stage-minimum/1。ID 用 canonical payload（去自身 ID）及独立 schema domain 推导，遵循现有语义 hash 算法。

纯函数 ScientificValidation 拥有 Freq fact 检查及分类型结果，不读原始文件、不自行 parse、不合并事实数组。Conformer 组合层关闭两个独立来源后建立联合 authority；不把 Opt marker 注入 Freq facts。

方法一致性比较明确的 stage-independent 科学字段，不要求 Opt route_contract_version 与新 Freq route_contract_version 相同；两份完整 route/input 均分别精确验证。Freq input 的 atom-order/Cartesian 必须逐项等于 Opt selected geometry。Freq 几何选择由新的私有 ScientificValidation 纯函数明确拥有，parser 仅提供全部 geometry_blocks，不假定 parser 已选出几何。规则如下：

- 所有候选 geometry/frequency span 必须属于同一精确 source artifact 与唯一 job_section，长度正、边界内、身份闭合；无法关联或 span 冲突是 provenance 边界拒绝。
- 从该 job_section 的完整 Input orientation blocks 中，选取 end 不晚于第一个 frequency block 的 start 的块；其中 start 最大者必须唯一，作为 selected_geometry。重复同 span 或无唯一最大者拒绝。没有频率块时先分类 INCOMPLETE/incomplete-mode-count，不生成 positive authority；已有频率但没有上述几何时为 INCOMPLETE/missing-frequency-geometry。
- selected_geometry 的14个中心序号须为1..14，元素与输入逐项相同，六位小数 Cartesian 必须与 Freq 输入及 Opt authority 精确一致。不使用 RMSD 或近似容忍放宽输入身份。
- 审查同一 job_section 的所有其他 Input orientation blocks（包括频率之后的块）：必须均完整并有相同中心序号、元素和 Cartesian。只要存在不一致、截断或无法关联，整个几何关联失败；不允许从有利子集选取。冲突为 provenance/geometry 边界拒绝，保留原始事实但不产生 positive authority。
- 其他 orientation 类型不作为本域的输入几何替代；正常终止或已有 Opt authority 都不能补造缺失的 Freq Input orientation。

检查顺序：来源/方法/几何不一致为边界拒绝，不产生 positive authority；不完整 capture/parse/终止为 INCOMPLETE；不支持 tuple/domain 或多于36模式为 UNSUPPORTED；少于36模式为 INCOMPLETE；完整36个有限连续模式中任何 value < 0.0 为 NOT_MINIMUM（无小负频容忍）；其余支持证据为 VALIDATED_TWO_STAGE_MINIMUM。纯 Freq 不可有 Opt/stationary marker。不得从有利子集、多个结果或多个 Attempt 拼频率。非有限/非法模式按 parser/边界失败保留负面证据。

本域固定14原子非线性中性闭壳层 n-butane。无更广方法、线性分子、TS 或反应路径语义。最低点 machine evidence 不是 ScientificAcceptance，也不触发 thermodynamic_eligible_members 或 ts_seed_members。精确零频沿用既有 <0 阈值，需在人类验收中明确展示，不自动隐藏或替换。

## 6. 集合与查询

新增私有 successor 两阶段分支，保留旧 V30 及 Opt authority 分支。成功成员可在新不可覆盖 ensemble revision 中标 validated_minimum，并带新的 authority schema；未执行成员维持 optimized_frequency_pending；负频/不完整保留相应证据和未通过状态。保留 supersedes、两个成员的 lineage、native connectivity/stereo audit 及 dedup，严禁只留下成功成员。

Freq owning reader 负责复核 Opt 与 Freq 原始资格和完整来源，再产生 detached DTO。固定启动登记的新版本显式绑定两阶段源；保留既有登记版本，不允许 HTTP 传数据库路径/权威 payload，不增加执行按钮。Query/UI 显示 cm^-1、频率数/负频数、parser版本、input/log摘要、Opt/Freq Attempt关联及分别的执行/科学状态。回归同进程并发和有限等待；跨进程 Transport 互斥不放松。

## 7. 最小验证及实施边界

接受后在独立 worktree/codex 分支实施。初始路径仅 Execution/Transport 的 Gaussian tuple与封闭资源接线、Result 私有来源/记录、SV私有两阶段facts检查、Conformer/Query owning reader、对应前端登记与展示、测试和版本化合同/context-map。不得增加平行执行器、Approval 系统、Core schema 或更宽计算功能。

验证复用当前 Opt、Q7、来源只读和 parser 证据。新增覆盖：Freq新tuple正例及所有旧tuple字节/拒绝域兼容；资源与生成源错配；真实Opt几何到草稿闭合；错成员/映射/方法/坐标/来源代际拒绝；缺失/重复/跨块/非有限/负频及模式数；伪造自洽解析payload拒绝；source readonly/同inode/符号链接/不覆盖修订；部分集合进度；query单位/来源/缺失状态及并发归属。测试不得发起 SSH/PBS/Gaussian。

离线实现与审阅通过后，再按变更证据映射准备精确源 commit/tree、Q/profile/material、实际 loader、安装清单与验证。候选 GJF 可先行冻结，但 Spec/Snapshot/intent/运行窗口需在其依赖闭合后才能生成真实绑定。

接受本提案建议只授权实施、离线验证、只读独立审阅和精确安装/运行包准备。提交/推送/PR/合并、安装、目标验证和实际 Gaussian 作业仍各按用户明确授权执行。新窗口必须明确 anti 首次提交及验收门槛；gauche 仅在 anti 通过后串行执行。不自动重试、改方法、qdel 或清理。
