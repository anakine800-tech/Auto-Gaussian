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

正常输出的汇总字段参考 [Gaussian Counterpoise 手册的 CONFLEX 官方译本](https://www.conflex.co.jp/gaussian_support/counterpoise.php)。
DCBS/MCBS 标记形态可在 [cclib 公开回归日志](https://github.com/cclib/cclib-data/blob/master/Gaussian/Gaussian03/H2FAs--AsH2F.opt-mp2-cp.log) 直接观察；该旧版 MP2/优化样例本身不属于本工具接受的气相 SCF 单点范围，也不作为现场验收。
合成水夹具只测解析与算术；仍需授权后的两份 G16 A.03 气相 CP 日志固定真实成功格式。缺项、未知格式、重复片段、多个汇总/作业段、能量加和不一致均拒绝，不猜测。
