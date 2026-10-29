# 当前开发与运维交接

核查日期：2026-10-29；当前后端正式发布 tag v4.7.0 为 `d2e6308e5f15964c363549d98e16239806650eb1`。
两仓同号正式 Release 已发布，T178/T177 发布 PR 均已合并，最终 HEAD 独立审阅、CI 与两项实际后端配套验证通过，配套 0 跳过；本机开发环境已部署两 tag，研究机未部署。
已合并的 21 个后端 PR 完整清单、行为和覆盖边界见 [CHANGELOG v4.7.0](../CHANGELOG.md#v470)。

| 当前能力 | 依据与边界 |
| --- | --- |
| 默认档位、walltime、单节点容量与具名 PBS 排队 | T154–T157 已合并。快照建议不保证启动；节点/作业不能匹配保持 unknown，可见性根因未确定，共享/排队正例未全部实测。 |
| CREST 诊断 | T159 已合并。旧普通 PBS/Slurm 正式取回兼容要求已满足；新输出集合、mdopt、不完整取回和真实错误的额外现场范围仍披露未覆盖，不伪造自然故障。 |
| 本地诊断与分析 | T161/T162 批量错误与原子对应、T164 父 chk 报告、T165 既有 SMD 单点组合已合并；T176 在 T163 历史规格基础上实现有限 xTB Hessian 本地导入与显式单候选 G0 analyses 来源。 |
| TS/构象与方法说明 | T166、T169、T170 阶段卡与构象分支已合并；T173 方法先例定位、T174 历史来源整理不改变方法值或科学范围。 |
| 远程观察缺陷 | T175 已在 #370 合并并通过独立审阅/CI；原 10 次观察外，新增 8 次调用各一次且通过预定判据。helper 覆盖两个 PBS 与两个 Slurm 入口，含 Multiwfn 隔离副本 status 保持 fetched；自然输出缺失、另一个未测 PBS 入口和完整新作业生命周期仍未覆盖。 |
| 历史 unreadable 调查 | T167 关键底层诊断未保存，历史根因无法判定；两个独立复现代码缺陷由 T175 修复，不以此声称原根因已查明。 |

协调方提供的既有私有部署记录确认：当时后端运行检出为 `c1a0d084fd5f53d1fb4ab15dd3c57c12ad447a8f`，前端为
`fa48ab1a0c0d669233a189bb5457b143d07dd798`，包版本仍为 4.6.3；Docs/Skills 同步与本机资源配置维护已完成。
这些是此前获准部署的事实，不是 v4.7.0 已部署的证据；真实配置值和原始记录只留私有目录。
前端另已合并 [T179 #52](https://github.com/anakine800-tech/Auto-Gaussian-Frontend/pull/52)，
合并提交 `8ceda045b1aa007c9dba882f287b11b4df12b840`；setuptools 固定为 84.1.0，前端运行代码与产品版本未改。
上述 `fa48ab1a` 只表示此前部署/功能基线，不是当前前端 main。T177 已整合 T179；后端依赖不随本单更改。

## v4.7.0 发布交接

| 项目 | 当前状态 |
| --- | --- |
| 后端 T176 | [#371](https://github.com/anakine800-tech/Auto-Gaussian/pull/371) 合并为 `7dba69194e0093dca955b98d9220653f8dd7e038`；最终 head `e722d9887e288015ebd4630afa4ee9c1a1e485b7` 两路独立终审及五项 CI 通过，Linux 后端 6385 passed / 2 skipped、Skills 527 passed；真实非研究水包的格式/数值和公开副本审阅通过 |
| 后端 T178 | [#372](https://github.com/anakine800-tech/Auto-Gaussian/pull/372) 已合并；最终 HEAD 独立审阅与 CI 通过，[T178](redesign-tasks/T178-release-v4.7.0-backend.md)保留发布前验证记录 |
| 前端 T177 | [#51](https://github.com/anakine800-tech/Auto-Gaussian-Frontend/pull/51) 已合并；使用实际 T178 合并源码完成两项配套验证，均通过、0 跳过，最终 HEAD 独立审阅与 CI 通过 |
| 两仓发布合并 SHA | 后端 `d2e6308e5f15964c363549d98e16239806650eb1`；前端 `f9c8143d4b30ff912140bcc4e2e931373754a84c`；分别为各仓 v4.7.0 固定 tag |
| tag/Release 与部署 | [后端 Release](https://github.com/anakine800-tech/Auto-Gaussian/releases/tag/v4.7.0) 与 [前端 Release](https://github.com/anakine800-tech/Auto-Gaussian-Frontend/releases/tag/v4.7.0) 已于 2026-10-29 正式发布。本机开发环境已部署两 tag、版本全为 4.7.0；五入口 doctor 各一次通过、首轮 21.407 秒内成功，心跳/PID、三个 HTTP 200、浏览器五卡/构建及最终独立审阅通过。研究机未部署，不自动触发部署 |

本次 T180 仅收尾此既有交接页的发布状态；发布 tag 及其内的准备阶段文字、T178 等历史任务均保留，不以本次文档提交替换发布目标。上方旧部署记录仅作历史，未扩大现有验证或科学适用边界。

当前入口：[T178 工单](redesign-tasks/T178-release-v4.7.0-backend.md)、[开发与验证](DEVELOPING.md)、
[部署目标与授权适用表](OPERATIONS.md#部署目标与授权适用表)、[文档索引](README.md)。
开发机采用已审阅合并提交的长期部署策略仍待负责人确认；单次已执行更新不等于长期策略获批。

## 架构速览

- `ag/`：CLI 与本地工具。远程只执行固定命令；提交核对一次性批准、明确选择的长期规则或 Mac 人工点击，具体入口/验证的更窄要求保留；取消始终由人点击；每个 Attempt 只能提交一次。
- `skills-next/`：study 编排、计算卡片，以及结构、文献等 Skill；方法和基组只在 `acceptance-methods.md` 定义。
- 前端（独立仓库）：省略 `--enable-actions` 时只读查看 study、3D 和监控；标准部署显式启用操作模式，并核对 `--ag` 后端路径。操作模式不代替 ag 授权核对，不推定前端支持每个 CLI 授权参数；取消仍须人点击。字段兼容性核对范围见 [README](../README.md#前端)。
- 集群：支持 PBS/Torque 和 Slurm；核数额度和程序环境以本机配置及实际核验为准。
- study 数据全部在仓库外；工程检查不读取或改写研究证据。

## 验收与验证状态

以下根据负责人在 T48 提供的结论更新，T47 实测与签字见 [#266](https://github.com/anakine800-tech/Auto-Gaussian/pull/266)；T66 的缺输出取回结论另据 [#282 的真实验证评论](https://github.com/anakine800-tech/Auto-Gaussian/pull/282) 更新；本次没有重新运行计算或代签。

| 项目 | 状态 | 要点 |
| --- | --- | --- |
| SCNet | 已验证 | Gaussian 链路；CREST/xTB 中性和 +1 体系、ALPB 溶剂、取回与解析 |
| L1 | 已签字（流程验收） | 构象、Opt+Freq、热化学全流程；不外推任意体系精度 |
| L2 | 已签字（流程验收） | 有限构象集合、覆盖不完整；签字证据不得静默改写 |
| L3 | 历史流程验收已签字 | 早于 T46；按当前判据仍缺完整连续性审阅，reverse 末点降能低于默认阈值，不能声称按 T46 双向完成，详见 irc 卡片第 7 节 |
| V-T21 扫描 | 已完成 | Gaussian 扫描与 scan-peak 验证；xTB 无合格局部峰时拒绝导出，不据此推断真实反应无能垒 |
| 某研究验证 study 双路线覆盖 | 已终止 | 不再单独验证，改由实际研究中的使用检验；不等于采样完备 |
| TS 中断后接续 | 已验证 | `final_input.xyz` + 父 chk 的 `Guess=Read Opt=(TS,CalcFC)`；没有 Freq 的中断优化不能用 RCFC 接续 |
| T47 不完整取回 | 已验证 | PBS 强杀、Slurm TIMEOUT 均通过；T66 已验证 Slurm 缺少声明输出分支，成功取回不等于计算成功，任意中断 chk 可读性不作保证 |

## 两台电脑

1. 开发机可以在具体工单/授权范围内连接集群，所有开发任务和合并前真实验证在开发机完成；计算机只负责研究 A 计算。日常提交按三种方式核对；开发验证要求负责人在对应 Mac 上亲手点击时仍须点击。
2. 每个 study 只属于一台电脑，不复制；换电脑必须整体移动，旧电脑不留副本，移动前确认没有 submitting 或 unknown 状态的 Attempt。
3. 日常 `ag` 只用获准固定运行检出的 `.venv/bin/ag`，核对确切提交/tag、导入来源和 Skills 链接，不在提交计算前自动拉取 main。未合并代码的真实验证按 [开发手册](DEVELOPING.md#开发机分工与合并前真实验证)在工单写明对象和步骤并取得批准，在开发机的临时 worktree 使用非研究 study，合并前完成；证据留在仓库外，worktree 不再需要时归档。
4. Slurm 台账只记录本地 ag 核时预估、预留与结算，不代表平台余额；`budget_core_hours` 不再拦截，unknown 不释放。全部本人作业及共享入口未观测预留仍受核数/排队上限检查，台账完整性检查仍有效。
5. 涉及证据清单、远程命令、提交、状态、取回的改动，合并前在 L1、L2 或专门的验证 study 完成真实验证；研究 A 只做观察，不作为验证对象。纯文档、纯本地分析工具不受此限。

按上述开发/计算分工使用两台电脑；同一 study 仍只由一个主会话推进，其他会话只读。

## 已知问题与后续工作

- catalog v2 升级不可降级；T162 已提供 [G0 显式原子对应](g0.md#显式原子对应t162)，reference/frequency 分别绑定来源。缺映射保持身份未核实、缺有效 frequency 映射不投影；`declared_verified` 只证明声明通过，不证明化学身份，也不新增提交门槛。立体标签仍须来自完全相同的几何。[T162 #359](https://github.com/anakine800-tech/Auto-Gaussian/pull/359)
- T161/T162 批量在频率分段歧义或可定位到候选的映射声明/绑定错误时保留成功项，单列错误并返回 2，且不写任何候选事件；来源本身损坏等完整性错误仍停止。`ag scan-path` 仅支持一维扫描。[T161 #352](https://github.com/anakine800-tech/Auto-Gaussian/pull/352)
- T163 保留为历史设计；[T176 #371](https://github.com/anakine800-tech/Auto-Gaussian/pull/371) 已实现 [有限的 xTB Hessian 本地导入](research/xtb-hessian-import.md#8-t176-本地导入接口)。该说明和 T176 任务内的 draft/待终审文字是合并前记录，最终状态以上方实际合并及 CI 定位为准。指定构建、同框架几何、有效质量及来源字节均须核验；不连接远程或生成 Hessian。单候选 `--modes-analysis` 使用独立来源描述符和显式原子映射，批量 Gaussian 来源不变，不把 xTB `g98.out` 或 analyses 标识伪装成 Gaussian Attempt。保留完整带符号谱；外部空间不能可靠分离时无可用模式，水包格式验收不等于科学驻点验收。
- [TS 总入口](../skills-next/auto-g16-recipes/cards/ts.md)保留兼容锚点和核心判据，按[初猜](../skills-next/auto-g16-recipes/cards/ts-guess.md)、[搜索/Freq](../skills-next/auto-g16-recipes/cards/ts-search.md)、[IRC/端点](../skills-next/auto-g16-recipes/cards/irc.md)拆分；各卡恢复统一 285 行上限。[原指南整理稿](../skills-next/auto-g16-recipes/references/ts-initial-guess-guide.md)标注来源与过时说明，未改旧 Attempt 快照。
- T127 仍串行采样；经转发时单条 SSH 约 10–20 秒、一轮可能 100–150 秒。重试启动需等待当前入口完成，新快照还需目标入口自身采样时间；电脑睡眠时停采，醒来自动恢复，首轮网络未就绪可能失败或退避。部署按 OPERATIONS 的睡眠判断与观察标准记录。
- **T127 Transport 重复逻辑已由 T130 解决：** 当前 `MonitorTransport._execute` 通过 `super()._execute(..., observe_stderr=classify)` 复用基类执行与错误处理，仅在脱敏前分类错误；`ag/tests/test_connect_timeout.py` 已覆盖与基类的返回结果、超时及本地启动失败一致性。监控仍不立即重试，串行采样及睡眠恢复限制见上一条。[T130 #332](https://github.com/anakine800-tech/Auto-Gaussian/pull/332)
- 前端证据库冷启动已有测量约 2.5 秒，source-map-js 临时 override 待上游修复后删除。
- Gaussian-only 白名单入口已支持；Slurm 省略 Gaussian 配置、只运行 xTB/CREST 仍未支持，config 校验仍读取 Gaussian 路径。T159 已补 CREST 异常诊断与新输出集合；现场缺日志仍记未知，旧 manifest/取回记录不变，不自动补取或刷新，旧普通 PBS/Slurm 取回均已通过；新集合、mdopt、不完整取回与真实错误仍按上方发布摘要保留现场边界。
- T108 facts 语义、T109 等价原子映射与 `--mirror report`、T112 doctor 独立 PBS 集群误报均已修复；既有 facts 是否重算及 catalog 是否补登记，由负责人逐 study 决定，不自动改写证据。
- **C 批：TS 初猜工具链（T130–T139）已完成。** `ag catalog` v2（[#334](https://github.com/anakine800-tech/Auto-Gaussian/pull/334)）、`ag scan-peak --gaussian-ts --route`（[#335](https://github.com/anakine800-tech/Auto-Gaussian/pull/335)）、`ag qst-endpoints`（[#336](https://github.com/anakine800-tech/Auto-Gaussian/pull/336)）、`ag scan-path`（[#337](https://github.com/anakine800-tech/Auto-Gaussian/pull/337)）、`ag g0` 与模式投影（[#338](https://github.com/anakine800-tech/Auto-Gaussian/pull/338)、[#339](https://github.com/anakine800-tech/Auto-Gaussian/pull/339)）、`ag profile` 的最低 TS / 系综 / 差值三数报告（[#333](https://github.com/anakine800-tech/Auto-Gaussian/pull/333)）、卡片口径（[#340](https://github.com/anakine800-tech/Auto-Gaussian/pull/340)）和连接超时（[#332](https://github.com/anakine800-tech/Auto-Gaussian/pull/332)）均已合并；前端通道与候选只读面板见 [#40](https://github.com/anakine800-tech/Auto-Gaussian-Frontend/pull/40)。诊断和登记不是门禁或科学验收。
- T155 路由已核对提供的 walltime 与入口配置上限，并排除单节点总规格装不下的排队回退；未提供 walltime、未配置时限或快照过期时明确未知，不把建议当作启动保证。
- T164 已提供[父 chk 本地报告](parent-chk-report.md)，分别汇总实际频率日志、历史 checkpoint 关联和坐标来源；不读取 chk/fchk，内部力常数仍为 unverified，科学适用性仍由人审。它不改变 prepare/submit，不把坐标匹配或复制哈希当作 RCFC 可用证明。[T164 #358](https://github.com/anakine800-tech/Auto-Gaussian/pull/358)
- T165 已支持 `cp-report --solvent-sp` 配合两项 `--solvent-fragment-sp <index>:<attempt>`，读取复合物几何下、片段自身基组的既有 SMD 单点。缺任一片段时相互作用能仍为 null；齐全时报告差值及加气相 BSSE 的近似值，不是结合自由能，不进入 thermo/profile。只完成合成组合验证，未新增配套真实 SMD 验证；详见 [CP 报告](ag-cp-1.md#已有片段-smd-单点t165)。[T165 #356](https://github.com/anakine800-tech/Auto-Gaussian/pull/356)
- T62 的 unreadable 已由 T65 回退恢复指定观察路径；关键底层诊断未保存，[T167 历史调查](research/unreadable-investigation.md#历史调查结案边界2026-10-29)结案为根因无法判定。两项独立复现代码缺陷已由 [T175 #370](https://github.com/anakine800-tech/Auto-Gaussian/pull/370) 修复；未覆盖场景见上方摘要，不再将 T175 列为待开发，也不将修复归因为原事故。
- T68 的 R1 已由 T89 修复：topology / irc-compare 识别固定编号下的共振等价；失败或超限保留 `unknown`，仍检查立体化学，共振等价不是电子密度证据。R2 已由 T73 修复，不确定接触不再单独把状态提升为 changed；确定变化仍列出。不要只凭总电荷、顶层状态或空差异列表签字，需结合原子映射、警告与结构审阅。[T89 #303](https://github.com/anakine800-tech/Auto-Gaussian/pull/303)、[T73 #288](https://github.com/anakine800-tech/Auto-Gaussian/pull/288)
- T77：其他用户的 PBS 数组作业不再阻断本人核数统计、提交和监控；本人数组（含已完成但仍保留在 qstat 中的 C 记录）仍拒绝提交，`ag monitor` 也会报错，须等记录消失后再提交。ag 不提交或取消数组作业。[#291](https://github.com/anakine800-tech/Auto-Gaussian/pull/291)
- 组里集群上作业结束后，PBS 有时仍短暂显示 R，曾观察到约 6 分钟后自行消失；ag 会将这类残留计入已占用核数，只会多算。该观察不等于任意残留都会自行消失。
- T102 已改为连续 60 秒无进展或达到 24 小时才停止取回；超时不自动重试。断点续传尚不支持，列为可选后续工作。[#311](https://github.com/anakine800-tech/Auto-Gaussian/pull/311)
- T102 已支持取消证据、作业绑定和独立结束证据齐全的 `cancelled` Attempt 不完整取回；仍保留 PBS 双次稳定观察或 Slurm 唯一终态核对，发出取消本身不证明作业已经停止。[#311](https://github.com/anakine800-tech/Auto-Gaussian/pull/311)
- T90 已提供按约束组枚举；真实用例中的二面角网格、位点范围与组合上限仍需审阅设定，超限应缩小范围，不随机抽样或以候选数证明采样完备。

- 证据清单对缺失/越界引用列出 `unresolved_references`，退出码 4 且不写入；签字人核对后用 `--accept-unresolved` 生成，不需改写历史卡片副本。study 内存在的 analyses 外引用和无 analyses 同名文件的裸名只记信息条目、汇总数量；普通 JSON 支持源目录/study 根目录回退与歧义拒绝。study 内符号链接、专用证据指针缺失/越界、收集期间改动仍硬拒绝，详见 [review manifest](../ag/README.md#签字证据清单review-manifest)。
- T101/T106：同一实际集群多个入口合并核数统计，总上限取各入口最小值。`max_cores` 为单作业上限，`max_committed_cores` 为运行加排队总上限，已取消四倍限制；可选 `max_queued_cores` 另限排队、挂起和未观测预留。ag 不控制调度器何时启动作业，运行核数可能达到总上限。升级时核对资源配置；default 明写 `max_cores = 44`，迁移须携带各 Slurm 入口台账。[#310](https://github.com/anakine800-tech/Auto-Gaussian/pull/310)、[#313](https://github.com/anakine800-tech/Auto-Gaussian/pull/313)

2026-10-14 卡片审阅的后续清单（按 T48 审阅确认更新）；T36–T47 完成不表示以下事项全部完成：

- **已完成：** F1、F2、S1、S9、U3、U5（T36–T40、T46）；F3 动力学解释卡、S7 隧穿适用边界、S8 SMD/标准态核对、F4 核时估算与记录说明、Gaussian 报错速查（T58；不新增隧穿程序或核时额度拦截）。
- **未完成，第二批：** U1 跨卡片重复段落；U2 拆卡（扫描单独成卡、crest-screen 拆分、profile 拆分）；U7 长句。U4 卡片要点和 F6 阶段决策表补行已由 T81 / T79 完成。
- **已提供，使用设定仍需审阅：** F5 的定向构建与系统枚举已由 T86 / T90 完成；不自动选位点、进攻面或采样范围。
- **推迟到第二阶段：** S2 几何层与阴离子基组；S4 质子转移与酸碱平衡；S5 高层级方法抽查（双杂化或 DLPNO，依赖 ORCA 的决定）。S10 已由 T105 提供固定两片段的气相 Counterpoise 诊断，T165 接入独立 SMD 片段单点的本地组合；G16 A.03 的 CP/SCRF 同作业限制仍保留，范围及验证边界见上文 CP 条目。
- **S3/S6 说明已补齐：** [study 模板](../skills-next/auto-g16-study/references/study-md-template.md)有“σ 约定与比较口径”，[profile 卡片](../skills-next/auto-g16-recipes/cards/profile.md)明确 IRC 连接不证明真实动力学轨迹或产物比例；工具不自动替人填写、验证或签字。
- **尚未开始：** 每周清理（AGENTS §4.3）。

- 以后按实际需要安排：二维扫描前端能量面显示、专用剖面图和 QST 预览、ORCA 接入、Gen/ECP、开壳层。二维扫描后端已支持，前端能量面显示尚未支持；T87 已提供只读 IRC 曲线与路径点结构。调研完成不等于功能已支持。
- `ag asm` 的实际研究应用仍需相应计算与科学审阅，本地工具和离线测试不代表研究分析已完成。

## 运维与新会话

- 当前维护以 [OPERATIONS](OPERATIONS.md) 的适用表为准：常规发布固定 tag，具体更新授权绑定两仓完整提交，安装/构建/服务验收与合并前代码验证分开。不要执行历史 v4.5.0 的跟随 main 指示。
- 研究用计算机的同步时间由负责人安排；先确认无取回、提交、reparse 或 catalog 写入，备份配置及执行环境，在获准维护窗口内独立验收。新入口和格式启用遵循既有批准要求，不把开发机结果当研究机结果。
- 前端常驻操作模式须显式配置，重启后刷新令牌；仅配置维护按具体授权重新加载。已停用监控保持停用，doctor、采样和代码部署不由文档更新自动触发。
- 新计算入口的公钥、主机指纹和跳转路径由负责人本人核验，私钥和密码不经过会话；接入后仍须负责人签字才能用于研究计算。首次使用聊天批准前，由负责人确认 Skills 中的新流程。
- study 和签字证据清单定期备份到仓库外的备份位置；备份不作为另一台电脑的可推进副本。
- 集群到期日、存储限制和余额由负责人按本机记录核对；定时自动审阅已停用，需要审阅时手动请监督方。
- 升级后旧 Opt+Freq facts 可能受 T99 route 换行误判影响；对 fetched Attempt 先用 `ag facts <Attempt> --reparse --dry-run --out <study 外的新 JSON>` 预览，审阅差异后再正式 `--reparse`。旧 facts 保留在 `facts-history/`，命令列出引用旧哈希的文件，涉及已签内容由负责人重新确认；不自动改引用或签字。T82 导致 thermo / profile 拒绝旧输入时，核对一致性和频率证据，不绕过；签字前先生成证据清单。
- 新研究先读 `auto-g16-study` Skill 和当前卡片，明确目标、机理假设、计算方案与方法依据，按所需里程碑签字后推进；恢复研究先读 study 的当前状态和阻塞，不凭对话记忆重复提交。

角色与审批见 [开发手册](DEVELOPING.md#角色与审批)，文档入口见 [文档索引](README.md)。

## 历史发布记录

以下保留当时的发布准备与计划，仅用于追溯；其中“待合并/部署”等措辞不表示当前仍待执行，也不授予操作权限。当前进度以上方核查基线为准，维护步骤统一查 OPERATIONS。

### v4.6.3 历史发布准备

2026-10-27，T152 在后端基线 `8011bccce078439cc8c80bd0790ec532c40d1a04` 上准备 v4.6.3，汇总已合并的 T148 #347、T149 #349、T150 #348；前端基线 `a65e4854c219cc819533fdfd6699080ee6b68a96` 已含 T147/T151，发布准备由 T153 独立负责。范围和兼容边界见 [CHANGELOG v4.6.3](../CHANGELOG.md#v463)，后续部署步骤见 [OPERATIONS](OPERATIONS.md)。

本批已合入 PBS 重复节点容量、时间可信度/只读内存名称归属、重试终态/配置重读与首次比较、新输入核数补齐，以及前端 Slurm Other/Idle 和四项页面反馈修补。它们不再作为待开发项；正式服务是否已采用这些修补只据私有部署证据，本次不部署。D01 前端运行时版本显示由 T153 同步为 4.6.3，属于配套发布准备验收，不另列为功能待开发。

重启前 running 的请求可能已查询，但没有可确认的发布完成结果；monitor_restarted 不表示从未执行，也不重放请求或取消作业。T149 仅澄清共用字段第 6 项，T153 修改 T151 后须比较完整共同字段块，当前不宣称两仓已同步。新输入仅补缺失资源；普通完整输入保持字节，既有 CP 转换保留，最终哈希绑定实际保存字节，旧 Attempt 不重写。

交付终点为一个发布准备 PR，待监督方复核、负责人合并；再将实际完整合并 SHA 交给 T153。最终 HEAD、测试、扫描与 CI 见本单 PR。tag/Release 和部署均须后续明确指示；两仓 tag 只能指向各自发布 PR 的确切合并提交，不用届时 main 代替。本次仅离线合成与发布准备验证；未新增现场查询、未部署、未运行真实计算。节点策略、资源上限、既有部署顺序、180 秒首轮/90 秒心跳、观察及停止条件不变；不新增 study/catalog 迁移或研究写入授权。

### v4.6.2 历史交接

2026-10-27，T146 准备同号 v4.6.2 发布 PR，基于已审阅并合并的后端 T145 #345 与前端 #44。两个发布 PR 经监督方审阅后，按负责人明确授权合并并在确切发布合并提交创建同号 tag/release；两仓版本验证完成后才部署。发布准备不等于部署或现场计算验收。当前步骤见 [v4.6.2 CHANGELOG](../CHANGELOG.md#v462) 和 [OPERATIONS.md](OPERATIONS.md)。

新能力仅对显式配置入口启用。节点必须明确选择，原始优先级组与顺序分开展示；半数默认、四分之一可选，资源仍匹配既有档位。保留原入口、Gaussian-only、四/五卡监控和提交审批。启用策略或调整档位前只读检查 prepared Attempt，禁止改写历史 manifest/哈希。新节点绑定记录不以删字段方式降级；回退先恢复相容配置和执行环境，无法安全操作新记录时报告部分恢复。

开发机须完成所有入口 doctor、180 秒首轮、90 秒心跳、节点选择及负责人指定观察期，并单独获批完成合成计算的实际运行位置、输出和回执核对，再安排研究机维护。特殊 CPU 映射、非原子跨机竞争、认证持久性和 PBS_NODEFILE 原文留证仍须分别落实。真实配置与全部原始证据只写私有交接。下述旧版段落为历史记录，不表示旧发布 PR 仍待合并。

### v4.6.1 历史交接

2026-10-27，T144 准备后端与前端同号 v4.6.1 发布 PR。功能范围为已合并的后端 T141 #342、T142 #343 及前端 T143 #42；升级和回退以 [v4.6.1 CHANGELOG](../CHANGELOG.md#v461) 与 [OPERATIONS.md](OPERATIONS.md) 为准，取代下文历史版本的部署步骤。两个发布 PR 仍须监督方审阅和负责人合并；随后由负责人在各自确切合并提交创建 tag/release，部署另行批准。开发机必须通过逐入口 doctor、180 秒首轮快照、90 秒内心跳且 PID 对应、原入口回归、前端和指定观察期，以及部署计划要求的其他独立验收后，才可安排研究机配置。研究机须有无研究写入的批准维护窗口并独立验收，不能复用开发机结果。共享目录、Gaussian 计算节点环境、单节点资源和调度限制、认证持久化仍以现场证据为准；发布不等于服务器接入成功。真实配置、备份、哈希、观察时长和结果仅写入私有交接。回退须恢复旧版本兼容配置，不改已有 Attempt 或研究证据。

本补丁不增加 study/catalog 迁移。既有 catalog v2 启用条件保留：两台电脑部署完成后，研究机临时非研究 study 的候选登记、`ag g0 --record` 与前端台账核对通过前，真实研究 study 不写 v2 事件；第一次 `--upgrade-catalog` 须负责人批准，升级不可降级，试写 study 保留在以下划线开头的容器目录。提交审批仍以 [v4.5.0 升级须知](../CHANGELOG.md#v450) 为准：显式聊天批准记录或长期规则经核对后可用于提交，未指定时弹 Mac 确认框；取消仍须人亲手确认，此规则取代下文旧的统一提交弹窗表述。

### v4.0–v4.5.0 历史汇总

本轮 v4.5.0 汇总 v4.4.0 之后的后端 12 个主线 PR 与前端 8 个主线 PR（另含合入功能分支的 #33）：facts 与去重、提交批准、自动内存、监控与时区、路由建议、采用登记、TS 初猜审计、四入口导航、报告阅读、计算链及比较证据。升级须知见 [CHANGELOG v4.5.0](../CHANGELOG.md#v450)；真实验证见各 PR 评论，发版不等于科学验收。

v4.4.0 汇总 v4.3.0 之后的后端 T101、T102、T105、T106 共 4 个 PR，以及前端 T103、T104 共 2 个 PR：共享入口核数、取回与确认、气相 CP 诊断、可配置 PBS/排队限额与独立 CREST、监控总上限与 R/U 比较修复、IRC 三结构并排查看。升级须知见 [CHANGELOG v4.4.0](../CHANGELOG.md#v440)；各项真实验证见对应 PR 评论，发版不等于科学验收。

v4.3.0 汇总后端 v4.2.2 之后的全部 15 个 PR：开题与结构准备、复合物构建和枚举、TS 立体标签、IRC 审阅与路径哈希、运行日志快照、共振等价、Multiwfn / NCI、输入与热化学一致性、Gaussian route 解析以及卡片与查看规则。前端汇总 T87、T94–T98a 的 7 个 PR，提供四个入口、IRC 查看及快速比较；各项真实验证见对应 PR 评论，发布不等于科学验收。升级须知见 [CHANGELOG v4.3.0](../CHANGELOG.md#v430)。

v4.2.2 汇总 v4.2.1 后已合并的 T73–T77：topology 不确定接触修复、SSH 日志与命令示例引用修复、Gaussian 二维扫描、畸变–相互作用分析、PBS 数组观察兼容；功能、兼容性与验证限制见 [CHANGELOG](../CHANGELOG.md#v422)。v4.2.1 已汇总 T62、T64–T66、T68–T70、T72。更正：v4.2.0 tag `34d88fc` 实际已包含 T63（#279）。此前 T36–T47（含 T36a/T36b、T42b）已随 v4.1.0 汇总。
`ag` 负责作业生命周期和确定性工具，Skills 卡片负责科学流程，人负责签字和提交确认。
新增分段解析、topology、mode-review、fragments、profile 焓熵/动力学/选择性与 σ 报告、不完整取回和中断父 chk 复用。
计算方案签字、显式方法依据、复合物卡片及 TS/IRC 判据已落地；研究按当前卡片推进，历史流程签字不代替现行科学判据。
