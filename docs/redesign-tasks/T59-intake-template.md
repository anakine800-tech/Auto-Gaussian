# T59：开题包模板（结构输入、实验信息、文献记录、讨论记录、假设与证据表）

版本：v1.1（2026-10-16，按负责人提供的 v1 任务单实施；公开副本将私有课题代称泛化，补记本次对话确认的 K1 对照范围，不改变允许路径）。

## 分支与目标

- 分支：`codex/t59-intake-template`；基于最新 main，一张任务单一个 PR。纯文档任务，不改代码。
- **目标：** 补上“结构输入 → 文献 → 课题背景与人讨论 → 开始计算”这条闭环里，开始计算之前的部分。每个课题在私有 study 目录里形成一份“开题包”，负责人签字后进入 N0，再由计算会话接手 prepare。
- **为什么：** 现在开题靠会话临时整理。既有已签课题 的 K1 材料是按需拼出来的；首个待补实验信息的试点课题 课题的实验信息、文献和假设也只是散在一份讨论稿里。来源、证据级别和未知项没有固定的位置，容易丢失，也容易把推测写成已知。
- **负责人 10-16 的决定（两轮问答，全部按建议）：**
  - 开题包全部写进私有 study，不另建系统。
  - 分工：开发机上的独立 Codex“研究会话”负责结构核对和文献检索，不连集群；监督方负责讨论和科学判断（问答形式）；负责人签字；开题定稿后由 study 所在电脑的会话接手计算。
  - 讨论按轮记录在 study.md，每条决定标日期和决定人；讨论过程不签字，只有汇总后的开题包签字。
  - 不自动判断有哪些立体通道，不自动生成 Attempt。
  - 第一次试点用 首个待补实验信息的试点课题 课题（等负责人补齐实验信息）；既有已签课题 已签的开题不回头重做。
- **资料：** `skills-next/auto-g16-study/references/study-md-template.md`、`acceptance-methods.md`；`skills-next/auto-g16-chemdraw-structures/references/validation-levels.md`、`chemistry-validation.md`；`skills-next/auto-g16-literature/SKILL.md`。

## 第 0 步：从 v2.7 归档提取（只读）

逐个阅读下列文件，把“可复用内容 → 放进模板哪一节 → 来源路径 → 舍弃的部分”整理成表，写进 PR 描述：

- `archive/docs/end-to-end-reaction-computation-workflow.md`（R00 研究目标与范围、R01–R02 反应信息与物种、R03 条件与模型）
- `archive/skills/auto-g16-reaction-workflow/references/intake-contract.md`、`literature-evidence-design.md`、`mechanism-support-matrix-contract.md`、`ts-precedent-map-contract.md`
- `archive/skills/auto-g16-reaction-literature/references/search-and-evidence-protocol.md`（证据分级）
- `archive/docs/human-scientific-decision-layer.md`（人工决策记录）
- `archive/docs/method-evidence-v2.5.md`（方法证据比较表）
- `archive/skills/auto-g16-reaction-workflow/scripts/mechanism_support_matrix.py`、`archive/skills/auto-g16-ts-seed/scripts/ts_seed_core.py`：只取表格的列和分类，不移植代码。

**只提取问题清单、字段和分类。** 不恢复 W1/W2、R00–Rxx 的审批门控、schema 合同、authority 链和旧命令名。与 v4 现行规则冲突时以现行规则为准，并在 PR 里列出。

## 允许改动的路径

- 新增 `skills-next/auto-g16-study/references/intake-template.md`：开题包主模板。
- 新增 `skills-next/auto-g16-study/references/literature-record.md`：文献记录表格式与核实规则。
- 新增 `skills-next/auto-g16-study/references/discussion-record.md`：讨论记录格式。
- `skills-next/auto-g16-study/references/study-md-template.md`：只在开头加一行“开题见 intake-template.md”和保密级别一行（见要做的第 1 条），其余不改。
- `skills-next/auto-g16-study/SKILL.md`：在引用列表里登记三个新文件；在流程里加一步“开题”。
- `skills-next/auto-g16-literature/SKILL.md`：加一段，说明课题检索记录按 `literature-record.md` 写进私有 study，`group-literature.md` 只放已发表的本组文献。
- `docs/redesign-tasks/T59-intake-template.md`：本任务单。

## 要做的

1. **保密级别一行**（`study-md-template.md` 开头）：是否已发表、保密级别、能否进公开仓库或 PR。写明：会话写 PR、评论或公开文档之前，先看这一行。
2. **`intake-template.md`，按以下各节：**
   1. **研究目标与范围**：要回答什么、不回答什么、结论边界、与实验怎么比较。
   2. **实验信息**：反应式、条件（溶剂、温度、浓度、时间、添加剂）、产率、ee/dr、绝对构型及其依据（X-ray 及 Flack 参数 / 类比 / 未知）、对照实验、机理实验。每项标“已知 / 推测 / 未知”，并写来源；不确定的不猜。
   3. **物种与结构**：输入来源优先级（ChemDraw 原件 CDXML/CDX > SDF/MOL > SMILES > 图片；图片重建必须由负责人逐个核对）；每个物种核对分子式、电荷、多重度；立体中心的 CIP 标签用 RDKit 重新计算并与 ChemDraw 命名对照，不一致就停下问；3D 用 RDKit ETKDG 生成，记录随机种子，生成后再核对一次立体。引用 `chemdraw-structures` 现有的验证分级，不另写一套。
   4. **原子对应（atoms.csv）**：可以用 RDKit 最大公共子结构辅助生成初稿；成键原子和立体中心逐个人工确认。列出必填列。
   5. **立体通道表**：模板加校验规则，主键是“空间构型 → 产物构型”，两套 CIP 标签分开列；用 既有已签课题 的通道表作为结构范例（写成通用示例，不含 既有已签课题 的具体分子和数据），说明中间体和产物 CIP 可能相反的情况。
   6. **机理假设与证据表**：列为假设、预测（如果成立应该看到什么）、支持证据、反对证据、证据级别（作者提出 / 实验支持 / 计算比较 / 我们的推断）、计算上怎么区分、状态。没有直接先例的，记为“证据缺口”。
   7. **方法与依据**：每一层方法写依据（文献先例的 DOI，或“本课题既有方案，无文献先例，精度未验证”）；与 `literature-record.md` 的方法摘要列对应。
   8. **能量口径与动力学模型**：引用现有 thermo、profile 卡片，只列需要填写的选择项。
   9. **首轮范围与“首轮不做”清单。**
   10. **TS 初猜来源表**（TS 阶段再填）：初猜编号、来源（文献结构 / 扫描 / QST / 约束采样 / 人工搭建）、对应通道、尝试过的 Attempt、结果、失败原因、备选方案。
   11. **第一批作业清单**：物种、程序、方法、核数、walltime、估算依据。
   12. **N0 进入条件**（负责人签字前逐项打勾）：结构核对完成、立体通道表完成、每层方法有依据、假设与证据表完成、首轮范围写好、保密级别写好、未知项列出及其对结论的影响写好。
3. **`literature-record.md`：**
   - 列：DOI、标题、年份、核实方式（出版商页面 / Crossref）与日期、与本课题的关系（同体系 / 同类反应 / 方法先例 / 反面证据）、证据级别、关键信息位置（正文或 SI 页码）、方法摘要（泛函、基组、溶剂、温度、标准态、低频处理）、未核实项、检索式与检索日期。
   - 规则：每条 DOI 都要核对标题、作者、年份；核实不了的标“未核实”，不能作为方法依据；不引用二手综述转述的数字；同时检索反面证据。
   - 保密：已发表的本组文献可以进公开的 `group-literature.md`；课题检索记录和对未发表工作的分析只放私有 study。
4. **`discussion-record.md`：** 每轮问答一节：日期、参与者、问题、建议、负责人的回答、形成的决定（编号、日期、决定人）、未决事项。说明讨论不签字，签的是汇总后的开题包；会话之间的转述要注明原话出处。
5. 所有示例都用虚构的通用小分子，不出现 既有已签课题、首个待补实验信息的试点课题 或其他未发表课题的结构、数据和名称。

## 不允许

- 不改代码和 ag 内核；不改卡片（`skills-next/auto-g16-recipes/cards/`）。
- 不恢复 v2.7 的审批流程、合同和命令。
- 不写任何未发表的研究内容、本机路径和用户名。

## 测试

- `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`（`test_skill_format.py` 会检查链接存在和没有私有路径）。
- 人工自查：模板里的每一节都能对应到 既有已签课题 K1 实际用过的一项内容（在 PR 里列对照表，只写节名，不写 既有已签课题 内容）。
- 敏感扫描与 `git diff --cached --check`。

## 真实环境验证

- 不需要连集群。合并后，以 首个待补实验信息的试点课题 课题做试点：研究会话按模板起草开题包，监督方审阅，负责人签字。试点中发现的问题记在 PR 评论里，另开小修。

## 停止条件

- 需要改卡片或 ag 代码。
- 归档内容与现行规则有实质冲突，不确定以哪个为准。
- 模板需要写入具体课题内容才能说清楚。

## 合并前审阅与交付

- 需要监督方审阅：是。
- 修改 AGENTS.md：无。
- PR 描述第一行：`Task: T59`；附第 0 步的复用表和 K1 对照表。
- 合并只由负责人操作。

## 本次对话补充：K1 对照范围（2026-10-16）

负责人确认仅按提供的节名对照，不读取或迁移计算机上的定稿 study。
PR 逐项说明对应模板章节；对不上的列明模板缺项或不属于开题。
公开表只保留以下通用节名：

1. 反应与条件。
2. 计算模型物种的电荷、多重度、原子数、分子式。
3. 催化剂结构与 ChemDraw 原件构型核对。
4. 实验背景与计算模型可比性。
5. 实验产物绝对构型归属及前置条件。
6. 保留/暂态中心、统一原子编号、atoms.csv、CIP 排序原子。
7. 立体通道及中间体/产物两套 CIP 标签。
8. 构象家族定义与通道计数。
9. 副反应或结构变化监测。
10. 首轮目标与不做清单。
11. 竞争机理假设、预测与首轮可检验范围。
12. 各层 route 与方法依据。
13. 程序版本、计算集群与跨平台可比性。
14. 能量、参考态、低频敏感性、σ/简并度与有效能垒。
15. 已知局限。
16. 阶段顺序、冻结项、停止条件与期限。
17. TS walltime、MaxCycles、收敛与中断接续。
18. 单点与第一批作业核时预算。
19. 存储情况。

第 13、17、18、19 项可以归计算方案或第一批作业清单；执行细节引用现有卡片，
不复制成开题审批步骤，不改代码或卡片。
