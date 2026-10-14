# Changelog

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
