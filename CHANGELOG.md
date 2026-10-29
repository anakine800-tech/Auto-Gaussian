# Changelog

## v4.7.0

### 发布准备状态与范围

**发布候选，尚未创建 tag/Release 或部署。** 功能基线为 `7dba69194e0093dca955b98d9220653f8dd7e038`；
相对 v4.6.3 的 first-parent 清单恰为下列 21 个后端 PR，Git 合并对象与 GitHub 合并状态已逐项核对。
T176 已完成独立格式/数值验收、代码审阅与最终 HEAD CI 并合并；T163 保留为历史设计，
实际导入能力及限制以 T176 为准。T178 仅整理版本与文档，不新增产品功能。
本次发布验证见 [T178 记录](docs/redesign-tasks/T178-release-v4.7.0-backend.md)；T177 最终配套在 T178 合并后完成。

| 后端任务 | PR | 确切合并提交 |
| --- | --- | --- |
| T154 入口默认档位 | [#351](https://github.com/anakine800-tech/Auto-Gaussian/pull/351) | `751f6b6d9ba4c141159ae4f2c6b6d006061cfd21` |
| T155 路由 walltime 与容量 | [#362](https://github.com/anakine800-tech/Auto-Gaussian/pull/362) | `20840ee7a51dae4e4da1c75dd6eef63052d47802` |
| T156 单节点容量 | [#354](https://github.com/anakine800-tech/Auto-Gaussian/pull/354) | `5bef4daede45f5bf10e064ec9a07a2fce769aa14` |
| T157 具名 PBS 共享准入与排队 | [#361](https://github.com/anakine800-tech/Auto-Gaussian/pull/361) | `e109019b3028aad75fb434b5eafce1633af72aca` |
| T159 CREST 取回与诊断 | [#357](https://github.com/anakine800-tech/Auto-Gaussian/pull/357) | `ebf711cafc934b15c6b045582e69511752117e53` |
| T161 G0 批量局部错误 | [#352](https://github.com/anakine800-tech/Auto-Gaussian/pull/352) | `e9e2f5b8fa2e7e78b668f55e58245f83d9668ddb` |
| T162 G0 原子对应来源 | [#359](https://github.com/anakine800-tech/Auto-Gaussian/pull/359) | `a921a48750fe2426c06694ef75a3d2fc4bc11a89` |
| T163 Hessian 来源与导入规格（仅设计） | [#355](https://github.com/anakine800-tech/Auto-Gaussian/pull/355) | `a3cc131b8935a208c29bc70c3463cb4334195ae3` |
| T164 父 checkpoint 证据报告 | [#358](https://github.com/anakine800-tech/Auto-Gaussian/pull/358) | `b6dc3cb81b1b43ae4521503e73923ca5d7ad196d` |
| T165 SMD 片段单点组合 | [#356](https://github.com/anakine800-tech/Auto-Gaussian/pull/356) | `df5d0413b00bc64eaf8db5a866892eccc285bb42` |
| T166 TS 卡片拆分与指南整理 | [#360](https://github.com/anakine800-tech/Auto-Gaussian/pull/360) | `488903eb26c3bac42d11bed4356b01758f0fd17d` |
| T167 历史 unreadable 调查 | [#353](https://github.com/anakine800-tech/Auto-Gaussian/pull/353) | `780f1f227132d415142566a66b03497bb644ab15` |
| T168 开发/部署说明统一 | [#367](https://github.com/anakine800-tech/Auto-Gaussian/pull/367) | `7304ffe89db9bdb58af608f827db4cc49b3f68ed` |
| T169 卡片快照、SP、预算与资源说明 | [#366](https://github.com/anakine800-tech/Auto-Gaussian/pull/366) | `806110cf02201fc0e6afa916cc428ea1a8440867` |
| T170 构象分支与结构入口 | [#368](https://github.com/anakine800-tech/Auto-Gaussian/pull/368) | `812a1b4c27f5898b0244532f86a4cfa0af4bce98` |
| T171 ChemDraw 私有输出 | [#364](https://github.com/anakine800-tech/Auto-Gaussian/pull/364) | `8545600831ee1086f2f0d1dd26bce3a67a47012b` |
| T172 现行公开扫描器范围 | [#363](https://github.com/anakine800-tech/Auto-Gaussian/pull/363) | `bc0b2a99b70e64728ab8ad3eb98610bf3e347e01` |
| T173 方法先例定位与学习引用 | [#365](https://github.com/anakine800-tech/Auto-Gaussian/pull/365) | `f46660a17b3062d8eaf09168eed74080242e6cf0` |
| T174 历史来源与动力学说明整理 | [#369](https://github.com/anakine800-tech/Auto-Gaussian/pull/369) | `c73298d3acbd1d7795be0cea38ab40af8e4892af` |
| T175 缺失分类与回执读取修复 | [#370](https://github.com/anakine800-tech/Auto-Gaussian/pull/370) | `c1a0d084fd5f53d1fb4ab15dd3c57c12ad447a8f` |
| T176 本地 xTB Hessian 导入与 G0 来源 | [#371](https://github.com/anakine800-tech/Auto-Gaussian/pull/371) | `7dba69194e0093dca955b98d9220653f8dd7e038` |

配套前端 v4.7.0 由 T177 准备，汇总已合并的 [T158 #49](https://github.com/anakine800-tech/Auto-Gaussian-Frontend/pull/49)
默认资源、容量与具名节点反馈，以及 [T160 #50](https://github.com/anakine800-tech/Auto-Gaussian-Frontend/pull/50)
CREST 诊断来源展示；两项历史功能基线为 `fa48ab1a0c0d669233a189bb5457b143d07dd798`，不代表当前前端 main。
本批另纳入已合并的 [T179 #52](https://github.com/anakine800-tech/Auto-Gaussian-Frontend/pull/52)，合并提交
`8ceda045b1aa007c9dba882f287b11b4df12b840`：前端构建工具 setuptools 精确固定为 84.1.0，
对应 [GHSA-xmj3-9gf7-h52w](https://github.com/pypa/setuptools/security/advisories/GHSA-xmj3-9gf7-h52w) 的修复版本。
T179 未改前端运行代码或产品版本，T178 不修改后端依赖；T177 已整合该修复，最终配套仍使用 T178 实际合并源码。
上述提交均不是未来的 T177 发布合并 SHA。T179 的既有验证为 Python 203 passed / 2 个可选配套 skip、
浏览器 362 passed、四项 CI 通过；这些跳过不计为 T177 最终后端配套通过，也未声称做过 Windows 现场复现。

### 行为与兼容边界

- **资源与路由（T154–T157）。** 新 prepare 可省略 tier，仅采用已选入口明确配置的 `resources.default_tier`；显式选择优先，无默认仍拒绝。默认解析早于节点映射、编号和目录分配，旧 manifest/bundle 不改。route 仍要求显式 tier，并核对提供的 walltime；未提供时限、未配置上限或快照过期均说明未知。容量同时检查同一节点的 CPU 和精确申请内存；已证实总规格不适用的入口不进入排队回退。具名 PBS 正常占用或具名排队不再一律拒绝，身份、状态、总规格、一致性和两次提交复查仍保留；半数/四分之一按总 slots 映射，不自动换节点。建议不保证启动时间。
- **核数和本机默认。** 单作业、运行加排队及可选排队上限分别生效；同一实际集群的入口合并全部本人作业与本地未观测预留，总上限取各入口 `max_committed_cores` 的最小值，已配置的排队上限同样取最小值；单作业仍核对所选入口的 `max_cores`。未知预留不释放，Slurm 台账完整性仍检查。ag 不设置调度器运行限额，运行核数可达到 committed 上限。各机器实际档位和默认值属于私有部署配置，不是本版为所有用户设置的生产默认；发布不改配置。
- **CREST（T159）。** 新普通 CREST/mdopt manifest 以 `crest_output_set=diagnostics-v1` 固定新增调度器输出集合；旧 manifest、旧不完整取回记录和 bundle 不扩写。错误、警告、正常标记及未知信息分开，来源记录本地文件哈希与行号；构象解析失败仍保留诊断但返回失败。缺日志不等于正常，不自动补取或刷新；前端 T160 读取已保存来源并校验哈希，不触发远程诊断。
- **G0（T161/T162）。** 明确的频率分段歧义及可定位到候选的映射声明错误保留其他成功项，批次返回 2，整批不登记；完整性错误仍停止。reference/frequency 的显式双射分别绑定候选、目标源字节和段范围；缺有效 frequency 映射不投影，声明通过不证明化学身份。Gaussian 来源及批量自动选取规则保持原样；G0 仅诊断，不替代 DFT、TS/IRC 或科学签字。
- **本地 xTB Hessian（T176）。** `ag import-xtb-hessian --study <study> --source <local-source.json> --out analyses/<new-dir>` 只读已有本地来源，独占生成分析；不计算 Hessian、不连接远程、不改 Attempt。有限支持 conda-forge osx-64 `xtb 6.7.1 gfortran_h7141999_5` 的普通非线性、非周期、无约束 GFN2 CLI 路径、默认有效质量与 scale=1，其他构建和变体不据此宣称支持。保留完整带符号谱，按几何和打印精度区分外部空间；无法可靠区分时不给可用模式。g98 校验按 writer 的可见频率子集，不丢弃内部软模式。单候选显式使用 `--modes-analysis analyses/<dir>/analysis.json`，与 `--modes-attempt` 互斥；重新核验来源、结果字节及特征系统，沿用来源绑定的 1-based 原子双射，只转换 Bq 的原子索引，不伪造 Gaussian Attempt。科学信息未知保留警示，数学必需来源缺失、损坏、矛盾或已知失败不能发布可用模式；正常结束不证明驻点。接口及格式见 [本地导入说明](docs/research/xtb-hessian-import.md#8-t176-本地导入接口) 和 [G0](docs/g0.md#模式投影)。
- **本地报告（T164/T165）。** 父 chk 报告区分真实频率段、坐标框架和历史 checkpoint 关联；不读取 chk/fchk，内部力常数仍未验证。CP 可组合已有同几何、自身基组的两个 SMD 片段单点；缺项保留 null，齐全时给出相互作用能及加气相 BSSE 的近似值，不是结合自由能，也不进入 thermo/profile。
- **远程观察（T175）。** receipt 和普通 output（含 Multiwfn）以固定助手区分 ENOENT 与不可核实错误；回执在读内容前固定文件身份，拒绝替换、链接及非普通文件。新增远端 Python ≥3.6 和 Linux O_PATH/O_DIRECTORY/O_NOFOLLOW/O_NONBLOCK、dir_fd/no-follow 能力要求；缺能力明确失败，不静默回退。回执格式、文件白名单、4096 字节上限和既有 UNKNOWN 规则不变；strict incomplete 及其结束证据规则未改。T167 的历史根因无法判定，与本次两个独立复现缺陷的修复分开。
- **Skills 与文档（T166–T174）。** TS 拆为初猜、搜索/Freq、IRC 阶段；卡片快照、筛选 SP、资源和核时台账说明对齐实现。构象可选先统一 xTB 或仅几何合并后统一 DFT，禁止跨来源混用低层能量；mdopt 不算独立来源。ChemDraw 研究输出留私有目录，方法 SI 仅补可核查定位，历史链接指向冻结来源而不恢复旧规则。方法、基组、能窗和科学适用边界未扩大。

### 已有验证与未覆盖范围

下表引用既有执行证据；T178 本身未连接集群、部署或运行计算。功能 PR 的测试不能替代本次最终发布 HEAD 的回归和 CI。

| 项目 | 已有证据 | 不外推的范围 |
| --- | --- | --- |
| T156 Slurm 节点格式 | 两个获批入口各一次固定查询，节点 CPU/内存字段解析通过，绑定代码与合并版本相同 | 只证明当次格式，不证明所有现场容量或实际调度 |
| T157 具名 PBS | 空闲节点合法选项可选；占用节点因作业/节点不能匹配保持 unknown；两次现场读取非原子 | 权限限制只是待核解释；本人/他人共享、具名排队、enough/queue、仅内存未知可选、并行运行及提交位置验证未全部覆盖 |
| T159 旧取回兼容 | 旧普通 PBS 四文件、Slurm 五文件正式取回成功，哈希一致；相关代码/旧现场 blob 兼容已在当前基线复核，相关回归 290 passed / 1 skipped（本机非 Linux GNU stat） | diagnostics-v1 与 mdopt 的正常计算方案仅为可选补强，尚未执行；不完整取回、真实程序/调度错误等待自然样例，不制造故障；原工单最低实际取回要求已满足 |
| T175 回执与普通输出 | 原 10 次观察后新增 8 次获准调用，各一次、无重试，全部通过预定判据；helper 现场证据现覆盖两个 PBS 和两个 Slurm 入口。新增 Slurm 双回执及 5 输出、PBS Multiwfn 隔离副本 status 的双回执/规范作业缺失/17 输出，以及 PBS xTB 3 输出；原控制文件、journal 和配置哈希不变 | 新增 7 条 helper 返回 0；qstat 返回 153 按正式协议识别已结束作业记录缺失，不能泛称全部 rc=0。声明输出仍全部存在；未测 PBS 入口、完整新作业生命周期及自然 output absent 未覆盖，权限/替换/I/O 负例仍为本地及 Linux CI 证据 |
| T167 历史事故 | 回退后指定观察恢复；两个独立复现缺陷由 T175 修复 | 关键底层诊断未保存，历史根因无法判定；不声称原事故已复现或根因已查明 |
| T176 Hessian | 同次真实非研究水包及脱敏 fixture 的独立格式/数值、公开数据审阅通过；三个内部频率约 1538.8984、3642.6655、3651.1643 cm⁻¹，与独立重建一致，完整九维带符号谱保留。最终 head `e722d9887e288015ebd4630afa4ee9c1a1e485b7` 两路独立代码终审与五项 CI 通过；Linux 后端 6385 passed / 2 skipped，Skills 527 passed，扫描 1896 文件零错误 | 小分子来源/格式和算术验收不证明其他构建、复杂体系、科学驻点或机制。原水包由协调方另行获准生成；T178 未执行该计算，未新增 Hessian 生成、上传或取回能力 |

自然错误、自然缺失和全部共享正例不额外变成无界扩大的发布条件；发布声明必须对应已观察范围，实际新失败仍按原停止条件处理。
T175 原始停止记录和受审续行保留，最终执行/测试详情见 [实现与验证记录](docs/research/observation-read-safety.md)。

### 升级、回退与发布顺序

1. 本版不自动迁移配置、study、catalog 或旧 Attempt，不修改既有输入、事实、哈希与签字。旧配置无 default_tier 时继续显式选档；实际资源值由负责人在本机设置。科学工作仍限已验证的主族闭壳层流程，局部数值或格式验收不扩大体系适用性。
2. 获准升级前按 [OPERATIONS](docs/OPERATIONS.md) 保存两仓确切提交、依赖、构建、配置和服务恢复信息；核对实际导入与所有版本元数据。后续回退恢复相容配置和环境，保留新增诊断输出、报告和原始证据；旧版不能安全理解的记录不交给旧版写入，不删字段或重写哈希。既有 catalog v2 不可降级、节点/资源配置兼容要求继续适用。T176 的 analyses 与源文件原样保留；缺少该适配器的旧版不能导入或重新核验此来源，不把分析改写成 Attempt 或让旧版重写其派生记录；原 Gaussian 来源接口保持兼容。此为恢复边界，未执行现场回退。
3. 顺序为 **T176 合并 → T178 独立审阅、最终验证并合并 → T177 使用实际 T178 合并源码完成配套验证并合并**。协调方随后记录两仓真实发布合并 SHA、版本、CI 与配套结果；本 PR 不预填未来 SHA，不用 CI 中跳过的配套用例冒充完成。
4. 本阶段不创建 tag/Release、不部署。准备完成后仍由用户明确决定发布；两个同号 tag 只能指向各自发布 PR 的确切合并提交。运维顺序、核数阈值、首轮/心跳、停止条件和计算批准均不变。

## v4.6.3

### 发布范围与配套

本版仅汇总 v4.6.2 之后已合并的后端 T148–T150；T152 同步版本、已有断言和文档，不再实现功能。配套前端 v4.6.3 由 T153 独立准备，汇总 T147 的 Slurm Other/Idle、未知 notes 去重、拒绝后不快速轮询、睡眠后等待提示与暂停文案修补，以及 T151 的请求终态反馈。

| 后端任务 | PR | 确切合并提交 |
| --- | --- | --- |
| T148 PBS 监控准确性 | [#347](https://github.com/anakine800-tech/Auto-Gaussian/pull/347) | `830ce69e69ff3559bbc72ab603fe3a7ed3e8eb43` |
| T149 请求追踪与配置重读 | [#349](https://github.com/anakine800-tech/Auto-Gaussian/pull/349) | `06f3dfe2d4a62452bbd003a51cd3472c427834a1` |
| T150 新输入资源补齐 | [#348](https://github.com/anakine800-tech/Auto-Gaussian/pull/348) | `8011bccce078439cc8c80bd0790ec532c40d1a04` |

### 行为与兼容边界

- **PBS 监控（T148）。** 重复完整节点名使本轮硬件容量未知，不再重复累计；作业与额度的独立成功结果保留。时区异常时，在排序前清空本轮依赖配置时区的开始/提交时间及直接异常的开始时间，其他可信绝对时间保留；耗时退回 walltime。唯一短名/全名匹配仅辅助只读内存归属，不放宽具名节点定向提交的精确身份核验。
- **重试与配置（T149）。** 默认 JSON 仍严格为 `entry/result/reason/requested_at` 四键，显式 `--track` 才增加请求标识；按入口、来源与标识关联真实发布结果。`auth_confirmation_required`、`entry_removed`、`config_changed` 表示待处理请求未执行；`monitor_restarted` 表示监控重启后本次结果尚未确认，重启前 running 可能已经查询，没有可确认的发布完成结果，不能断言从未执行。丢弃不等于作业取消，不重放遗留请求、不制造采样快照。配置按元数据缓存并保留 30 秒兜底完整重读，首次比较使用启动配置；未改配置不会因首次建立 transport 而误丢请求。串行采样、退避和暂停规则不变。
- **新 Gaussian 输入（T150）。** prepare 仅在缺失时按人已选档位补 `%nprocshared`，随后沿用 R1 内存规则；显式非法、重复或冲突值仍拒绝。完整合法的普通 Gaussian 输入逐字节保留，gaussian-cp 沿用既有片段转换。`auto_nprocshared` 仅实际补齐时记录，输入与 bundle 哈希绑定补齐及既有转换后的最终保存字节；源文件、旧 Attempt、manifest 与旧 bundle 不重写。补齐不自动选择方法或资源，不授权提交、不自动提交。
- **当前说明。** T149 共用字段第 6 项澄清重启语义，字段、状态枚举、CLI、磁盘格式与运行逻辑不变；T153 同步 T151 后再比较完整共用字段块。当前待办移除已完成 T146 和本批已解决项，保留 T127 transport 重复逻辑、串行采样、睡眠恢复及其他未解决事项。前端运行时版本显示由 T153 修正，配套验收同时核对 Python 包元数据、运行时和网页包。

### 验证与发布边界

本次仅离线合成与发布准备验证；未新增现场查询、未部署、未运行真实计算。准确 PR HEAD 的全量测试、PBS/Slurm 字节回归、有效本机词表扫描及 CI 结果记录在发布 PR，不借用功能 PR 的旧结果。

T152 先交监督复核，再由负责人合并；T153 最终配套验收使用 T152 的实际完整合并 SHA。两个同号 tag/Release 只能在后续明确授权后指向各自发布 PR 的确切合并提交，不以届时 main 代替；本次不创建它们。部署另行批准，依 [OPERATIONS](docs/OPERATIONS.md) 和每台机器私有维护安排执行，不能由版本号推断真实状态。节点策略、资源限制、审批、首轮/心跳阈值、观察与停止条件不变；不新增 study/catalog 迁移或研究写入授权。

PBS_NODEFILE 原文留证、Slurm 无 Gaussian 时的 xTB/CREST 支持、CREST stderr 诊断、TS 卡拆分和指南整理不在本次范围。真实输入上传、计算节点执行和科学验收仍需各自授权及证据。

## v4.6.2

### 升级须知

1. **PBS 具名节点为入口级显式能力（T145）。** 只对配置 `node_targeting` 的入口启用，初期仅 Gaussian、每次一个 Attempt；必须由用户选择具体节点，禁止默认选择或回退到通用 `nodes=1`。半数 slots 为默认比例、四分之一为可选，必须匹配已有档位。真实允许名单、分组、禁止及特殊 CPU 限制只在本机配置。
2. **绑定与提交保护。** 新 Attempt 将节点、比例、容量、队列及实际资源纳入不可变 manifest 和脚本/bundle 哈希。提交确认后、审批/Claim 消耗前，以及上传核验后、qsub 前分别检查实时节点与作业。保留一次性提交、UNKNOWN、submission.json、哈希与审批语义；不自动换节点、重提或取消。
3. **运行位置独立判定。** Q/H/W/T 即使已有 `exec_host` 仍为 pending；R/E/S/C 只有完整且精确匹配的节点/slots 证据才 verified，缺失或异常证据为 unverified，分配冲突为 mismatch。qsub 接受不证明实际运行位置。已验证的历史分配在调度器正常清理后保留。
4. **前后端同号。** 配合前端 v4.6.2 显示 `priority_group`、`order`、候选状态和明确的节点选择；旧 `priority` 保留为顺序别名。严格定向解析失败保留普通只读监控数据和提示，但不允许用回退数据推荐或提交。复用已有监控查询，不增加逐节点连接。
5. **配置与回退。** 未启用策略的 PBS/Slurm 入口、Gaussian-only、原有资源上限和监控行为保持兼容。启用策略前检查旧 prepared Attempt，未绑定节点的记录不会被自动补写。回退 v4.6.1 必须恢复相容配置，并阻止旧版对不兼容的新节点绑定记录执行写操作；不删除字段、重写脚本或重新提交。不能完整恢复时如实报告，见 [OPERATIONS.md](docs/OPERATIONS.md)。

本版功能增量为已合并的后端 [T145 #345](https://github.com/anakine800-tech/Auto-Gaussian/pull/345)，配套前端 [T145 #44](https://github.com/anakine800-tech/Auto-Gaussian-Frontend/pull/44)。T146 仅更新版本、版本断言和发布文档，不增加功能、依赖或 study/catalog 迁移。

### 验证与现场限制

- 发布 PR 记录准确提交的后端全量/旧脚本字节回归、前端 Python/Playwright/构建、配套集成和有效私有词表扫描结果。四/五卡、节点分配、Gaussian-only、旧入口与 Slurm 行为继续回归。
- 特殊 CPU 编号与调度器/亲和性映射未核实前保持禁用。两次查询不是跨机原子预留，最后一次查询后的竞争仍须现场界定。
- PBS_NODEFILE 守卫检查节点和行数，但当前不归档其原文；需要原文的真实作业验收必须先落实获准的留证方式。重复节点条目可能影响只读总量，作为非阻断数据质量后续项保留。
- 配套发布、开发机部署、真实合成作业与研究机维护分阶段执行。真实计算另行批准；正常重新登录后的认证持久性及实际计算节点条件不得由 CI 代替。前端 runtime `__version__` 历史值仍按既有约定记录，以包与网页版本核对配套版本。


## v4.6.1

### 升级须知

1. **Gaussian-only 入口（T141）。** 仅当非空 `allowed_templates` 完全由 `gaussian` / `gaussian-cp` 组成时，才允许省略 xTB；未配置 xTB 时不得单独配置 CREST。doctor 与渲染使用真实已配置的程序，不填写假路径；原完整程序配置保持兼容，禁用模板不能 prepare。
2. **资源能力按入口显式配置（T142）。** 原四档仍合法，`max` / `ultra` 可选；PBS 默认内存上限仍为 120 GB，显式入口能力最高支持 200 GB。可选 `resources.max_walltime` 在 prepare 和 submit 前强制校验，人工批准不能绕过。配置收紧后也重新核对单作业资源；不改旧 Attempt 的 manifest、输入或哈希。AG 本地上限不代表物理单节点容量、调度器许可或账号配额。
3. **前后端配套。** 使用前端 v4.6.1 展示 PBS 节点分配、全部已配置档位和可选单作业时限；`ag-monitor/1` 保持版本，仅扩展可选资源字段。排队总量继续使用已有 `max_queued_cores` 机制。配置入口、路由和真实资源值留在本机，不随发布自动变更。
4. **先备份再升级或回退。** 保存两仓版本、依赖、构建、配置、SSH 与 LaunchAgent 备份和 SHA-256。回退至 v4.6.0 必须同步恢复旧版兼容配置：缺 xTB 的 Gaussian-only 入口不能直接交给旧版，新增档位和时限也不能依赖旧版忽略字段。恢复原四档 PBS 内存限制及原完整程序配置；不伪造软件路径、不改历史研究证据。具体顺序见 [OPERATIONS.md](docs/OPERATIONS.md)。
5. **部署仍单独批准。** 两个发版 PR 审阅并由负责人合并后，负责人在各自确切合并提交创建同号 tag/release。先完成开发机所有必要验收，再在批准的研究机维护窗口独立验收；观察时长以私有部署消息为准。发布准备不连接真实集群、不提交作业，也不代表新增入口、共享目录、计算节点环境、高资源档位或长期认证已验收。

按 `git log v4.6.0..main --first-parent` 核对本版功能增量：后端 T141 #342、T142 #343；配套前端 T143 #42。T144 仅调整版本、版本断言与发布文档，不增加功能、依赖或 study/catalog 迁移。

### 兼容性与资源

- T141 增加显式 Gaussian-only 配置、doctor 与渲染兼容，保留完整配置行为和模板白名单限制。[#342](https://github.com/anakine800-tech/Auto-Gaussian/pull/342)
- T142 统一 config、prepare、CLI、route、monitor、clusters 的可选六档资源；不支持的档位给出明确原因。新增入口级 PBS 高内存与 walltime 硬上限，提交时重新校验收紧后的配置，保持原脚本字节兼容。[#343](https://github.com/anakine800-tech/Auto-Gaussian/pull/343)
- 前端 T143 展示 PBS 节点状态、已分配/总/剩余 slots、作业与内存；`free` 不代表未分配，slots 不代表真实 CPU 利用率。未知与失败/过期数据明确提示，复用快照不增加远程查询。[前端 #42](https://github.com/anakine800-tech/Auto-Gaussian-Frontend/pull/42)

### 验证与已知边界

- 发布 PR 记录本次版本的后端全量、前端 Python/Playwright、跨页面集成、构建及本机有效词表扫描结果；不以功能 PR 或 CI 通过代替真实部署验收。
- Gaussian 初始化、共享目录与计算节点可见性、单节点容量及调度限制、双调度器冲突风险均须现场独立核实。Keychain 正常重新登录后的持久化验证另行记录，不为测试清空 agent 或重启电脑。
- 既有 prepared Attempt 与当前资源配置不一致时保留原证据并报告，不重写 manifest 或自动重建/提交。
- v4.6.0 的 catalog v2 不可降级与启用批准要求继续适用；本补丁不触发升级。既有监控串行采样、睡眠后退避及 Slurm“其他”核数显示等已知问题保留，详见下方 v4.6.0。前端 runtime `__version__` 仍为 4.0.0，按包元数据与网页包版本核对 4.6.1。

## v4.6.0

### 升级须知

1. **catalog v2（T131）不能降级。** 第一次写入 v2 事件的命令必须带 `--upgrade-catalog`；升级后，ag 4.5.x 会拒绝该 study 的 journal，前端 4.5.x 会把它显示为未登记。ag 和前端必须同时升到 4.6.0；已升级的 study 不能再用 4.5.x 打开或写入，也不能靠删行降级。两台电脑都部署完成、并在研究用计算机上完成一次临时非研究 study 的合成试写和前端显示核对之前，真实研究 study 不写 v2 事件。已有研究 study 第一次升级须经负责人批准。
2. **SSH 连接超时（T130）。** 入口级 `ssh.connect_timeout_seconds` 为整数 15–60，默认 15；命令总超时、上传超时和下载无进展阈值自动顺延（值 − 15）秒。经转发的 PBS 入口建议设为 40；本轮两台电脑的 PBS 入口均采用 40，并设置 `monitor_interval_seconds = 60`，Slurm 沿用默认。回退到 4.5.1 时必须一并恢复旧配置；已升级的 catalog 不能随服务回退而降级。
3. **新命令和新输出只做加法。** `ag scan-path`（T136）诊断一维扫描沿程的成键、二面角和接触变化；`ag scan-peak` 并入同一份诊断，峰附近有问题时在输出最前面警告。`ag scan-peak --gaussian-ts --route`（T133）从扫描峰生成 TS 输入草稿，可选 `--register-candidate`。`ag qst-endpoints`（T134）由两个已取回端点和人给的完整映射生成 QST2 草稿，对称歧义时报错。`ag g0`（T137、T138）提供 DFT 之前的本地诊断，只有输入完整性和几何损坏两类硬拒绝，其余为标记和排序，可选模式投影，`--record` 写入 diagnosed 结果。`ag profile`（T135）新增 `lowest_ts` 和最低 TS / 系综 / 差值三个数。所有草稿都不含 Link0；prepare 仍要求先补匹配档位的 `%nprocshared`。
4. **卡片（T139）。** ts、irc、profile、kinetics、crest-screen 五张卡修订 TS 初猜口径，ts 卡新增“TS 初猜工作流”。Skills 通过软链接指向检出，检出更新后卡片随之更新；研究会话须重新读取卡片。
5. **G0、scan-path、catalog 状态都是登记和诊断，不是门禁，也不是科学验收。** 提交审批规则不变。

后端与前端统一为 v4.6.0，配合前端 v4.6.0 使用。按 `git log v4.5.1..main --first-parent` 核对全部 9 个 PR：T130 #332、T135 #333、T131 #334、T133 #335、T134 #336、T136 #337、T137 #338、T138 #339、T139 #340。T140 只修改版本号和文档；其他小修另行安排。两个发布 PR 经监督方审阅、负责人合并后，由负责人在各自确切合并提交上创建 `v4.6.0` tag/release。

### 连接

- T130 提供入口级 SSH 连接超时，并使命令、上传和下载无进展阈值按增量顺延，保留共享核数统计、只读重试与提交审批语义。[#332](https://github.com/anakine800-tech/Auto-Gaussian/pull/332)

### catalog v2

- T131 增加通道、候选、诊断和负责人声明事件及派生视图；首次写入显式升级，不回写已有计算证据。登记状态不替代科学签字。[#334](https://github.com/anakine800-tech/Auto-Gaussian/pull/334)

### TS 初猜输入

- T133 从扫描局部峰生成无 Link0 的 Gaussian TS 草稿，可选登记候选及来源。[#335](https://github.com/anakine800-tech/Auto-Gaussian/pull/335)
- T134 由已取回端点、完整原子映射生成 QST2 草稿并可选登记；对称映射歧义须由人解决。[#336](https://github.com/anakine800-tech/Auto-Gaussian/pull/336)

### 扫描诊断

- T136 新增一维 `ag scan-path`，报告沿程成键、二面角和接触变化；`scan-peak` 共用诊断并前置峰附近警告。[#337](https://github.com/anakine800-tech/Auto-Gaussian/pull/337)

### G0

- T137 新增本地输入完整性、几何和通道诊断、批量排序及可选 diagnosed 登记。[#338](https://github.com/anakine800-tech/Auto-Gaussian/pull/338)
- T138 将可选模式投影接入 G0 报告、批量排序和登记；投影是诊断信息，不确认 TS 或反应机理。[#339](https://github.com/anakine800-tech/Auto-Gaussian/pull/339)

### profile

- T135 增加 `lowest_ts` 选择及最低 TS / 系综 / 差值三数报告，区分最低构象与系综结果。[#333](https://github.com/anakine800-tech/Auto-Gaussian/pull/333)

### 卡片与运维文档

- T139 修订 ts、irc、profile、kinetics、crest-screen 五张卡的 TS 初猜口径，补齐从构建、扫描/端点到 G0、DFT 和后续审阅的工作流。[#340](https://github.com/anakine800-tech/Auto-Gaussian/pull/340)
- T140 修订 [OPERATIONS.md](docs/OPERATIONS.md)：至少完成首轮核对，观察时长由每次部署消息指定。本轮不设观察时长；先部署开发机，通过后当天暂停研究会话，再部署研究用计算机。逐入口 doctor、监控加载后 180 秒内首轮快照、90 秒内心跳且 PID 对应、快照字段和前端各入口卡片均须核对。研究用计算机通过后，用临时非研究 study 登记候选并执行 `ag g0 --record`，核对前端台账；通过后真实研究 study 才可写 v2 事件，试写 study 移入以下划线开头的容器目录保留。

### 已知问题与验证边界

- catalog v2 升级后不能降级，见升级须知第 1 条。
- `ag g0` 的原子顺序检查只比较元素序列，同种元素互换查不出来；立体标签必须针对与候选完全相同的几何生成；批量诊断时，频率段有歧义会使整批报错而不是跳过。xTB Hessian 来源属于 T138 范围外的后续工作。
- `ag scan-path` 只支持一维扫描。
- ts 卡已接近放宽后的 400 行上限，再增内容前需要拆分；可将“TS 初猜工作流”移到单独卡片或参考文档。
- prepare 尚不按档位自动补 `%nprocshared`；前端 Slurm“其他”状态核数仍被计入空闲，后续独立修正。
- 监控仍串行采样；经转发时单条 SSH 约 10–20 秒，一轮可能 100–150 秒，实际耗时须现场记录。手动重试启动最多需等待当前一个入口采完，得到新快照还需加上目标入口自身的采样耗时。
- 电脑睡眠期间停止采样，醒来自动恢复；刚醒来的一两轮可能因网络未就绪而失败并进入退避。不要求防睡眠，也不改电源设置。
- 前端睡眠醒来后 `next_sample_at` 可能显示过去时间；核数和内存都未知时 notes 会重复显示。前端 Python 包的 `autog_frontend/__init__.py` 中 `__version__` 仍为 4.0.0，包元数据与网页包为 4.6.0。
- 沿用 v4.5.0：`timezone-mismatch` 只让耗时退回 walltime，开始时间和提交时间仍按配置解析；后续应一并置为 null。
- 沿用 v4.5.0：路由建议不考虑 walltime，公共分区有他人排队时通常被判为“没地方”；建议不保证启动。父 chk 的频率来源与可用力常数仍靠卡片和人工审阅，坐标框架核验不能替代来源审阅。
- 沿用 v4.5.0：取回不支持断点续传；`cp-report --solvent-sp` 仍缺溶剂相片段单点，溶剂相相互作用能未知。已有 facts 是否重算及 catalog 是否补登记由负责人逐 study 决定，发版不改已有证据。
- 前端重试被拒仍进入短暂快速轮询；暂停确认框文字有一个多余空格。两项均为 T128 非阻塞建议，后续修正。

各项真实验证结果见对应 PR；本次发布准备只做离线验证。**发版不等于部署完成，也不等于科学验收；部署结果另行记录。**

## v4.5.1

### 升级须知

1. **常驻监控改为直接运行 `ag monitor`（T127）。** 后端已检测认证失败和主机指纹失败，不再需要本机包装脚本。先备份再替换服务；LaunchAgent 使用 [监控 plist 样例](docs/ops/launchd/local.autogaussian.monitor.plist.example)，完整步骤见 [运维文档](docs/OPERATIONS.md)。
2. **监控行为变化（T127）。** 同一入口连续失败 3 次后开始退避，间隔逐次翻倍，最长 600 秒，成功一次恢复基础间隔。认证失败或主机指纹失败只暂停该入口，其他入口照常采样；修复原因后，可通过改该入口配置、重启监控，或手动重试并确认恢复。stdout 默认每个有采样的循环输出一行摘要，`--json` 才输出完整快照。新增 `ag monitor --retry <ENTRY> [--auth-fixed]`，仅在本机登记一次立即采样请求，由运行中的监控执行。入口可选 `monitor_interval_seconds`（30–600）；PBS 直连或经转发均建议 60 秒，Slurm 不配置，沿用默认值。
3. **快照字段只做加法（`ag-monitor/1`）。** 新增 `sampling`、`cluster.scheduler`（PBS 也写）与 `cluster.hardware.notes`；异构内存等局限说明从 `hardware.error` 移到 `notes`。v4.5.0 前端可以读取新快照。
4. **Torque 节点内存。** 总内存取 `physmem`，不含 swap；已分配内存只在节点上所有作业都申请了内存时按申请值加总，否则为 null 并附说明。
5. **本机控制文件。** `.ag-monitor/` 根目录新增 `watch.json`、`watch.lock`，入口目录可能出现 `retry-request.json`。同一缓存目录不允许同时运行两个 `ag monitor --watch`；不要靠手工删除控制文件解除占用。

后端与前端统一为 v4.5.1，配合前端 v4.5.1 使用。按 `git log v4.5.0..main --first-parent` 核对全部 2 个 PR：T127 #329、T127 补修 #330。T129 只准备版本号与文档；两个发布 PR 经监督方审阅、负责人合并后，由负责人核对各自确切合并提交，再创建 `v4.5.1` tag/release。

### 监控

- T127 增加按入口退避、认证/主机指纹暂停、手动重试、独立采样间隔与一行摘要；修正 Torque 物理内存及已申请内存口径，将硬件局限移到 notes。采样保持串行，每个入口采完后优先处理全部入口的待处理重试。[#329](https://github.com/anakine800-tech/Auto-Gaussian/pull/329)
- T127 补修让监控未运行时的重试拒绝路径不创建任何文件或目录，包括缓存目录与 `watch.lock`。[#330](https://github.com/anakine800-tech/Auto-Gaussian/pull/330)

### 运维

- T127 提供直接运行 `ag monitor --watch 30` 的 [LaunchAgent 样例](docs/ops/launchd/local.autogaussian.monitor.plist.example)。[#329](https://github.com/anakine800-tech/Auto-Gaussian/pull/329)
- T129 新增 [OPERATIONS.md](docs/OPERATIONS.md)：备份、更新、服务替换与回退、睡眠判断、30 分钟观察、连接切换和手动重试。先部署开发机并观察通过，再部署研究用计算机；具体本机值只保存在私用记录。

### 已知问题与验证边界

- 监控仍串行采样；经转发时单条 SSH 约 10–20 秒，一轮可能 100–150 秒，实际耗时须现场记录。手动重试启动最多需等待当前一个入口采完，得到新快照还需加上目标入口自身的采样耗时。
- 电脑睡眠期间停止采样，醒来自动恢复；刚醒来的一两轮可能因网络未就绪而失败并进入退避。不要求防睡眠，也不改电源设置。
- 前端睡眠醒来后 `next_sample_at` 可能显示过去时间；核数和内存都未知时 notes 会重复显示。前端 Python 包的 `autog_frontend/__init__.py` 中 `__version__` 仍为 4.0.0，包元数据与网页包为 4.5.1。
- 沿用 v4.5.0：`timezone-mismatch` 只让耗时退回 walltime，开始时间和提交时间仍按配置解析；后续应一并置为 null。
- 沿用 v4.5.0：路由建议不考虑 walltime，公共分区有他人排队时通常被判为“没地方”；建议不保证启动。父 chk 的频率来源与可用力常数仍靠卡片和人工审阅，坐标框架核验不能替代来源审阅。
- 沿用 v4.5.0：取回不支持断点续传；`cp-report --solvent-sp` 仍缺溶剂相片段单点，溶剂相相互作用能未知。已有 facts 是否重算及 catalog 是否补登记由负责人逐 study 决定，发版不改已有证据。

各项真实验证结果见对应 PR；本次发布准备只做离线验证。**发版不等于部署完成，也不等于科学验收；部署结果另行记录。**

## v4.5.0

### 升级须知

1. **提交审批规则改变（T111）。** 按 AGENTS.md 第 3.4 条，提交可显式使用一次性聊天批准记录（逐字引用负责人原话，最长 24 小时，绑定 study、Attempt、bundle SHA-256、集群和核数），或按 study 明确列出的本机长期放行规则。通过 `--approval` 或 `--policy` 选择并逐项核对；未指定两者时仍由负责人点击 Mac 确认框，显式授权核对失败不回退弹框。**取消仍须在 Mac 上亲手确认。** [#318](https://github.com/anakine800-tech/Auto-Gaussian/pull/318)
2. **Gaussian 输入可省略 `%mem`（T112）。** prepare 自动填写 `min(核数 × 2, floor(档位内存 × 0.85))` GB；已写的 `%mem` 原样保留并按既有规则校验。[#319](https://github.com/anakine800-tech/Auto-Gaussian/pull/319)
3. **常驻监控需更新参数并重启一次（T112、T114、T123）。** `--watch` 范围为 30–600 秒；PBS 按 watch 间隔采样，Slurm 至少间隔 60 秒。PBS 会将**所有用户**的作业（含用户名）写入本机快照缓存，缓存不进入仓库，前端仅监听 127.0.0.1。硬件、存储、`AllocMem`、分区汇总查询失败只将相应部分标为未知并保留其他成功数据；本人作业查询失败仍使本轮采样失败。[#319](https://github.com/anakine800-tech/Auto-Gaussian/pull/319)、[#320](https://github.com/anakine800-tech/Auto-Gaussian/pull/320)、[#325](https://github.com/anakine800-tech/Auto-Gaussian/pull/325)
4. **研究对象与采用登记（T119、T123）。** 新增 `ag catalog`，study 内的 `catalog/journal.jsonl` 只追加，`catalog/state.json` 是派生视图；读写共用 `catalog/catalog.lock`。升级前确认旧版本 catalog 命令已退出。采用必须逐字引用负责人原话；已签字结论补登记需负责人逐 study 授权，不修改原 facts 或签字。[#322](https://github.com/anakine800-tech/Auto-Gaussian/pull/322)、[#325](https://github.com/anakine800-tech/Auto-Gaussian/pull/325)
5. **路由建议（T117）。** `ag route` 只读本机监控快照，按本机 `[routing]` 配置顺序建议入口；prepare 的实际选择不同只提示，不拦截或改写绑定。使用前补充 `[routing]`，某 study 在新入口签字前用 `[routing.studies]` 覆盖顺序。建议不替代 submit 的实时核验与批准。[#324](https://github.com/anakine800-tech/Auto-Gaussian/pull/324)
6. **PBS 调度器时区（T124）。** `scheduler_timezone` 必须是经负责人实测确认的 IANA 时区名，不接受固定偏移；不要从开发机时区推断。检测到时间差异常时发出 `timezone-mismatch` 并将耗时退回 walltime；错误配置不保证都能被检测，具体显示限制见下文。[#326](https://github.com/anakine800-tech/Auto-Gaussian/pull/326)
7. **公开仓库保护（T116）。** CI 对整个仓库运行 `python scripts/scan_public.py`；开发机启用 `.githooks/pre-commit` 并维护不入库的本机敏感词表。扫描包括归档，不能替代人工检查，也不表示 Git 历史已清理。[#321](https://github.com/anakine800-tech/Auto-Gaussian/pull/321)、[#323](https://github.com/anakine800-tech/Auto-Gaussian/pull/323)
8. **facts 语义（T108）。** 新规则用于新生成的 facts 和明确授权的 `--reparse`；已有 facts，特别是已签字证据，不自动重写。重算须先预览差异、保留旧证据并按 study 取得负责人决定。[#316](https://github.com/anakine800-tech/Auto-Gaussian/pull/316)

后端与前端统一为 v4.5.0，配合前端 v4.5.0 使用。本节以 `git log v4.4.0..main --first-parent` 核对全部 12 个 PR：T108 #316、T109 #317、T111 #318、T112 #319、T114 #320、T116 #321 与 #323、T119 #322、T117 #324、T123 #325、T125 #327、T124 #326。T126 只准备版本号与发布文档；两个 PR 经监督方审阅、负责人合并后，由负责人在各自确切合并提交上创建 `v4.5.0` tag/release，不直接选择届时的 main。

### 计算事实与去重

- T108 单列驻点结论并区分优化与频率几何收敛判据，按频率分级记录；`route-join-v2` 修正跨行 route 拼接，补充稳定性与 ⟨S²⟩ 事实。使用者可区分程序结束、几何收敛与驻点证据，仍须科学审阅。[#316](https://github.com/anakine800-tech/Auto-Gaussian/pull/316)
- T109 在 RMSD 查询副本中按元素和连接、与键级无关地枚举等价原子映射并核对立体中心，避免芳香 Kekulé 表示导致假差异；新增 `--mirror off|report` 与阈值边界候选。镜像报告不合并构象，映射超限仍拒绝，边界候选留给人工复核。[#317](https://github.com/anakine800-tech/Auto-Gaussian/pull/317)

### 提交与资源

- T111 提供聊天批准记录和按 study 限定的长期放行规则，保存授权来源与确认摘要；仍保留单次声明、两次核数检查及字节核验。明确批准可在绑定范围内用于提交，取消流程不变。[#318](https://github.com/anakine800-tech/Auto-Gaussian/pull/318)
- T112 自动补缺失 `%mem`，确认摘要增加资源参考；监控每轮重读配置、慢速存储查询独立处理，新增入口无需依赖旧进程中的配置副本；修复独立 PBS 集群的 doctor 未合并提示误报。[#319](https://github.com/anakine800-tech/Auto-Gaussian/pull/319)
- T117 新增 `ag route` 本地路由建议，按快照新鲜度、入口顺序和核数/内存条件说明可运行或排队建议；共享入口不重复累加占用，prepare 只提示选择差异。[#324](https://github.com/anakine800-tech/Auto-Gaussian/pull/324)

### 监控

- T114 增加 PBS 全员作业、实际分配核数与已运行时间、硬件核数与内存、Slurm 分区汇总和按入口采样间隔。前端可区分本人、他人和空闲资源；Slurm 保留本人明细与他人汇总，未知值不视为零。[#320](https://github.com/anakine800-tech/Auto-Gaussian/pull/320)
- T123 让硬件、`AllocMem`、存储和分区汇总的局部失败不掩盖成功数据；Slurm 本人内存仅取精确作业绑定的 Attempt manifest，缺证据保持未知，不按名称或当前档位推算。[#325](https://github.com/anakine800-tech/Auto-Gaussian/pull/325)
- T124 按入口配置的 IANA 时区解析 PBS 英文文本时间，拒绝夏令时歧义/不存在时间，并对异常时间差给出匿名警告、退回 walltime；时区正确性仍依赖负责人实测。[#326](https://github.com/anakine800-tech/Auto-Gaussian/pull/326)

### 研究记录

- T119 新增 `ag catalog` 的对象、成员、采用和报告类别登记，使当前采用结果与原始计算证据分开；追加日志、派生状态和来源哈希便于前端读取，不替代科学签字，也不自动采用或补登。[#322](https://github.com/anakine800-tech/Auto-Gaussian/pull/322)
- T123 补充 `coverage`、`ts`、`nci` 报告类别，读写共用 `catalog.lock`，避免切换派生视图后锁仍指向旧文件；升级须等旧命令退出。[#325](https://github.com/anakine800-tech/Auto-Gaussian/pull/325)

### 仓库与文档

- T116 清理当前公开文件及归档中的研究/环境信息，增加全仓库扫描、带本机私有词表的提交 hook 和公开仓库写作规矩；后续补齐并行合入的文件与归档扫描失败规则。当前文件清理不等于历史已清理。[#321](https://github.com/anakine800-tech/Auto-Gaussian/pull/321)、[#323](https://github.com/anakine800-tech/Auto-Gaussian/pull/323)
- T125 完成 TS 初猜开发规格与现状审计，明确 catalog、扫描峰、端点映射、G0 诊断和报告/卡片的后续范围；本项只有文档，不提供新的 TS 搜索或验证能力。[#327](https://github.com/anakine800-tech/Auto-Gaussian/pull/327)

### 已知问题与验证边界

- `timezone-mismatch` 触发时，只有耗时退回 walltime（缺失则未知）；开始时间和提交时间仍显示按配置时区解析的值，后续应一并置为 null。
- 路由建议不考虑 walltime；超算公共分区几乎总有他人排队，因此通常被判为“没地方”，建议不保证实际启动。
- 父 chk 是否来自频率计算、是否含可用力常数，仍由卡片和人工审阅保证，程序没有强制检查；已有坐标框架核验不能替代力常数来源审阅。
- 取回不支持断点续传；`cp-report --solvent-sp` 仍缺溶剂相片段单点，溶剂相相互作用能未知，不能用气相值替代。
- 已有 study 的 facts 是否按 T108 重算、catalog 是否补登记，由负责人按 study 决定；发版不改已有研究证据。

各项真实验证结果见对应 PR 的评论；本次只运行发布要求的离线验证，不重跑真实计算，**发版不等于科学验收**。

## v4.4.0

### 升级须知

1. 迁移 study 或切换配置目录时，必须同时带上各 Slurm 入口的台账。有提交痕迹却缺台账时会拒绝提交，这是防止漏算预留的有意设计；从备份或原配置目录找回，不能自动重建或按零处理。[#310](https://github.com/anakine800-tech/Auto-Gaussian/pull/310)
2. 新入口若配置独立的 `programs.crest.executable`，prepare 会先通过 SSH 只读检查程序是否可执行；失败即拒绝，不回退到默认安装布局。[#313](https://github.com/anakine800-tech/Auto-Gaussian/pull/313)
3. 既有配置中的 `budget_core_hours`、`expires` 不作为提交拦截条件，可以删除；保留 `expires` 时仍可显示到期提醒。核时台账继续记录预留和结算，不代表平台余额。[#310](https://github.com/anakine800-tech/Auto-Gaussian/pull/310)
4. default（组里集群）请在配置中明确写 `max_cores = 44`；PBS 单作业上限现在由配置决定，不再写死为 44。[#313](https://github.com/anakine800-tech/Auto-Gaussian/pull/313)
5. 取回连续 60 秒无进展或达到 24 小时兜底上限时停止并保留残片，不自动重试，等待人检查；这一变化不等于断点续传。[#311](https://github.com/anakine800-tech/Auto-Gaussian/pull/311)

后端与前端统一为 v4.4.0，配合前端 v4.4.0 使用。本节按 `git log v4.3.0..main --first-parent` 核对全部 4 个 PR：T101 #310、T102 #311、T105 #312、T106 #313。T107 只修改版本与发布文档；两个 PR 均须监督方审阅、负责人合并，再由负责人在各自 PR 的确切合并提交上创建 `v4.4.0` tag/release，不直接选择届时的 main。

### 集群与队列

- T101 按同一调度器、同一规范化 SSH 配置文件及 host 别名识别同一实际集群，多个队列入口合并核数统计：远程本人作业只计一次，全组本地未观测预留均计入，总上限取各入口最小值。确认框显示入口名和 partition，便于确认实际投递目标；核时余额不再拦截提交，只提示本次最多消耗的核时。新增入口级 `allowed_templates`，可将测试入口限制为 CREST；仅约束新 prepare，不改已有 Attempt 绑定。AGENTS.md 第 3.9 条同步多入口规则。[#310](https://github.com/anakine800-tech/Auto-Gaussian/pull/310)
- T106 将 PBS 单作业核数上限改为可配置，取消总上限不得超过单作业上限四倍的限制；新增可选 `max_queued_cores`，对排队、挂起和未观测预留另设限额。同集群入口取已配置排队限额中的最小值。新增可选独立 CREST 路径 `programs.crest.executable`，支持与 xTB 分开安装；AGENTS.md 第 3.9 条同步修改。ag 仍只做提交准入检查，运行核数可能达到总上限；运行限额说明不代表调度器已经实施。[#313](https://github.com/anakine800-tech/Auto-Gaussian/pull/313)

### 取回与确认

- T102 将固定 60 秒下载上限改为连续 60 秒无进展才超时，另设 24 小时兜底；有进展的大文件可持续取回，超时后不自动重试。由 `ag cancel` 取消的作业，在取消声明、成功 journal、确切作业绑定及独立结束证据齐全时，可通过 `fetch --incomplete` 取回已有输出，仍核对前后哈希且不改 cancelled 状态；PBS 需两次间隔至少 300 秒的稳定、不活跃且无退出回执观察，Slurm 需唯一受支持终态。提交按钮为“不提交 / 提交”，取消按钮为“保留作业 / 终止作业”，默认选项仍在安全一侧。[#311](https://github.com/anakine800-tech/Auto-Gaussian/pull/311)

### 新能力

- T105 新增 `gaussian-cp` 模板（气相 `Counterpoise=2` 单点，固定两个片段）及 `ag cp-report`（`ag-cp/1`），汇总带哈希和原文行号的 BSSE 与相互作用能，供 RC、离子对和 TS 诊断。CP 能量不进入 thermo/profile；G16 A.03 实测拒绝 CP 与 SCRF 同用，因此 prepare 明确拒绝该组合。溶剂叠加保留近似与缺项，不能当作完整溶剂相相互作用能。[#312](https://github.com/anakine800-tech/Auto-Gaussian/pull/312)

### 已知问题与验证边界

- 两个 SSH 身份不同的独立 PBS 集群会触发 doctor 的“疑似同集群入口未合并”提示，这是误报，不改变核数统计或检查退出码；后续修复提示范围。[#310](https://github.com/anakine800-tech/Auto-Gaussian/pull/310)
- `cp-report --solvent-sp` 目前只接受复合物的溶剂相单点，缺两个片段的溶剂能量时，溶剂相相互作用能显示“未知”。另行支持两个片段在复合物几何下、使用自身基组的 SMD 单点列为后续任务。[#312](https://github.com/anakine800-tech/Auto-Gaussian/pull/312)
- 取回不支持断点续传；超时保留残片，后续重新下载从新的临时目标开始。[#311](https://github.com/anakine800-tech/Auto-Gaussian/pull/311)
- PBS 作业结束后可能仍短暂显示 R，ag 继续将残留计入已占用核数；不保证所有残留都会自行消失，不自动取消。

各项真实验证结果见对应 PR 评论；T107 的全量离线测试与 CI 记录见两个发布 PR。本发布任务不重跑真实计算，发版不等于科学验收。

## v4.3.0

### 升级须知

1. 旧版本可能把 route 在关键词中间换行的 Gaussian Opt+Freq 误判为 `incomplete`（T99）。对已有 `facts.json` 且状态为 `fetched` 的 Attempt，先运行 `ag facts <Attempt> --reparse --dry-run --out <study 外的新 JSON>` 查看新 facts 与命令列出的差异，确认后再运行 `ag facts <Attempt> --reparse`。正式执行将旧字节归档到 `facts-history/`，并列出 study 中引用旧哈希的文件；不自动改写这些引用，涉及已签内容须由负责人重新确认。[#308](https://github.com/anakine800-tech/Auto-Gaussian/pull/308)
2. T82 加强 thermo / profile 的输入一致性与频率证据检查，以前能生成的部分报告升级后可能被拒绝。按报错核对方法和物种口径、收敛与来源，不绕过检查；拒绝不等于软件回归。[#297](https://github.com/anakine800-tech/Auto-Gaussian/pull/297)
3. Multiwfn 是可选程序，只有使用 `multiwfn` 模板才需要在本机配置 `programs.multiwfn`（多集群配置为 `clusters.default.programs.multiwfn`）。目前仅支持 `default`（PBS）集群；已有 Gaussian / xTB / CREST 用法无需增加该配置。[#307](https://github.com/anakine800-tech/Auto-Gaussian/pull/307)

后端与前端统一为 v4.3.0，配合前端 v4.3.0 使用。本节按 `git log v4.2.2..main --first-parent` 核对全部 15 个功能与文档 PR；本次仅准备版本号和发布文档。两个 T100 PR 均须监督方审阅、负责人合并，再由负责人分别在各自 PR 的确切合并提交上创建 `v4.3.0` tag/release，不直接选择届时的 main。

### 结构与开题

- T80 增加开题物种核验，明确结构身份、显式氢与待确认项，支持结构确认前逐物种检查。[#295](https://github.com/anakine800-tech/Auto-Gaussian/pull/295)
- T93 增加开题完整性检查、`study.md` 草稿及首批准备交接；止于本地准备，不自动提交或代替人工签字。[#306](https://github.com/anakine800-tech/Auto-Gaussian/pull/306)
- T86 按人指定的六个内坐标定向构建主族复合物，核对几何、接触与约束，提供可审阅的采样起点。[#301](https://github.com/anakine800-tech/Auto-Gaussian/pull/301)
- T90 按指定的位点与二面角网格枚举复合物，过滤重叠并在约束组内去重；不同约束组分别导出候选与约束文件，组合数超限时报错，不随机抽样。补充 `atom_count_with_h` 和 `source_explicit_h_atom_count`，保留旧 `explicit_h_atom_count` 的值并标明弃用，避免把补氢后总原子数误当显式氢数。[#305](https://github.com/anakine800-tech/Auto-Gaussian/pull/305)
- T91 按产物参照标注 TS 立体构型并生成通道归属建议，保留歧义；建议须人确认，不能据此自动接受 TS 或确定选择性。[#304](https://github.com/anakine800-tech/Auto-Gaussian/pull/304)

### 审阅与分析

- T79 新增 `ag irc-review`，逐方向汇总 IRC 完成判据、能量、距离和路径 XYZ，保留停止原因与人工审阅项；工具报告不等于双向 IRC 科学验收。[#296](https://github.com/anakine800-tech/Auto-Gaussian/pull/296)
- T88 在 IRC 报告中记录导出路径 XYZ 的 SHA-256，供读取方核对实际字节与报告绑定。[#300](https://github.com/anakine800-tech/Auto-Gaussian/pull/300)
- T89 的 topology / irc-compare 识别固定原子编号下的共振等价，避免把不同局域电荷或键级表示误报为化学变化；枚举失败或超限保留 `unknown`，仍检查立体化学，不据此推断电子密度。[#303](https://github.com/anakine800-tech/Auto-Gaussian/pull/303)
- T84 新增 `ag snapshot`，只读获取运行中 Attempt 的日志快照，保存到本地 `snapshots/`；快照不是正式取回结果，不用于结果签字。[#302](https://github.com/anakine800-tech/Auto-Gaussian/pull/302)
- T92 增加 `multiwfn` 模板的 IGM / IGMH 分析，以及本地 `ag nci-report` 的 `ag-nci/1` 报告，汇总来源、网格、原子 / 原子对与片段贡献，便于人工审阅非共价相互作用；不自动作科学解释。[#307](https://github.com/anakine800-tech/Auto-Gaussian/pull/307)

### 一致性与正确性修复

- T82 在可比较的构象集合及 SP/Freq 配对中核对方法、基组、色散、溶剂、基函数形式、程序版本、元素组成、电荷与多重度，拒绝不一致来源、非正常终止、频率阶段未收敛或模式不完整的输入。`thermo` 极小点须为零虚频；`profile` 的 TS 仍允许且要求恰好一个虚频并通过相应审阅，不把不同物种之间的合法反应步骤当作同一构象集合。[#297](https://github.com/anakine800-tech/Auto-Gaussian/pull/297)
- T83 加强 prepare 的笛卡尔输入检查：有效元素、有限坐标、电子数与多重度一致性；卡片补充数值设置核对，较早发现无效输入。[#299](https://github.com/anakine800-tech/Auto-Gaussian/pull/299)
- T99 修复 Gaussian route 在 `Fre` / `q` 等关键词中间换行时的拼接与 Opt+Freq 顶层终止误判；热化学来源绑定到实际产生频率的子任务，由 chk 继承的溶剂只认本段打印参数。比较方法时按多重度补全省略的 R/U 前缀，显式 R/U/RO 仍保持区别。[#308](https://github.com/anakine800-tech/Auto-Gaussian/pull/308)

### 规则与文档

- T81 为卡片补充要点与出处，补齐扫描初猜和方法敏感性的决策提示，便于查阅已有规则。[#294](https://github.com/anakine800-tech/Auto-Gaussian/pull/294)
- T85 增加严格限定的逐条授权只读远程查看例外：仅用于 ag 暂无对应入口的需求，每条命令展示后单独取得同意；正式命令可用后改用正式命令，运行中日志使用 T84 的 `ag snapshot`。[#298](https://github.com/anakine800-tech/Auto-Gaussian/pull/298)

### 已知问题与验证边界

- 取回单个文件仍有固定 60 秒上限；慢速连接下较大的 cube 等文件可能超时，后续改为按传输速率判断。
- 前端快速比较尚未同步 R/U 前缀规则，单重态的 `M062X` 与 `RM062X` 会被当作不同口径而拒绝比较。正式结论以 ag 报告为准，后端不受此前端限制影响。
- 组里集群的 PBS 在作业结束后有时仍短暂显示 R，曾观察到约 6 分钟后自行消失；ag 会将其计入已占用核数，只会多算，不保证任意残留都会自行消失。

各项真实验证结果见各 PR 评论；本发布任务不重跑真实计算，发布不等于科学验收。

## v4.2.2

发布准备中；T73（#288）、T74（#290）、T75（#289）、T76（#292）、T77（#291）均已合并。本节汇总 v4.2.1 之后的这五个 PR。T78 经审阅、负责人合并后，由负责人在本 PR 的合并提交上创建 `v4.2.2` tag 和 release；建 tag 前核对该提交就是发版提交，不直接选择届时的 main。本轮前端没有改动，不发前端版本，继续配合前端 v4.2.1 使用。

### 分析

- T73 修复 T68 风险报告的 R2：`ag topology` 不再仅因依赖不确定接触的片段数变化，将顶层状态从 `unknown` 提升为 `changed`；已有确定键变化仍保留 `changed`，同时列出不确定接触及两种连接处理的片段数，供人工审阅。R1 的局域共振表示限制仍在。[#288](https://github.com/anakine800-tech/Auto-Gaussian/pull/288)
- T76 新增纯本地 `ag asm split` / `ag asm summary`：按人工原子映射拆分几何，核对已有计算的口径后汇总畸变能、相互作用能与两个体系的差值。仅使用电子能，不含零点能、热校正或基组重叠误差校正，不自动准备或提交片段计算，也不判断选择性来源。证据清单收录报告与 facts；几何文件通过报告中的相对路径和 SHA-256 间接绑定。[#292](https://github.com/anakine800-tech/Auto-Gaussian/pull/292)

### 扫描

- T75 支持 Gaussian 二维弛豫扫描：最多两条 `S` 行，二维扫描每维 1–20 步，含各维起点的总点数不超过 144；按实测坐标将完成点放入网格，不依赖输出遍历顺序。二维 `scan-peak` 仅通过人工指定的 `--point i,j` 导出已列出的鞍点候选，不自动选点；候选仍只是 TS 初猜。前端二维能量面显示尚未支持。[#289](https://github.com/anakine800-tech/Auto-Gaussian/pull/289)
- **兼容性提示：扫描步长必须写成带小数点的形式，例如 `5.0`。** 一维和二维中不带小数点的写法（如 `5` 或 `5e0`）现在在准备阶段即被拒绝，不自动改写输入。这是对一维扫描的唯一行为变化；被拒写法在 Gaussian L101 本来就会出错。[#289](https://github.com/anakine800-tech/Auto-Gaussian/pull/289)

### 执行与观察

- T77 让其他用户的 PBS 数组作业不再阻断本人核数统计、提交和监控，节点槽位也支持数组子作业号。本人有数组记录时仍拒绝提交，`ag monitor` 也会报错；包括已完成但仍保留在 `qstat` 中的本人数组记录，须等记录消失后再提交。ag 不提交或取消数组作业。[#291](https://github.com/anakine800-tech/Auto-Gaussian/pull/291)
- T74 修复 SSH 本地日志：配置目录位于符号链接路径下时可以正常写入；日志目录或文件自身的符号链接仍被拒绝。日志写入失败的警告每个进程最多打印一次，不改变 SSH/scp 操作结果或重试语义。[#290](https://github.com/anakine800-tech/Auto-Gaussian/pull/290)

### 证据清单

- T74 不再把正文中含空白、且按原规则解析不到文件的反引号命令示例列为缺失引用；能解析到真实文件的引用仍照旧收录，也不把命令参数自动当作证据。L1–L3 只读复扫的已收录文件、大小和 SHA-256 均不变。[#290](https://github.com/anakine800-tech/Auto-Gaussian/pull/290)

真实验证结果见各 PR 评论及正文。T75 已完成水分子九点扫描验收；T74 已记录 SSH 日志真实只读验证和 L1–L3 复扫。T77 验证中第一组测试数组没有手动删除成功的证据；两组测试数组均已确认离开队列，doctor 已恢复，监督方已接受该验证偏差。其他用户数组和 `qstat -f` 子作业格式仍以离线夹具为准，详见 [T77 验证与审阅记录](https://github.com/anakine800-tech/Auto-Gaussian/pull/291#issuecomment-6216846202)。发布不等于科学验收，本发布任务不推进研究、不补签。

## v4.2.1

发布准备中；后端与前端的版本 PR 经审阅、负责人合并后，由负责人在各自的合并提交上创建 v4.2.1 tag 和 release。逐项核对 v4.2.0 之后已合并的 T62、T64、T65、T66、T68、T69、T70、T72；前端 T71 已合并，配合前端 v4.2.1 使用。

### 执行与恢复

- T62 的五项小修保留：L123 按原因文字识别 IRC 校正失败；`FactsConflictError` 让自动 facts 按异常类型识别冲突；离线文献核实沿用缓存查询日期，缺失/无效日期仍为未核实；显式 `analyses/` 引用不再多报 `resolved_from`；SMD 输出说明改引 Gaussian 官方依据。[#278](https://github.com/anakine800-tech/Auto-Gaussian/pull/278)
- **T62 的远程观察命令改动在真实集群上导致运行中作业状态读为 unreadable，已由 T65 回退。** 回退恢复此前的 receipt、输出观察及 status 行为，其余五项小修保留；现场根因尚未确定，不把回退描述为权限诊断问题已修复。T65 评论记录真实观察路径恢复正常；带诊断信息的观察命令须在非研究 study 上真实验证后再合并。[#281](https://github.com/anakine800-tech/Auto-Gaussian/pull/281)
- T66 兼容 Slurm 清除队列记录后的精确 `Invalid job id specified` 诊断，允许继续进入不完整取回的记账核验；仍须 sacct 确认匹配的确切作业及受支持终态，SSH/其他查询错误不视为无记录。真实缺输出场景已安全取回，计算本身仍是非正常结束。[#282](https://github.com/anakine800-tech/Auto-Gaussian/pull/282)

### 证据与分析

- T64 将证据清单引用分为缺失、越界、analyses 外现存引用及无同名候选的裸名。缺失/越界完整列出，须显式 `--accept-unresolved` 才生成清单；其余两类只记信息。普通 JSON 支持 study 根目录回退，歧义、study 内符号链接及专用证据指针错误仍拒绝，旧签字不改写。[#280](https://github.com/anakine800-tech/Auto-Gaussian/pull/280)
- T69 新增纯本地 `ag channel-coverage`：从明确分配通道的 CSV 和集合清单汇总通道/产物分支的候选及计算覆盖，提示采样不均衡，保留歧义、未匹配及能量可比性限制；报告不判定采样完备或科学合格。[#283](https://github.com/anakine800-tech/Auto-Gaussian/pull/283)
- T70 为 `ag ensemble` 增加可选二面角分组、近边界标记、关键距离和分组最低能候选汇总，便于逐候选审阅。不传参数时输出行为不变；不合并、删除或重排候选，`ag-ensemble/1` 不变。前端 T71 提供相应列、筛选与汇总跳转。[#285](https://github.com/anakine800-tech/Auto-Gaussian/pull/285)、[Frontend #15](https://github.com/anakine800-tech/Auto-Gaussian-Frontend/pull/15)

### 验证与已知限制

- T68 用 23 个合成 XYZ 检查 RDKit 推断：22 个常规样例的连接、总电荷及可指派立体身份通过检查，有限样例不能外推到任意含硼/离子体系。**R1 尚未修复：** nitronate 的局域形式电荷/键级可能变为另一共振表示，总电荷与身份相容，不是电子密度证据。**R2 尚未修复：** B–O 不确定接触时，topology 顶层可能因确定边片段数变化返回 changed，而 irc-compare 保留 unknown；必须读取详细警告，不能仅凭顶层状态签字。三项严格预期失败持续记录这两类限制，详见 [风险报告](docs/research/rdkit-inference-risk.md)。[#284](https://github.com/anakine800-tech/Auto-Gaussian/pull/284)

### 文档与开发流程

- T72 在文献记录中补充检索覆盖表与可选的逐 TS 证据表，分开记录双向 IRC 完成和端点身份；开题模板说明通道表 CSV 位置、列名及多清单分隔规则，有限检索与访问缺口不等于没有先例。[#286](https://github.com/anakine800-tech/Auto-Gaussian/pull/286)
- 按负责人 2026-10-16 决定，开发机可连接集群，全部开发及合并前真实验证在开发机完成；计算机只负责研究 A 计算。涉及证据清单、远程命令、提交、状态、取回的改动必须在工单明确对象和步骤，合并前以非研究 study 验证，提交由负责人点击确认；研究 A 仅观察。测试范围与例外见 [开发手册](docs/DEVELOPING.md#测试与敏感信息)。

真实验证结果见各 PR 评论，尤其 T65、T66 的恢复与取回记录；未记录通过的场景仍为未验证。发布不等于科学验收，本发布任务不推进研究、不补签。

## v4.2.0

发布准备中，tag 和 GitHub release 由负责人在本 PR 合并后创建。本节汇总 v4.1.0 之后已合并的 #268–#276；本次仅更新版本号和文档。T62、T63 在本任务开工时尚未合并，不纳入本版本。

### 提交与资源

- T51 将单作业上限 `max_cores` 与运行加排队（含挂起）的总额度 `max_committed_cores` 分开，后者最多为前者的 4 倍；按集群统计全部本人作业，包含非 ag 提交的作业。删除严格模式及提交时的 `pbsnodes` 核验，排队额度不再被节点核验降回单作业上限。ag 只在提交时检查额度，不限制运行中核数；调度器可能使运行核数达到 `max_committed_cores`。[#271](https://github.com/anakine800-tech/Auto-Gaussian/pull/271)
- T51 为每次 SSH/scp 调用追加本地结构化日志，记录耗时、结果及错误类别，便于核对连接失败时间线；不保存连接信息或原始 stderr，日志写入失败不改变操作结果或重试语义。[#271](https://github.com/anakine800-tech/Auto-Gaussian/pull/271)
- **升级提示：** 两台电脑分别检查本机配置：`max_cores` 是单个作业上限，`max_committed_cores` 是运行加排队总额度，范围为 `max_cores` 至 `4 × max_cores`；后者不是单独的排队额度，也不保证运行中核数不超过 `max_cores`。[#271](https://github.com/anakine800-tech/Auto-Gaussian/pull/271)

### 取回与解析

- T52 在普通 `ag fetch` 和 `--incomplete` 成功后自动运行本地 facts 解析，减少忘记手动解析造成的结果缺失；绝不覆盖已有 `facts.json`。内容相同保留原字节和 mtime，冲突或解析失败通过 `facts.status` 与提示报告，不把已成功的取回改成失败。`--no-facts` 可关闭；`--add-missing` 和缺依赖时跳过自动解析，不自动刷新证据。[#276](https://github.com/anakine800-tech/Auto-Gaussian/pull/276)

### 模板

- T50 在 CREST/xTB 模板固定 `OPENBLAS_NUM_THREADS=1`、`OMP_MAX_ACTIVE_LEVELS=1`，保留原 OpenMP 核数，抑制嵌套并行导致的 OpenBLAS 警告和日志膨胀；Gaussian 模板不变，既有 Attempt 的脚本不重写。[#268](https://github.com/anakine800-tech/Auto-Gaussian/pull/268)

### 证据清单

- T49 修复中文说明与裸路径边界，保留带引号或链接包裹的中文文件名，并支持递归展开 `analyses` 内的目录引用；记录 `expanded_from`，避免漏掉签字依据或把目录误判为缺失文件。非路径长说明不再触发文件名过长错误；显式错误仍定位到来源。[#269](https://github.com/anakine800-tech/Auto-Gaussian/pull/269)
- T49b 修复 Attempt 相对文件名和 study 快照引用的解析基准：JSON 中特定字段的裸文件名在源目录不存在时忽略；文本可回退到 study 根目录并记录 `resolved_from`，两处指向不同文件时报歧义。符号链接、越界及缺失显式引用仍拒绝；L3 保存卡片的仓库相对链接仍越界，详见交接文档。[#275](https://github.com/anakine800-tech/Auto-Gaussian/pull/275)

### 分析

- T53 新增本地 `ag ensemble`，把 dedup 候选、路线、已保存的 SP/Opt facts 和可选 thermo 数据汇总为 JSON 与 Markdown，便于逐候选审阅与前端读取。保留未匹配和歧义，不跨不可比较路线混排能量，不重算布居或代替科学验收。[#270](https://github.com/anakine800-tech/Auto-Gaussian/pull/270)

### Skills 与文档

- T58 新增 kinetics 动力学解释卡片，补充 S8 SMD/标准态核对、F4 核时估算与 Gaussian 报错速查，帮助区分模型换算、方法适用性和执行诊断；不新增隧穿程序或核时额度拦截。[#274](https://github.com/anakine800-tech/Auto-Gaussian/pull/274)
- T59 提供私有 study 的开题包、文献记录及逐轮讨论模板，明确来源、未知项、方法依据和首轮范围，供负责人审阅签字后交接计算。[#273](https://github.com/anakine800-tech/Auto-Gaussian/pull/273)
- T60 新增轻量文献整理脚本，支持归一化、合并去重、Crossref 元数据核实及 CSV/Markdown 导出；保留冲突和失败状态，DOI 元数据核实不等于全文、SI 或科学结论核实。[#272](https://github.com/anakine800-tech/Auto-Gaussian/pull/272)

真实环境验证的结果见各 PR 评论（部分详细对照见 PR 正文）；尚待合并后执行的验证不能视为通过，发布不等于科学验收。

更正（2026-10-16）：v4.2.0 tag（`34d88fc`）实际包含 T63（[#279](https://github.com/anakine800-tech/Auto-Gaussian/pull/279)，`ag dedup` 可选局部构象判别，不加参数时行为不变），本节原文写作未包含。

## v4.1.0

发布准备中，tag 和 GitHub release 由负责人在本 PR 合并后创建。本节汇总 v4.0.0 之后已合并的 #252–#266；本次仅更新版本号和文档。

### 解析与事实

- T42/T42b 按 Gaussian 作业段提取事实，记录段号和来源行，修复 IRC 统计行误切段与优化完成措辞漏识别，避免后段未完成时沿用前段结论。[#256](https://github.com/anakine800-tech/Auto-Gaussian/pull/256)、[#261](https://github.com/anakine800-tech/Auto-Gaussian/pull/261)
- T45 按实际报错原因生成 `error_hint`，区分优化步数耗尽、TS 曲率不符与 SCF 不收敛；不再仅凭 link 编号推断原因。[#265](https://github.com/anakine800-tech/Auto-Gaussian/pull/265)

### 新命令

- T38 `ag topology` 比较提交与最终结构的拓扑、质子及立体差异；TS 按指定原子对报告距离。[#257](https://github.com/anakine800-tech/Auto-Gaussian/pull/257)
- T43 `ag mode-review` 导出正常频率段的正负位移、指定原子对距离与全对排名，振动方向由人审阅。[#258](https://github.com/anakine800-tech/Auto-Gaussian/pull/258)
- T44 `ag fragments` 按共价半径识别片段，导出保留原子编号映射的报告与 XYZ，不推断片段电荷、多重度或化学身份。[#264](https://github.com/anakine800-tech/Auto-Gaussian/pull/264)

### 剖面

- T39 新增焓熵分项、分子数变化、Eyring 速率与半衰期换算、按产物汇总的 `selectivity` 和扰动分析，以及 σ 来源和警告；区分模型换算与实验动力学。[#255](https://github.com/anakine800-tech/Auto-Gaussian/pull/255)

### 取回

- T47 `fetch --incomplete` 只读取回已确认结束作业的已有声明输出，记录缺失项和结束证据；允许从有有效记录的中断作业安全复用父 chk 到新 Attempt，保留人工确认、独占复制及哈希核验。[#266](https://github.com/anakine800-tech/Auto-Gaussian/pull/266)

### 方案与签字

- T37 为 Gaussian、xTB、CREST 准备显式要求非空 `--method-basis`，卡片增加计算方案签字，保留文献先例、既有方案和兜底方法的区别。[#254](https://github.com/anakine800-tech/Auto-Gaussian/pull/254)

### 卡片

- T36a/T36b 清理验收示例与错字，回写历史 IRC 验收及其与现行完成判据的区别；历史签字不替代当前判据。[#253](https://github.com/anakine800-tech/Auto-Gaussian/pull/253)、[#263](https://github.com/anakine800-tech/Auto-Gaussian/pull/263)
- T40 新增复合物与双分子步骤卡片，限定为已审阅原子对约束采样，明确分离反应物参考态、缔合熵、低频与 BSSE 未检查的边界。[#262](https://github.com/anakine800-tech/Auto-Gaussian/pull/262)
- T46 补充 TS Hessian 策略、低频残余审阅及 IRC 双向“走完”判据，不以达到步数或正常退出代替路径审核。[#260](https://github.com/anakine800-tech/Auto-Gaussian/pull/260)

### 文档与兼容性

- 更新文档索引、交接与角色分工；T41 完成 ORCA 接入和仓库瘦身调研，不表示已支持 ORCA。[#252](https://github.com/anakine800-tech/Auto-Gaussian/pull/252)、[#259](https://github.com/anakine800-tech/Auto-Gaussian/pull/259)
- Frontend v4.0.0 配合 ag 4.1.0 使用：前端读取的 facts 字段保留，`ag-facts/1`、`ag-profile/1` 不变，profile 新增字段；分段解析修正可能改变既有 facts 的值，仍需人工审阅差异后显式刷新。
- 截至 2026-10-15，PBS 强杀与 Slurm TIMEOUT 不完整取回、父 chk 波函数接续已有真实验证；缺少声明输出分支仅有离线覆盖，任意中断 chk 的完整性不作保证。验收范围和已知问题见 [README](README.md#验收状态)。

## v4.0.0

发布准备中，尚未创建 tag 或 release。以下为相对 `v3-frozen` 的主要变化，仅计入本次 main 基线已合并内容。
本仓库 `#编号` 链接指向 Auto-Gaussian；跨仓库 PR 明确标注 Frontend。旧变更记录原样保留在 [archive/CHANGELOG.md](archive/CHANGELOG.md)。

### 架构

- 新建独立 `ag/` CLI 与 `skills-next/`，科学规划交给 Skills、LLM 和人，代码负责确定性操作及副作用控制；state/journal/manifest 存在 study 文件中，不再接入旧运行时。[#205](https://github.com/anakine800-tech/Auto-Gaussian/pull/205)、[#209](https://github.com/anakine800-tech/Auto-Gaussian/pull/209)、[#211](https://github.com/anakine800-tech/Auto-Gaussian/pull/211)
- 旧代码、脚本、配置、文档与 CHANGELOG 移入 `archive/`，新入口文档按 ag + Skills 重写；继续维护的绘图和学习辅助 Skill 迁到 `skills-next/`。[#215](https://github.com/anakine800-tech/Auto-Gaussian/pull/215)、[#216](https://github.com/anakine800-tech/Auto-Gaussian/pull/216)

### 安全内核

- Mac 人工确认、Attempt 原子单次提交声明、新远程目录、根目录/符号链接检查、模板白名单和确认前后哈希校验；UNKNOWN 只核对，不自动重提。[#209](https://github.com/anakine800-tech/Auto-Gaussian/pull/209)
- 完成回执、调度器残留和未知作业号核对；首次证据不足的观察与频率阶段收敛分别报告，避免将队列消失或优化收敛误当完成。[#212](https://github.com/anakine800-tech/Auto-Gaussian/pull/212)、[#213](https://github.com/anakine800-tech/Auto-Gaussian/pull/213)、[#214](https://github.com/anakine800-tech/Auto-Gaussian/pull/214)
- PBS 硬件容量核验、运行加排队额度与严格回退；批次只核验一次硬件、逐 Attempt 重查作业并计入尚未读回的本批提交，monitor 超额告警使用有效上限。[#219](https://github.com/anakine800-tech/Auto-Gaussian/pull/219)、[#224](https://github.com/anakine800-tech/Auto-Gaussian/pull/224)

- 同 study、同集群的父 checkpoint 受限复用：确认前核验父作业结束及调度器中不存在，确认大小/哈希后复制到新 Attempt，拒绝覆盖及路径替换。[#230](https://github.com/anakine800-tech/Auto-Gaussian/pull/230)

### 命令

- `init/prepare/submit/status/fetch/cancel/list/doctor` 作业生命周期与环境检查；Gaussian、xTB、CREST 模板。[#209](https://github.com/anakine800-tech/Auto-Gaussian/pull/209)
- `facts/thermo` 日志事实、GoodVibes qRRHO 与布居；`dedup/cluster/graph` 构象去重、聚类及 Attempt 关系。[#210](https://github.com/anakine800-tech/Auto-Gaussian/pull/210)、[#206](https://github.com/anakine800-tech/Auto-Gaussian/pull/206)
- `monitor` 只读快照和前台定时采样；保留上次成功信息并明确失败/陈旧状态。[#218](https://github.com/anakine800-tech/Auto-Gaussian/pull/218)
- Cartesian QST2/QST3 校验与位移摘要、CREST 约束文件入包及哈希绑定、IRC facts 和 `irc-compare` 映射端点比较。[#222](https://github.com/anakine800-tech/Auto-Gaussian/pull/222)、[#223](https://github.com/anakine800-tech/Auto-Gaussian/pull/223)、[#226](https://github.com/anakine800-tech/Auto-Gaussian/pull/226)
- `profile` 从构象系综组装守恒的反应自由能曲线、能垒、适用时的 Kozuch–Shaik 能量跨度与扰动分析。[#227](https://github.com/anakine800-tech/Auto-Gaussian/pull/227)
- `prepare --card` 记录卡片文本、Skills Git 来源；`review init/check` 生成审阅骨架并核对 facts 指纹，不代替科学签字。[#228](https://github.com/anakine800-tech/Auto-Gaussian/pull/228)

### Skills 与卡片

- study 编排、三处人工里程碑、Opt+Freq/单点/初筛/热化学/失败诊断及文献先例卡片；迁移 ChemDraw/RDKit 结构处理，部署采用软链接。[#208](https://github.com/anakine800-tech/Auto-Gaussian/pull/208)、[#207](https://github.com/anakine800-tech/Auto-Gaussian/pull/207)
- 纳入 L1 频率阶段与状态观察经验，确认摘要增加前端 3D 预览入口。[#214](https://github.com/anakine800-tech/Auto-Gaussian/pull/214)、[#217](https://github.com/anakine800-tech/Auto-Gaussian/pull/217)
- 新增机理规划、TS、IRC 与证据审阅卡片；TS 工具调研仅形成研究记录，不宣称自动搜索已集成。[#220](https://github.com/anakine800-tech/Auto-Gaussian/pull/220)、[#221](https://github.com/anakine800-tech/Auto-Gaussian/pull/221)
- 补全方法先例、DFT 重排/优化后去重、阴离子弥散、方法敏感性等科学卡片；规定单 study 单主会话推进、经验先留 lessons 后整理。[#225](https://github.com/anakine800-tech/Auto-Gaussian/pull/225)、[#228](https://github.com/anakine800-tech/Auto-Gaussian/pull/228)

### 多集群 / SCNet

- 配置驱动的 PBS/Slurm 适配，Attempt 绑定集群，提交记录与确切作业号交叉核验；按集群统计资源、核时预算、到期信息及监控快照，并校验跨结果程序版本一致性。实现不等于各站点实机验收。[#229](https://github.com/anakine800-tech/Auto-Gaussian/pull/229)

- 修复 Slurm 长作业名截断与填充空白解析；非父 chk 任务的可选环境检查改为警告，真正使用父 chk 时仍须满足环境要求。[#232](https://github.com/anakine800-tech/Auto-Gaussian/pull/232)
- 新增只读 `ag clusters --json`，返回白名单资源/程序配置及目录匹配布尔值；Slurm monitor 增加预算、到期和存储信息，缺值不当零。[#233](https://github.com/anakine800-tech/Auto-Gaussian/pull/233)
- SCNet Gaussian A.03 使用固定 `scnet-a03` 环境，scratch 留在新 Attempt，避免直接加载平台脚本造成根目录外写入；已完成单点链路验证。[#234](https://github.com/anakine800-tech/Auto-Gaussian/pull/234)
- 混合集群记录先按 manifest 过滤，再按所属调度器核验绑定；本地 review 不受无关远程配置阻塞，旧 manifest 可在审阅时补指定卡片。[#235](https://github.com/anakine800-tech/Auto-Gaussian/pull/235)
- PBS 槽位解析支持逗号组合范围并拒绝重叠/坏输入；解析失败仍严格回退，不放宽数组作业号限制。[#243](https://github.com/anakine800-tech/Auto-Gaussian/pull/243)

### 父 chk 与 RCFC 坐标取向

- 导出 `final_input.xyz` 与实际坐标取向；读取父 Cartesian 力常数时按固定原子顺序核对 Input 框架，拒绝 Standard/Input 错配，已有几何不覆盖。[#240](https://github.com/anakine800-tech/Auto-Gaussian/pull/240)

### 扫描与 scan-peak 局部极大

- 支持 Gaussian ModRedundant 和 xTB 一维弛豫扫描，解析逐点坐标、能量、收敛状态并导出扫描轨迹与 TS 初猜。[#239](https://github.com/anakine800-tech/Auto-Gaussian/pull/239)
- `scan-peak` 改为仅选两侧邻点均收敛的严格内部局部极大；列出全部候选，`--point` 按原扫描序号选择。无峰或非候选拒绝导出，不将扫描峰当成已验证 TS。[#248](https://github.com/anakine800-tech/Auto-Gaussian/pull/248)

### 构象双路线与 mdopt

- 多来源构象合并保留路线溯源，`coverage` 按 DFT 能量报告路线重叠和低能独有项，cluster 支持 medoid；卡片加入双路线与 NCI/定向采样边界。[#238](https://github.com/anakine800-tech/Auto-Gaussian/pull/238)
- CREST `--mdopt` 校验与优化多帧系综，提供专属输出及 `mdopt.xyz`；ETKDG 候选统一到 xTB 层级后，以 `dedup --representative lowest` 合并并开能量窗口，不混排力场与 xTB 能量。[#242](https://github.com/anakine800-tech/Auto-Gaussian/pull/242)

### 极性氢去重

- `dedup --hydrogens heavy|polar|all` 默认 polar，保留 N/O/S/P 上的氢朝向；coverage/cluster 继承选择。lowest 来源合并同时核对能差，报告重原子与实际判定 RMSD；旧无模式记录仍按 heavy 解释。[#246](https://github.com/anakine800-tech/Auto-Gaussian/pull/246)

### 热化学配对与审计

- 正确记录单原子 Freq 的零振动模式，区分线性/非线性模式完整性；修正 profile 方法规范化，保留基组与后续关键词边界。[#237](https://github.com/anakine800-tech/Auto-Gaussian/pull/237)
- SP 输入与 Freq 最终几何按原子顺序、proper Kabsch RMSD ≤ 0.001 Å 配对，拒绝错构象、镜像与来源缺失；输出 RRHO/qRRHO H/S/G、SP 替换、低频及标准态修正、d_i/σ_i 审计分项，不重复修正 qh_G。[#244](https://github.com/anakine800-tech/Auto-Gaussian/pull/244)

### facts 不改写与签字清单

- thermo/profile/review check 只读解析；facts 相同内容保留原字节与 mtime，不同内容默认拒绝，显式 `--refresh` 先保存旧版本。review 绑定 facts 生成时来源，`review manifest` 独占生成签字前的递归证据清单；清单不代替签字。[#247](https://github.com/anakine800-tech/Auto-Gaussian/pull/247)

### 波函数稳定性

- facts 提取 Stable 的 stable/internal_instability/rhf_to_uhf/unknown 及原文诊断，保留独立终止状态；不把 Stable=Opt 作为自动修复，不由普通 Opt/Freq 推断已验证波函数稳定性。[#245](https://github.com/anakine800-tech/Auto-Gaussian/pull/245)

### xTB 结束判定与 fetch 补取

- 普通/scan 输出声明补齐 PBS 输出，按调度器读取正常终止标记及错误；错误优先，缺失核查文件明确提示，并记录标记来源，不以退出回执替代程序标记。[#249](https://github.com/anakine800-tech/Auto-Gaussian/pull/249)
- `fetch --add-missing` 为已 fetched Attempt 补取缺失声明输出；先核验已有文件、全部暂存核验后独占发布，保留原文件/状态/manifest/journal，另存补取记录，不自动刷新 facts。[#251](https://github.com/anakine800-tech/Auto-Gaussian/pull/251)

### 卡片一致性与科学边界修订

- 新增开发手册、现场经验与任务单模板，明确提交顺序、证据边界和发布操作。[#236](https://github.com/anakine800-tech/Auto-Gaussian/pull/236)
- 按实际 CLI 检查卡片命令、选项和过期待办；统一方法表，连接 GKB 知识与参考书目，说明合并后本机运行版本的同步方式。[#241](https://github.com/anakine800-tech/Auto-Gaussian/pull/241)
- 明确预算窗口不等于覆盖、TS 不沿用极小点剪枝、电子态稳定性诊断、热化学/简并度/温度解释、IRC 步长与取向、约束搜索及无鞍点路径等科学边界。[#250](https://github.com/anakine800-tech/Auto-Gaussian/pull/250)

### 前端

- 独立前端改为本地 study 文件查看器，保留结构/振动显示，重做结果、热化学和关系图，移除旧数据库/查询服务依赖。[Frontend #4](https://github.com/anakine800-tech/Auto-Gaussian-Frontend/pull/4)
- 输入结构预览、父 Attempt 输入对比、日志搜索、结果总览、优化过程和 `ag monitor` 快照展示。[Frontend #5](https://github.com/anakine800-tech/Auto-Gaussian-Frontend/pull/5)、[Frontend #6](https://github.com/anakine800-tech/Auto-Gaussian-Frontend/pull/6)
- 默认只读；显式 `--enable-actions` 经本机 ag 新建、提交、查询、取回、取消，Mac 确认仍由 ag 执行。后续 T7e 已补齐多集群适配，见下一项。[Frontend #7](https://github.com/anakine800-tech/Auto-Gaussian-Frontend/pull/7)、[#229](https://github.com/anakine800-tech/Auto-Gaussian/pull/229)

- T7e 经 `ag clusters` 发现资源、核对 study 根目录并显式选择新 Attempt 集群；按集群展示快照、Slurm 预算/到期/存储和 default 来源歧义，继续由 ag 执行确认与作业绑定。[Frontend #9](https://github.com/anakine800-tech/Auto-Gaussian-Frontend/pull/9)、[#233](https://github.com/anakine800-tech/Auto-Gaussian/pull/233)
