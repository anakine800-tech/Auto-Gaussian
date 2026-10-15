# 文档索引

v4.0.0 起，从这一页进入仓库文档。先按身份找到自己的入口，再按需要往下读；标为“历史”的文档只用于追溯，不作为现行规则。

## 负责人（研究者、合并者）

| 文档 | 什么时候读 |
|---|---|
| [仓库 README](../README.md) | 安装、配置、命令一览、一个 study 的典型流程、验收状态和已知限制 |
| [v4.0 交接](handoff-v4.md) | 了解当前进度、未完成事项和下一步，开新对话前先读 |
| [CHANGELOG](../CHANGELOG.md) | 查某个功能在哪个版本、哪个 PR 加入 |
| [开发手册：角色与审批](DEVELOPING.md#角色与审批) | 判断一件事该由谁拍板 |
| 前端仓库 Auto-Gaussian-Frontend 的 README | 启动只读查看器、3D 预览和服务器监控 |

## LLM 研究会话

研究会话不直接读本目录，而是从 Skills 进入：

1. `skills-next/auto-g16-study/SKILL.md`：每次调用的固定流程、阶段决策表、里程碑签字。
2. `skills-next/auto-g16-recipes/SKILL.md`：卡片列表与适用范围；具体卡片在 `cards/`。
3. `skills-next/auto-g16-study/references/acceptance-methods.md`：方法、基组、筛选窗口与热化学设置的唯一来源。
4. `skills-next/auto-g16-study/references/study-md-template.md`：新 study 的 `study.md` 模板。
5. `skills-next/auto-g16-structures/`：结构读入、立体化学审阅和构象工作流。

## Codex 开发

按顺序读：

1. [AGENTS.md](../AGENTS.md)：硬内核与开发流程，任何情况下都不能违反。
2. [DEVELOPING.md](DEVELOPING.md)：模块地图、提交顺序、怎么加功能、测试、PR 与发布、角色与审批。
3. [LESSONS.md](LESSONS.md)：开发与现场经验，新增功能前查一遍有没有踩过的坑。
4. [任务单模板](redesign-tasks/TEMPLATE.md) 和本次任务单；未完成任务清单见 [open-tasks.txt](redesign-tasks/open-tasks.txt)。

## 审阅者

- [AGENTS.md](../AGENTS.md) 第 3 节硬内核，是退回 PR 的红线。
- [DEVELOPING.md](DEVELOPING.md) 的“角色与审批”“PR 与发布”两节：哪些改动必须等审阅，审阅评论的格式。
- `skills-next/tests/test_card_consistency.py`：卡片与 CLI、方法表、待办标记的一致性检查。

## 历史文档

- [REDESIGN-PLAN.md](REDESIGN-PLAN.md)：v4.0 改造期的设计记录与决策表。其中的阶段计划已由后续任务和 README 取代。
- `redesign-tasks/T*.md`：已完成任务的任务单，记录当时的范围与验收标准。
- [research/](research/)：改造期的调研记录。
- [ORCA 接入调研](research/orca.md)：许可、模板、解析、DLPNO 资源证据与分期建议。
- [仓库瘦身评估](research/repo-slimming.md)：文档、测试、脚本与卡片的候选清单及风险。
- `archive/`：v3 及更早版本，冻结，不修改、不引用为规则。
