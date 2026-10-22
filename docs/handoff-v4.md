# v4.4.0 交接

2026-10-22，后端与前端统一为 v4.4.0，发布准备由两份 T107 PR 完成。两边均须监督方审阅、负责人合并，再由负责人在各自 PR 的确切合并提交上创建 tag 和 release。本文供接手的人与新会话读取当前状态和使用规则。

## 现状

本轮 v4.4.0 汇总 v4.3.0 之后的后端 T101、T102、T105、T106 共 4 个 PR，以及前端 T103、T104 共 2 个 PR：共享入口核数、取回与确认、气相 CP 诊断、可配置 PBS/排队限额与独立 CREST、监控总上限与 R/U 比较修复、IRC 三结构并排查看。升级须知见 [CHANGELOG v4.4.0](../CHANGELOG.md#v440)；各项真实验证见对应 PR 评论，发版不等于科学验收。

v4.3.0 汇总后端 v4.2.2 之后的全部 15 个 PR：开题与结构准备、复合物构建和枚举、TS 立体标签、IRC 审阅与路径哈希、运行日志快照、共振等价、Multiwfn / NCI、输入与热化学一致性、Gaussian route 解析以及卡片与查看规则。前端汇总 T87、T94–T98a 的 7 个 PR，提供四个入口、IRC 查看及快速比较；各项真实验证见对应 PR 评论，发布不等于科学验收。升级须知见 [CHANGELOG v4.3.0](../CHANGELOG.md#v430)。

v4.2.2 汇总 v4.2.1 后已合并的 T73–T77：topology 不确定接触修复、SSH 日志与命令示例引用修复、Gaussian 二维扫描、畸变–相互作用分析、PBS 数组观察兼容；功能、兼容性与验证限制见 [CHANGELOG](../CHANGELOG.md#v422)。v4.2.1 已汇总 T62、T64–T66、T68–T70、T72。更正：v4.2.0 tag `34d88fc` 实际已包含 T63（#279）。此前 T36–T47（含 T36a/T36b、T42b）已随 v4.1.0 汇总。
`ag` 负责作业生命周期和确定性工具，Skills 卡片负责科学流程，人负责签字和提交确认。
新增分段解析、topology、mode-review、fragments、profile 焓熵/动力学/选择性与 σ 报告、不完整取回和中断父 chk 复用。
计算方案签字、显式方法依据、复合物卡片及 TS/IRC 判据已落地；研究按当前卡片推进，历史流程签字不代替现行科学判据。

## 架构速览

- `ag/`：CLI 与本地工具。远程只执行固定命令；提交和取消必须由人在 Mac 上点击确认；每个 Attempt 只能提交一次。
- `skills-next/`：study 编排、计算卡片，以及结构、文献等 Skill；方法和基组只在 `acceptance-methods.md` 定义。
- 前端（独立仓库）：默认只读查看 study、3D 预览和服务器监控；显式开启后才能触发 ag 操作，提交仍需人点击确认。字段兼容性核对范围见 [README](../README.md#前端)。
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
| V-T22 双路线覆盖 | 已终止 | 不再单独验证，改由实际研究中的使用检验；不等于采样完备 |
| TS 中断后接续 | 已验证 | `final_input.xyz` + 父 chk 的 `Guess=Read Opt=(TS,CalcFC)`；没有 Freq 的中断优化不能用 RCFC 接续 |
| T47 不完整取回 | 已验证 | PBS 强杀、Slurm TIMEOUT 均通过；T66 已验证 Slurm 缺少声明输出分支，成功取回不等于计算成功，任意中断 chk 可读性不作保证 |

## 两台电脑

1. 开发机可以连接集群，所有开发任务和合并前真实验证在开发机完成；计算机只负责 HSS 计算。每次提交仍由负责人在对应 Mac 上亲手点击确认。
2. 每个 study 只属于一台电脑，不复制；换电脑必须整体移动，旧电脑不留副本，移动前确认没有 submitting 或 unknown 状态的 Attempt。
3. 运行 `ag` 只用跟随 main 的检出，提交前先 `git pull --ff-only`，调用该检出的 `.venv/bin/ag`；日常研究不使用开发分支。未合并代码的真实验证按 [开发手册](DEVELOPING.md#开发机分工与合并前真实验证)在工单写明对象和步骤并取得批准，在开发机的临时 worktree 使用非研究 study，合并前完成；证据留在仓库外，worktree 不再需要时归档。
4. Slurm 核时预算只统计本机提交的 ag 作业，平台余额由负责人自己查看；核数上限按该用户在集群上的全部作业统计。
5. 涉及证据清单、远程命令、提交、状态、取回的改动，合并前在 L1、L2 或专门的验证 study 完成真实验证；HSS 只做观察，不作为验证对象。纯文档、纯本地分析工具不受此限。

按上述开发/计算分工使用两台电脑；同一 study 仍只由一个主会话推进，其他会话只读。

## 已知问题与后续工作

- facts 语义修正：驻点结论另设字段，明确两套收敛阈值，补充稳定性识别与 ⟨S²⟩ 读取；当前工具状态不能代替科学审阅。
- dedup 后续支持芳香等价原子识别与 `--mirror report` 模式；这些能力尚未提供。
- doctor 会对不同 SSH 身份的独立 PBS 集群误报“疑似同集群入口未合并”；不影响统计，后续修复提示范围。[#310](https://github.com/anakine800-tech/Auto-Gaussian/pull/310)
- CP 溶剂相片段单点：`cp-report --solvent-sp` 目前只有复合物单点输入，缺两个片段 SMD 能量时相互作用能未知。后续支持两个片段在复合物几何下、使用自身基组的 SMD 单点；不以气相值代替。[#312](https://github.com/anakine800-tech/Auto-Gaussian/pull/312)
- T62 远程观察改动在真实运行中出现 unreadable，已由 T65 回退；T65 评论确认观察路径恢复，现场根因尚未确定。旧 receipt/普通输出观察对权限与缺失的判断局限仍在；带诊断信息的观察命令须在非研究 study 上真实验证后再合并。[#281](https://github.com/anakine800-tech/Auto-Gaussian/pull/281)
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
- **推迟到第二阶段：** S2 几何层与阴离子基组；S4 质子转移与酸碱平衡；S5 高层级方法抽查（双杂化或 DLPNO，依赖 ORCA 的决定）。S10 已由 T105 提供固定两片段的气相 Counterpoise 诊断；G16 A.03 实测拒绝 CP/SCRF，溶剂相片段单点仍待扩展。
- **部分完成：** S3 已有 σ 报告和修订版一致性检查，但 study 里没有强制写定 σ 约定；S6 已写明“端点只证明连接”，profile 卡片尚未专门补充。
- **尚未开始：** 每周清理（AGENTS §4.3）。

- 以后按实际需要安排：二维扫描前端能量面显示、专用剖面图和 QST 预览、ORCA 接入、Gen/ECP、开壳层。二维扫描后端已支持，前端能量面显示尚未支持；T87 已提供只读 IRC 曲线与路径点结构。调研完成不等于功能已支持。
- `ag asm` 的实际研究应用仍需相应计算与科学审阅，本地工具和离线测试不代表研究分析已完成。

## 运维与新会话

- 负责人在两个 T107 PR 各自的**合并提交**上建 `v4.4.0` tag，release 正文使用各仓库 CHANGELOG v4.4.0 一节。建 tag 前核对确切合并提交，不直接选择届时的 main；沿用上次处理签名问题的做法。
- 合并后开发机同步两边 main，核对 `ag --version` 为 4.4.0；对 default、scnet、scnet-test、newhpc 各运行一次 `ag doctor`。前端重新构建后，作业、Study、分析、文件四个入口各打开一次。本次发布准备不等于已部署或自检通过。
- 计算机同步时间由负责人安排；同步前确认没有进行中的取回、提交或 reparse。
- study 和签字证据清单定期备份到仓库外的备份位置；备份不作为另一台电脑的可推进副本。
- 集群到期日、存储限制和余额由负责人按本机记录核对；定时自动审阅已停用，需要审阅时手动请监督方。
- 升级后旧 Opt+Freq facts 可能受 T99 route 换行误判影响；对 fetched Attempt 先用 `ag facts <Attempt> --reparse --dry-run --out <study 外的新 JSON>` 预览，审阅差异后再正式 `--reparse`。旧 facts 保留在 `facts-history/`，命令列出引用旧哈希的文件，涉及已签内容由负责人重新确认；不自动改引用或签字。T82 导致 thermo / profile 拒绝旧输入时，核对一致性和频率证据，不绕过；签字前先生成证据清单。
- 新研究先读 `auto-g16-study` Skill 和当前卡片，明确目标、机理假设、计算方案与方法依据，按所需里程碑签字后推进；恢复研究先读 study 的当前状态和阻塞，不凭对话记忆重复提交。

角色与审批见 [开发手册](DEVELOPING.md#角色与审批)，文档入口见 [文档索引](README.md)。
