# 单点电子能

## 1. 适用范围

主族闭壳层的候选构象 DFT 单点重排、已接受极小点的电子能精化，以及
已按 TS 卡片审核的鞍点候选/参考物种的能垒方法敏感性。单点本身不证明
结构是极小点或 TS，也不单独产生用于布居的 Gibbs 自由能。
不开放双分子初筛、金属或开壳层执行。

## 2. 前置条件

先在 study 标明本次单点用途：

- **筛选单点**：xTB 6 kcal/mol 窗口内已去重且身份经审阅的候选，或按
  自己窗口选出的 RDKit 候选；尚无 DFT Opt+Freq，不能要求或伪造该父作业。
- **最终精化**：父 Opt+Freq 的 review 通过，读取最终几何；TS 要通过
  ts 卡片的频率和方向审核，路径结论仍依赖双向 IRC 及端点识别。
- **方法敏感性**：已确定关键能垒及完整参考物种、竞争通道，在同一几何
  集合上比较至少两类泛函，按[方法表](../../auto-g16-study/references/acceptance-methods.md)。

整组明确同一单点方法和溶剂。流程验收只用 B3LYP-D3(BJ)/6-31G(d)
作筛选单点，不做高精度单点；若验收对象为阴离子或负电荷明显离域，
将优化和筛选单点基组均换为 `6-31+G(d)`。方法表已由负责人于 2026-10-14 确认。

## 3. 输入模板

最终精化从父 Attempt 的 `final.xyz` 写显式笛卡尔输入；筛选单点从已审阅
xTB/RDKit 候选坐标写入，并记录构象编号。均不跨 Attempt 读取 checkpoint。
研究无直接先例时的中性最终精化骨架（筛选时按下表更换 route）：

```text
%chk=sp.chk
%nprocshared=8
%mem=10GB
#p wB97XD/def2TZVPP SP SCRF=(SMD,Solvent=<已核实关键词>)

<最终精化构象名>

<charge> <multiplicity>
<与本次用途对应的已审阅坐标>

```

研究的两种单点用途采用不同基组，所有 route 均写明 SMD 溶剂：

| 用途 | 中性骨架 | 阴离子或负电荷明显离域骨架 |
|---|---|---|
| 候选筛选（优化层级） | `#p wB97XD/6-31G(d) SP SCRF=(SMD,Solvent=<已核实关键词>)` | `#p wB97XD/6-31+G(d) SP SCRF=(SMD,Solvent=<已核实关键词>)` |
| 最终几何精化 | `#p wB97XD/def2TZVPP SP SCRF=(SMD,Solvent=<已核实关键词>)` | `#p wB97XD/6-311++G(d,p) SP SCRF=(SMD,Solvent=<已核实关键词>)` |

筛选单点只在候选几何上重排；优化后仍须在最终几何上做精化单点。
阴离子或负电荷明显离域的配套优化也含弥散函数。
ωB97X-D 不额外叠加 GD3BJ。溶液相按 study 加
`SCRF=(SMD,Solvent=<已核实关键词>)`；直接先例优先。
方法敏感性第二类采用 `M062X/def2TZVPP SP`，弥散方案则为
`M062X/6-311++G(d,p) SP`；同基组、溶剂及几何，不自行添加 D3。

下面 parent 示例仅适用于最终精化；筛选时若来自 CREST，改为真实 CREST
parent，并用说明筛选来源的 relation 文本（如 `screening_sp_of`）；本地
RDKit 坐标无 Attempt，不伪造 parent。relation 仅记录来源，不触发分析。

```text
ag prepare --study <study_id> --template gaussian --input <sp.gjf> --tier simple --walltime 12:00:00 --label sp-c01 --parent <optfreq_id> --relation single_point_of
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
- 敏感性结果逐种泛函重建完整能垒；若结论翻转，必须在 study.md 写明数值和不稳健性，交给 [profile](profile.md) 比较。
- 若最终精化单点用于复合自由能，清楚记录 `G_composite = E_SP + (G_qRRHO,low − E_elec,low)` 的配对；交给 thermo 卡片核实工具支持，不能把 `E_SP` 直接称作 G。

## 7. 常见失败与处理

SCF 失败、内存或时长不足时按 failure-diagnosis 审阅已有事实。最终精化若发现父驻点不合格，先回到 opt-freq 或 ts 卡片；筛选失败保留缺项，不能直接按高能筛除；提出新 Attempt，等人确认。

## 8. 常见坑

- 单点电子能与低层级热修正必须分列，标准态按每个独立物种处理，不能把一次修正加到整个反应上。来源：`skills/auto-g16-rtwin-pbs/references/scientific-workflows.md`。
- 旧预览输入中的方法只是占位示例，不能无依据用于正式研究。来源：`skills/auto-g16-view-rt-win/references/chemistry-boundaries.md`。
