# T135：profile 选择性三数报告（最低 TS / 系综 / 差值）

版本：v1（监督方，2026-10-26）。**开发机做。** 后端出一个 PR，PR 描述第一行写 `Task: T135`。

## 分支与目标

- 分支：`codex/t135-profile-three-numbers`。
- **开工条件：** 以后端 main（不早于 `1e1d66b`）为基线；T135 编号未被占用。可以与 T131 并行（两单不改同一文件）。
- **目标：** 选择性结果同时报告“只用最低 TS 的 ΔΔG‡”“系综 ΔΔG‡”和两者之差，让构象采样对结论的影响一眼可见（规格 T-X 第 2 条）。审计第 10 节已确认，现有 `lowest_conformer` 并不是“每个产物只取一个最低 TS”：它对每个 TS species 各取最低构象后，仍然按多个通道和 paths 求和。所以本单**另加字段**，不改它。
- **负责人决定（10-24 Q2；10-26）：**
  - Q2 每个产物分支只取**一个**结构：在该分支所有 TS species 的全部构象中，取经标准态和浓度修正后自由能最低的那一个；**保留它所在通道的真实 `paths`**；不对构象求和，**也不乘构象简并度 `degeneracy`**（简并度属于系综概念），但要把它的值一并报告。
  - 报告这个结构属于哪个 species、哪个 Attempt，以及它的修正后自由能。
  - 现有 `corrected_G_kcal`（系综）与 `lowest_conformer` 两套结果的字段和含义一律不变。
- **资料：** `ag/src/ag/profile.py`（`selectivity_definitions` 130、`selectivity_distribution` 167、`selectivity_results` 194、`markdown` 443 起）；`ag/src/ag/_profile_sources.py:load_species`（构象的 `qh_G_hartree`、`degeneracy`）；`ag/tests/test_profile_decomposition.py`；`docs/research/ts-guess-audit.md` 第 10 节；Laplaza 等，*J. Phys. Chem. Lett.* 2024, 15, 7363–7370（DOI 10.1021/acs.jpclett.4c01657）。
- **新增字段防的事故：** 只报系综数值时，看不出结论有多大程度取决于构象采样；把现有 `lowest_conformer` 误当成单最低 TS 来解读（审计第 10 节）。

## 允许改动的路径

- `ag/src/ag/profile.py`：`selectivity_results` 中新增计算；`markdown` 中新增一张表。
- 测试：`ag/tests/test_profile_decomposition.py` 中受影响的用例（PR 中列出）；新建 `ag/tests/test_profile_three_numbers.py`。夹具全部合成。
- 文档：`README.md` 的 profile 一节加几句说明；本单 `docs/redesign-tasks/T135-profile-three-numbers.md`、`docs/redesign-tasks/open-tasks.txt`。
- **不改** `_profile_sources.py`、`thermo.py`、`ensemble.py`、`dedup.py`、卡片（profile 卡的口径在 T139 修订）、前端、`CHANGELOG.md`、版本号。

## 要做的

1. **逐构象修正后自由能**：每个构象的修正后自由能 = `qh_G_hartree × HARTREE_TO_KCAL + 该 species 的 standard_state_correction_kcal + concentration_correction_kcal`，与 species 级的修正完全同一口径。只能有一份修正计算，复用现有的变量，不重复写公式。
2. **每个产物分支的最低 TS**：
   - 在该分支所有通道（species）的全部构象中，取修正后自由能最低者；
   - 并列（差值 ≤ 1e-9 kcal/mol）时，按定义里通道出现的顺序、再按 Attempt ID 取第一个，并在 `ties` 里列出所有并列项。
   - 该分支的“单结构权重”为 `ln(paths) − G/RT`，`paths` 取这个结构所在通道的值。
3. **三数**：对 `selectivity_distribution` 已有的每一对产物 (a, b)，在新字段里输出：
   - `lowest_ts_ddG_kcal`：只用两个分支各自的最低 TS（含 paths）算出的 ΔΔG‡，符号约定与现有 `pairwise[].ddG_barrier_kcal` 相同；
   - `ensemble_ddG_kcal`：直接取现有系综结果的同一对数值（不重算）；
   - `difference_kcal = ensemble_ddG_kcal − lowest_ts_ddG_kcal`。
   - 两个产物时，另给出只用最低 TS 的 `ee_percent`，符号约定与现有一致。
4. **输出字段**：每个 selectivity 结果新增 `lowest_ts`：

```
lowest_ts:
  definition: 固定说明文字（每个产物分支取修正后自由能最低的单个 TS 结构；保留其通道 paths；不对构象求和；不乘构象简并度）
  branches: {<产物>: {species, attempt_id, corrected_G_kcal, paths, conformer_degeneracy, ties: [{species, attempt_id}]}}
  pairwise: [{a, b, lowest_ts_ddG_kcal, ensemble_ddG_kcal, difference_kcal, ratio_a_over_b}]
  ee_percent / ee_sign_convention（仅两个产物时）
```

   `ag-profile/1` 只做加法；原有字段和数值逐字节不变。
5. **Markdown**：选择性一节新增一张表“最低 TS / 系综 / 差值”，每对产物一行，列出三个数和各分支最低 TS 的 species 与 Attempt；并在表下写明：单结构结果和系综结果不是同一个物理量，“差值大”说明结论对构象采样敏感，不代表哪个更正确。
6. **README**：profile 一节加一段，说明三数的定义、与 `lowest_conformer` 的区别，以及 paths 和构象简并度的处理方式。

## 不允许

- 不改现有 `corrected_G_kcal`、`lowest_conformer`、`pairwise`、`ee_percent`、`sensitivity` 的计算和含义。
- 不对构象做去重、不判断两个构象是否同一驻点（审计第 2 节，属另外的范围）；不把采样次数当简并度。
- 不新增自动判断或阈值（例如“差值超过 x 就警告”）。

## 测试

| 场景 | 预期 |
|---|---|
| 两产物、各一个 species、各一个构象 | 三数中前两个相等，差值为 0 |
| 两产物、各一个 species、多个构象 | 最低 TS 取各自最低构象；系综值与现有一致；差值与手算一致（容差 1e-9） |
| 一个产物分支含两个 species（不同通道），且最低者在第二个 species | 取整个分支最低，并记录正确的 species 和 Attempt |
| 最低者所在通道 `paths = 2` | 单结构权重含 ln2；系综结果不变 |
| 最低构象 `degeneracy = 2` | 单结构不乘 2；`conformer_degeneracy` 报告为 2 |
| 两个构象并列最低 | 按定义规则选取，`ties` 列出两者 |
| 三个产物 | 每对一行，符号约定与现有 pairwise 一致 |
| 标准态 1 M 与 1 atm；带浓度修正的 species | 逐构象修正与 species 级同口径（与手算一致） |
| 现有全部 profile 用例 | 原字段逐字节不变（对比 main 的输出 JSON） |
| Markdown | 新表出现，旧表不变 |

推送前本地跑一次全量 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，之后以 CI 为准；运行 `python scripts/scan_public.py`（带本机词表）和 `git diff --cached --check`。

## 真实环境验证

- 不需要：纯本地计算，没有远程或证据写入。
- 可选：在开发机用已有的非研究、已签字的小分子示例（若存在）跑一次 profile，确认新表能生成；不碰研究 study。

## 停止条件

- 需要改 `_profile_sources.py` 或 thermo 的计算才能拿到逐构象数值。
- 原有输出无法保持逐字节不变。
- 同一问题修两次仍未解决。

## 合并前审阅与交付

- 需要监督方审阅：**是，逐行审**（科学数值换算）。合并只由负责人操作。
- PR 描述包括：Q2 的实现说明、新字段对照、测试表逐项结果、一份合成示例的 Markdown 新表截取。
- 用 `gh pr view <编号> --comments` 读取审阅评论，逐条处理并回复。

## 版本记录

- v1（2026-10-26，监督方）：依据 10-24 Q2 与 10-26 补充决定起草；对应审计拆单建议中 T-X 的代码项。

## 执行记录（2026-10-26）

- 基线：`main` 的 `1e1d66b`；开工核对未发现其他 T135 工单、分支或 PR。
- 实现：只在 `selectivity_results` 追加 `lowest_ts`，复用已算出的两项 species 修正；每分支先按修正后的单构象 G 选取，再保留所选通道 paths。简并度只报告，不进入单结构权重。原系综数值直接取已有同对产物结果。
- 并列规则：与实际最小值相差不超过 1e-9 kcal/mol 的候选按通道定义顺序、Attempt ID 排序；`ties` 包含全部并列项，无并列时为空。
- 浓度边界：现有公共输入仅允许极小点 species 设置显式溶剂浓度，规则保持不变；合成测试核对带浓度修正的完整剖面，并对内存中的预计算修正量单独验证最低 TS 选择。
- 新增 `test_profile_three_numbers.py` 的 18 个参数化用例；`test_profile_decomposition.py` 无需修改，既有断言全部保留。
- 相关验证：四个 profile 测试文件合计 **168 passed**。临时差分检查器在同一进程加载 `1e1d66b` 的原始 profile 模块；62 次成功计算移除新增 `lowest_ts` 后，按 CLI JSON 序列化逐字节相同；16 次 Markdown 去除新增小节后逐字节相同。检查覆盖既有全部 profile 用例及新增用例。
- 全量验证：`PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs` → **4922 passed, 19 skipped**（18 项 Linux 方言检查交 CI，1 项私有日志默认不启用）。另有 1 条沙箱不能创建 pytest 缓存的提示，不影响测试执行结果。
- 敏感信息：全量与暂存区扫描均带本机私有词表，零命中；`git diff --cached --check` 通过，提交身份为 GitHub noreply。
- 当前阻塞：科学审阅，待监督方对数值换算逐行审阅；合并由负责人操作。纯本地计算无需真实集群验证，未操作研究 study。
