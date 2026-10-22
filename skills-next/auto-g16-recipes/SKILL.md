---
name: auto-g16-recipes
description: 为 ag 新架构提供 Opt+Freq、单点、RDKit 或 CREST 初筛、qRRHO 热化学、机理计划、TS/IRC 及失败诊断卡片；准备输入或审阅主族闭壳层结果时使用。
---

# Auto-G16 Recipes

先匹配适用范围和前置条件，再打开一张卡片。编排和人的签字由 `auto-g16-study` 负责；无适用卡片就停下说明缺口，金属、开壳层不在本组卡片的执行范围。双分子步骤与复合物按 [complex](cards/complex.md) 卡片执行，仅开放以已审阅原子对为约束的采样；通用对接搜索不开放。TS/IRC 卡片中的能力缺口按当前工具逐项记录，不能用旧 Skill 或自造命令绕过。

| 卡片 | 适用范围 | 前置条件 |
|---|---|---|
| [reaction-plan](cards/reaction-plan.md) | 主族闭壳层同面机理假设与修正 | 明确科学问题；假设需人签字后才能推进依赖计算 |
| [complex](cards/complex.md) | 双分子步骤、反应物/产物复合物与离子对；仅已审阅原子对约束采样 | 已签机理假设、计算方案及各组分身份；原子对已审阅 |
| [ts](cards/ts.md) | 已审阅单结构初猜的 TS 优化与振动审核 | 已签机理假设、结构与代表构象集合 |
| [irc](cards/irc.md) | 双向路径与端点极小点识别 | 已接受 TS 与振动方向；缺能力或证据时记录具体阻塞 |
| [opt-freq](cards/opt-freq.md) | 主族闭壳层单分子极小点 | 已签结构与代表构象集合、已定方法 |
| [sp](cards/sp.md) | 同一物种极小点的电子能精化 | 已接受的 Opt+Freq 最终几何 |
| [rdkit-screen](cards/rdkit-screen.md) | 力场可参数化的主族单分子初筛 | 已签结构，structures Skill 可用 |
| [crest-screen](cards/crest-screen.md) | 主族闭壳层单分子构象搜索 | 已签结构、可用 CREST 模板 |
| [thermo](cards/thermo.md) | 同一物种的相对自由能与布居 | 合格 Opt+Freq、最终去重集合及简并度 |
| [profile](cards/profile.md) | 守恒的反应能量曲线、催化循环能量跨度与 TS 扰动 | 同口径物种系综、已审阅 TS、完整状态组成 |
| [counterpoise](cards/counterpoise.md) | RC、离子对、TS 的气相 BSSE 诊断；不进入主线剖面 | 两个已审阅单重态片段、无跨片段共价键或不确定接触 |
| [kinetics](cards/kinetics.md) | Eyring 时间尺度、可逆性、通道选择性与隧穿边界 | 同口径自由能、参考盆地及快交换/浓度假设经审阅 |
| [failure-diagnosis](cards/failure-diagnosis.md) | 已有结果的诊断与新 Attempt 建议 | 本地 facts、输出及原输入 |

每张卡片固定八节：**适用范围、前置条件、输入模板、资源建议、提交前检查清单、结果判据清单、常见失败与处理、常见坑**。本地任务不产生提交，但仍按第 5 节检查分析输入。

所有卡片的签字步骤均为“先生成清单，再签字”：先在 study.md/review.md 以明确本地路径引用分析输出，运行 `ag review manifest --study <dir>`，展示生成的清单，再请求人签字。将清单相对路径及命令返回的 SHA-256 记入签字记录；清单覆盖全部 facts.json、review.md 和被引用的分析输出，生成成功不代表科学接受。后续证据变化时保留旧清单，重新审阅并生成新清单。

在 Attempt 的 `review.md` 中逐项记录第 6 节判据，先运行 `ag review init <id>`，使用“判据 | 依据（facts 字段、日志行号或文件） | 结论”表，写完运行 `ag review check <id>`。信息不足写“无法判断”并说明缺少的证据；本地分析的 review 放在 `analyses/`，并在 study 引用。不得将正常终止、排队完成或一个较低能量直接当成科学结论。

卡片里的程序参数表示模板允许的参数值；具体 CLI 绑定方式先读当前 `ag <命令> --help`。未定义的选项不猜写；缺少方案要求的能力就报告。远程动作只通过 `ag`；所有计算失败先报告，提出新 Attempt，等人确认。提交 / 取消仍必须由人点击 Mac 对话框。

“常见坑”中的仓库相对来源路径仅供追溯科学经验，不是执行依赖；不加载其历史流程作为新工作的规则。新经验先起草到 study 的 `lessons/`，在每周清理时经人审阅合并进卡片。“常见坑”最多 10 条、每张卡片最多 285 行；防止经验无限追加淹没可执行判据，超出时先合并或删除，再追加。
