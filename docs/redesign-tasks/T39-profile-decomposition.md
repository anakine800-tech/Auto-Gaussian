# T39：profile 的焓熵分项、σ 报告与动力学换算，以及 S1、S3 的卡片规则

## 分支与目标

- 分支：`codex/t39-profile-decomposition`；基于最新 main（T36a 合并后 rebase），一张任务单一个 PR。
- 目标：`ag profile` 只新增输出，不改变任何既有数值。新增内容如下：
  1. 每一步的 ΔH‡、−TΔS‡（正向、逆向）和 ΔH、−TΔS 分项，并标出分子数变化的步骤（缔合或解离）；
  2. 每一步正向、逆向的 Eyring 速率常数与半衰期；
  3. 可选的“竞争 TS 比较”：两个同组成 TS 物种的 ΔΔG‡、速率比和对应的 ee；
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
4. **竞争 TS 比较：** 定义文件新增可选字段 `competing_ts`，列表中每项为 `{"id": ..., "a": "<物种名>", "b": "<物种名>"}`。
   - a、b 必须都是 TS 物种（n_imag = 1），元素组成和电荷都相同；
   - 只出现在 `competing_ts` 里的物种，不算“未使用的物种定义”；
   - 输出 ΔΔG‡ = G(b) − G(a)（用修正后的系综 G）、速率比 exp(ΔΔG‡/RT)、对应 ee 的大小，以及哪个更快；
   - 另附两者“最低构象”的同口径对照值（只作敏感性参考）。
5. **σ 与对称处理报告：** 每个物种列出各构象的 σ 及其来源（Gaussian 输出或 GoodVibes 默认），以及 route 是否含 nosymm。出现下面任一情况就给出警告（不报错），并列出每个物种 RT ln σ 的数值：
   - 同一剖面内的物种有的用 nosymm、有的没用；
   - 同一物种的不同构象 σ 不同；
   - 任一 σ 大于 1。
6. **Markdown 输出：** 新增“焓熵分项”“动力学换算”“竞争 TS 比较”“对称数”四节，原有各节不变。schema 仍为 `ag-profile/1`，只新增键。
7. **thermo 卡片：**
   - 第 6 节加判据：σ 逐个结构核对（保留真实几何，C1 取 1，路径简并度另记）；同一比较内所有物种的对称处理一致；
   - 关键 ΔΔG 小于 1 kcal/mol 时，用 `ag thermo --s-cutoff/--h-cutoff` 报告 50、100、150 cm⁻¹ 三档结果；
   - 比较口径统一用系综 G，最低构象只作敏感性报告，不混用。
8. **profile 卡片：**
   - 分子数变化的步骤必须同时报告 ΔH‡ 与 −TΔS‡，并标注“受缔合熵模型影响”；不默认替换熵模型，GoodVibes freespace 只在其支持的溶剂下作为敏感性对照，并写明它是实验性功能；
   - 立体或区域选择性用 `competing_ts` 输出，速率比和 ee 只是简单 TST 下的表观值；存在可逆步骤或后续选择性捕获时，不能等同于实验 ee；
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
  - competing_ts：ΔΔG‡ = 1.13 kcal/mol 时，ee 约 74%；组成或电荷不同则拒绝；非 TS 物种则拒绝；
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

## 实施与离线验证（2026-10-15）

- 基于已含 T36a 的 main `00705b9`，分支 `codex/t39-profile-decomposition`。
- `species` 新增系综 H/S、修正后 S、最低构象 G 及逐构象 qh 值/权重/σ/来源/nosymm/RT ln σ；`states` 新增 `molecule_count`。
- `steps` 新增六个指定焓熵字段、`molecule_counts`、正反及反应分子数变化，`forward_kinetics` / `reverse_kinetics` 内含 `k_s-1`、`half_life_s`、自然对数和说明。
- 顶层新增 `competing_ts`（ΔΔG‡、a/b 速率比、ee 大小、快通道、最低构象对照）、`symmetry` 警告及三项模型说明。极端指数无法表示时返回 null 并保留自然对数，避免新增换算导致原自由能输出失败。
- schema 仍为 `ag-profile/1`。旧合成样例的完整输出快照递归核对全部旧字段，值精确相同；旧 Markdown 内容作为新报告的前缀逐字节一致。未修改 thermo 计算/输出或 facts。
- 测试文件：修改 `ag/tests/test_profile.py`；新增 `ag/tests/test_profile_decomposition.py` 和合成旧输出快照 `ag/tests/data/profile_legacy_output.json`。未使用研究数据。
- 定向验证 162 passed；全量 `PYTHONPATH=ag/src .venv/bin/python -m pytest ag/tests skills-next -q -rs`：1574 passed、2 skipped。跳过：Linux stat/ps 方言由 Linux CI 验证；私有本地日志未启用。
- 24 kcal/mol、298.15 K 得到半衰期 12.116692 h；1.13 kcal/mol 得到 ee 大小 74.141337%。profile 卡片 222 行，常见坑 6 条。
- 提交前敏感扫描及差异检查通过，作者/提交者 noreply 身份已本地核对。当前无开发阻塞；监督方审阅和负责人合并仍待完成。
- 未连接集群；L3 真实环境只读重跑留待合并后由负责人另行安排，不以离线测试替代科学验收。
