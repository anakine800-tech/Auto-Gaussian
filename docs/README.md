# 文档索引

v4.0.0 起，从这一页进入仓库文档。先按身份找到自己的入口，再按需要往下读；标为“历史”的文档只用于追溯，不作为现行规则。

当前 v4.7.0 已于 2026-10-29 与配套前端同号正式发布；T178 #372、T177 #51 均已合并，最终 CI/独立审阅及两项实际后端配套验证通过，配套 0 跳过。本机开发环境已部署两仓发布 tag，研究机未部署。确切提交、Release 与部署摘要见 [发布范围与证据边界](../CHANGELOG.md#v470)；[T178 任务及验收记录](redesign-tasks/T178-release-v4.7.0-backend.md)保留发布前历史阶段，[T180](redesign-tasks/T180-v470-published-status.md)仅收尾当前状态，不改固定发布 tag。

## 负责人（研究者、合并者）

| 文档 | 什么时候读 |
|---|---|
| [仓库 README](../README.md) | 安装、配置、命令一览、一个 study 的典型流程、验收状态和已知限制 |
| [当前交接](handoff-v4.md) | 当前进度、未完成事项和证据边界置顶；旧版本仅作历史，开新对话前先读 |
| [运维文档](OPERATIONS.md) | 部署目标与授权适用表、备份、常驻服务、观察标准、回退及连接切换 |
| 数据契约（`docs/ag-*.md`、[docs/g0.md](g0.md)） | 核对登记、报告和诊断的字段与兼容边界 |
| [CHANGELOG](../CHANGELOG.md) | 查某个功能在哪个版本、哪个 PR 加入 |
| [开发手册：角色与审批](DEVELOPING.md#角色与审批) | 判断一件事该由谁拍板 |
| [前端仓库 README](https://github.com/anakine800-tech/Auto-Gaussian-Frontend/blob/main/README.md) | 可选只读查看、3D 和监控；标准部署显式启用操作模式并核对后端路径，计算授权仍单独核对 |

## LLM 研究会话

研究会话不直接读本目录，而是从 Skills 进入：

1. `skills-next/auto-g16-study/SKILL.md`：每次调用的固定流程、阶段决策表、里程碑签字。
2. `skills-next/auto-g16-recipes/SKILL.md`：卡片列表与适用范围；具体卡片在 `cards/`。
3. `skills-next/auto-g16-study/references/acceptance-methods.md`：方法、基组、筛选窗口与热化学设置的唯一来源。
4. `skills-next/auto-g16-study/references/study-md-template.md`：新 study 的 `study.md` 模板。
5. `skills-next/auto-g16-structures/`：结构读入、立体化学审阅和构象工作流。
6. [TS 总入口](../skills-next/auto-g16-recipes/cards/ts.md)：按[初猜](../skills-next/auto-g16-recipes/cards/ts-guess.md)、[搜索/Freq](../skills-next/auto-g16-recipes/cards/ts-search.md)、[IRC/端点](../skills-next/auto-g16-recipes/cards/irc.md)选择阶段卡，旧 Attempt 快照不改。

## Codex 开发

按顺序读：

1. [AGENTS.md](../AGENTS.md)：硬内核与开发流程，任何情况下都不能违反。
2. 本次任务单；[任务单模板](redesign-tasks/TEMPLATE.md)用于开单，未完成任务清单见 [open-tasks.txt](redesign-tasks/open-tasks.txt)。
3. [DEVELOPING.md](DEVELOPING.md)：模块地图、提交顺序、怎么加功能、离线/合并前真实验证/部署验收、PR 与发布、角色与审批。
4. [LESSONS.md](LESSONS.md)：开发与现场经验，新增功能前查一遍有没有踩过的坑。

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
- [TS 初猜工具指南整理版](../skills-next/auto-g16-recipes/references/ts-initial-guess-guide.md)：已核对 v4.6.0 使用指南原稿的来源、章节去向与过时说明更正；与开发交接规格区分。
- `archive/`：v3 及更早版本，冻结，不修改、不引用为规则。
