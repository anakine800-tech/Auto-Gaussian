# T169：卡片快照、预算、SP 路径与资源说明同步

版本：v1，2026-10-29。目标仓库：Auto-Gaussian。写单与准备 PR 不代表已部署或获准计算。

## 分支与目标

- 分支：`codex/t169-recipe-current-behavior`；一工单、一新对话、一独立工作树、一 PR，PR 第一行 `Task: T169`。
- 核查基线：`20840ee7a51dae4e4da1c75dd6eef63052d47802`。实际实施从包含前置改动的最新 main 建工作树；开工重核编号未被占用，不切换正在运行的主检出。
- 开工先读现行 AGENTS.md、本单、docs/DEVELOPING.md、docs/LESSONS.md；旧流程只作历史，不恢复旧 authority/合同。
- 来源问题：D07 的 Skills 部分、D12、D13、D14、D15；D/S 是本批检查清单编号，不是新流程或产品状态。
- 并行与依赖：与 T168、T171、T172、T175 和本机配置单并行；T170/T173/T174 后续依赖本单的相应文件，合并后再从最新主线整合。
- 要防的具体问题：过时或互相矛盾的说明引导开发者执行错误流程、创建不完整证据或误判功能边界；本单不增加与上述问题无关的约束。

## 允许改动的路径

- `skills-next/auto-g16-recipes/SKILL.md`
- `skills-next/auto-g16-study/SKILL.md`
- `skills-next/auto-g16-study/references/study-md-template.md`
- `skills-next/auto-g16-study/references/confirmation-summary.md`
- `skills-next/auto-g16-study/references/acceptance-methods.md`
- `skills-next/auto-g16-recipes/cards/opt-freq.md`
- `skills-next/auto-g16-recipes/cards/sp.md`
- `skills-next/auto-g16-recipes/cards/crest-screen.md`
- `skills-next/auto-g16-recipes/cards/irc.md`
- `skills-next/auto-g16-recipes/cards/complex.md`
- `skills-next/auto-g16-recipes/cards/reaction-plan.md`
- `skills-next/auto-g16-recipes/cards/failure-diagnosis.md`
- `skills-next/auto-g16-recipes/cards/counterpoise.md`
- `docs/redesign-tasks/T169-recipe-current-behavior.md`：本工单随自身实现 PR 纳入。
- `docs/redesign-tasks/open-tasks.txt`：只增删本单条目，不覆盖其他任务。

括号中的限制是该文件允许修改的段落范围，不是文件名的一部分。未列文件只读；需要范围外改动先说明具体必要性。

## 要做的

1. 把所有本单范围内完整 prepare 示例逐条对照 CLI，为相应 Opt+Freq、SP、CREST、IRC 补正确 --card；区分完整可复制示例与不单独执行的片段，不机械对所有文本追加参数。
2. 说明新 Attempt 保存卡片快照；旧记录可 review init --card 显式指定审阅来源，不补写 manifest，不换掉已有快照和旧审阅依据。
3. 统一 study 模板、reaction-plan 的核时预算口径：预估、预留、结算继续保留，预算字段不拦截提交；与 T168 对齐且不改 DEVELOPING。
4. complex 摘要与既有 CP 正文一致，保留双片段、溶剂近似和诊断不进入主线自由能剖面的边界。
5. Study 阶段表、recipes 索引区分筛选 SP、最终精化、方法敏感性；优化前筛选 SP 不要求不存在的 Opt+Freq 父作业。仅表达既有方法表路径，不增加方法/基组或科学通过条件。
6. 固定 CPU/内存数标为示例；实际值取所选入口配置及已保存 manifest。确认模板支持实际配置的档位，不仅三档；保留调度内存与 Gaussian 输入余量区别。不得将某个实际入口的私人配置写成通用默认。
7. 本单的 acceptance-methods 仅改资源表达与已经批准的阶段说明；文献定位归 T173，构象流程分支归 T170，不改方法、基组、能窗和热化学设置。

## 不允许

- 不改产品 Python/前端代码、模板、测试逻辑、版本号或 CHANGELOG；不通过放松检查掩盖文档问题。
- 不改其他任务负责的公共文件；不重写已保存的 Attempt、manifest、bundle、卡片快照、facts 或签字。
- 不部署、不修改生产配置、不恢复监控、不连接集群、不提交/取消/重试计算；其他本批任务的权限不转入本单。
- 不提交真实主机、账号、路径、作业号、配置、私有词表或研究数据；公开示例仅用占位符/合成小分子。

## 验收与测试

- 列出完整示例清单，对照实际 argparse/card 名称验证；必要时在隔离合成配置、小分子目录走本地 prepare/review，禁止真实 Transport、生产配置与旧 Attempt 写入。
- 核对相应 cards 第 6 节可直接提取、八节结构和 285 行上限；不为通过测试删掉科学边界。
- 验证旧 manifest 不需要补字段；文档不能承诺改变真实配置后的旧资源提交兼容性。
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
