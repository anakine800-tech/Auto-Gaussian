# ag-cp/1：Counterpoise 诊断报告

T105 新增 `gaussian-cp` 和本地 `ag cp-report`。诊断量；未进入 thermo/profile；不构成已校正剖面。
只接受两片段气相单点，整体及片段均为单重态。不会更改 thermo/profile/ASM 的计算。

## 输入与命令

源 GJF 使用普通 Cartesian 原子行和整体电荷/多重度，route 含且仅含一次 `Counterpoise=2`；`SP` 可省略。
CSV 精确四列 `fragment,atoms,charge,multiplicity`，两行；索引从 1 开始，每原子恰好一次，片段电荷和等于整体。
成键或 uncertain 接触跨越片段、开放壳层、父 checkpoint、自定义 Gen/GenECP/ExtraBasis/IOp、Opt/Freq/IRC/Scan/Guess 等均拒绝。
方法沿用 T82 `protocol()` 的受支持 SCF 方法口径，不改变普通 Gaussian 的输入规则。

prepare 生成片段标签及整体/片段 1/片段 2 三组电子态；`<input>.gjf.fragments.csv` 与 GJF 一同计入 bundle。
复用原有 Gaussian PBS 和 SCNet 作业脚本。附加 CSV 排序在对应 GJF 后，保持既有输出文件名绑定。

```text
ag prepare --study <id> --cluster default --template gaussian-cp --input <cp.gjf> --fragments <fragments.csv> --tier mini --walltime 00:30:00 --label cp --card counterpoise --method-basis <依据>
ag facts <cp_attempt> --study <study_dir>
ag cp-report <cp_attempt> --study <study_dir> --out analyses/cp.json
ag cp-report <cp_attempt> --study <study_dir> --solvent-sp <solvent_sp_attempt> --asm analyses/asm.json --out analyses/cp-comparison.json
ag cp-report <cp_attempt> --study <study_dir> --solvent-sp <complex_smd_attempt> --solvent-fragment-sp 1:<fragment_1_smd_attempt> --solvent-fragment-sp 2:<fragment_2_smd_attempt> --out analyses/cp-smd.json
```

report 不加载集群配置、不连接网络、不写 facts，只独占创建新的 JSON 和同名 Markdown。
它重算输入 bundle、重读日志、核对可选已保存 facts；符号链接、越界、过期 facts 或输出覆盖均拒绝。

## 第 0 节实测

2026-10-22，G16 A.03 水二聚体探针的日志第 89 行：`No SCRF with counterpoise/fragments.`；第 90 行为 Error termination，退出码 1。
原日志 SHA-256：`ff18259cdb5970fa1198aa804116be2978bbd7a4136bbfaaf39d946ecba4401d`。
因此 prepare 拒绝任何含 SCRF 的 CP route，并提示用 `ag cp-report --solvent-sp` 叠加普通溶剂单点。
临时探针模板不在仓库内；测试中只保留无路径、无主机名的两行夹具。

## JSON 字段

| 字段 | 含义 |
| --- | --- |
| schema | `ag-cp/1` |
| attempt, program_version | CP Attempt 与日志中的程序版本 |
| protocol, integration_grid | T82 方法/基组/色散/基函数类型/气相口径和网格记录 |
| fragments | 两片段原子映射、原子数、分子式、电子态、CSV 哈希与来源 |
| gas.uncorrected_energy | 复合物自身 SCF 能量，不能取最后一个片段的 SCF |
| gas.corrected_energy, gas.bsse | Gaussian 汇总打印的校正能量与 BSSE |
| gas.sum_fragments | 同一复合物几何下两个 MCBS 片段能量和 |
| gas.interaction_raw, gas.interaction_corrected | 分别减去 sum_fragments 得到的相互作用能 |
| gas.fragments | DCBS（复合物基组/ghost）及 MCBS（片段自身基组）的逐片段能量与原文行号 |
| gas.printed_interaction_* | Gaussian 原文舍入到有限精度的 kcal/mol 数值，用于一致性核对 |
| solvent | 可选同几何普通溶剂 SP，见下节 |
| asm | 可选现有 `ag-asm/1` 的形变能并列对照，JSON Pointer 与报告哈希，不合成新能量 |
| sources | 本地 study 相对路径及 SHA-256 |
| notice | 固定诊断附注 |

每个直接/推导能量包含 Hartree、kcal/mol、来源列表与可选公式。日志来源含 1-based `line`；推导量保留全部操作数来源。
换算常数记录在 `hartree_to_kcal_mol`，沿用 Gaussian 解析模块；普通模板 facts 不增加 CP 字段。

## 溶剂与 ASM

同几何需保持原子序，所有原子等权、proper Kabsch 对齐（不反射、不交换同元素原子），RMSD ≤0.001 Å。
整体电子态、方法、基组、基函数类型和色散一致；网格差异仅警告；需要实际打印的溶剂参数块，route 回显不足以证明执行。

固定说明：**溶剂相结果 = 溶剂相相互作用能 + 气相 BSSE；假设 BSSE 基本不受溶剂影响**。
普通单个 Gaussian SP 不含独立的片段能量；未指定片段时明确列出两个缺项，`interaction_raw` / `interaction_corrected` 为 null。
此时仅提供 `complex_energy` 和 `complex_energy_plus_gas_bsse`，后者不叫相互作用能。不用气相 MCBS/DCBS 补齐溶剂片段。

### 已有片段 SMD 单点（T165）

可重复给出 `--solvent-fragment-sp <index>:<attempt_id>`，index 必须是已绑定 CP CSV 的 1 或 2。
参数只接受本 study 已有 Attempt ID，不接受名称猜配、外部路径、重复 index 或同一 Attempt 兼作两片段。
给片段参数必须同时给 `--solvent-sp`。三个来源均须是正常结束的 ordinary Gaussian SP，片段模式只接受受支持 SCF 方法的 SMD。
不会生成输入、创建 Attempt、提交计算或刷新已有 facts；显式提供的损坏来源直接拒绝，不当作缺失跳过。

片段参考坐标来自 CP 输入中该片段的真实原子，按全体系原子号升序抽取。
对片段输入和输出分别作固定行顺序的 proper Kabsch 比较，沿用 RMSD ≤0.001 Å；只允许刚性移动，不反射、不搜索置换。
电荷/多重度须等于 CP 的该片段声明。优化后片段、额外原子、ghost、CP 输出、Gen/ECP/外部基组和混合任务不接受。
匹配几何不能证明所有同元素原子的化学身份：对称或近对称原子的换序可能无法由此阈值区分，原始原子映射仍需人工审阅。
三个 SMD 来源和气相 CP 的方法、基组、基函数类型、色散一致；三个 SMD 来源的模型、溶剂及实际打印的关键溶剂参数也须一致。
溶剂块缺失或与 route 矛盾时拒绝；网格差异沿用提示，不新增阈值。

能量仍取各自唯一的 `SCF Done`（含日志 SHA-256 和行号），与解析 facts 核对。
Gaussian 发布说明确认 SMD 非静电项已经包含在该能量中，不再加 SMD-CDS 或改取其他“溶剂能量”标签。
依据：[Gaussian 09 Rev. D.01 Release Notes，第 12 页](https://info.mse.waseda.ac.jp/wp-content/uploads/2017/06/Gaussian09_RevD01_ReleaseNote.pdf)。
这保留原报告的 SCF 能量口径，并不新增热化学处理。

| 溶剂字段 | 内容 |
| --- | --- |
| `complex_energy` | E_AB(SMD)，既有复合物能量字段 |
| `complex_energy_plus_gas_bsse` | E_AB(SMD) + BSSE(gas)，仍不是相互作用能 |
| `fragment_energies[].energy` | 有效片段自身基组的 SMD SCF 能量；未提供则为 null |
| `fragment_energies[].binding` | CP Attempt、CSV/复合物输入哈希、片段电子态、`complex_atom` → `fragment_atom` 映射 |
| `fragment_energies[].pairing`, `output_pairing` | CP 几何子集与片段输入、输出的两份几何匹配证据 |
| `fragment_energies[].input_source`, `section_source` | 输入哈希、日志哈希/段行号、实际溶剂执行证据和协议 |
| `complex_source` | 片段模式下复合物的同类来源与匹配证据 |
| `interaction_raw` | E_AB(SMD) − E_A(SMD) − E_B(SMD) |
| `interaction_corrected` | interaction_raw + BSSE(gas)，假设 BSSE 基本不受溶剂影响的近似值 |

两个片段都有效时先以 Hartree 运算，再用既有常数换算 kcal/mol。推导量列明公式、全部操作数的日志行/哈希及 `operand_pointers`；片段映射与几何证据位于对应 `fragment_energies` 条目。
只给一个片段时保留其能量与来源，`missing` 逐一列出余下片段，两个 interaction 字段继续为 null。
这些是固定几何相互作用能诊断，**不是计算出的结合自由能**；不加入形变能、标准态、热校正，不进入 thermo/profile。

兼容性核查：保留 `ag-cp/1` 及所有核心字段名；旧命令仍生成气相/缺片段结果。仓库内直接读取这两个 interaction 字段的消费者是本模块 Markdown 渲染器与 CP 测试，已覆盖 null 和 quantity 两种情况；其他本地能量工具仍拒绝 CP Attempt。
本核查不代表未提供的外部消费者已通过验证。

合成水二聚体手算（不是实测）：E_AB = −152.010、E_A = −76.001、E_B = −75.998、BSSE = 0.002 Hartree。
故 interaction_raw = −0.011 Hartree = −6.902604951 kcal/mol，interaction_corrected = −0.009 Hartree = −5.647585869 kcal/mol。
测试 `test_smd_fragment_arithmetic_sources_mapping_and_cli` 独占生成完整 JSON/Markdown，独立用十进制数核算并逐项核验来源哈希、原子映射、文件不变与覆盖拒绝。

ASM 的每项来源哈希会核验，输出原报告的对象标签和形变能；它是独立对照，不代表同一计算协议，也不自动与 CP 相加。

## 解析与验证边界

2026-10-22 已用 G16 A.03 的水二聚体和 NH₄⁺···H₂O 气相 CP 实际日志定稿解析器，并保留两个必要片段的脱敏内联夹具及原行号映射（`ag/tests/test_counterpoise.py`）。
实际标签为 `Counterpoise: doing full-system calculation.`，以及 `using the basis set of the full-system, NewBq=T`（DCBS）和 `using the basis set of the fragment.`（MCBS）；后接固定五行汇总。旧 G03 的 DCBS/MCBS 标签只曾作旁证，不是 A.03 格式依据，本解析器不接受该标签写法。
缺项、未知格式、重复片段、多个汇总/作业段、能量加和不一致均拒绝，不猜测。汇总字段也可参考 [Gaussian Counterpoise 手册的 CONFLEX 官方译本](https://www.conflex.co.jp/gaussian_support/counterpoise.php)。

| 气相固定几何 | BSSE (kcal/mol) | 相互作用能（未校正 / 校正，kcal/mol） | 原日志关键行 |
| --- | ---: | ---: | --- |
| 水二聚体 | 0.79066081 | -5.69216550 / -4.90150448 | 197、274–651、717–721、737 |
| NH₄⁺···H₂O | 0.15765470 | -15.12466087 / -14.96700605 | 207、299–711、778–782、799 |

两份原日志 SHA-256 分别为 `6bea540a4fb31615d2910b63aba963f03127e51d6cdd0a50176b3eee9a6d4db9` 和 `3b034d49ebab671a54bfc36e65093d2ebc6305908edb3755da5290171a5f615e`。
同几何 NH₄⁺···H₂O SMD(DCE) 单点也正常结束并通过溶剂配对；实测报告正确保留两个片段溶剂能量缺项，未计算溶剂相相互作用能。
这些是工程验证的固定几何结果；只检查量级和内部自洽，不作文献数值对标，不代表结构优化或科学研究验收。

T165 没有三份真实配套 SMD 输出；新片段组合只完成合成数值、拒绝矩阵和既有脱敏气相日志回归，未进行新的现场验证或科学验收。
