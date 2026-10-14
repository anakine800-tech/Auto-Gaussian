# IRC 双向路径与端点

## 1. 适用范围

从已审核的一阶鞍点沿同一主族闭壳层势能面追踪两个方向，并识别连接的极小点。**IRC 必须两个方向都走完并识别端点后才能声称验证。** 一次正常退出或仅一个方向不满足此标准。

## 2. 前置条件

[TS 卡片](ts.md)的优化、完整频率、恰好一个虚频及目标方向审核全部通过；[机理假设](reaction-plan.md)已签字。两个方向使用同一已接受 TS 的最终几何、原子顺序、电荷、多重度和方法；预先列明可能的反应物/产物与原子映射，不预设 Forward 就是产物。

当前 ag 可准备单结构显式坐标输入，但跨 Attempt 复用 chk、IRC 方向完成事实的结构化解析、端点提取及连接关系自动比对待 T13。需要这些功能时停止相关步骤并在 study 记录缺口；本卡不承诺现有 ag 可自动跑通完整 IRC 验证。

## 3. 输入模板

Gaussian 路线形式为 `irc=(calcfc,maxpoints=<点数>,stepsize=<步长>,forward)`，反方向将 `forward` 改为 `reverse`。例如以下单结构骨架在起点重新算力常数，不读取父 chk；50 和 10 仅是待审阅示例值，不保证走到极小点。使用前核对安装版本对步长的单位/约定。

```text
%chk=irc-forward.chk
%nprocshared=8
%mem=10GB
#p wB97XD/6-31G(d) irc=(calcfc,maxpoints=50,stepsize=10,forward)

<TS 编号与 forward 方向>

<charge> <multiplicity>
<element> <TS 最终 x> <TS 最终 y> <TS 最终 z>

```

此处为[方法](../../auto-g16-study/references/acceptance-methods.md)的中性骨架，
并非重选 IRC 方法。阴离子或负电荷明显离域的 TS/IRC/端点优化使用
`wB97XD/6-31+G(d)` 等已选定的弥散基组；wB97XD 不叠加 GD3BJ。
方法、色散和溶剂（溶液相含 SMD）必须替换为该 TS 的实际设置。另建 reverse 输入、标签和 Attempt；每个方向完整展示输入摘要并经人确认。已有准备接口如下（反方向相应换输入和标签）：

```text
ag prepare --study <study_id> --template gaussian --input <irc-forward.gjf> --tier simple --walltime 24:00:00 --label irc-forward --parent <ts_id> --relation irc_from --method-basis <与TS相同的方法依据>
```

`irc_from` 只是现有 relation 文本，不会复用 chk 或验证路径。基于 chk 的 RCFC/Geom=AllCheck 输入待 T13，不提供绕行复制命令。两侧端点经人工确认坐标后，要各自再按 [Opt+Freq](opt-freq.md)优化为极小点；可用现有 parent/relation 参数记录 `endpoint_of` 来源。端点自动提取和比对待 T13，不发明端点命令。

## 4. 资源建议

每个方向先估计 simple（8 核 / 12 GB，`%mem=10GB`），24:00:00；参照 TS 实际耗时再决定 general（22 核 / 50 GB，`%mem=42GB`），48:00:00。计入两次 CalcFC、路径各点和两个端点 Opt+Freq 的成本。MaxPoints 是上限，不是完成证据；增大点数/减小步长会增加代价，需新方案和确认。

## 5. 提交前检查清单

- 起点是通过 TS 及振动方向审核的同一个几何；两份输入元素和原子行号一致，方向关键词明确且不重复。
- 方法、电荷、多重度、溶剂与 TS 一致，CalcFC 的来源和代价已说明；需要父 chk 的方案在 T13 支持前暂停。
- 结构、立体警告、方法依据、完整 route、资源档位、walltime、远程目录和输入哈希均已展示，提交仍由人点击 Mac 对话框。
- 端点获取和人工审阅路径已说明；缺解析/比对能力就记录待 T13，不把通用 facts 字段当成 IRC 专用完成标志。

## 6. 结果判据清单

- 每个方向分别核对完整原日志、路径点、校正器收敛、终止原因和最终几何；当前 `facts.json` 不提供专门的方向完成/端点判据，不能只看 `termination=normal`。仅达到 MaxPoints、校正器失败或输出截断不能写“走完”。
- 两个方向均走完，并保留与同一 TS 的原子映射和来源；缺一侧就写“IRC 未完成”。
- 两侧最后路径点分别再优化并做 Freq：满足极小点收敛、频率阶段收敛、完整模式数和零虚频。最后路径点不是自动接受的极小点。
- 用 `ag graph --study <study_dir> --json` 核对 TS → 两个方向 → 端点优化的 Attempt 来源。**当前 ag graph 仅为来源图，IRC 端点与反应物/产物的连接关系自动比对待 T13**。现阶段需人工按相同原子映射核对键连接、身份和立体化学，在 review 写出对应证据；来源图不能替代此比较。缺少可审阅的几何或匹配证据就保持未验证。
- 两侧确实连接目标反应物与产物后才赋予化学标签；连接其他物种则如实记录并更新机理假设，不强改标签。任何“验证”结论均须具备双向完成和已识别极小点证据。

## 7. 常见失败与处理

`Maximum number of corrector steps exceded`、仅到 MaxPoints 或一侧失败时，保留结果，停止报告，审阅起点/方法和积分设置；不能把增加 MaxCycle 或 `ReCorrect=Never` 当通用修复。需要改变 StepSize、MaxPoints 或积分算法时说明理由、代价和方法变化；提出新 Attempt，等人确认。

端点仍有虚频或优化不收敛，转 [失败诊断](failure-diagnosis.md)；出现断开的片段时先请人确认每个片段身份、电荷与多重度，不能直接当普通单分子超分子优化，也不能把片段电子能之和叫反应自由能。缺支持能力记待 T13，停止依赖它的工作。

## 8. 常见坑

以下改写自 [archive/skills/auto-g16-ts-irc/SKILL.md](../../../archive/skills/auto-g16-ts-irc/SKILL.md) 的 Safety and scope、Workflow 和 Interpretation gates，仅保留科学经验：

- Forward/Reverse 是数学方向，化学反应物/产物标签由端点比对决定。
- 第一点校正失败要排查起点几何与力常数来源；不要反复增大迭代数制造成功表象。
- MaxPoints 的最后一帧不等于极小点；端点需独立 Opt+Freq 并核对身份。
- 断开片段有近自由相对平移/转动，不能假定存在唯一有限距离极小点。
