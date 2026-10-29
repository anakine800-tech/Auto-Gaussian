# qRRHO 热化学与构象布居

## 要点

- 只汇总同一主族闭壳层单分子的已接受极小点；不同物种、反应计量或自旋面不合并为一个构象布居表。（[见第 1 节](#1-适用范围)）
- 先有合格 Opt+Freq review，统一方法、溶剂、温度和标准态；最终几何重新去重，集合改变须请人重新确认对应里程碑。（[见第 2 节](#2-前置条件)）
- 跨物种能量比较分别汇总后用 `ensemble_G`；`weighted_mean_G` 不能替代系综自由能，最低构象只作敏感性报告。（[见第 3 节](#3-输入模板)）
- 核对 SP/Freq 配对证据、修正分项与简并度；有限集合布居不宣称完整平衡布居，最终结果须生成证据清单后请人签字。（[见第 6 节](#6-结果判据清单)）

## 1. 适用范围

同一主族闭壳层单分子的已接受极小点集合，比较相对自由能和 Boltzmann 布居。不同物种、反应计量或不同自旋面不合并成一个构象布居表。

## 2. 前置条件

参与构象均有合格 Opt+Freq review（含零虚频及完整频率）；方法、溶剂、温度、标准态一致。对 DFT 最终几何再次 `ag dedup` / `ag cluster`，更新代表与简并度；若集合改变，请人重新确认对应里程碑。需要单点时，所有代表的单点已完成并与父频率作业一一配对。

## 3. 输入模板

运行 `ag thermo <id>...`，输入为所选代表的 Attempt。参数值按 D21 及仓库所有者 2026-10-13 确认的设置：**GoodVibes 4.3.0、Grimme 准谐振子熵修正 + Head-Gordon 准谐振子焓修正，两个截断频率均为 100 cm⁻¹、温度 298.15 K、浓度 1 mol/L**。从当前命令帮助确认设置方式及默认值，核对并保存实际报告的两种修正及各自截断频率；不杜撰诸如温度、简并度或单点配对的选项名。工具不能表达所需设置时，列出缺口并停下，不以手写结果冒充 `ag thermo` 输出。

简并度从最终 `ag cluster` 输出逐项抄写到代表表，保留构象、簇、简并度和来源对应关系。工具输出若只是样本成员数，不能直接当物理简并度；请人说明等价性依据并确认其用途。不要把已经逐个列出的 gauche 等价极小点又乘一次简并度。

非手性分子（如正丁烷）使用 `ag cluster --mirror` 合并镜像构象：anti 的简并度为 1，两个 gauche 合并为一个代表、简并度为 2；gauche 只需一个 Opt+Freq，热化学中对该代表计入权重 2。保留初筛聚类的镜像成员对应关系，不能因为最终只计算了一个代表就丢掉其简并度，也不能再另列其镜像重复计权。手性分子不要使用 `--mirror`。

无 SP 时用频率层级 qRRHO G；复合方案为 `E_SP + (G_qRRHO,low − E_elec,low)`，核实工具的配对和标准态处理避免重复修正。SP 输入必须保留频率最终几何的元素与原子顺序；工具按全部原子的固定行号做 Kabsch 对齐（仅旋转、平移），要求 RMSD ≤ 1e-3 Å，不进行原子重排或镜像反射。布居满足 `p_i = d_i exp(−ΔG_i/RT) / Σ_j d_j exp(−ΔG_j/RT)`，G 与 RT 必须使用一致单位。

计算反应能、能垒等需要比较不同物种时，分别汇总各物种的构象集合，统一使用 `ag thermo` 输出的 **`ensemble_G`（构象系综自由能）** 按相应化学计量比较。`weighted_mean_G` 只描述构象分布，不能替代 `ensemble_G`。最低构象只作敏感性报告，在 `study.md` 记录构象与比较口径，不与系综 G 混用。

反应自由能剖面、能垒和通道选择性转 [profile](profile.md)（R13/R14）；
本卡只汇总同一物种极小点。研究温度须与实验对齐，不能不加说明地沿用
298.15 K；先核对当前工具支持所需设置，再报告结果。

输出的 `H/S/G` 为单点替换后的 RRHO，`qh_H/qh_S/qh_G` 为同温度、同浓度的 qRRHO；`frequency_rrho` 保留未替换电子能的原始 RRHO H/S/G。能量单位为 Hartree，熵为 Hartree/K。
审计分解为 `qh_G = frequency_rrho_G_1atm + spc_correction + low_frequency_correction + standard_state_correction + concentration_correction`。
低频修正为 qRRHO G − RRHO G；标准态修正为 `RT ln(RT × 1 mol/L / 1 atm)`，已包含在所报 G 中，不能再次相加。非 1 M 时，另列从 1 M 到指定浓度的 `RT ln(c / 1 mol/L)`。
每行的构象简并度 `degeneracy`（d_i）与旋转对称数 `rotational_symmetry_number`（σ_i）分别记录来源；后者为 GoodVibes 实际采用的日志值，缺失时明确标为默认 1。默认值不等于已审阅的物理对称数。反应路径数须在机理说明中另行记录，不作为这里的 d_i 或 σ_i。

SMD 下 H/S 分项只是当前 RRHO/qRRHO 与单点替换模型的审计分项，
不能解释为实验溶液的焓熵分解；连续介质溶剂化自由能没有在此独立拆成
溶剂化焓与熵。仅改变热化学温度会重算分子热修正和相应标准态项，
不等于包含溶剂化自由能的温度依赖；温度效应结论须说明固定溶剂模型的近似。
布居只代表所选集合内归一化结果。构象互变相对实验/反应时间尺度很慢时，
按可快速互变的盆地分别处理，盆地间权重需初始条件或动力学依据，
不能把所有构象直接汇成一个全局平衡布居。
频率和 ZPE 缩放均为 1.0；100 cm⁻¹ 为两种低频修正的项目约定，
[依据与局限](../../auto-g16-study/references/acceptance-methods.md#数值设置与热化学依据)须随结果记录。

## 4. 资源建议

本地解析，研究最多 20 个、验收最多 10 个代表通常无需集群资源；没有 PBS walltime 和提交对话框。输出写到 study 的 `analyses/`，记录程序版本、设置和输入集合。

## 5. 提交前检查清单

- 本任务不提交；确认完整日志已取回、输入属于同一物种和同一方法层级，不含失败或重复极小点。
- 温度、标准态、低频方案、简并度明确；气相验收采用统一 1 mol/L 比较约定时写清楚，不能暗示用了溶剂模型。
- SP 与 Opt+Freq 几何正确配对，标准态修正只计一次；缺参数 / 版本 / 简并度支持就停下报告。

## 6. 结果判据清单

- 准入仍要求 `freq_step_converged=true`；`freq_step_review=manual_review` 时按 `freq_step_gaussian_stationary` 的依据和行号人工判定，thermo 不自动接受。默认阈值通过而 `freq_step_converged_tight=false` 时工具照常计算并警告；若父优化为 Opt=Tight，须人工决定是否接受，不把计算成功当签字。旧 facts 与已签判定不自动改写，负责人逐 study 决定是否先外部 dry-run 再 reparse。
- 工具成功并报告要求的版本及设置；所有代表具有有限的能量、修正和布居，没有静默漏掉失败记录。
- 工具运行成功不代表配对正确，要以输出里的 `pairing_evidence` 为准：核对 SP 输入与频率最终几何的 SHA-256、固定行号 Kabsch RMSD 及来源 Attempt；无 SPC 时此项为 null，不能当作已验证的配对。
- 同温度、同浓度的原始 RRHO 与最终 qRRHO H/S/G 分清，核对单点替换、低频和标准态分解，以及每个代表的 d_i、实际 σ_i 和来源。< 50 cm⁻¹ 的频率结合 opt-freq 审阅，不用 qRRHO 掩盖虚频。
- 明确 SMD H/S 的模型解释边界及温度变化未包含的溶剂化项；慢互变构象按盆地报告，不以归一化代替平衡证据。
- 相对能量零点明确，单位换算明确；布居均非负且总和在数值舍入误差内为 1（百分数为 100%）。
- 将输出表写入 `study.md`：`代表/盆地 | Attempt | d_i 及来源 | σ_i 及来源 | 反应路径数（另记，不适用则注明） | qRRHO G (Hartree) | ΔG (kcal/mol) | 集合内布居 (%)`；复合方案另列 E_SP 与低层级修正。
- **S3（σ 与系综口径）**：逐个结构核对 σ，保留真实几何，C1 取 1；默认 1 不等于已确认。所有比较物种的对称处理一致，路径简并度另记，不重复计入构象 d_i 或 σ。跨物种比较统一用 `ensemble_G`、单位及化学计量，最低构象只作敏感性报告，不混用，不使用 `weighted_mean_G` 替代。
- **S9（低频截断敏感性）**：关键 ΔΔG < 1 kcal/mol（按绝对值）时，用 `ag thermo --s-cutoff <cm1> --h-cutoff <cm1>` 报告 50、100、150 cm⁻¹ 三档结果（每档两截断同值），比较组各物种同步重算；TS 用 profile 的 `thermo_settings` 同步设置两截断。保留三个独立输出和排序变化，不挑选最符合预期的一档。
- **S1（缔合熵）**：分子数变化的反应转 profile 同时报告 ΔH‡、−TΔS‡ 并标注“受缔合熵模型影响”；标准态与显式溶剂浓度修正计入熵项，不默认替换熵模型。
- 报告构象与分组定义，再给 ΔG 和布居（示例（L1 正丁烷流程验收）：报告 anti / gauche 的构象与分组定义、ΔG 和布居）。只计算有限集合时明确为该集合内归一化结果，不宣称完整平衡布居；达到目标后先运行 `ag review manifest --study <dir>` 生成证据清单，再请求人签最终结果，并记录清单路径及 SHA-256。

## 7. 常见失败与处理

解析或设置缺失时保存报告并核实本地完整输出；有虚频、方法混用或缺 SP 时不能纳入表中。需要补算就提出新 Attempt，按 [Study 流程](../../auto-g16-study/SKILL.md)及 [AGENTS 自主运行规则](../../../AGENTS.md#自主运行)区分模式取得授权。仅本地分析问题先说明修正方案和受影响结果，不消耗远程作业。

工具拒绝频率阶段未明确收敛、振动模式不完整、集合组成/电荷/多重度不一致、部分构象缺 SP、同层方法/版本或显式 5D/6D、7F/10F 不同，以及非 SCF 最终能量方法（名单见 ag/README.md）；旧 facts 缺频率字段时提示 `ag facts <attempt> --refresh`，不自动改写。单原子只豁免模式完整性并注明；积分网格差异仅展示和警告。分子式相同不等于同一物种，构象身份仍须人审阅。

## 8. 常见坑

本节历史来源链接固定到 `v3-frozen`，仅用于追溯经验出处；现行执行以本卡为准，不沿用冻结文档中的流程。

知识衔接：[GKB-0512：自由能与标准态](../../auto-g16-gaussian-learning-library/references/advanced-properties.md)。

- 力场 / xTB 排序不是最终 Gibbs 布居；必须在同一化学身份与方法栈内比较。来源：[scientific-workflows.md（v3-frozen）](https://github.com/anakine800-tech/Auto-Gaussian/blob/v3-frozen/skills/auto-g16-rtwin-pbs/references/scientific-workflows.md)、[conformer-workflow.md（v3-frozen）](https://github.com/anakine800-tech/Auto-Gaussian/blob/v3-frozen/skills/auto-g16-view-rt-win/references/conformer-workflow.md)。
- 标准态修正按独立物种计数，不能对整个反应只加一次；各物种的构象集合分别汇总，再比较系综自由能。来源：[scientific-workflows.md（v3-frozen）](https://github.com/anakine800-tech/Auto-Gaussian/blob/v3-frozen/skills/auto-g16-rtwin-pbs/references/scientific-workflows.md)。
- 旧文档要求另议低频处理，新方案已选定 D21 qRRHO；保留“报告低频”的经验，不沿用其未选定处理的旧流程。来源：[scientific-workflows.md（v3-frozen）](https://github.com/anakine800-tech/Auto-Gaussian/blob/v3-frozen/skills/auto-g16-rtwin-pbs/references/scientific-workflows.md)。
- SMD 下的 H/S 分项不能当成实验溶液中的焓熵分解；这里只是同一热化学模型下的审计分项。

### S8：标准态账目与离子适用性

改编自 [scientific-workflows.md（v3-frozen）](https://github.com/anakine800-tech/Auto-Gaussian/blob/v3-frozen/skills/auto-g16-rtwin-pbs/references/scientific-workflows.md)
的逐物种标准态记账，以及
[thermochemistry-readiness-contract.md（v3-frozen）](https://github.com/anakine800-tech/Auto-Gaussian/blob/v3-frozen/skills/auto-g16-reaction-workflow/references/thermochemistry-readiness-contract.md)
的温度、溶剂、数量类型与单点配对信息要求；不沿用旧合同或“不能比较”的历史状态。
SMD 各项及电子能替换见 [sp 的 S8](sp.md#s8smd-能量项与复合自由能)。

对源于 1 atm 理想气体分子热化学、尚未换算的每个独立物种，
`ΔG°_1atm→1M = RT ln(R_gas T c°/p°)`；
`R_gas = 0.082057366080960 L·atm·mol⁻¹·K⁻¹`、`c° = 1 mol/L`、`p° = 1 atm`。
298.15 K 下为 +1.894328 kcal/mol（公式复算值），反应/能垒的贡献按计量求和：
两个分离物种形成一个 TS/复合物时为 −1.894328 kcal/mol，等分子数变化时抵消。
同一物种多个构象的共同修正只平移其系综 G，不改变集合内布居。

| 来源 | 1 atm→1 M 是否再加 | 审计记录 |
|---|---|---|
| Gaussian 原始 1 atm RRHO 或尚未浓度换算的气相热修正，与 SMD 单点组合 | 需要逐物种转换一次 | 原始热修正、SMD 单点、低频项、标准态项分别列出 |
| 本项目 GoodVibes 4.3.0 的 1 M `qh_G`，或已正确生成的 1 M 复合 G / `ensemble_G` | 不再加 | 核对输出浓度、`standard_state_correction` 和组成公式；保留已包含项 |
| 外部溶剂化自由能或外部 G | 先核实其定义，不能直接决定 | 若定义为气相 1 atm→溶液 1 M，标准态转换已在其中；若为同浓度气→液，则尚不替代分子热化学转换；定义不明写待核实 |

原 SMD 模型采用相同浓度的气液标准态定义；出版商原文
[DOI:10.1021/jp810292n，§3 标准态、§6 离子结果讨论](https://pubs.acs.org/jpcbfk/article/113/18/6378/1427431/Universal-Solvation-Model-Based-on-Solute-Electron)。
不要在已有溶液 SMD 总能量上再叠加外部 ΔG_solv。1 M 标准态也不等于实验
实际浓度；后者是有依据时另列的活度/化学势项，未知则不加。

离子与电荷分离体系通常更受空腔、局域溶剂化、反离子及离子配对模型影响；
不能把中性分子的模型表现外推到这些体系，也不能把整体电中性等同于没有局域电荷。
SMD 原文的离子基准误差大于中性组的典型误差，但不把其总体统计量当作
本体系误差条；此处不摘取具体误差数值。结论应限定为“在所用连续介质、
电荷/离子配对及有限构象模型下的趋势，绝对能垒与近简并排序仍有溶剂模型不确定性”。
必要时提出反离子、显式溶剂或模型敏感性研究；未计算的项明确未验证。

比较时继续使用分离物种各自的合格系综作为已选零点；复合物只放在同一零点上，
其内禀能垒另标。ΔH‡、−TΔS‡ 是模型审计分项，分子数变化时注明
“受缔合熵模型影响”；BSSE 未检查就写“未检查”，SMD 不是 BSSE 校正。
温度、qRRHO 截断、σ、路径/构象简并度按已签方案和本卡执行，标准态只计一次。
