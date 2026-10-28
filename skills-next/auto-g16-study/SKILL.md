---
name: auto-g16-study
description: 在 ag 新架构中创建、恢复和推进主族闭壳层计算研究；选择任务卡片、准备提交摘要、审阅结果并记录三个里程碑及机理假设签字。
---

# Auto-G16 Study

科学判断由 LLM 和人完成，确定性的作业操作交给 `ag`。study 放在配置 `local.studies_root`，不放仓库；连接与远程根从本地配置读取，不写入 Skill。仅使用已审阅的 `ag` 模板和命令，不自行编写远程命令或作业脚本；唯一例外是 AGENTS.md 第 7 条规定的、逐次授权的只读查看。

新建或恢复在 `scnet` 上运行 Gaussian 的研究时，按[研究模板](references/study-md-template.md)的“计算平台与软件许可”填写负责人决定；正式作业前核对正丁烷单点全流程验证记录。

准备新 Attempt 前先运行 `ag route --template <模板> --tier <档位> --study <study>`，按建议显式选 `--cluster`；偏离建议时在 study.md 写明原因。默认路由顺序在本机配置中明确设置：Gaussian（含 gaussian-cp、multiwfn）为 `default → newhpc → scnet`，CREST（含 xTB）为 `scnet-test → default → newhpc`，仍须满足各入口的模板许可。研究尚未签字允许某入口时，用 `[routing.studies."<study>"]` 覆盖顺序并跳过该入口；未配置路由时沿用研究已批准安排，不猜建议。命令只读本机监控快照；“需要排队”与“内存未知”须保留在判断中，建议不保证立即运行。ag 不自动改入口；prepare 的不同入口提示不拦截，已有 Attempt 不迁移，批准时仍核对原绑定与输入哈希。

## 开题参考

- [开题包主模板](references/intake-template.md)：结构、实验、假设与证据、计算范围及 N0 交接。
- [文献记录](references/literature-record.md)：检索记录、DOI 核实与方法摘要。
- [讨论记录](references/discussion-record.md)：逐轮问答、决定及原话出处。

## 每次调用的固定流程

0. **开题。** 新课题由开发机上的独立研究会话在私有 study 整理结构、实验与文献，不连接集群。先核对主会话，沿用[开题包主模板](references/intake-template.md)；已有已签开题不回头重做。写 PR、评论或公开文档前先读 study.md 顶部保密级别。为避免错误结构进入采样或检索，依次完成以下步骤，每步核对上一步产出：

   - **0a 结构输入。** 用 [ChemDraw 结构技能](../auto-g16-chemdraw-structures/SKILL.md)或人提供的 CDXML/SMILES，建立起始物、产物、催化剂和试剂的结构文件；图片只作对照，不从图片直接生成坐标，中间体留给后续流程。按[开题物种核验](../auto-g16-structures/SKILL.md#开题物种核验)填写 `analyses/intake/species.csv`，需要配平时填写 `reaction.csv`（含必要副产物/添加剂）。进入 0b 前检查逐物种源文件、人工预期值、电荷和研究者提供的多重度；缺项写明，不推断。
   - **0b 自动核验。** 运行 `check_species.py --study STUDY`，核对报告覆盖全部物种、源文件哈希和预览。有 `has_mismatch`、`incomplete` 或已声明反应式的配平差额/未知时，先解决或由负责人明确接受并记录理由，不能跳过。`out_of_scope` 列出能力缺口，暂停依赖计算；接受备注不扩大工具适用范围。修订输入后用新的输出目录重跑，保留旧报告。退出码成功不能代替逐项核对。
   - **0c 人工确认结构。** 核对 0b 报告与当前源文件一致，向负责人展示报告、全部预览及未决项，按[结构确认条目](references/discussion-record.md#结构确认条目0c)记录报告相对路径与 SHA-256、逐物种结论、明确接受的未决项、确认日期、确认人及原话出处。沿用第 7 步先生成证据清单，再确认原有结构里程碑，不新增里程碑、不代签。**确认之前不进入 0d，也不开始任何采样。** 结构改变后重新核验并确认相应对象，保留旧记录。
   - **0d 文献检索记录。** 先核对 0c 的明确结构确认及其报告，再以已确认结构的规范 SMILES、名称为检索对象，按[文献记录](references/literature-record.md#检索覆盖记录)填写检索覆盖记录；TS 相关文献填写[文献 TS 证据摘录表](references/literature-record.md#文献-ts-证据摘录表)。覆盖记录有空缺时开题包不能定稿；零结果、访问限制和未覆盖部分如实记录，不伪称完整检索。

   - **0e 检查开题包。** 监督方问答讨论、主会话将决定汇总到开题包后，运行 `python <本技能目录>/scripts/check_intake.py --study STUDY --report analyses/intake/intake-check-v1.json`；默认开题包是 `study.md`，独立文件用 `--intake analyses/intake/intake-v1.md`。参数和记录内文件引用都相对 study 根目录；讨论和文献可在同一文件，也可用 Markdown 链接或反引号引用 `analyses/` 下的 `.md`。报告逐项输出 `present` / `missing` / `mismatch`，退出码分别为全部通过 0、缺项/不一致 1、路径/输入错误 2；检查只新增指定报告，不改输入。每次换新的报告名。任何 `missing` / `mismatch` 都先补齐再重查，不能跳过；全部 `present` 仅说明记录完整，不是科学接受。
     结构确认沿用 0c 的字段及逐物种表，文件路径和 SHA-256 在同一行成对记录（如反引号路径后跟反引号哈希），不能借用其他章节的哈希或确认人。为防止笼统接受掩盖具体差异，未决项按报告 `checks` 的项目名列出，写明“接受 项目名；理由：…；影响：…；后续处理：…”；多重度缺失记 `multiplicity`，读入错误记 `read_errors`。已声明反应式的未决项在同表以 `reaction` 为对象记录。`out_of_scope` 仍阻断；报告输入文件的当前哈希也须一致。
   - **0f 方案定稿与签字。** 0e 全部通过后，用新的 `--report` 文件名重跑并加 `--draft`，在 `analyses/intake/` 独占生成 `study.md.draft` 和 `channels.csv.draft`；任一草稿已存在就拒绝，先由人审阅并保留旧版，再选择后续处理。草稿沿用研究模板结构，原样引用物种与方法表；通道 `product_branch` 取第 5 节明确写出的“→”右侧文本，不从 CIP 推断，`ensemble_manifests` 留空并注明采样后填写（补齐前不能直接运行 channel-coverage）。人审阅后由主会话合并到 `study.md`，保留原内容与签字；按第 7 步引用证据、生成并展示清单，请负责人确认计算方案与适用的机理假设。沿用现有里程碑：机理研究一起签，纯性质研究随结构签，不新增里程碑，不代签。
   - **0g 准备第一批 Attempt。** 已获得 0f 的明确签字后，进入 N0 并记录主会话交接；由 study 所在电脑的计算会话按第 9 节“首轮做什么”、第 11 节批次计划及所选卡片核对输入、方法、资源与 walltime，逐个运行 `ag prepare --card <卡片名>`。按[确认摘要](references/confirmation-summary.md)生成并展示每个 Attempt 的完整摘要，核对状态为 prepared。**到此为止，尚未获准提交。** 再按第 4 步取得本批聊天批准、核对适用的长期规则，或由负责人点击 Mac 确认；草稿、清单和科学签字不能替代提交授权。

1. **恢复上下文。** 先核对“主会话”：同一 study 同时仅主会话推进，其他会话只读；接手时记录交接。再读目标目录 `study.md` 的“当前阻塞”，再读其余内容和 `ag list --study <study_id> --json`；核对目标、未完成的量、签字和 Attempt 状态。新研究尚无目录时，用 `ag init <study_dir>` 建骨架，按[研究模板](references/study-md-template.md)与人补齐目标和体系，再读取清单。缺电荷、多重度、溶剂或温度时询问，不从旧研究推断。
2. **判断阶段并选卡。** 按下表打开 `auto-g16-recipes` 的对应卡片。极小点/初筛覆盖主族闭壳层单分子；机理研究可用 reaction-plan、ts、irc 卡片，不开放开壳层或金属计算。双分子步骤与复合物按 [complex](../auto-g16-recipes/cards/complex.md) 卡片执行，仅开放以已审阅原子对为约束的采样；通用对接搜索不开放。没有适用卡片或所需能力仍有缺口时说明缺口并暂停依赖步骤，不借用旧 Skill 执行。真实环境出现异常时先停下报告。
3. **确定计算方案与机理假设。** 在 study.md 的“计算方案”列出各阶段方法/基组、溶剂模型与溶剂、温度、标准态与浓度处理、σ 约定与比较口径、方法敏感性及已知局限。每项方法依据按三类填写，并显式传给 `--method-basis`：文献先例用 `auto-g16-literature` 优先查人提供的本组论文和 SI，记录 DOI 加主文页码或 SI 位置，区分直接先例与类比；本课题既有方案写明来源计算或 study，并声明“不是文献先例，精度未经验证”；兜底方法使用[方法表](references/acceptance-methods.md)并明确声明，不能把前两类静默记作兜底。验收用最快的验收方法，不宣称研究精度。涉及机理时先按 [reaction-plan](../auto-g16-recipes/cards/reaction-plan.md) 写出各步骤、待算物种与 TS、竞争假设及可推翻条件，计算方案随机理假设一起签字；纯性质研究随结构里程碑签字，不新增里程碑。按第 7 步生成证据清单并请人签字；计算方案签字前不准备依赖它的 Gaussian Attempt，机理假设未签也不推进依赖该假设的计算。这用于防止未经同意的方法、条件或机理猜想变成计算计划，不替代提交确认。
4. **准备与提交。** 核查卡片输入、资源和前置结果，调用 `ag prepare --card <卡片名>`，按[确认摘要](references/confirmation-summary.md)展示每个 Attempt。同一卡片、同一方法的多个 Attempt 可以一次批量确认。负责人在本 study 当前会话明确说“批准”后，先运行 `ag approve --study <study_id> --attempt <id> --quote "<负责人逐字原话>"`（批次重复 `--attempt`），再运行 `ag submit <id>... --approval <批准ID>`。批准最多有效 24 小时且整条只用一次；批次中途失败或停止，已消费的批准也不恢复。先停止并报告，剩余仍为 prepared 且没有 `.submit-claim` 的成员须重新取得批准，或改由负责人点击 Mac 对话框才能提交；已有 claim 的成员不能重提，不自动继续批次。适用负责人已设定的长期放行规则时，可以显式使用 `ag submit <id>... --policy <规则名>`；两参数互斥。不指定两者时仍由人点击 Mac 对话框，不代点；显式批准或规则核对失败必须停止，不回退弹框。`ag` 负责单次提交、文件一致性、路径检查和全用户作业核数统计，无法核实就不提交。
   会话不得在负责人没有明确批准时自行生成批准记录。原话必须逐字引用，不能概括；只批准负责人点名的、或其原话明确覆盖的 Attempt，含糊时先问清楚。批准记录只对本 study 有效，跨会话或跨 study 转述的批准一律无效。长期规则只能在负责人明确指示后写入本机配置，study 必须为明确名单；会话不能自行扩展名单或资源范围。取消不适用批准记录或长期规则，仍须亲手点击。
5. **接收并解释结果。** 用 `ag status <id>` 查询；`awaiting_second_observation` 表示证据不足，按显示的最早时间再次只读观察，不视为失败或允许取回。结合 `resources_used.cput`、声明输出的大小/mtime 和观察时间判断活动，缺值记未知。完成后 `ag fetch <id>`、`ag facts <id>`，取回后若 `scheduler_residue=true`，提醒人先用 `ag status` 核查残留；仍残留且人明确授权后才调用 `ag cancel`，由人亲手点击确认，只针对 status.json 的确切 job_id，之后只读核查。不自动 qdel，不重试已声明的取消；qdel 返回不等于最终离队。审阅时先运行 `ag review init <id>`，从 manifest 保存的卡片第 6 节生成 `review.md`；已存在时不覆盖，直接读已有 review。阅读事实和原判据，逐行填写“判据 | 依据 | 结论（通过 / 不通过 / 无法判断）”，依据指向 facts 字段、日志行号或文件；自动预填的字段核对不替代完整科学判据。写完后运行 `ag review check <id>`，补齐漏项，出现“review 可能过期”时重新核对新 facts 并更新审阅记录，不把提示当成科学失败或自动重算授权。作业离开队列不等于科学成功；缺失事实不能填成零。更新 `study.md` 进度和剩余问题，每次结束前更新“当前阻塞”和“待你决定”（无则写“无”）；后者集中列出所有待人决定事项、所需信息与证据、选项及影响。
6. **处理异常。** 遇到 `unknown` 或 `failed_presubmit` 按[异常说明](references/unknown-and-failures.md)只报告、不自行处理。计算失败转 `failure-diagnosis` 卡片，提出新 Attempt 的修改方案，等人确认；原 Attempt 保留。取消仅使用 `ag cancel <id>`，由人点击确认，作业号来自其 `status.json`。
7. **先生成清单，再请求里程碑签字并更新假设。** 先在 study.md/review.md 引用全部相关分析输出，运行 `ag review manifest --study <dir>`；展示清单及结构、代表构象集合（含简并度）或最终结果后，再请人签字，将清单相对路径、命令返回的 SHA-256、明确确认的日期和签字人写入 `study.md`。不可代签或把清单生成、提交按钮当成科学签字；已有签字可以沿用到未改变的对象，发生改变时重新审阅、生成新清单并确认对应里程碑，保留旧清单。机理研究在每个里程碑之后更新假设（即使保留也写证据和理由）；TS 方向审核、IRC 端点识别有新证据时及时更新。假设的步骤、物种、TS 或推翻条件改变后，也先生成清单，再重新取得机理假设签字才推进依赖工作；既有签字仅适用于未变化对象，不代签。计算方案（含方法、溶剂、温度、标准态等）改变时，先记录修订及原因，重新生成清单，机理研究随机理假设、纯性质研究随结构里程碑重新签字后再准备依赖新方案的 Gaussian Attempt；保留旧方案、旧签字与旧清单。
8. **沉淀经验。** 解决问题或被人纠正后，按[经验格式](references/lessons.md)在 study 的 `lessons/` 起草，提议修改具体卡片小节，不直接改 Skill；在每周清理时经人审阅合并进卡片。
9. **判定完成。** 只有目标中的量都算出、三个里程碑都签字、机理研究的当前假设已签字且里程碑后更新已记录、`study.md` 有结论，才能称 study 完成；否则说明目前结果及尚缺的证据。下次继续从第 1 步恢复。

prepare 在 manifest 的 `card` 中记录 `name`、`git_commit`、`dirty` 和原始 `content`，优先读取已部署的 `auto-g16-recipes`（解析软链接），未部署时读取 ag 源码仓库的卡片。摘要显示提交号前 7 位和 dirty；保存文本防止 dirty 内容或后续改卡导致旧判据丢失。旧 Attempt 未记录卡片时，review init 会报错，不猜卡、不改 manifest；由 LLM 手工记录依据。check 只检查完整性和 facts 新鲜度，不代表科学接受。facts 重生成后，须逐行重新核对依据和结论，再把 review 顶部 `<!-- facts: ... -->` 的 JSON 更新为 check 返回的 `current_facts`，重跑 check；不要只改快照消除提示。check 本身不修改文件。

第 5 步审阅发现 facts 解析错误时，先运行 `ag facts <Attempt> --reparse --dry-run --out <study外的新文件.json>` 给负责人看逐字段差异；人同意后正式执行 `--reparse`（旧版归档保留），在 study.md 进度日志记录哪些 Attempt、重新解析原因及旧/新 SHA-256 前 12 位；命令列出的引用旧完整哈希的已签内容须由负责人重新确认，不自动继承旧签字。能量、频率或收敛字段出现非预期变化时停下报告，不直接正式执行。

## 登记对象与采用结果

会话可以运行 `ag catalog object`、`member`、`report-kind`、`show`、`suggest`，
登记构象 × 电子态、精确 Attempt 归属和 analyses 报告类别；写命令先用 `--dry-run` 核对。
`suggest` 仅按 parents 打印分组与命令草稿，不证明构象或电子态相同，不自动执行。
接口和前端字段见 [ag-catalog/1](../../docs/ag-catalog-1.md)。

**`adopt` 只能逐字引用负责人在本 study 当前对话中的原话作为 `--quote`**，不能转述、
跨会话引用或自行生成；已有签字的结论也须负责人按 study 逐个授权后才补登记。
CLI 只核对本地记录，不能验证说话者身份。manual_review 警告仍需人工审阅，登记不替代科学签字。
`retire --reason` 将对象转为历史；后续采用不自动恢复状态。
catalog 只追加自身日志和生成自身状态，不改 manifest、facts、review.md、study.md 或签字记录。
日志损坏或状态发布异常立即停止，保留文件并报告；不能自行修复或重复写入采用记录。

## 阶段决策

| 当前阶段 | 下一步 | Skill / 卡片 |
|---|---|---|
| 目标或体系未定 | 补全 study；查计算先例 | `auto-g16-literature` |
| 涉及机理，假设或计算方案未签或已修订 | 写步骤、物种/TS、可推翻条件及计算方案，一起请人签字；暂停依赖计算 | [reaction-plan](../auto-g16-recipes/cards/reaction-plan.md) |
| 结构未确认 | 按第 0 步核验并展示报告、预览，记录结构确认 | [开题物种核验](../auto-g16-structures/SKILL.md#开题物种核验) |
| 双分子步骤或端点为复合物 | 审阅组分及原子对，约束采样；明确参考态、缔合熵与端点比较对象 | [complex](../auto-g16-recipes/cards/complex.md) |
| 已确认结构，待初筛 | 选择本地 RDKit 或集群 CREST | `rdkit-screen` / `crest-screen` |
| 已有初筛集合 | 去重、聚类、展示代表与简并度，请人签字 | 所选初筛卡片 |
| 已签代表集合，目标是极小点 | 同一方法逐个准备 Opt+Freq | `opt-freq` |
| 已接受极小点且计划有单点 | 对最终几何准备单点 | `sp` |
| 已签机理假设与代表集合，待准备 TS 初猜 | 审阅扫描/端点/文献来源、映射及 G0 诊断；阶段总览与覆盖见 ts | [ts-guess](../auto-g16-recipes/cards/ts-guess.md) / [ts](../auto-g16-recipes/cards/ts.md) |
| 有已审阅 TS 初猜 | 按目标原子对准备 TS 搜索、完整 Freq 和方向审核；缺能力或证据则记录具体阻塞 | [ts-search](../auto-g16-recipes/cards/ts-search.md) |
| TS 恰好一个虚频且方向审核通过 | 提出双向 IRC；缺能力或证据则记录具体阻塞 | [irc](../auto-g16-recipes/cards/irc.md) |
| 双向 IRC 已走完 | 两侧端点 Opt+Freq、身份与连接关系比对；缺证据不称验证 | [irc](../auto-g16-recipes/cards/irc.md) / `opt-freq` |
| 刚完成里程碑或得到关键机理证据 | 更新假设；改变时重新请人签字 | [reaction-plan](../auto-g16-recipes/cards/reaction-plan.md) |
| 作业已提交 | status → fetch → facts → review | 当前计算卡片 |
| 出现计算失败、极小点有虚频或 TS 虚频数量/方向不符 | 停下报告，诊断并提出新 Attempt | `failure-diagnosis` |
| unknown / failed_presubmit | 报告状态与已有证据，等待人决定 | [异常说明](references/unknown-and-failures.md) |
| 同一极小点物种的合格最终构象已齐 | 再去重、核对简并度，计算自由能和布居 | `thermo` |
| 目标量已齐 | 展示结论和局限，请人签最终结果；机理研究同时更新假设 | 所选结果卡片，然后更新 study |

这里只描述方案已有接口。运行前读取当前 `ag <命令> --help`；模板参数和本地工具选项按实际接口填写，不猜选项名。若所需能力尚未提供，列出缺口交给人，不用旁路补齐。


## 常见坑

- 首次观察尚无稳定输出证据时，`awaiting_second_observation`（等待第二次观察）不是 `interrupted`；需相隔至少 60 秒且输出不变，并满足正常标记等完整证据，才能取回。明确异常或非零退出不能用等待掩盖。来源：study `butane-l1-20261013`，`lessons/01-await-second-observation.md`。
- PBS R 不等于程序仍在计算：同时查看 CPU 时间、声明输出大小/mtime、观察时间与数据新鲜度；未知不能填 0，时间不替代退出或正常终止证据。来源：study `butane-l1-20261013`，`lessons/02-status-cpu-output-times.md`。
- 结果 fetched 后 PBS 仍可能残留占核；提示可用 `ag cancel`，核查是否自然离开，再由人授权并点击确认。取消响应与最终查询分开记录，不重试已声明取消。来源：study `butane-l1-20261013`，`lessons/03-fetch-residue-reminder.md`。
