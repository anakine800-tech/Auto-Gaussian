# Opt+Freq 极小点

## 要点

- 用于主族闭壳层单分子极小点；不用于 TS、金属、开壳层或碎片间结合构象搜索。（[见第 1 节](#1-适用范围)）
- 结构和代表构象集合须已由人签字；每个代表单独输入、单独 Attempt，整组采用相同方法。（[见第 2 节](#2-前置条件)）
- 核对身份、整组设置与完整确认摘要后，按 Study 流程取得聊天批准记录、匹配长期规则或 Mac 人工确认。（[见第 5 节](#5-提交前检查清单)）
- 须正常终止、Opt 与末次 Freq 阶段均收敛、频率完整且零虚频；频率阶段收敛未知不能按通过处理。（[见第 6 节](#6-结果判据清单)）
- 结构改变不能计入原构象集合；任何负频不能直接置零，qRRHO 不会修复非极小点。（[见第 6 节](#6-结果判据清单)）

## 1. 适用范围

主族、闭壳层、单分子、中性或带电的极小点优化与频率。不能用于 TS、金属、开壳层或碎片间结合构象搜索。

## 2. 前置条件

结构和代表构象集合已由人签字；知道电荷、多重度、溶剂、温度及方法依据。每个代表对应自己的输入和 Attempt，整组采用相同方法。读取 `auto-g16-study` 的方法表和确认摘要。

TS 族、关键中间体、复合物必须双路线，可旋转键较多也建议；按
[构象工作流](../../auto-g16-structures/references/conformer-workflow.md)保留路线来源，
读覆盖报告的未匹配项、最低构象和单路线独有低能项。警告时讨论延长 CREST、
增加适用体系的 ETKDG 种子或定向构造约束 CREST（directed），经人确认扩样
后重新出报告。覆盖报告不能证明采样已经完备，也不取代本卡科学判据。

## 3. 输入模板

中性流程验收示例（用审阅过的笛卡尔坐标替换占位行，保留 Gaussian 必需空行）：

```text
%chk=optfreq.chk
%nprocshared=8
%mem=10GB
#p B3LYP/6-31G(d) EmpiricalDispersion=GD3BJ Opt Freq

<结构名与构象编号>

<charge> <multiplicity>
<element> <x> <y> <z>

```

`Opt Freq` 合在一个作业。方法/基组：见 [acceptance-methods.md](../../auto-g16-study/references/acceptance-methods.md)。
研究骨架为 `#p <方法/基组> Opt Freq`；阴离子弥散、色散及溶剂按方法表选择，
最终摘要必须展示替换后的完整 route。上面的中性流程验收示例不能直接用于阴离子或正式研究。
记录 Gaussian 修订版、优化阈值（含末次四项数值/阈值）、积分网格及 SCF 设置。
未显式指定的逐项写“程序默认”；积分网格注明“程序默认，G16 为 UltraFine”，
并核对输出及环境默认覆盖，不能从 route 省略就猜出实际值；缺证据写未知。
当结论依赖很小的能差时，再针对相关构象、TS 和完整参考物种比较更严格的
优化阈值、网格和 SCF 收敛设置，记录能差/结论是否改变，不无差别升级所有作业。
量级参考：298.15 K、相同 TST 前因子/传输系数时，能垒差 1 kcal/mol
对应速率比 exp(1/RT) ≈ 5.4；这不是误差条或可靠性保证。
频率和 ZPE 缩放因子均取 1.0，低频截断取 100 cm⁻¹ 的依据及局限见
[方法表](../../auto-g16-study/references/acceptance-methods.md#数值设置与热化学依据)，并随实际结果记录。

```text
ag prepare --study <study_id> --template gaussian --input <conformer.gjf> --tier simple --walltime 24:00:00 --label optfreq-c01 --method-basis <文献先例 DOI 及位置 / 本课题既有方案及来源（不是文献先例，精度未经验证） / 兜底方法声明>
```

若上游来自 CREST Attempt，补 `--parent <crest_id> --relation conformer_of`；本地 RDKit 产物不是 Attempt，不伪造 parent，在 study 记录结构来源。

## 4. 资源建议

小于约 50 原子的验收或普通单分子先用 simple（8 核、12 GB，`%mem=10GB`），建议 24:00:00；较大或已有耗时证据的体系考虑 general（22 核、50 GB，`%mem=42GB`），48:00:00。complex（44 核、120 GB，`%mem=100GB`）仅在确有规模需求时提出。原子数是估计起点，不是方法精度；并发总量受配置上限限制。

## 5. 提交前检查清单

- 身份、连通性、坐标、电荷、多重度和立体化学与签字对象一致；没有未替换占位符。
- `%nprocshared` 与档位核数相同，`%mem` 不超过档位内存的 85%，`%chk` 只有文件名；route、标题、电荷多重度与坐标各段完整。
- 整组方法、色散、溶剂与数值设置一致；确认摘要列明完整 route、资源、目录和每个 Attempt。按 Study 流程取得聊天批准记录、匹配长期规则或 Mac 人工确认。

## 6. 结果判据清单

- `termination = normal`，`opt_converged = true`，输出含完整 Opt 和 Freq，而非只完成前半段。
- `freq_step_converged = true`：单独核对末次频率阶段的四项收敛表及 `Non-Optimized Parameters`。`freq_step_convergence` 给出各项值、打印阈值、YES/NO、Tight 比较和日志行号；`false` 不自动接受，`null` 表示缺失或无法确认，须查原日志，不能按通过处理。不能用优化阶段早期的 NO 代替末次频率阶段判据。
- `freq_step_gaussian_stationary` 另记 Gaussian 本 Freq 的驻点结论、依据及行号；`freq_step_review=manual_review` 表示四项未全通过但 Gaussian 判驻点，需人工判定，thermo 不自动接受。`freq_step_threshold_set=default` 且原判据通过、`freq_step_converged_tight=false` 时，若父优化为 Opt=Tight，需人工判定是否接受；不能从父 route 推断本表阈值。旧 facts 与已签判定不自动改写，负责人逐 study 决定 reparse，先外部 dry-run。
- 最终结构保持目标身份、连通性与立体化学；结构改变时不能仍计入原构象集合。
- 极小点要求 `n_imag = 0`；核对完整频率，非线性分子有 3N−6 个、线性分子有 3N−5 个振动模式，不能把截断输出当零虚频。
- 对低于 50 cm⁻¹ 的正频逐项记录并检查软扭转 / 数值敏感性；任何负频都不能直接置零。热化学按 thermo 卡片的 100 cm⁻¹ qRRHO 处理，但 qRRHO 不会修复非极小点。
- 记录 SCF、ZPE、热修正及 Gaussian 原始 G 的单位和来源；与后续 qRRHO 结果区分。优化后调用 `ag dedup` / `ag cluster` 检查不同初猜是否落到同一极小点。
  Gaussian 修订版、优化阈值、网格与 SCF 设置有实际依据或明确默认/未知标记；小能差结论附针对性数值检查及窗口放宽的最低构象、系综 G、关键能垒比较。

### 极小点系综（R09）

来源：[旧设计 R09](../../../archive/docs/end-to-end-reaction-computation-workflow.md)。
先验证给反应路径提供参考的极小点；每个保留候选须满足正常优化、完整频率、
零虚频，以及身份、立体化学、电荷、多重度、配位和预期缔合状态不变。
变化为另一种化学态时另行标记，不纳入原物种系综。多个起点坍缩为相同
优化结构时重新去重，保留起点到终态映射，避免重复计权。

按[筛选方法](../../auto-g16-study/references/acceptance-methods.md)先完成
xTB 6 kcal/mol → DFT 单点重排 → 3 kcal/mol 内进入优化（研究最多 20 个）。
在 xTB 几何上做 DFT 单点、按 3 kcal/mol 筛选只是控制预算，不能证明窗口外
候选可以忽略；几何松弛及热修正可能改变排序。每个来源、每种氢键模式中，
窗口外但结构独特的候选各保留 1–2 个作为验证对象（不足则全留，缺项注明），
记录来源、氢键模式和保留理由；xTB 预筛也保留相应窗外候选，避免先被丢失。
它们经同一 DFT Opt+Freq、最终去重及适用的精化单点后参加敏感性比较。
关键结论须检查窗口放宽前后最低构象、系综 G 和关键能垒是否变化，记录
实际窗口、集合与差值；预算不足则写验证未完成，不把缺算当作可忽略。
研究 20 个、验收 10 个的预算上限照旧；先为验证对象预留名额，超额时
列明未覆盖候选与成本，由人决定调整集合或预算，不能自行绕过上限。TS 通道不能照搬极小点的剪枝规则，逐通道审阅覆盖。
之后每个化学盆地分别用一致 Opt/Freq/SP 与热修正建立系综；使用
[thermo](thermo.md) 的可比自由能及 `ensemble_G`，不能用力场排序或平均 G
代替系综自由能。筛选单点在初始几何上，研究需要最终精化时，优化后须重新做单点；流程验收不增设高精度单点。
替代催化活性态不能仅因能量较高就删除，记录排除的化学与动力学依据。
本规则防止重复构象、改变身份的极小点或低层级误排污染参考自由能。

### 静默失败检查清单

为防止把程序正常退出误当科学成功，借鉴 [QUASAR，arXiv:2602.00185v2](https://arxiv.org/html/2602.00185v2) §2.3 “Long Simulation Handling”（完成状态不保证收敛）及 §4 “Discussion”（貌似合理的结果仍需物理核验）。下面七项是面向 Gaussian 和本项目的具体化，并非论文给出的 Gaussian 清单；不采用其自动终止/重启操作。

- **正常终止但不在驻点**：分别检查 `opt_converged` 和 `freq_step_converged`。尤其 `freq_step_converged=false` 时即便零虚频也暂停接受；`null` 是缺证据，查末次频率阶段的收敛表和 `Non-Optimized Parameters`，不能用别的阶段替代。
- **连接关系或立体构型改变**：先运行 `ag topology <attempt> --study <study_dir> --out <analyses/新文件.json>`，在 review.md 中引用 JSON 与 Markdown 输出，按相同原子映射人工审阅 changed/unknown 项，包括成键、断键、质子转移、B/N/O 不确定接触及立体中心。结构改变或无法判定时不能计入原构象集合；结构比较不代替科学审阅。`ag graph` 仅核对 Attempt 来源，不能用于声明结构一致。
- **小虚频**：当负频的绝对值 < 50 cm⁻¹ 时，检查完整位移，区分软扭转、片段运动、真实反应方向与数值误差；不能直接置零。可提出更严格优化/积分网格或沿该模式小扰动后同方法重新优化，重新核对完整 Freq；提出新 Attempt，等人确认。100 cm⁻¹ qRRHO 截断不负责消除虚频。
- **低频残余**：记录末次已完成频率段的 `Low frequencies ---` 第一行及原日志行号，核对平动、转动残余。
  TS 的真实虚频可能排在这些残余之前，软振动也可能混排；必要时连同后续行及投影后的频率、模式辨认，
  不能把首行所有数都当残余或按数值大小直接删除真实虚频。依据：[Gaussian 振动分析说明 §2.1](https://gaussian.com/wp-content/uploads/dl/vib.pdf)。
  **辨认出的平动、转动残余**绝对值超过约 20 cm⁻¹ 时，在 review 标为“残余偏大”，提示几何收敛或积分网格可能不足、
  热化学中的低频熵不可信，不直接接受；提出更严收敛标准或积分网格重新优化并做 Freq 的新 Attempt，经人确认后提交。
  缺该行或无法区分模式则写缺证据。它不是 `facts.json` 的 `frequencies_low`（cclib 提取的最低几个振动频率），不能用该字段代替。
- **实际方法、电荷或多重度不符**：核对最终计算对应的 Gaussian archive 行（展开折行），与输入、manifest 摘要及 `facts.json` 的 route/charge/multiplicity 对照；色散、溶剂等再对照输出回显。当前 facts 不提供完整 archive 审计字段，须查原日志，缺 archive/信息不全写缺证据，不能默认为一致。
- **能量离群**：仅在同一组成、电荷、多重度、方法、溶剂和能量类型/单位下比较同组构象；区分 SCF 与 G/qRRHO。显著偏离时先检查结构是否改变、解析是否选错步骤和收敛情况，写出差值与依据；不设无来源的通用阈值，也不因更低就自动选中或因离群就删除。
- **开壳层自旋污染**：本卡不开放开壳层执行；若输入/输出实际为开壳层，先报告超范围并停止接受。`s2` / `s2_after_annihilation` 是最后 SCF 的湮灭前/后值，`s2_line` 定位原文；以 S=(多重度−1)/2 的 S(S+1) 为参照，缺值不当零，不用稳定性本征向量的标签替代。`wavefunction_stability` 未知仍为 `unknown`，最低本征值 `{value,line}` 缺失为 null；不凭湮灭后接近理想值或 stable 认定目标态正确。方法选择交给人判断。

每项在 review 写“通过 / 不通过 / 依据”；需补算时转 [失败诊断](failure-diagnosis.md)，不自动重提。

## 7. 常见失败与处理

真实计算异常先停下报告，再按 failure-diagnosis 卡片审阅已有输出。未收敛、SCF 失败、超时或虚频分别提出针对性的修改，保留原输入和结果；提出新 Attempt，等人确认。

频率阶段收敛未通过时，按 failure-diagnosis 第 7 节提出从最终几何用 `Opt=CalcFC Freq` 重新优化的新 Attempt，relation 为 `reoptimized_from`；等人确认。

## 8. 常见坑

知识衔接：[GKB-0422、GKB-0451：优化与虚频排障](../../auto-g16-gaussian-learning-library/references/core-job-types.md)。

- 正常终止并不足以证明优化和频率均完成，要核对驻点与完整频率证据。来源：`archive/skills/auto-g16-rtwin-pbs/references/environment-and-failures.md`、`skills/auto-g16-rtwin-pbs/references/scientific-workflows.md`。
- 多个初猜可能收敛为同一极小点，直接逐作业计数会重复加权。来源：`archive/skills/auto-g16-view-rt-win/references/conformer-workflow.md`。
- 增加核数不会使不适用的方法变得可靠；方法和资源分别说明。来源：`archive/skills/auto-g16-rtwin-pbs/references/protocols.md`。

- 正常终止、`opt_converged=true`、零虚频仍可能伴随频率阶段位移检查 NO；在频率阶段收敛复核通过前暂停热化学接受。来源：study `butane-l1-20261013`，`lessons/04-frequency-stage-convergence.md`。
