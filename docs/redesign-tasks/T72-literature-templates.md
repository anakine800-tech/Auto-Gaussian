# T72：文献记录补两张表；开题模板补通道表 CSV 说明

## 分支与目标

- 分支：`codex/t72-literature-templates`；基于最新 main，一张任务单一个 PR。**开发机做。** 纯文档。
- **目标：**
  1. `literature-record.md` 增加两张表：**检索覆盖记录**和**文献 TS 证据摘录表**；
  2. `intake-template.md` 的立体通道表一节补一句：计算阶段把通道表另存为 `ag channel-coverage`（T69）用的 CSV。
- **为什么：**
  - 检索覆盖记录：防止把“只看了前几页”“访问失败”写成“没有先例”，也方便接手者继续检索。
  - 文献 TS 证据摘录表：防止把论文里一句“进行了 IRC”当成某个 TS 已有双向端点证明。
- **负责人决定：** 这一轮只改模板，不回补研究 A 已有的文献记录。研究 B 开题时第一次使用。
- 资料：`skills-next/auto-g16-study/references/literature-record.md`、`intake-template.md`；v2.7 来源（只读提取）：`archive/skills/auto-g16-reaction-workflow/references/literature-evidence-design.md`（检索复查要求）、`archive/skills/auto-g16-reaction-literature/references/search-and-evidence-protocol.md`（文献版本处理、TS 与路径证据要求）。

## 允许改动的路径

- `skills-next/auto-g16-study/references/literature-record.md`：在现有表之后追加两张表和填写说明。
- `skills-next/auto-g16-study/references/intake-template.md`：只在第 5 节（立体通道表）末尾追加一段。
- `docs/redesign-tasks/T72-literature-templates.md`：本任务单。

## 要做的

1. **检索覆盖记录**（按检索批次一行）：检索批次｜检索式与提供方｜日期与过滤条件（年份、语言、文献类型）｜已审阅范围及末条位置｜纳入 / 排除理由｜人工去重决定与版本关系（预印本与正式版）｜访问限制及未覆盖部分。已有的检索式、日期、纳入排除理由列不重复，只补缺的部分。
2. **文献 TS 证据摘录表**（按每个文献 TS 一行，可选附表，TS 研究时使用）：

   | 项目 | 内容 |
   |---|---|
   | 文献与对象 | DOI、正文或 SI 位置、文献中的 TS 标签、对应基元步骤 |
   | 模型身份 | 组分、原子数、电荷 / 多重度、模型截断、构象及结合方式 |
   | 几何来源 | 坐标表或数据文件位置、原子顺序、关键原子对应；图示与坐标分开记录 |
   | 鞍点证据 | 报道的虚频、是否解释振动方向、是否给出完整频率信息 |
   | 路径证据 | 正向、反向**分别**是否完成，端点身份及出处 |
   | 能量口径 | 电子能 / H / G、数值与单位、参考态、温度、标准态 |
   | 适用性与缺项 | 用于背景、机理类比、初猜还是方法候选；未报告 / 未核实 / 冲突分别记录 |

   说明：论文只写“进行了 IRC”而没有给出两个方向的端点，记为“路径证据不完整”，不能当作双向验证。
3. **通道表 CSV 说明**（追加到 intake-template 第 5 节末尾）：计算阶段需要用 `ag channel-coverage` 时，把通道表另存为 `analyses/` 下的 CSV，列为 `channel_id, product_branch, ensemble_manifests, note`（多个清单用分号分隔），与 study.md 中的通道表保持一致；以 study.md 为准。
4. 示例一律用虚构的通用小分子，不出现研究 A、研究 B 或其他未发表课题的内容。在文件里注明“改编自 archive/…”。

## 不允许

- 不改代码、卡片和其他模板节；不恢复 v2.7 的审批流程、schema 合同或旧命令。
- 不写未发表研究内容、本机路径、用户名。

## 测试

- `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`（`test_skill_format.py` 会检查链接和私有路径）。
- 敏感扫描与 `git diff --cached --check`。

## 真实环境验证

- 不需要。研究 B 开题时实际使用。

## 停止条件

- 需要改 intake-template 第 5 节以外的内容。
- 归档内容与现行规则冲突，不确定以哪个为准。

## 合并前审阅与交付

- 需要监督方审阅：是。
- PR 描述第一行：`Task: T72`。
- 合并只由负责人操作。

## 版本记录

- T116 脱敏：研究标识、编号与环境字面量改为泛称；原工单结构和结论不变。
