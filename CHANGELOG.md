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

### 多集群

- 配置驱动的 PBS/Slurm 适配，Attempt 绑定集群，提交记录与确切作业号交叉核验；按集群统计资源、核时预算、到期信息及监控快照，并校验跨结果程序版本一致性。实现不等于各站点实机验收。[#229](https://github.com/anakine800-tech/Auto-Gaussian/pull/229)

### 前端

- 独立前端改为本地 study 文件查看器，保留结构/振动显示，重做结果、热化学和关系图，移除旧数据库/查询服务依赖。[Frontend #4](https://github.com/anakine800-tech/Auto-Gaussian-Frontend/pull/4)
- 输入结构预览、父 Attempt 输入对比、日志搜索、结果总览、优化过程和 `ag monitor` 快照展示。[Frontend #5](https://github.com/anakine800-tech/Auto-Gaussian-Frontend/pull/5)、[Frontend #6](https://github.com/anakine800-tech/Auto-Gaussian-Frontend/pull/6)
- 默认只读；显式 `--enable-actions` 经本机 ag 新建、提交、查询、取回、取消，Mac 确认仍由 ag 执行。当前前端操作与监控限旧单集群配置，多集群布局兼容边界见 README。[Frontend #7](https://github.com/anakine800-tech/Auto-Gaussian-Frontend/pull/7)、[#229](https://github.com/anakine800-tech/Auto-Gaussian/pull/229)
