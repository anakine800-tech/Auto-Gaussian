# T39：profile 的焓熵分项、σ 报告与动力学换算，以及 S1、S3 的卡片规则

版本：2026-10-15 修订版。按 [PR #255 对 head `78d0e70` 的监督审阅](https://github.com/anakine800-tech/Auto-Gaussian/pull/255) 同步：以按产物分组的 `selectivity` 替换第一版两两 TS 比较，不保留两套接口。其余已通过部分保持原规格。

## 分支与目标

- 分支：`codex/t39-profile-decomposition`；基于最新 main（T36a 合并后 rebase），一张任务单一个 PR。
- 目标：`ag profile` 只新增输出，不改变任何既有数值。新增内容如下：
  1. 每一步的 ΔH‡、−TΔS‡（正向、逆向）和 ΔH、−TΔS 分项，并标出分子数变化的步骤（缔合或解离）；
  2. 每一步正向、逆向的 Eyring 速率常数与半衰期；
  3. 可选的产物选择性：汇总同一产物的全部 TS 通道，输出产物比例、有效能垒、产物两两 ΔΔG‡ 和比例、两产物有符号 ee、多产物 dr 及逐 TS 扰动；
  4. 每个物种的旋转对称数 σ 与对称处理报告，混用时给出警告和影响估算。

  同时在 thermo、profile 卡片里写明 S1（缔合熵）、S3（σ 与系综口径）、S9（低频截断敏感性）的判据。
- 资料：
  - `ag/src/ag/profile.py`：`step_table`（57–65 行）、`calculate_profile`（97–213 行）、markdown 输出；
  - `ag/src/ag/_profile_sources.py`：读 thermo 表与 Attempt 系综（172–237 行）；
  - `ag/src/ag/thermo.py`：行字段 `qh_H`、`qh_S`、`qh-G`（`qh_G`）、`rotational_symmetry_number` 及其来源（123–135、200–206 行）；
  - 2026-10-14 卡片审阅 S1、S3、S7、S9、F3；DOI 10.1021/ja5111392（与实验对照的必要性）。
- 防的事故：
  - L3 中端点与代表构象的 σ 不同，RT ln 3 ≈ 0.65 kcal/mol，量级与它的能垒（0.83 kcal/mol）相当，而当时没有任何输出提示。
  - 双分子步骤只给 ΔG‡，看不出缔合熵占多大比重，容易把受熵模型影响的能垒当成确定值。
  - 能垒与实验时间尺度、选择性的换算靠手算，容易出错。
  - 每个对映产物可能由多个立体通道汇入；只比较两个 TS 会漏计同一产物的其他贡献，算错产物比例和 ee。

## 允许改动的路径

- `ag/src/ag/profile.py`、`ag/src/ag/_profile_sources.py`：新增计算与输出。
- `ag/tests/` 中 profile 相关测试（新增或修改，PR 中列明）。
- `skills-next/auto-g16-recipes/cards/profile.md`、`skills-next/auto-g16-recipes/cards/thermo.md`。
- `README.md`：只改 profile 相关说明行。
- `docs/redesign-tasks/T39-profile-decomposition.md`：本任务单。

## 要做的

1. **系综 H 与 S：** 每个物种都用与系综 G 相同的权重计算：p_i ∝ d_i·exp(−G_i/RT)，G_i 是现有用于系综 G 的那一列。
   - H_ens = Σ p_i·H_i，H_i 用与 G_i 配对的 qh_H（含单点修正）；
   - S_ens = (H_ens − G_ens)/T，这样构象熵和简并度会自然包含在内；
   - 标准态修正和显式溶剂浓度修正全部记入 −TΔS 一项，并在输出里写明这一点；
   - 核对每一行的 qh_H − T·qh_S 与 qh_G 是否在 1e-6 Hartree 内一致，不一致就拒绝并指明是哪个 Attempt。
   - 用 `attempts` 直接给出系综的物种（不经 thermo 表），用 GoodVibes 结果中对应的 qh 字段，规则相同。
2. **每一步的分项：** 在现有 `steps` 每一项里新增字段：
   - `forward_dH_kcal`、`forward_minus_TdS_kcal`、`reverse_dH_kcal`、`reverse_minus_TdS_kcal`、`reaction_dH_kcal`、`reaction_minus_TdS_kcal`；
   - 每个状态的分子数（化学计量系数之和），以及 `molecularity_change`（TS 状态与反应物状态分子数之差）。

   现有字段名和数值保持不变。
3. **动力学换算：** 每一步新增正向、逆向的 `k_s-1` 和 `half_life_s`，用 k = (k_B·T/h)·exp(−ΔG‡/RT)，κ = 1，温度取 profile 的温度。
   - 分子数减少的步骤，在说明里写“按标准态浓度的准一级近似，受缔合熵模型影响”；
   - 1 M 下能垒低于 5 kcal/mol 的双分子步骤，写“接近扩散控制，不宜用 TST 速率解释”；
   - 所有换算结果都注明：没有隧穿校正，不是微观动力学模型。
4. **按产物分组的选择性：** 定义文件新增可选字段 `selectivity`，格式如下：

   ```json
   {"selectivity": [{"id": "products", "products": {
     "R": [{"species": "ts_r1"}, {"species": "ts_r2", "paths": 2}],
     "S": [{"species": "ts_s1"}, {"species": "ts_s2"}]
   }, "perturb_kcal": 1.0}]}
   ```

   - 列出的物种必须都是 TS（n_imag = 1），所有物种的元素组成和电荷都相同；只出现在这里的物种，不算“未使用的物种定义”。
   - 产物权重 w_p = Σ paths·exp(−G_TS/RT)，G 用 `corrected_G_kcal`。输出各产物比例、有效能垒（−RT ln w_p，相对最低者）、产物两两之间的 ΔΔG‡ 和比例；用稳定的对数权重计算。
   - paths 是正整数，可省略，默认 1；构象简并度已含在系综 G 中，与 paths 分开显示；省略 paths 时注明“默认 1”，不能重复计权。
   - 产物标签按定义文件顺序固定。恰好两个产物时，输出有符号 ee：第一个标签占优为正，并写明符号约定；多于两个产物时，输出比例分布和两两比值（dr）。
   - 给了非负有限 `perturb_kcal` 时，逐个把每个 TS 物种 G 加减该值（一次只改一个，该物种所有出现位置一起改变），报告各产物比例最小/最大值及占优产物是否翻转。区间包含基线，并列集合改变单独报告。
   - 另附只用每个 TS 物种最低构象的同口径结果，复用 `corrected_lowest_conformer_G_kcal`，保留 paths；只作敏感性参考。
   - 第一版 `competing_ts` 输入/输出移除，不与 `selectivity` 并存。
5. **σ 与对称处理报告：** 每个物种列出各构象的 σ 及其来源（Gaussian 输出或 GoodVibes 默认），以及 route 是否含 nosymm。出现下面任一情况就给出警告（不报错），并列出每个物种 RT ln σ 的数值：
   - 同一剖面内的物种有的用 nosymm、有的没用；
   - 同一物种的不同构象 σ 不同；
   - 任一 σ 大于 1。
6. **Markdown 输出：** 新增“焓熵分项”“动力学换算”“产物选择性”“对称数”四节，原有各节不变。schema 仍为 `ag-profile/1`，相对 main 只新增键。
7. **thermo 卡片：**
   - 第 6 节加判据：σ 逐个结构核对（保留真实几何，C1 取 1，路径简并度另记）；同一比较内所有物种的对称处理一致；
   - 关键 ΔΔG 小于 1 kcal/mol 时，用 `ag thermo --s-cutoff/--h-cutoff` 报告 50、100、150 cm⁻¹ 三档结果；
   - 比较口径统一用系综 G，最低构象只作敏感性报告，不混用。
8. **profile 卡片：**
   - 分子数变化的步骤必须同时报告 ΔH‡ 与 −TΔS‡，并标注“受缔合熵模型影响”；不默认替换熵模型，GoodVibes freespace 只在其支持的溶剂下作为敏感性对照，并写明它是实验性功能；
   - 立体或区域选择性用 `selectivity` 汇总产物通道，说明 paths/构象简并度、定义顺序和有符号 ee、逐 TS 扰动；比例和 ee 只是简单 TST 下的表观值，存在可逆步骤或后续选择性捕获时不能等同于实验 ee；
   - 读 σ 警告的方法；
   - 卡片不超过 285 行，“常见坑”不超过 10 条。超出时，把理由挪到参考文档。

## 不允许

- 不改变 `steps`、`states`、`species`、`energetic_span`、`sensitivity` 的任何既有数值与字段名。
- 不改 thermo 的计算与输出；不改 facts。
- 不把 σ 不一致改成报错；不自动替换熵模型。
- 不修改上述范围外文件；不连接集群；不使用研究数据做测试。

## 测试

- 回归：现有 profile 测试的全部既有字段与数值原样通过；用一个既有合成样例，比较新旧输出中旧字段完全相同。
- 新增（合成数据）：
  - 两构象物种：H_ens、S_ens 与手算一致，且 G_ens = H_ens − T·S_ens；
  - qh_H − T·qh_S 与 qh_G 不一致时拒绝；
  - 缔合步骤的 molecularity_change 与说明文字；
  - Eyring：ΔG‡ = 24 kcal/mol、298.15 K 时，半衰期约 12 h（与审阅文档的表一致，允许小于 2% 的误差）；
  - selectivity：两产物各一个 TS、ΔΔG‡ = 1.13 kcal/mol 时，ee 约 +74%；交换产物顺序后约 −74%；
  - 同一产物两个 TS 按通量相加，覆盖每个产物各有两个立体通道的合成样例；paths = 2 等价于 G 降低 RT ln 2，paths 与构象简并度不重复计权；
  - 三个产物：归一化比例分布和全部两两比值，不给 ee；逐 TS 扰动导致占优产物翻转，报告比例区间；
  - 组成或电荷不同、非 TS 物种都拒绝；旧接口不再接受；
  - σ 警告：nosymm 混用、σ 大于 1 时出现警告，并给出 RT ln σ 数值。
- 后端：`PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`；记录通过数和跳过原因。
- 暂存精确文件后运行敏感扫描与 `git diff --cached --check`，人工核对 PR 文本和 Git 身份。

## 真实环境验证

- 合并后由负责人另行安排：在计算机上对 L3 已有的 profile 定义只读重跑，核对旧字段不变、σ 警告出现在预期位置。结果写在 PR 评论里，不含主机信息。

## 停止条件

- 发现新增字段必须改动既有数值或字段名才能实现：停下说明。
- 前端读取 profile 时因新增键报错：停下，在 PR 中说明需要前端配合的改动。
- 要改范围外文件；同一问题修两次仍未解决。

## 合并前审阅与交付

- 需要监督方审阅：是（本地分析工具、卡片修改）。不涉及 remote、submit、cancel、status、fetch。
- 修改 AGENTS.md：无。
- PR 描述第一行：`Task: T39`；写新增字段清单、测试结果，并声明既有数值未变。
- 用 `gh pr view <编号> --comments` 读取评论，逐条处理并回复；冲突本地 rebase；合并只由人操作。
- 与 T36a 共用 `thermo.md`（不同行），T36a 先合并。

## 实施记录（2026-10-15 修订）

- 基于已含 T36a 的 main `00705b9`，分支 `codex/t39-profile-decomposition`。
- `species` 新增系综 H/S、修正后 S、最低构象 G 及逐构象 qh 值/权重/σ/来源/nosymm/RT ln σ；`states` 新增 `molecule_count`。
- `steps` 新增六个指定焓熵字段、`molecule_counts`、正反及反应分子数变化，`forward_kinetics` / `reverse_kinetics` 内含 `k_s-1`、`half_life_s`、自然对数和说明。
- 顶层新增 `selectivity`（产物比例、相对有效能垒、两两 ΔΔG‡/比例、两产物有符号 ee、逐 TS 敏感性、最低构象同口径对照）、`symmetry` 警告及模型说明。极端指数无法表示时返回 null 并保留自然对数，避免新增换算导致原自由能输出失败。
- schema 仍为 `ag-profile/1`。旧合成样例的完整输出快照递归核对全部旧字段，值精确相同；旧 Markdown 内容作为新报告的前缀逐字节一致。未修改 thermo 计算/输出或 facts。
- 测试文件：修改 `ag/tests/test_profile.py`；新增 `ag/tests/test_profile_decomposition.py` 和合成旧输出快照 `ag/tests/data/profile_legacy_output.json`。未使用研究数据。
- 修订版定向验证 178 passed；全量 `PYTHONPATH=ag/src .venv/bin/python -m pytest ag/tests skills-next -q -rs`：1590 passed、2 skipped。跳过：Linux stat/ps 方言由 Linux CI 验证；私有本地日志未启用。profile 卡片 233 行，常见坑 6 条。
- 24 kcal/mol、298.15 K 得到半衰期 12.116692 h；两产物各一个 TS 时，1.13 kcal/mol 得到有符号 ee +74.141337%，交换标签顺序后为 −74.141337%。
- 提交前敏感扫描及差异检查通过，作者/提交者 noreply 身份已本地核对。当前无开发阻塞；监督方审阅和负责人合并仍待完成。
- 未连接集群；L3 真实环境只读重跑留待合并后由负责人另行安排，不以离线测试替代科学验收。
