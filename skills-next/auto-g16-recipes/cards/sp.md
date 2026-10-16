# 单点电子能

## 1. 适用范围

主族闭壳层的候选构象 DFT 单点重排、已接受极小点的电子能精化，以及
已按 TS 卡片审核的鞍点候选/参考物种的能垒方法敏感性。单点本身不证明
结构是极小点或 TS，也不单独产生用于布居的 Gibbs 自由能。
不开放金属、开壳层执行。双分子步骤与复合物按 [complex](complex.md) 卡片执行，仅开放以已审阅原子对为约束的采样；通用对接搜索不开放。

## 2. 前置条件

先在 study 标明本次单点用途：

- **筛选单点**：xTB 6 kcal/mol 窗口内及窗外验证组中已去重且身份经审阅的候选，或按
  自己窗口选出的 RDKit 候选；尚无 DFT Opt+Freq，不能要求或伪造该父作业。
- **最终精化**：父 Opt+Freq 的 review 通过，读取最终几何；TS 要通过
  ts 卡片的频率和方向审核，路径结论仍依赖双向 IRC 及端点识别。
- **方法敏感性**：已确定关键能垒及完整参考物种、竞争通道，在同一几何
  集合上比较至少两类泛函，按[方法表](../../auto-g16-study/references/acceptance-methods.md)。

整组明确同一单点方法和溶剂。流程验收仅作筛选单点，不做高精度单点；
验收和研究的阴离子弥散方案均见方法表。

TS 族、关键中间体、复合物必须双路线，可旋转键较多也建议；按
[构象工作流](../../auto-g16-structures/references/conformer-workflow.md)保留路线来源，
读覆盖报告的未匹配项、最低构象和单路线独有低能项。警告时讨论延长 CREST、
增加适用体系的 ETKDG 种子或定向构造约束 CREST（directed），经人确认扩样
后重新出报告。覆盖报告不能证明采样已经完备，也不取代本卡科学判据。

在 xTB 几何上做 DFT 单点、按 3 kcal/mol 筛选只是控制预算，不能证明窗口外
候选可以忽略；几何松弛及热修正可能改变排序。每个来源、每种氢键模式中，
窗口外但结构独特的候选各保留 1–2 个作为验证对象（不足则全留，缺项注明），
记录来源、氢键模式和保留理由；xTB 预筛也保留相应窗外候选，避免先被丢失。
它们经同一 DFT Opt+Freq、最终去重及适用的精化单点后参加敏感性比较。
关键结论须检查窗口放宽前后最低构象、系综 G 和关键能垒是否变化，记录
实际窗口、集合与差值；预算不足则写验证未完成，不把缺算当作可忽略。
研究 20 个、验收 10 个的预算上限照旧；先为验证对象预留名额，超额时
列明未覆盖候选与成本，由人决定调整集合或预算，不能自行绕过上限。TS 通道不能照搬极小点的剪枝规则，逐通道审阅覆盖。

## 3. 输入模板

方法/基组：见 [acceptance-methods.md](../../auto-g16-study/references/acceptance-methods.md)。
骨架中的 `<方法/基组>` 必须按已审阅方案替换，并补齐适用的色散与溶剂设置。

最终精化从父 Attempt 的 `final.xyz` 写显式笛卡尔输入；筛选单点从已审阅
xTB/RDKit 候选坐标写入，并记录构象编号。均不跨 Attempt 读取 checkpoint。
最终精化输入骨架（方法按本次用途从方法表选择）：

```text
%chk=sp.chk
%nprocshared=8
%mem=10GB
#p <方法/基组> SP SCRF=(SMD,Solvent=<已核实关键词>)

<最终精化构象名>

<charge> <multiplicity>
<与本次用途对应的已审阅坐标>

```

候选筛选采用优化层级；最终精化采用方法表指定的较大基组。
筛选单点只在候选几何上重排，优化后仍须在最终几何上重算精化单点。
方法敏感性的第二类泛函也只在方法表定义；比较时保持同基组、溶剂和几何。

下面 parent 示例仅适用于最终精化；筛选时若来自 CREST，改为真实 CREST
parent，并用说明筛选来源的 relation 文本（如 `screening_sp_of`）；本地
RDKit 坐标无 Attempt，不伪造 parent。relation 仅记录来源，不触发分析。

```text
ag prepare --study <study_id> --template gaussian --input <sp.gjf> --tier simple --walltime 12:00:00 --label sp-c01 --parent <optfreq_id> --relation single_point_of --method-basis <文献先例 DOI 及位置 / 本课题既有方案及来源（不是文献先例，精度未经验证） / 兜底方法声明>
```

## 4. 资源建议

约 50 原子以下常规单点从 simple（8 核、12 GB，`%mem=10GB`）、12:00:00 起；大基组或既有耗时支持时考虑 general（22 核、50 GB，`%mem=42GB`）、24:00:00。复杂规模再提 complex（44 核、120 GB，`%mem=100GB`）；不因“高精度”字样直接占满节点。

## 5. 提交前检查清单

- 逐项核对元素顺序、电荷、多重度及本次用途：最终精化来自已接受驻点最终几何；筛选单点来自已审阅候选，不混用两者。
- 完整 route 与整组单点方案一致，未误加 Opt 或 Freq；Link0 与档位一致且不引用父 checkpoint。
- parent 与本次用途的实际来源一致；展示确认摘要，等人说“提交”及点击系统对话框。

## 6. 结果判据清单

- 正常终止且 SCF 收敛，得到有限的最终电子能，单位 Hartree；没有把缺失能量填零。
- 输出的体系、几何、方法及溶剂符合本次输入，未更换来源构象。
- 整组单点覆盖了参与比较的全部代表；缺少一个不能以其低层级能量混填。
- 筛选单点只按同组 DFT 电子能重新排序，≤ 3 kcal/mol 的进入优化（研究最多 20 个、验收最多 10 个）；优化后重新去重，研究所需最终精化单点重算，验收不增设高精度单点；筛选能量不配热修正。
- 窗外验证对象覆盖每个来源和每种氢键模式；窗口放宽前后的最低构象、系综 G、关键能垒及未验证部分均已记录，不能用 3 kcal/mol 或数量上限声称排除其余候选。
- 敏感性结果逐种泛函重建完整能垒；若结论翻转，必须在 study.md 写明数值和不稳健性，交给 [profile](profile.md) 比较。
- 若最终精化单点用于复合自由能，清楚记录 `G_composite = E_SP + (G_qRRHO,low − E_elec,low)` 的配对；交给 thermo 卡片核实工具支持，不能把 `E_SP` 直接称作 G。

## 7. 常见失败与处理

SCF 失败、内存或时长不足时按 failure-diagnosis 审阅已有事实。最终精化若发现父驻点不合格，先回到 opt-freq 或 ts 卡片；筛选失败保留缺项，不能直接按高能筛除；提出新 Attempt，等人确认。

## 8. 常见坑

知识衔接：[GKB-0410、GKB-0411：单点边界与 SCF 排障](../../auto-g16-gaussian-learning-library/references/core-job-types.md)。

- 单点电子能与低层级热修正必须分列，标准态按每个独立物种处理，不能把一次修正加到整个反应上。来源：`skills/auto-g16-rtwin-pbs/references/scientific-workflows.md`。
- 旧预览输入中的方法只是占位示例，不能无依据用于正式研究。来源：`skills/auto-g16-view-rt-win/references/chemistry-boundaries.md`。

### S8：SMD 能量项与复合自由能

为防止把已包含的溶剂项或标准态项重复相加，区分“单点模型能量”和
“分子热修正”。改编自 `archive/skills/auto-g16-rtwin-pbs/references/scientific-workflows.md`
的复合热化学分项；当前 qRRHO 与独立 Attempt 规则优先。

SMD 溶剂化自由能包括自洽体相静电项及空腔、色散、溶剂结构等 CDS 项；
后者用经验表面张力描述，也吸收部分短程非体相静电效应，不能把两项当作
唯一的实验分解。依据为 Marenich–Cramer–Truhlar 原文 §2，
[DOI:10.1021/jp810292n](https://pubs.acs.org/jpcbfk/article/113/18/6378/1427431/Universal-Solvation-Model-Based-on-Solute-Electron)。
Gaussian 的 SMD 输出若标明 `SMD-CDS` 已计入上方总能量，不再加 CDS，
也不再加一份完整 ΔG_solv。输出形式可核对 Gaussian 官方
[SCRF 说明页的 SMD 输出示例](https://gaussian.com/scrf/)；
记录实际采用的能量行和来源段。

| 已审阅组合 | 正确组装（逐物种） | 不可重复项 |
|---|---|---|
| 气相频率热修正 + 溶液 SMD 单点 | `G_sol = E_SP,SMD + (G_qRRHO,gas − E_low,gas)` | 括号只留气相分子热修正；不另加 SMD 溶剂化项；这是假定气相几何/热修正可用于溶液的近似，须单独说明适用性 |
| SMD 几何/Freq + 同溶剂 SMD 精化单点 | `G_sol = E_SP,SMD + (G_qRRHO,low,SMD − E_low,SMD)` | 从低层级 G 中减去与其匹配、已含 SMD 的低层级能量，只替换一次；不叠加两个层级的溶剂化能 |

这里 `E_*,SMD` 表示包含相应 SMD 项的程序模型能量，不是完整有限温度溶液 G。
SP/Freq 必须正确配对；以上公式描述科学组合，不表示当前工具支持任意混合协议。
气相 Freq 与溶液 SP 的组合若被工具协议检查拒绝，记录能力缺口，不能改 route
元数据或伪造输出来通过。已签溶液几何/Freq 方案不能自动改成气相方案。

SMD 的相同浓度气→液溶剂化项不自动替代 Gaussian 分子热化学的 1 atm→1 M
转换；需否加 `RT ln(R_gas T c°/p°)` 取决于输入 G 的实际标准态。
GoodVibes 或来源 G 已按 1 M 处理时不再加；具体分项与离子结论限定见
[thermo 的 S8](thermo.md#s8标准态账目与离子适用性)。
