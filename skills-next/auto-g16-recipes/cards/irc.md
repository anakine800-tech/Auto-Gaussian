# IRC 双向路径与端点

## 1. 适用范围

从已审核的一阶鞍点沿同一主族闭壳层势能面追踪两个方向，并识别连接的极小点。**IRC 必须两个方向都走完并识别端点后才能声称验证。** 一次正常退出或仅一个方向不满足此标准。

## 2. 前置条件

[TS 卡片](ts.md)的优化、完整频率、恰好一个虚频及目标方向审核全部通过；[机理假设](reaction-plan.md)已签字。两个方向使用同一已接受 TS 的最终几何、原子顺序、电荷、多重度和方法；预先列明可能的反应物/产物与原子映射，不预设 Forward 就是产物。

当前 ag 可准备单结构显式坐标输入，并用 `--parent-chk` 声明父 chk 副本。后续方向完成、端点提取和连接比对须另行核对对应工具与证据。若缺少所需能力或证据，停止相关步骤并在 study 记录缺口；本卡不承诺现有 ag 可自动跑通完整 IRC 验证。

## 3. 输入模板

方法/基组：见 [acceptance-methods.md](../../auto-g16-study/references/acceptance-methods.md)。
骨架中的 `<方法/基组>` 必须按已审阅方案替换，并补齐适用的色散与溶剂设置。

Gaussian 路线形式为 `irc=(calcfc,maxpoints=<点数>,stepsize=<步长>,forward)`，反方向将 `forward` 改为 `reverse`。例如以下单结构骨架在起点重新算力常数，不读取父 chk；50 和 10 仅是待审阅示例值，不保证走到极小点。使用前核对安装版本对步长的单位/约定。

```text
%chk=irc-forward.chk
%nprocshared=8
%mem=10GB
#p <方法/基组> irc=(calcfc,maxpoints=50,stepsize=10,forward)

<TS 编号与 forward 方向>

<charge> <multiplicity>
<element> <TS 最终 x> <TS 最终 y> <TS 最终 z>

```

这里不重选 IRC 方法；阴离子的弥散方案也必须与 TS 一致。
方法、色散和溶剂（溶液相含 SMD）必须替换为该 TS 的实际设置。另建 reverse 输入、标签和 Attempt；每个方向完整展示输入摘要并经人确认。已有准备接口如下（反方向相应换输入和标签）：

```text
ag prepare --study <study_id> --template gaussian --input <irc-forward.gjf> --tier simple --walltime 24:00:00 --label irc-forward --parent <ts_id> --relation irc_from --method-basis <与TS相同的方法依据>
```

`irc_from` 只是现有 relation 文本，不会复用 chk 或验证路径。经审阅复用 TS 力常数时，在 prepare 中追加 `--parent-chk <ts_id>:<父输入中声明的chk文件名>`，与现有 `--parent <ts_id>` 配套。父 Attempt 必须 finished/fetched，submit 确认前后均核对调度器中已无该作业，且父子属于同一集群。

```text
%oldchk=parent.chk
%chk=irc-forward.chk
%nprocshared=8
%mem=10GB
#p <方法/基组> guess=read irc=(rcfc,maxpoints=50,stepsize=10,forward)

<TS 编号与 forward 方向>

<charge> <multiplicity>
<element> <TS 最终 x> <TS 最终 y> <TS 最终 z>

```

反方向另建 Attempt，改为 `reverse` 和 `%chk=irc-reverse.chk`，引用同一父 chk。**坐标仍须显式写在输入中**；`Geom=Check`/`Geom=AllCheck` 不允许。父 chk 必须确有适用的力常数；Guess=Read 也须核对方法、电荷、多重度、原子顺序和几何。

使用 RCFC/ReadFC 前，对父 TS 运行 `ag facts`，坐标取其 `final_input.xyz`
（最终几何的 Input orientation，去掉 XYZ 前两行），保持原子顺序；
`final.xyz` 通常是 Standard orientation，无标准取向时可能退回输入取向，
以 facts 的 `final_geometry_orientation` 为准。缺少 Input 表时不会臆造
`final_input.xyz`；需核对原日志或改用 CalcFC。
prepare 已在 `--parent-chk` + RCFC/ReadFC 时逐原子校验输入与父作业 `final_input.xyz` 的坐标，容差 1e-4 Å，
不做旋转、平移或原子交换；父 TS 的 route 带 `nosymm` 时，两种取向相同，
可用任一导出文件。也可预先让新的 TS Opt+Freq 带 `nosymm`；
仅对子 IRC 加它不能补救父力常数与输入坐标的框架错配。

prepare 纯本地；submit 在 Mac 确认弹窗展示父 ID、来源文件名、大小、SHA256 前 12 位和固定目标 parent.chk。确认后只在新 Attempt 目录独占创建副本，源与目标哈希都等于确认值才继续上传/qsub，父文件只读。固定复制助手需要远端 Python ≥ 3.6 和 Linux /proc；缺少时停止；先运行 `ag doctor --cluster <cluster>` 查看 Python 版本和 /proc 支持。复制失败、SSH 255、超时或哈希变化均为 failed_presubmit，保留副本、不重试、不 qsub。

两侧端点经人工确认坐标后，要各自再按 [Opt+Freq](opt-freq.md)优化为极小点；可用现有 parent/relation 参数记录 `endpoint_of` 来源。`ag facts <irc_id>` 提取 `irc` 字段及 `irc_end.xyz`；后者只是最后报告路径点，不是已验证的端点。

## 4. 资源建议

每个方向先估计 simple（8 核 / 12 GB，`%mem=10GB`），24:00:00；参照 TS 实际耗时再决定 general（22 核 / 50 GB，`%mem=42GB`），48:00:00。计入两次 CalcFC、路径各点和两个端点 Opt+Freq 的成本。MaxPoints 是上限，不是完成证据；增大点数/减小步长会增加代价，需新方案和确认。

## 5. 提交前检查清单

- 起点是通过 TS 及振动方向审核的同一个几何；两份输入元素和原子行号一致，方向关键词明确且不重复。
- 方法、电荷、多重度、溶剂与 TS 一致，CalcFC 的来源和代价已说明；采用 RCFC 时核对父力常数适用性、`final_input.xyz` 取向（或父 TS 的 `nosymm`）、附件声明和确认哈希。
- 结构、立体警告、方法依据、完整 route、资源档位、walltime、远程目录和输入哈希均已展示，提交仍由人点击 Mac 对话框。
- 端点获取和人工审阅路径已说明；解析或比对证据缺失就记录具体缺口，不把通用终止字段当成 IRC 专用完成标志。

## 6. 结果判据清单

- 每个方向分别核对完整原日志、路径点、校正器收敛、终止原因和最终几何；核对 `facts.json` 的 `irc.direction`、`point_count`、`path_complete_reported`、`reached_max_points` 和 `corrector_failed`，并回查日志，不能只看 `termination=normal`。仅达到 MaxPoints、校正器失败或输出截断不能写“走完”。
- 两个方向均走完，并保留与同一 TS 的原子映射和来源；缺一侧就写“IRC 未完成”。
- 两侧最后路径点分别再优化并做 Freq：满足极小点收敛、频率阶段收敛、完整模式数和零虚频。最后路径点不是自动接受的极小点。
- 用 `ag graph --study <study_dir> --json` 核对 TS → 两个方向 → 端点优化的 Attempt 来源。`ag graph` 仅为来源图；另用 `ag irc-compare --ts <ts_id> --forward <forward_id> --reverse <reverse_id> --reactant <reactant_id> --product <product_id> --out <新报告.json>` 获取保留原子编号的连接、质子和立体差异。工具的“匹配 / 不匹配 / 无法确定”仍须人工审阅，写入 review；来源图不能替代此比较。缺少可审阅的几何或匹配证据就保持未验证。
- 两侧确实连接目标反应物与产物后才赋予化学标签；连接其他物种则如实记录并更新机理假设，不强改标签。任何“验证”结论均须具备双向完成和已识别极小点证据。

## 7. 常见失败与处理

`Maximum number of corrector steps exceded`、仅到 MaxPoints 或一侧失败时，
保留结果并停止报告。先核对起点、原子映射、RCFC 取向和方法；首点失败不能
直接归咎于平坦区。确认取向正确、部分轨迹已走出后，平坦区校正失败可依次提出：

1. 缩小 StepSize，例如由 10 到 5，比较已接受点、失败位置与轨迹，而非只看退出码。
2. 校正仍在改善但达到次数上限时增大 MaxCycle，例如由 20 到 40；
   不能用增加 MaxPoints 代替校正器收敛，也不用 `ReCorrect=Never` 掩盖失败。
3. 若 Hessian 更新不足，核对方法/算法支持后改用 CalcAll（每点重算），
   或 `irc=(calcfc,recalc=N,...)` 定期重算；N>0 为每 N 个预测步，
   N<0 为每 |N| 个校正步，ReCalc 仍需指定初始 CalcFC/RCFC，且要求解析二阶导数。
   语义见 [Gaussian IRC 手册（镜像）](https://theochem.mercer.edu/chm295/g09ur/k_irc.htm)；
   使用前核对实际版本，说明增加 Hessian 计算的成本。

每次修改均提出新 Attempt，展示完整参数、依据和代价，经人确认后提交；
这不是自动重提阶梯。L3 A/B 已观察到：正确 Input 坐标的 RCFC 与独立 CalcFC
部分轨迹高度吻合，均越过原先首点失败，但随后仍有校正失败；四方向均未走完，
不能写作端点一致或完整验证。L3-C/D 的实测结果待主 study 会话提供后补充，
包括失败位置、校正行为、完整性、端点身份及成本；当前不预填成功结论。

端点仍有虚频或优化不收敛，转 [失败诊断](failure-diagnosis.md)；出现断开的片段时先请人确认每个片段身份、电荷与多重度，不能直接当普通单分子超分子优化，也不能把片段电子能之和叫反应自由能。缺所需能力或证据时写具体阻塞，停止依赖它的工作。

## 8. 常见坑

知识衔接：[GKB-0441：IRC 完成证据与 RCFC 取向陷阱](../../auto-g16-gaussian-learning-library/references/core-job-types.md)。

以下改写自 [archive/skills/auto-g16-ts-irc/SKILL.md](../../../archive/skills/auto-g16-ts-irc/SKILL.md) 的 Safety and scope、Workflow 和 Interpretation gates，仅保留科学经验：

- Forward/Reverse 是数学方向，化学反应物/产物标签由端点比对决定。
- 第一点校正失败要排查起点几何与力常数取向；相同 chk 哈希、起点能量和对齐 RMSD 不能排除 RCFC 坐标系错配。
- MaxPoints 的最后一帧不等于极小点；端点需独立 Opt+Freq 并核对身份。
- 断开片段有近自由相对平移/转动，不能假定存在唯一有限距离极小点。
