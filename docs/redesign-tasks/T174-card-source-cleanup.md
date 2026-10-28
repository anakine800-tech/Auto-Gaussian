# T174：历史来源链接修正与 profile/kinetics 去重

版本：v1，2026-10-29。目标仓库：Auto-Gaussian。写单与准备 PR 不代表已部署或获准计算。

## 分支与目标

- 分支：`codex/t174-card-source-cleanup`；一工单、一新对话、一独立工作树、一 PR，PR 第一行 `Task: T174`。
- 核查基线：`20840ee7a51dae4e4da1c75dd6eef63052d47802`。实际实施从包含前置改动的最新 main 建工作树；开工重核编号未被占用，不切换正在运行的主检出。
- 开工先读现行 AGENTS.md、本单、docs/DEVELOPING.md、docs/LESSONS.md；旧流程只作历史，不恢复旧 authority/合同。
- 来源问题：D19、S03；D/S 是本批检查清单编号，不是新流程或产品状态。
- 并行与依赖（2026-10-29 排期细化）：T169 合并后可先精简 profile/kinetics 的共同解释，确需时仅使用本单允许的共享 references 文件；这些文件与 T170/T173 不冲突。历史来源文件中与 T170 共享者等 T170 合并后再改，完整来源修订与最终 CI 在其后整合；不依赖 T173 新来源定位的改动无需单纯等待 T173。可先准备草稿 PR，实施者不合并；文件、公式、判据及旧快照范围不变。无需等待 T171/T172/T175 的独立文件。
- 要防的具体问题：过时或互相矛盾的说明引导开发者执行错误流程、创建不完整证据或误判功能边界；本单不增加与上述问题无关的约束。

## 允许改动的路径

- `skills-next/auto-g16-recipes/cards/sp.md`
- `skills-next/auto-g16-recipes/cards/thermo.md`
- `skills-next/auto-g16-recipes/cards/crest-screen.md`
- `skills-next/auto-g16-recipes/cards/rdkit-screen.md`
- `skills-next/auto-g16-recipes/cards/opt-freq.md`
- `skills-next/auto-g16-recipes/cards/profile.md`
- `skills-next/auto-g16-recipes/cards/kinetics.md`
- `skills-next/auto-g16-structures/SKILL.md`
- `skills-next/auto-g16-structures/references/conformer-workflow.md`
- `skills-next/auto-g16-structures/references/chemistry-boundaries.md`
- `skills-next/auto-g16-recipes/references/profile-kinetics-common.md（仅确需抽取共同解释时新建）`
- `docs/redesign-tasks/T174-card-source-cleanup.md`：本工单随自身实现 PR 纳入。
- `docs/redesign-tasks/open-tasks.txt`：只增删本单条目，不覆盖其他任务。

括号中的限制是该文件允许修改的段落范围，不是文件名的一部分。未列文件只读；需要范围外改动先说明具体必要性。

## 要做的

1. 核对报告定位的 8 个文件、15 处旧 skills/... 来源引用：sp、thermo、crest-screen、rdkit-screen、opt-freq、structures/SKILL、conformer-workflow、chemistry-boundaries。按新基线重新计数，变化如实解释。
2. 来源改为真实 archive 文件链接或确切历史 tag；明确只是出处，不是现行执行规则。不编辑、恢复或 import 历史冻结文件。
3. profile/kinetics 仅抽取重复背景解释，确需共享文档时只使用允许的一个 references 文件；避免为两张卡再建框架或新流程。
4. 保留每张卡第 6 节的直接可执行判据、八节结构、必要警告、旧锚点和兼容内容；历史 Attempt 已保存的卡片快照不改。旧快照不应依赖最新共享说明才能解释。
5. TS 拆卡已完成，不重新拆 TS，不改变计算/自由能/速率公式、科学阈值或当前 CLI 示例行为。

## 不允许

- 不改产品 Python/前端代码、模板、测试逻辑、版本号或 CHANGELOG；不通过放松检查掩盖文档问题。
- 不改其他任务负责的公共文件；不重写已保存的 Attempt、manifest、bundle、卡片快照、facts 或签字。
- 不部署、不修改生产配置、不恢复监控、不连接集群、不提交/取消/重试计算；其他本批任务的权限不转入本单。
- 不提交真实主机、账号、路径、作业号、配置、私有词表或研究数据；公开示例仅用占位符/合成小分子。

## 验收与测试

- 每条新链接或历史 tag 路径实际可追溯；不得为修链接无意执行旧文档指令。
- 去重前后逐项比对判据、公式、警告及兼容内容，删除的是重复解释而非验收条件；卡片仍不超过285行。
- 复核 T169/T170 的 --card、资源和流程说明全部保留，新增共享链接可在仓库与部署 Skill 结构中正常解析。
- 纯文档本地按现行 DEVELOPING 运行 `PYTHONPATH=ag/src python -m pytest skills-next -q -rs`，相关链接、片段和语义人工核对；代码测试由 CI 按既有工作流运行。
- 不为文字复述新写测试，不改已有测试来接受错误示例；失败先核对说明/接口，确需扩大范围时报告。
- 只暂存本单文件；运行现行敏感扫描与 `git diff --cached --check`，核对 author/committer 为 GitHub noreply，并检查 PR 文本；私有词表不公开。
- 写明实际通过/失败/跳过项。本单未执行检查前不能照搬报告的 177 通过数当作自己的结果。

## 真实环境验证

本单不需要 SSH、调度器查询或计算。文档所描述的真实验证只是后续执行要求，不在本单顺手执行；网络文献读取仅 T173 的公开来源核验适用。纯文档通过不代表部署、实际调度或科学验收。

## 停止条件与交付

- 范围越界、同一问题修两次仍未解决，或需要改变科学/长期操作规则而缺少明确决定时，保留具体差异并报告。
- 任何误触真实环境的 UNKNOWN、SSH 错误、哈希不一致或异常输出立即停止；不自动重试。
- 独立审阅绑定最终 head，读取并逐条处理 `<!-- ag-review head=... -->`；更新 head 后复核受影响差异及 CI。
- 每项问题在 PR 中对应解决段落/依据或明确未完成原因；未解决项不能隐藏在“文档已同步”结论下。
- 本轮用户已明确授权协调方在独立审阅、CI及必要验证通过后合并；实施者不自行合并。不使用admin、不改保护、不直接推main。文档PR不顺带部署、建tag或发版。
