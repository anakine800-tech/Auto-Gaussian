# T80：开题闭环前半段——结构输入 → 自动核验 → 人工签字 → 文献检索记录

## v2 修订记录（负责人 2026-10-16 明确授权）

下方保留 v1 任务内容；本节仅修订读入函数范围与对应停止条件，其余要求不变。
为防止 SMILES 独立显式氢被移除后 CIP 核对到错误原子，允许在
`make_gaussian_input.py` 的 `read_molecule` 中增加默认关闭的可选参数，
只控制是否移除显式氢，仅 `check_species.py` 启用；其他读入、规整化及立体识别逻辑不变。
`prepare_preview.py`、`prepare_conformers.py` 与 `cdx_stereo.py` 不修改。

验收追加：用现有合成数据对比旧版与新版默认调用的 preview/conformers 全部输出文件 SHA-256，
要求逐字节一致；新增保留/移除显式氢的对照测试，CIP 结论、分子式和电荷相同，编号按源原子变化。
PR 明确说明 `make_gaussian_input.py` 只改 `read_molecule` 的此项可选参数并附哈希对比。
此授权只豁免上述最小读入改动；其他停止条件继续适用。

## v1 原任务内容


## 分支与目标

- 分支：`codex/t80-intake-structures`；基于最新 main（v4.2.2），一张任务单一个 PR。**开发机做。**
- **目标：** 把开题时“结构对不对、文献查到哪”这一段串成有关口的固定流程：
  1. 新增结构核验脚本 `check_species.py`：按物种清单读入每个物种的结构文件，自动给出分子式、电荷、原子数、组分数、立体中心与 CIP，并与人写下的预期值、第二来源逐项对照；可选核对反应式的原子和电荷配平；
  2. study 技能第 0 步（开题）拆成有前后关口的四小步，每一步检查上一步的产出；
  3. 开题模板第 3 节、讨论记录模板接上核验报告。
- **为什么：** 结构是整条链的地基。现在开题模板第 3 节的“核对结果”靠手填，`prepare_preview.py` 一次只看一个物种，也不和预期值、第二来源对照；结构错了，后面的采样和 DFT 全白做。
- **负责人 10-16 决定：** 以流程为主，配少量检查脚本；输入以 .cdxml 和 SMILES 为主，图片只作对照、不生成坐标；只核验起始物、催化剂、试剂和产物（中间体放到闭环后半段）；先用 L1–L3 之一倒着走一遍检验，再以 BCB 作第一个真实试点。
- 资料：`skills-next/auto-g16-structures/scripts/prepare_preview.py`、`make_gaussian_input.py`（`read_molecule`、`validate_scope`）、`cdx_stereo.py`（`structure_stereo_invariants`）；`skills-next/auto-g16-study/SKILL.md` 第 0 步；`references/intake-template.md` 第 3 节；`references/discussion-record.md`；`references/literature-record.md`（T72 的检索覆盖记录、文献 TS 证据摘录表）；`skills-next/auto-g16-chemdraw-structures/SKILL.md`。

## 允许改动的路径

- 新增 `skills-next/auto-g16-structures/scripts/check_species.py`；从同目录模块 **import 复用**读取和立体识别，不复制实现，不改 `prepare_preview.py`、`make_gaussian_input.py`、`cdx_stereo.py` 的行为。
- `skills-next/auto-g16-structures/tests/test_structures.py`（或新增 `test_check_species.py`）和合成夹具。
- `skills-next/auto-g16-structures/SKILL.md`：加“开题物种核验”一节。
- `skills-next/auto-g16-study/SKILL.md`：只改第 0 步；“阶段决策”表中“结构未确认”一行可补链接。
- `skills-next/auto-g16-study/references/intake-template.md`：只改第 3 节（物种与结构）。
- `skills-next/auto-g16-study/references/discussion-record.md`：追加“结构确认”条目格式。
- `docs/redesign-tasks/T80-intake-structures.md`：本任务单。
- 不改 `ag/` 下任何文件；不改卡片（T81 在改）。

## 要做的

### 1. 物种清单（study 内 `analyses/intake/species.csv`，UTF-8，带表头）

| 列 | 必填 | 含义 |
|---|---|---|
| `species_id` | 是 | 与开题模板第 3 节一致 |
| `role` | 是 | reactant / product / catalyst / reagent / byproduct / additive |
| `source_file` | 是 | study 内的结构文件（.cdxml / .cdx / .mol / .sdf / .smi） |
| `second_source` | 否 | 第二来源：study 内文件，或 `smiles:` 开头的 SMILES 文本（例如 SI 或数据库给出的） |
| `expected_formula` | 是 | 人从原件读出的分子式（Hill 顺序，含电荷时另列） |
| `expected_charge` | 是 | 整数 |
| `multiplicity` | 是 | 来自研究者，不推断 |
| `expected_cip` | 否 | `原子序号:R;原子序号:S`，序号是 `source_file` 中**从 1 开始**的原子序号；`none` 表示应无立体中心；空表示未给 |
| `stereo_basis` | 否 | X-ray / 类比 / 文献 / 未知，及位置 |
| `note` | 否 | 备注 |

### 2. 反应式（可选，`analyses/intake/reaction.csv`）

列：`species_id, side（left/right）, coefficient`。核对两边元素计数和总电荷是否相等；不等时列出差额（例如“右侧少 1 个 B、2 个 O”），提示可能漏了副产物或未画出的组分。只报告，不自动补组分。

### 3. 核验内容（每个物种）

- 读入方式与 `prepare_preview.py` 相同（ChemDraw 直接读入，不经 MOL 往返）；超出 `validate_scope` 范围（自由基、金属、多组分等）时，该物种记为 `out_of_scope` 并说明，不中止其余物种。
- 实际值：规范同分异构 SMILES、分子式、总电荷、显式氢原子数、组分数、立体中心列表及 CIP（从 1 开始的原子序号）、未指定的立体中心、读入诊断。
- 对照：分子式、电荷与预期是否一致；每个预期 CIP 是否一致，有无未列出的立体中心；`second_source` 的规范 SMILES 与 `source_file` 是否相同（不同则逐项指出是构造、电荷还是立体不同）。
- 每项结果为 `match` / `mismatch` / `unknown`（缺预期值时），物种汇总为 `all_match` / `has_mismatch` / `incomplete` / `out_of_scope`。
- 输出 `analyses/intake/species-check.json` 和 `.md`，以及每个物种的 `preview.png`（放在 `analyses/intake/<species_id>/`）；所有输入文件记录 study 内相对路径和 SHA-256；输出已存在就拒绝（要求换名，保留旧报告）。
- **脚本不签字、不修改结构文件、不修改 study.md。**

### 4. study 技能第 0 步改为四小步（每步有关口）

- **0a 结构输入：** 用 ChemDraw 结构技能或人提供的 .cdxml / SMILES 建立每个物种的结构文件；图片只作对照，不从图片直接生成坐标。填写 `species.csv` 和（如适用）`reaction.csv`。
- **0b 自动核验：** 运行 `check_species.py`；有 `has_mismatch` 或 `incomplete` 时，先解决或由人明确接受并写明理由，不能跳过。
- **0c 人工确认结构：** 向负责人展示核验报告和预览图，按讨论记录的“结构确认”格式记录确认（报告相对路径和 SHA-256、确认日期、确认人、接受的未决项）。**确认之前不进入 0d，也不开始任何采样。**
- **0d 文献检索记录：** 以确认后的结构（规范 SMILES、名称）为检索对象，按 literature-record 填写检索覆盖记录；TS 相关文献填写文献 TS 证据摘录表。检索覆盖记录有空缺时，开题包不能定稿。
- 0d 之后接现有的讨论和开题包定稿流程（闭环后半段另开工单，本单不改）。

### 5. 模板

- 开题模板第 3 节：说明“核对结果”一列引用 `species-check` 报告中对应物种的汇总状态，不再手填核对结论；保留人工备注。
- 讨论记录：追加“结构确认”条目格式（对象、报告路径与 SHA-256、逐物种结论、接受的未决项、确认人和日期、原话出处）。

## 不允许

- 不从图片生成坐标；不自动修正结构以消除不一致；不推断多重度。
- 不自动签字，不改已签 study（包括 L1–L3）。
- 不改卡片和 `ag/` 代码；不新增里程碑（沿用现有结构里程碑和证据清单）。
- 测试只用合成小分子。

## 测试

- 合成物种：一个无立体中心、一个含两个立体中心（预期 CIP 一致）、一个 CIP 写反（报 mismatch）、一个分子式写错、一个电荷写错、一个第二来源立体不同、一个超出范围（含自由基或金属）。
- 反应式配平：平衡；缺副产物时报告差额。
- 原子序号从 1 开始的换算；输出已存在拒绝；符号链接拒绝；路径不出 study。
- 开发中只跑 skills-next 相关测试；推送前本地跑一次全量 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，之后以 CI 为准。敏感扫描与 `git diff --cached --check`。

## 真实环境验证（合并前，开发机，只读）

- 选 L1–L3 中的一个，把它的结构源文件**复制**到一个临时验证 study（不改原 study），按新流程走 0a–0b：写 `species.csv`（预期值取自原 study 已签的结构记录），运行 `check_species.py`。
- 在 PR 评论中报告：核验结果与原 study 已签结构记录是否一致；有不一致时逐项列出并判断是脚本问题还是原记录问题；走流程时发现的模板或步骤不顺之处。不写主机、路径和用户名。
- BCB 试点在合并后、负责人提供实验信息之后进行，不作为合并条件。

## 停止条件

- 需要改 `prepare_preview.py`、`make_gaussian_input.py`、`cdx_stereo.py` 的行为。
- 现有读入函数无法给出从 1 开始、可稳定对应源文件的原子序号。
- 需要改第 0 步以外的流程。

## 合并前审阅与交付

- 需要监督方审阅：是。
- PR 描述第一行：`Task: T80`；附倒走验证的结果。
- 合并只由负责人操作。
