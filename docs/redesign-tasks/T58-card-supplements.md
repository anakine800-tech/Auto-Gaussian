# T58：卡片补充项（F3 动力学解释卡、S7 隧穿、S8 SMD 核对、F4 核时预算、Gaussian 报错速查）

## 分支与目标

- 分支：`codex/t58-card-supplements`；基于最新 main，一张任务单一个 PR。
- **目标：** 完成 2026-10-14 卡片审阅清单里的补充项（handoff-v4.md “已知问题与后续工作”一节）：
  - **F3** 动力学解释卡片（换算工具已有，缺解释）；
  - **S7** 隧穿估计（扩散极限提示已有）；
  - **S8** SMD 能量项和离子适用性的核对；
  - **F4** 研究级核时预算（负责人 10-16 已取消 SCNet 核时预算检查，ag 只记账，F4 改为“如何估算和记录”的说明）；
  - **Gaussian 报错速查表**。
- **不做：** 第二批的 U1、U2、U4、U7、F6（会挪动现有卡片的内容或行号，HSS 进行中不动，N1 之后再做）；F5 片段摆放工具（是代码，另开工单）；推迟到第二阶段的 S2、S4、S5、S10。
- **为什么现在做：** HSS 的 N1 要做通道排序、可逆性筛查（逆能垒约 24 kcal/mol 对应 298 K 下半衰期约 12 h）和 ΔΔG‡ 到选择性的换算；K3、K7 审阅时需要统一的解释口径。

## 第 0 步：先从 v2.7 归档提取可复用内容（只读）

开写之前，逐个读下列归档文件，列出“可复用内容 → 用在哪一项 → 来源路径”的表格，写进 PR 描述：

| 候选来源（仓库内相对路径） | 可能用于 |
|---|---|
| `archive/skills/auto-g16-rtwin-pbs/references/environment-and-failures.md` | 报错速查 |
| `archive/skills/auto-g16-rtwin-pbs/references/protocol-rigor.md`、`scientific-workflows.md` | S8、F4 |
| `archive/skills/auto-g16-reaction-workflow/references/thermochemistry-readiness-contract.md` | F3、S7、S8 |
| `archive/docs/method-evidence-v2.5.md` | S8 |
| `archive/docs/ts-freq-irc-design.md` | 报错速查（TS、IRC 部分） |
| `archive/docs/end-to-end-reaction-computation-workflow.md` | F3、F4 |
| `archive/skills/auto-g16-asymmetric-catalysis/references/candidate-and-selectivity-protocol.md` | F3（选择性换算、Curtin–Hammett） |
| `archive/docs/resource-monitor-efficiency-migration.md` | F4 |

规则：
- 只提取知识内容（判据、换算、常见错误与处理）。**不恢复**旧的审批门控、schema 合同、authority 链和旧命令名。
- 归档内容与 v4 现行规则（AGENTS.md、现有卡片）冲突时，以现行规则为准，在 PR 里列出冲突。
- 采用的内容在新文本里注明“改编自 archive/…”（与 `mode_review.py` 的做法一致）。

## 允许改动的路径

- 新增 `skills-next/auto-g16-recipes/cards/kinetics.md`（F3 + S7），沿用现有卡片的章节结构。
- 新增 `skills-next/auto-g16-study/references/gaussian-errors.md`（报错速查）。
- `skills-next/auto-g16-recipes/cards/sp.md`、`thermo.md`：**只在文件末尾追加** S8 一节，不改已有的行。
- `skills-next/auto-g16-recipes/cards/failure-diagnosis.md`：只在文件末尾追加一行，链接到报错速查。
- `skills-next/auto-g16-recipes/cards/reaction-plan.md`、`skills-next/auto-g16-study/references/study-md-template.md`：**只在文件末尾追加** F4 一节。
- `skills-next/auto-g16-recipes/SKILL.md`：卡片索引里登记 kinetics 一行。
- `skills-next/tests/`：如果有测试固定列出全部卡片，只允许登记新卡一行（已预先批准），在 PR 里写明。
- `docs/handoff-v4.md`：清单里把完成的项移到“已完成”。
- `docs/redesign-tasks/T58-card-supplements.md`：本任务单。

**ts.md、irc.md、crest-screen.md、opt-freq.md、complex.md、profile.md 一行都不改。** HSS 正在按这些卡片的行号工作。

## 要做的

1. **kinetics.md（F3 + S7）：**
   - Eyring 换算：ΔG‡ ↔ 速率常数 ↔ 半衰期（一级、准一级），给 298.15 K 的对照表，并说明换算工具在哪。
   - 可逆性判读：逆能垒和反应时间的关系，与 HSS 方案里的写法一致（约 24 kcal/mol 对应约 12 h），注明这是量级判断，不是结论。
   - 选择性：ΔΔG‡ ↔ er、ee、dr 的换算表；Curtin–Hammett 的适用条件（构象或中间体之间的转换要快于产物生成）和不适用时怎么办；有效能垒的 Boltzmann 汇总与 `selectivity` 工具的对应关系。
   - 误差口径：1 kcal/mol 在 298 K 约等于 5 倍速率差；说明 DFT 误差量级下 ee 数值比较的局限。
   - S7 隧穿：Wigner 校正公式和适用范围（只适用于虚频不太大、势垒顶部近似抛物线的情况）；什么时候需要更高级的处理（如涉及 H 转移且虚频很大），现在 ag 不支持，只能写成能力缺口。
2. **S8（追加到 sp.md、thermo.md 末尾）：**
   - SMD 溶剂化自由能里已经包含哪些项（静电和非静电）；“气相热校正 + 溶液相单点”组合时，各项怎么加、哪些不能重复加；1 atm → 1 M 标准态修正什么时候需要、什么时候已经包含。
   - 离子和电荷分离体系上 SMD 的误差更大；写明这时结论应加什么限定。
   - 与已签的 HSS 能量口径（1 M 标准态、标准态修正不重复）对照一遍，有出入就停下报告，不改 HSS 口径。
3. **F4（追加到 reaction-plan.md、study-md-template.md 末尾）：** 按阶段估算核时的方法（构象采样、单点、TS、IRC），用第一批实测耗时校准；ag 的 Slurm 台账只记录不拦截（`budget_core_hours` 可省略）；平台余额由负责人自己看；study.md 里记录预估和实际。
4. **gaussian-errors.md：** 一张表：报错特征（如 `Error termination via Lnk1e in .../l9999.exe`、`l502` 不收敛、`l103` 优化步数用完、`l123` IRC 校正失败、`l1` 内存或输入问题、`galloc` 等）→ 常见原因 → 首选处理 → 对应的 ag 操作（新建 Attempt、`--parent-chk` 等）。与 `failure-diagnosis.md` 和 `unknown-and-failures.md` 已有内容不重复，重复的地方只放链接。
5. **文献：** 每条引用都要有 DOI，并逐条在出版商页面核实；核实不了的，不写具体数值，只写“待核实”。不引用二手综述里转述的数字。

## 不允许

- 不改上面点名的 6 张 HSS 正在使用的卡片；不在已有卡片的中间插入内容。
- 不改代码、不改 AGENTS.md。
- 不恢复 v2.7 的审批流程、合同和命令。
- 不写任何研究数据或未发表内容（HSS 的数字只能以“例如约 24 kcal/mol 对应约 12 h”这种通用换算出现）。

## 测试

- `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`（卡片结构测试要通过）。
- 用 `git diff --stat` 证明 6 张 HSS 卡片零改动；sp.md、thermo.md、reaction-plan.md、study-md-template.md、failure-diagnosis.md 的改动只出现在文件末尾（`git diff` 里没有删除行）。
- 换算表的数值用脚本复算一遍，脚本不进仓库，复算结果贴在 PR 里。
- 敏感扫描与 `git diff --cached --check`。

## 真实环境验证

- 不需要。HSS 的 K3 审阅会实际使用 kinetics.md，有问题再开小修。

## 停止条件

- S8 核对发现与已签的 HSS 能量口径不一致。
- 需要改动 6 张 HSS 卡片中的任何一张。
- 归档内容和现行规则有实质冲突，不确定以哪个为准。

## 合并前审阅与交付

- 需要监督方审阅：是（科学内容）；负责人审科学表述。
- PR 描述第一行：`Task: T58`；附第 0 步的复用表、文献核实清单和换算复算结果。
- 合并只由负责人操作。
