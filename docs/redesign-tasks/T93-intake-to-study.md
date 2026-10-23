# T93：开题闭环后半段——开题包完整性检查 → study.md 骨架 → 第一批 Attempt 准备（不提交）

## 分支与目标

- 分支：`codex/t93-intake-to-study`；基于最新 main（含 T80），一张任务单一个 PR。**开发机做。**
- **开工条件：** T89–T92 中任意一张合并后开工（本轮放宽为四条线，本单是第五项）。
- **目标：** 接上 T80 的前半段（结构输入 → 核验 → 签字 → 文献检索），把“讨论 → 方案定稿 → 开始计算”串起来：
  1. 新增检查脚本 `check_intake.py`：检查开题包各节是否填完、关键签字是否在、引用的报告是否存在且哈希一致；
  2. 检查全部通过后，生成 study.md **骨架**和通道表 CSV **草稿**，交负责人签字；
  3. study 技能第 0 步之后增加 0e–0g 三小步，终点是“第一批 Attempt 已准备、确认摘要已生成”，**不提交**。
- **负责人 10-17 决定：** 以流程为主，配一个汇总检查脚本；停在准备好第一批 Attempt，提交仍由负责人说“提交”并亲手点击。
- 资料：`skills-next/auto-g16-study/SKILL.md`（第 0 步 0a–0d、第 3 步计算方案与机理假设、第 7 步证据清单与签字）、`references/intake-template.md`（全部各节）、`references/study-md-template.md`、`references/discussion-record.md`（含 T80 的“结构确认”格式）、`references/literature-record.md`（T72 两张表）、`skills-next/auto-g16-structures/scripts/check_species.py`（T80，读写与哈希写法）、`docs/ag-channel-coverage-1.md`。

## 允许改动的路径

- 新增 `skills-next/auto-g16-study/scripts/check_intake.py` 及 `skills-next/auto-g16-study/tests/`（或放入 `skills-next/tests/`，与现有测试组织一致）和合成夹具。
- `skills-next/auto-g16-study/SKILL.md`：第 0 步追加 0e–0g，其余步骤不改。
- `skills-next/auto-g16-study/references/intake-template.md`：只在需要明确“哪一节填完的判定标准”时补一句说明，不改各节结构。
- `skills-next/auto-g16-study/references/study-md-template.md`：只在需要“由开题包生成”的占位说明处补注释。
- `docs/redesign-tasks/T93-intake-to-study.md`：本任务单。
- 不改 `ag/` 下任何文件；不改卡片。

## 要做的

### 1. `check_intake.py`

```
python check_intake.py --study <study> [--intake <开题包 md，默认 study 内约定位置>] --report <analyses/intake/ 下新的 .json>
```

逐项检查并输出 `missing` / `present` / `mismatch`：

- 开题包第 1–9 节：每节存在；表格中不残留模板占位（例如 `<填写>`、`<逐物种核对>`）；“首轮做什么 / 首轮不做什么”已填。
- 结构：`analyses/intake/species-check.json` 存在；讨论记录中有“结构确认”条目，引用的报告路径与 SHA-256 与实际文件一致；报告中没有未被接受的 `has_mismatch` / `incomplete`（被接受的须在确认条目中列出）。
- 文献：文献记录中“检索覆盖记录”表存在且非空；方法依据（第 7 节）每一层都有依据类别。
- 讨论：讨论记录有定稿条目（“会话转述与定稿”）。
- 通道：第 5 节立体通道表至少一行，列齐全。
- 只检查、不改写任何文件；不判断科学内容是否正确。

### 2. 生成 study.md 骨架和通道表草稿（仅在第 1 步全部 `present` 时）

```
python check_intake.py ... --draft
```

- `study.md.draft`：按 study-md-template 的结构生成；“体系”“计算方案”“机理假设”等节填入指向开题包对应小节的链接和关键摘要（物种表、方法表直接引用，不改写数值）；“里程碑签字”节列出待签项（计算方案、机理假设）；不生成任何签字内容。
- `channels.csv.draft`：从开题包第 5 节解析，列 `channel_id`、`product_branch`、`ensemble_manifests`（留空，注明“采样后填写”）、`note`；表头不符合预期时报错，不猜。
- 两个草稿写在 `analyses/intake/` 下，已存在就拒绝；**不覆盖已有 study.md**（如果 study.md 已存在，只生成草稿，由人合并）。

### 3. study 技能第 0 步新增三小步

- **0e 检查开题包：** 运行 `check_intake.py`；有 `missing` / `mismatch` 时补齐，不能跳过。
- **0f 方案定稿与签字：** 生成草稿 → 人审阅后写入 study.md → 按第 7 步生成证据清单 → 负责人签计算方案和机理假设（沿用现有里程碑，不新增）。
- **0g 准备第一批 Attempt：** 按开题包第 9 节“首轮做什么”，用 `ag prepare` 准备第一批 Attempt，生成确认摘要并展示；**到此为止，不提交**，等负责人说“提交”并亲手点击。

## 不允许

- 不自动签字，不覆盖 study.md，不提交作业，不判断科学内容。
- 不新增里程碑；不改第 0 步以外的流程。
- 测试只用虚构的合成开题包。

## 测试

- 完整的合成开题包 → 全部 `present`，草稿生成正确（通道表 CSV 列与 `ag channel-coverage` 一致，`ensemble_manifests` 留空）。
- 逐项缺失：残留占位、缺结构确认、确认条目哈希不符、species-check 有未接受的 mismatch、缺检索覆盖记录、缺定稿条目、通道表缺列 → 对应 `missing` / `mismatch`。
- study.md 已存在时不覆盖；草稿已存在时拒绝；符号链接、越界拒绝。
- 开发中只跑相关测试；推送前本地跑一次全量 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，之后以 CI 为准。敏感扫描与 `git diff --cached --check`。

## 真实环境验证

- 纯本地。合并前用 T80 倒走验证时的临时 study（L1 复制品）补齐开题包，走一遍 0e–0g（0g 只准备、不提交），结果写进 PR。
- 研究 B 开题时作为第一个真实试点（不作为合并条件）。

## 停止条件

- 开题包的某些节无法用确定规则判断“是否填完”（列出后停下，由监督方定规则）。
- 需要改第 0 步以外的流程或 `ag/` 代码。

## 合并前审阅与交付

- 需要监督方审阅：是。
- PR 描述第一行：`Task: T93`。
- 合并只由负责人操作。

## 版本记录

- T116 脱敏：研究标识、编号与环境字面量改为泛称；原工单结构和结论不变。
