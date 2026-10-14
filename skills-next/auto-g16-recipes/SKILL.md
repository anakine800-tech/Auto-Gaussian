---
name: auto-g16-recipes
description: 为 ag 新架构提供 Opt+Freq、单点、RDKit 或 CREST 初筛、qRRHO 热化学、机理计划、TS/IRC 及失败诊断卡片；准备输入或审阅主族闭壳层结果时使用。
---

# Auto-G16 Recipes

先匹配适用范围和前置条件，再打开一张卡片。编排和人的签字由 `auto-g16-study` 负责；无适用卡片就停下说明缺口，金属、开壳层及双分子初筛仍不在本组卡片的执行范围。TS/IRC 卡片中的能力缺口标注“待 T13”，不能用旧 Skill 或自造命令绕过。

| 卡片 | 适用范围 | 前置条件 |
|---|---|---|
| [reaction-plan](cards/reaction-plan.md) | 主族闭壳层同面机理假设与修正 | 明确科学问题；假设需人签字后才能推进依赖计算 |
| [ts](cards/ts.md) | 已审阅单结构初猜的 TS 优化与振动审核 | 已签机理假设、结构与代表构象集合 |
| [irc](cards/irc.md) | 双向路径与端点极小点识别 | 已接受 TS 与振动方向；缺能力时待 T13 |
| [opt-freq](cards/opt-freq.md) | 主族闭壳层单分子极小点 | 已签结构与代表构象集合、已定方法 |
| [sp](cards/sp.md) | 同一物种极小点的电子能精化 | 已接受的 Opt+Freq 最终几何 |
| [rdkit-screen](cards/rdkit-screen.md) | 力场可参数化的主族单分子初筛 | 已签结构，structures Skill 可用 |
| [crest-screen](cards/crest-screen.md) | 主族闭壳层单分子构象搜索 | 已签结构、可用 CREST 模板 |
| [thermo](cards/thermo.md) | 同一物种的相对自由能与布居 | 合格 Opt+Freq、最终去重集合及简并度 |
| [profile](cards/profile.md) | 守恒的反应能量曲线、催化循环能量跨度与 TS 扰动 | 同口径物种系综、已审阅 TS、完整状态组成 |
| [failure-diagnosis](cards/failure-diagnosis.md) | 已有结果的诊断与新 Attempt 建议 | 本地 facts、输出及原输入 |

每张卡片固定八节：**适用范围、前置条件、输入模板、资源建议、提交前检查清单、结果判据清单、常见失败与处理、常见坑**。本地任务不产生提交，但仍按第 5 节检查分析输入。

在 Attempt 的 `review.md` 中逐项记录第 6 节判据，先运行 `ag review init <id>`，使用“判据 | 依据（facts 字段、日志行号或文件） | 结论”表，写完运行 `ag review check <id>`。信息不足写“无法判断”并说明缺少的证据；本地分析的 review 放在 `analyses/`，并在 study 引用。不得将正常终止、排队完成或一个较低能量直接当成科学结论。

卡片里的程序参数表示模板允许的参数值；具体 CLI 绑定方式先读当前 `ag <命令> --help`。未定义的选项不猜写；缺少方案要求的能力就报告。远程动作只通过 `ag`；所有计算失败先报告，提出新 Attempt，等人确认。提交 / 取消仍必须由人点击 Mac 对话框。

“常见坑”中的仓库相对来源路径仅供追溯科学经验，不是执行依赖；不加载其历史流程作为新工作的规则。新经验先起草到 study 的 `lessons/`，在每周清理时经人审阅合并进卡片。“常见坑”最多 10 条、每张卡片最多 285 行；防止经验无限追加淹没可执行判据，超出时先合并或删除，再追加。
