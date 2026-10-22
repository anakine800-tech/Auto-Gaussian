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
普通单个 Gaussian SP 不含独立的片段能量；本版明确列出两个缺项，`interaction_raw` / `interaction_corrected` 为 null。
仅提供 `complex_energy` 和 `complex_energy_plus_gas_bsse`，后者不叫相互作用能。不用气相 MCBS/DCBS 补齐溶剂片段。

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
