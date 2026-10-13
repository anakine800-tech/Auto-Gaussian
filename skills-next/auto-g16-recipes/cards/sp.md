# 单点电子能

## 1. 适用范围

已接受的主族闭壳层单分子极小点的电子能精化。单点本身不证明结构是极小点，也不单独产生用于布居的 Gibbs 自由能。

## 2. 前置条件

父 Opt+Freq 的 review 通过，最终几何已读到本地；整组明确同一单点方法和溶剂，study 计划确实需要单点。流程验收不做高精度单点。

## 3. 输入模板

从父 Attempt 的 `final.xyz` 写显式笛卡尔输入，不跨 Attempt 读取 checkpoint。无文献先例时的一个候选：

```text
%chk=sp.chk
%nprocshared=8
%mem=10GB
#p B3LYP/def2TZVP EmpiricalDispersion=GD3BJ SP

<已接受的构象名>

<charge> <multiplicity>
<父 Opt+Freq 最终坐标>

```

可另选 ωB97X-D/def2-TZVP（Gaussian 关键词 `wB97XD/def2TZVP`，不再额外叠加 GD3BJ）。溶液相按 study 加完整 SMD 设置；先例优先。

```text
ag prepare --study <study_id> --template gaussian --input <sp.gjf> --tier simple --walltime 12:00:00 --label sp-c01 --parent <optfreq_id> --relation single_point_of
```

## 4. 资源建议

约 50 原子以下常规单点从 simple（8 核、12 GB，`%mem=10GB`）、12:00:00 起；大基组或既有耗时支持时考虑 general（22 核、50 GB，`%mem=42GB`）、24:00:00。复杂规模再提 complex（44 核、120 GB，`%mem=100GB`）；不因“高精度”字样直接占满节点。

## 5. 提交前检查清单

- 逐项核对元素顺序和坐标来自已接受的父极小点，而非初始结构；电荷、多重度不变。
- 完整 route 与整组单点方案一致，未误加 Opt 或 Freq；Link0 与档位一致且不引用父 checkpoint。
- parent 是实际的 Opt+Freq Attempt；展示确认摘要，等人说“提交”及点击系统对话框。

## 6. 结果判据清单

- 正常终止且 SCF 收敛，得到有限的最终电子能，单位 Hartree；没有把缺失能量填零。
- 输出的体系、几何、方法及溶剂符合本次输入，未更换父构象。
- 整组单点覆盖了参与比较的全部代表；缺少一个不能以其低层级能量混填。
- 若用于复合自由能，清楚记录 `G_composite = E_SP + (G_qRRHO,low − E_elec,low)` 的配对；交给 thermo 卡片核实工具支持，不能把 `E_SP` 直接称作 G。

## 7. 常见失败与处理

SCF 失败、内存或时长不足时按 failure-diagnosis 审阅已有事实。若发现父结构并非合格极小点，先回到 opt-freq 卡片；提出新 Attempt，等人确认。

## 8. 常见坑

- 单点电子能与低层级热修正必须分列，标准态按每个独立物种处理，不能把一次修正加到整个反应上。来源：`skills/auto-g16-rtwin-pbs/references/scientific-workflows.md`。
- 旧预览输入中的方法只是占位示例，不能无依据用于正式研究。来源：`skills/auto-g16-view-rt-win/references/chemistry-boundaries.md`。
