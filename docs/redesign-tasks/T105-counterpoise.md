# T105：S10 counterpoise（BSSE）诊断——`gaussian-cp` 模板与 `ag cp-report`

版本：v1（监督方，2026-10-20）。**开发机做。** 一个后端 PR，PR 描述第一行写 `Task: T105`。

## 分支与目标

- 分支：`codex/t105-counterpoise`。
- **开工条件：** 后端 main 为 `b318639`（T102）或其后；T105 编号未被占用；没有与本单路径冲突的未合并 PR。
- **负责人 2026-10-20 决定（共两轮，全部采纳监督方推荐）：**
  - C1 counterpoise 只用于 **RC、离子对、TS 的相互作用能**，作为诊断量单独报告，**不进入主线剖面**（ΔG‡、ΔΔG‡ 不做 CP 校正）。
  - C2 按 study 的原子映射把体系分成两个片段，逐原子标记；有共价键跨越片段就拒绝。成键后的物种（例如某研究课题的成键后物种）不做。
  - C3 溶剂：先实测 Gaussian 16 能否在同一作业里同时用 `Counterpoise` 和 `SCRF`。不能用就只算气相 CP，再把 BSSE 加到溶剂相的相互作用能上，同时写明"假设 BSSE 基本不受溶剂影响"。
  - C4 层级：以几何层的 M06-2X/6-31+G(d,p) 为主。校正量 >1 kcal/mol 时，到最终 SP 层级补算一次，看是否收敛。（这是使用规则，写进卡片，工具不强制。）
  - C5 只出报告，不修改 thermo / profile。开发机现在就开工，研究 A 等首批 TS 出来后再用。
  - I1 新增独立模板 `gaussian-cp`：只做单点，route 固定为 `Counterpoise=2`。
  - I2 片段沿用现有 `--fragments` CSV 格式，增加电荷和多重度两列；prepare 时做四项校验。
  - I3 工单第 0 步先实测 C3，结果决定模板是否接受 SCRF。
  - I4 新增 `ag cp-report`，输出 `ag-cp/1`。
  - I5 真实验证体系：水二聚体、NH₄⁺···H₂O；离线另加一个"片段间有共价键"的反例。
- **资料：** `AGENTS.md`、`docs/DEVELOPING.md`、`docs/LESSONS.md`；T40（complex 卡）、T76（`ag asm`）、T82（口径一致性）、T92（`--fragments` 与 multiwfn 模板）、T99（route 拼接与来源行号）任务单；`render.py`、`attempt.py`、`gaussian_input.py`、`facts.py`、`topology.py`、`thermo.py`、`profile.py`、`asm.py`、`cli.py`；`skills-next/auto-g16-recipes/cards/complex.md`。

## 背景（main `b318639` 的代码现状）

1. `render.declaration()` 只认四个模板：`gaussian`、`xtb`、`crest`、`multiwfn`。`allowed_templates`（T101）在加载配置时用它来校验模板名。
2. `--fragments` 目前只给 `multiwfn` 用：CSV 两列（`fragment,atoms`），2–4 个片段。prepare 遇到其他模板带 `--fragments` 会直接拒绝。
3. complex 卡第 185 行写的是"当前不能做 counterpoise 检查，输入校验不接受片段标记"，本单完成后要改写。
4. Gaussian counterpoise 的输入格式：电荷/多重度行依次写"整体、片段 1、片段 2……"；每个原子写成 `元素(Fragment=n)`。输出里会打印 counterpoise 校正后的能量、BSSE，以及校正前后的复合能（complexation energy）。具体的输出格式以实测日志为准，不要凭记忆写解析器。

## 允许改动的路径

- `ag/templates/gaussian-cp.toml`（新建）。作业脚本**复用**现有的 gaussian PBS 脚本和 SCNet 脚本，不要另复制一份改写。如果确实非新建脚本不可，先停下申请。
- `ag/src/ag/render.py`：只做三件事——登记 `gaussian-cp`，复用 gaussian 的渲染路径，输出名称与 gaussian 一致。
- `ag/src/ag/attempt.py`：放开 `gaussian-cp` 使用 `--fragments`，并加上片段校验；确认摘要里列出片段信息。
- `ag/src/ag/gaussian_input.py`：生成带片段标记的坐标，以及多片段的电荷/多重度行。
- `ag/src/ag/cli.py`：`--fragments` 的帮助文字；注册新命令 `cp-report`。
- `ag/src/ag/facts.py`：解析 counterpoise 输出，写入新的 `counterpoise` 字段。
- `ag/src/ag/cp_report.py`（新建）。
- `ag/src/ag/thermo.py`、`ag/src/ag/profile.py`、`ag/src/ag/asm.py`：**只加一项拒绝**——不接受 `gaussian-cp` 的 Attempt 作为能量来源。
- 测试：新建 `ag/tests/test_counterpoise.py`；为登记模板确有必要时，可改 `ag/tests/test_clusters.py`、`ag/tests/test_shared_cluster_caps.py`（`allowed_templates` 合法名称）。
- 文档：`docs/ag-cp-1.md`（新建）、`docs/ag-facts-1.md`（补 `counterpoise` 字段）、`README.md`、`docs/LESSONS.md`（加一条）。
- 卡片：`skills-next/auto-g16-recipes/cards/complex.md`（改写 BSSE 一节）；新建 `skills-next/auto-g16-recipes/cards/counterpoise.md`；`skills-next/tests/test_card_consistency.py` 只在新卡登记确有必要时才改。
- `docs/redesign-tasks/T105-counterpoise.md`（本单）、`docs/redesign-tasks/open-tasks.txt`。

## 要做的

### 0. 先实测 Counterpoise 与 SCRF 能否同时使用（I3，在写代码之前做）

- 在开发机上手写一个水二聚体输入：`# M062X/6-31+G(d,p) SP Counterpoise=2 SCRF=(SMD,Solvent=DiChloroEthane)`，带片段标记。**不要经过 ag**，在 default 上提交一次。这次提交仍需负责人亲手点 Mac 确认框；如果不经 ag 就没法弹出确认框，就改成先 prepare 一个临时模板再提交，由开发机说明采用哪种方式，经负责人同意后再执行。
- 读日志，确认是报错、静默忽略某一项，还是正常算完，并贴出相关原文行（脱敏）。
- **报错或静默忽略** → 模板拒绝 SCRF，只算气相，按 C3 执行。
- **正常算完** → 先停下汇报，由负责人决定。不要自行决定启用溶剂相 CP。

### 1. 模板 `gaussian-cp`（I1）

- 只做单点：route 必须含 `SP`（或不含任何任务关键词）和 `Counterpoise=2`；含 `Opt`、`Freq`、`IRC`、`Scan`、`Guess=Read` 等任务关键词的一律拒绝。
- 方法和基组沿用现有 gaussian 的白名单和 T82 检查，仍不支持 `Gen`、`GenECP`、`ExtraBasis`、`IOp`。按第 0 节的结果决定是否拒绝 `SCRF`。
- `--fragments` 必须提供，且片段数**固定为 2**。第一版只做双片段，不做三体及以上。
- 允许 default 和 scnet 两种入口，入口规则与 gaussian 相同（T101：scnet-test 不允许跑 Gaussian 类模板，`allowed_templates` 照常生效）。
- 输出文件名、完成判定与 gaussian 模板一致。

### 2. 片段文件与校验（I2）

- CSV 列：`fragment,atoms,charge,multiplicity`。`atoms` 沿用现有写法（从 1 开始的编号和区间）。multiwfn 仍使用原来的两列格式，不受影响。
- prepare 时做四项校验，任一不通过就拒绝，报错写清楚是哪个原子、哪个片段：
  1. 每个原子恰好属于一个片段；
  2. 各片段电荷之和等于整体电荷；
  3. 所有片段都是单重态（多重度为 1），整体也是单重态；
  4. 用 `topology` 现有的成键判断检查：有共价键跨越两个片段就拒绝。拓扑结论不确定的接触（T73 的 uncertain）也要拒绝，并在报错中列出那一对原子，由人工确认后改片段。
- 确认摘要逐片段列出原子数、分子式、电荷、多重度，并给出片段文件的 SHA-256。
- 片段文件和生成的输入一起纳入 bundle 哈希。

### 3. facts 解析

- 对 `gaussian-cp` 的日志，在 facts 中新增 `counterpoise` 对象，包含：复合物未校正能量、CP 校正后能量、BSSE（Hartree）、各片段的相关能量（以 Gaussian 实际打印的为准），每一项都带日志行号，做法与 T99 一样。
- 解析器的写法依据第 0 节和真实验证得到的日志，不凭记忆推断输出格式；遇到不认识的格式就报错，不猜。
- 已有模板的 facts 字段和含义一律不变。

### 4. `ag cp-report`（I4）

- 输入：一个 `gaussian-cp` Attempt。可选：同一几何的溶剂相单点 Attempt，以及一个 `ag asm` 报告。
- 输出：`ag-cp/1` JSON 和一份同名 Markdown。内容包括：
  - 复合物未校正能量、CP 校正后能量、BSSE（Hartree 和 kcal/mol）；
  - 未校正和校正后的相互作用能（kcal/mol）、各片段能量、方法口径、片段定义及其哈希；
  - 每个数值的来源（文件路径、哈希、行号）。
- 提供了溶剂相单点时：先核对与 CP Attempt 是同一几何（原子序一致、刚性对齐 RMSD ≤0.001 Å）、同一方法和基组，再输出"溶剂相相互作用能 + 气相 BSSE"。相互作用能的片段能量，按溶剂相单点里能取得的内容计算；取不到片段的溶剂相能量时，只给出"溶剂相复合物能量 + 气相 BSSE 修正量"，**并写明缺什么**，不拿气相数值代替。附注写明"假设 BSSE 基本不受溶剂影响"。
- 提供了 asm 报告时：只把形变能列在旁边对照，不合成任何新的结合能结论。
- 报告固定附注："诊断量；未进入 thermo/profile；不构成已校正剖面"。不出现"已校正剖面""已排除 BSSE"之类措辞。

### 5. 防止误用

- thermo、profile、asm 收到 `gaussian-cp` Attempt 作为能量来源时，拒绝并提示"CP 单点仅用于 cp-report"。
- complex 卡第 6 节的 BSSE 部分改写为：可以用 `gaussian-cp` 做诊断；规则按 C1–C5（只做 RC/离子对/TS 相互作用能、两片段、成键物种不做、溶剂处理、层级与 >1 kcal/mol 的补算规则、不进剖面）。新建 counterpoise 卡，写清楚输入、片段文件、命令、判读和限制，并与 complex 卡互相链接。

## 不允许

- 不改现有 gaussian 模板的 route 白名单、渲染出的字节和 facts 字段。
- 不支持三片段及以上、开壳层片段、`Gen`/`ECP`、`Opt` 与 counterpoise 组合（`Opt=Counterpoise`）。
- 不修改 thermo/profile 的计算，只加拒绝；不自动把 BSSE 写进任何剖面或签字材料。
- 不碰研究 A 数据；不提交研究 A 体系。

## 测试

只用合成数据或小分子，加假 Transport。

| 场景 | 预期 |
|---|---|
| 水二聚体，两片段 0/1 + 0/1 | 输入的电荷/多重度行和 `Fragment=` 标记正确，bundle 哈希包含片段文件 |
| NH₄⁺···H₂O，+1/1 + 0/1 | 电荷行为 `1 1 1 1 0 1`，摘要逐片段列出 |
| 有原子漏标或重复 | 拒绝，报出原子编号 |
| 片段电荷之和与整体不符 | 拒绝 |
| 有片段不是单重态 | 拒绝 |
| 乙醇切成两半（片段间有共价键） | 拒绝，报出成键的原子对 |
| 拓扑不确定的接触跨越片段 | 拒绝，报出原子对 |
| route 含 Opt / Freq / Guess=Read / Gen | 拒绝 |
| route 含 SCRF | 按第 0 节结论拒绝（或停下等负责人决定） |
| 片段数不是 2 | 拒绝 |
| multiwfn 的两列 CSV | 行为不变 |
| facts 解析真实验证得到的日志（脱敏夹具） | `counterpoise` 各字段和行号正确；格式异常时报错 |
| cp-report 只给 CP Attempt | 输出未校正值、校正值、BSSE、相互作用能，带来源 |
| cp-report 附溶剂相单点 | 几何、方法不一致则拒绝；一致则输出修正值和附注；缺片段能量时写明缺失 |
| thermo/profile/asm 输入 `gaussian-cp` | 拒绝 |
| scnet-test 设置了 `allowed_templates` | `gaussian-cp` 被拒绝 |
| 已有 gaussian Attempt | 渲染字节和 facts 不变 |

开发中只跑相关测试；推送前本地跑一次全量 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，之后以 CI 为准。只暂存本单涉及的文件；运行 `python ag/tools/scan_sensitive.py --staged` 和 `git diff --cached --check`。

## 真实环境验证（合并前，开发机，非研究体系）

未合并的代码用于真实提交前，按 DEVELOPING.md 要先由负责人批准；每次提交都由负责人亲手点击 Mac 确认框。

1. **第 0 节实测**：在 default 上提交一次（见第 0 节）。
2. **水二聚体**：用 `gaussian-cp` 在 default 上以 M06-2X/6-31+G(d,p) 做气相 CP 单点，提交一次；正常结束后取回，跑 facts 和 `cp-report`。
3. **NH₄⁺···H₂O**：同上，提交一次。另用普通 gaussian 模板对同一几何做一次 SMD(DCE) 单点，再跑一次带溶剂相单点的 `cp-report`。
4. 回报：各作业的资源和耗时、BSSE 数值（kcal/mol）、相互作用能（未校正 / 校正）、报告的哈希；第 0 节的结论及相关日志行（脱敏）。只核对数值的量级是否合理，**不作文献对标结论**；如要对比文献值，必须引用核实过 DOI 的原始论文。
5. 合计 4 个小作业，核数和 walltime 由开发机在验证方案里给出，并列明上限。出现异常就停下，不重试。

## 停止条件

- 第 0 节实测显示 Counterpoise 与 SCRF 可以同时使用（等负责人决定）。
- 需要新建作业脚本，或改动范围外的文件。
- Gaussian 实际输出与解析预期不一致，又无法从日志中唯一确定。
- 同一问题修两次仍未解决。

## 合并前审阅与交付

- 需要监督方审阅：**是**（新模板、facts 新字段、卡片科学口径）。合并只由负责人操作。
- PR 描述包括：C1–C5、I1–I5 逐条对应的改动；第 0 节结论；全量测试结果；真实验证的提交号与数值；卡片改动摘要。
- 用 `gh pr view <编号> --comments` 读取 `<!-- ag-review head=... -->` 评论，逐条处理。
- **合并后：** 开发机同步。研究 A 计算机的同步时间由负责人定。研究 A 首次使用前，由负责人确认第一个 RC 或 TS 的片段文件。

## 版本记录

- T116 脱敏：研究标识、编号与环境字面量改为泛称；原工单结构和结论不变。

- v1（2026-10-20，监督方）：依据负责人 10-20 两轮 S10 决定（C1–C5、I1–I5）起草。

## 2026-10-22 批复（v1.1，保留 v1 原文）

负责人在本任务对话转发并采纳批复：

- 批准第 0 节使用临时模板，在 default 上提交水二聚体探针一次，4 核、10 GB、30 分钟；仍由负责人亲手点击 Mac 系统确认框并核对入口和核数。
- route 与第 0 节完全一致；临时模板仅放临时目录或临时 worktree，不提交、不进入 PR。
- 结束后仅取回日志，如实报告报错、静默忽略或正常完成，附脱敏原文行；正常完成则停止等待负责人决定；任何意外立即停止，不重试。
- 监督方 2026-10-22 批准的范围扩展：`ag/tests/test_smoke.py`、`skills-next/auto-g16-recipes/SKILL.md`、`skills-next/tests/test_skill_format.py`。仅增加 `cp-report` 命令/模块和 counterpoise 卡片登记，不修改其他条目、不放宽断言；PR 描述列出三个文件实际路径及改动行数。
- 第 0 节结论前可以做与结论无关的片段校验、cp-report 框架及测试夹具；SCRF 取舍等待实测结果。此条取代 v1 中必须等第 0 节完成才写全部功能代码的顺序限制。


## 2026-10-22 第 0 节结论确认（v1.2）

负责人确认 G16 A.03 明确拒绝 CP 与 SCRF 同用，按 C3 继续气相 CP 开发，无需再次决定溶剂策略。
日志第 89 行 `No SCRF with counterpoise/fragments.`，第 90 行异常终止；原日志 SHA-256 `ff18259cdb5970fa1198aa804116be2978bbd7a4136bbfaaf39d946ecba4401d`。
prepare 必须拒绝任何 SCRF route，提示气相 CP 与 `ag cp-report --solvent-sp`。脱敏错误/终止两行作为测试内联夹具，不含安装路径或主机名。
complex/counterpoise 卡片以“G16 A.03 实测拒绝，T105 第 0 节”为溶剂限制依据；临时模板不入 PR。
继续其余开发与离线测试；后续水二聚体和 NH₄⁺···H₂O 气相 CP、NH₄⁺···H₂O SMD 三个单次作业，须先向负责人交付具体验证方案并获批准。
