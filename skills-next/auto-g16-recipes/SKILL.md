---
{
  "name": "auto-g16-recipes",
  "description": "为 ag 新架构提供 Opt+Freq、单点、RDKit 或 CREST 初筛、qRRHO 热化学及失败诊断卡片；准备输入或审阅主族闭壳层单分子结果时使用。"
}
---

# Auto-G16 Recipes

先匹配适用范围和前置条件，再打开一张卡片。编排和人的签字由 `auto-g16-study` 负责；无适用卡片就停下说明缺口，首版没有 TS/IRC、金属或双分子初筛卡片。

| 卡片 | 适用范围 | 前置条件 |
|---|---|---|
| [opt-freq](cards/opt-freq.md) | 主族闭壳层单分子极小点 | 已签结构与代表构象集合、已定方法 |
| [sp](cards/sp.md) | 同一物种极小点的电子能精化 | 已接受的 Opt+Freq 最终几何 |
| [rdkit-screen](cards/rdkit-screen.md) | 力场可参数化的主族单分子初筛 | 已签结构，structures Skill 可用 |
| [crest-screen](cards/crest-screen.md) | 主族闭壳层单分子构象搜索 | 已签结构、可用 CREST 模板 |
| [thermo](cards/thermo.md) | 同一物种的相对自由能与布居 | 合格 Opt+Freq、最终去重集合及简并度 |
| [failure-diagnosis](cards/failure-diagnosis.md) | 已有结果的诊断与新 Attempt 建议 | 本地 facts、输出及原输入 |

每张卡片固定八节：**适用范围、前置条件、输入模板、资源建议、提交前检查清单、结果判据清单、常见失败与处理、常见坑**。本地任务不产生提交，但仍按第 5 节检查分析输入。

在 Attempt 的 `review.md` 中逐项记录第 6 节判据，使用“判据 | 通过 / 不通过 | 依据（数值与输出位置）”表。信息不足写“不通过（缺证据）”；本地分析的 review 放在 `analyses/`，并在 study 引用。不得将正常终止、排队完成或一个较低能量直接当成科学结论。

卡片里的程序参数表示模板允许的参数值；具体 CLI 绑定方式先读当前 `ag <命令> --help`。未定义的选项不猜写；缺少方案要求的能力就报告。远程动作只通过 `ag`；所有计算失败先报告，提出新 Attempt，等人确认。提交 / 取消仍必须由人点击 Mac 对话框。

“常见坑”中的仓库相对来源路径仅供追溯科学经验，不是执行依赖；不加载其历史流程作为新工作的规则。新经验先起草到 study 的 `lessons/`，经人审阅后另行修改卡片。
