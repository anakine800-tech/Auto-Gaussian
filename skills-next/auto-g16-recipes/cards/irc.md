# IRC 双向路径与端点

## 要点

- 两侧沿同一已审核 TS、同一方法和原子映射出发，分别创建 Attempt；见[前置条件](#2-前置条件)。
- RCFC 读取父 Freq 的力常数，必须保持父 TS Input 坐标框架；见[输入模板](#3-输入模板)。
- 两个方向分别核对连续性、降能、目标键长中点及独立端点极小点与身份；见[结果判据](#6-结果判据清单)。
- 正常退出、MaxPoints 或部分轨迹不能单独作为完成证据；工具核对后仍需人工审阅；见[结果判据](#6-结果判据清单)。

## 1. 适用范围

从已审核的一阶鞍点沿同一主族闭壳层势能面追踪两个方向，并识别连接的极小点。**IRC 必须两个方向都走完并识别端点后才能声称验证。** 一次正常退出或仅一个方向不满足此标准。“走完”按第 6 节逐方向核对，允许满足全部四条判据的有限步 IRC 加独立端点 Opt+Freq。

## 2. 前置条件

[TS 搜索卡片](ts-search.md#6-结果判据清单)的优化、完整频率及恰好一个虚频判据通过；手动模式目标方向须经人审核。符合 [AGENTS 自主运行规则](../../../AGENTS.md#自主运行)时，可按已确认计划初查方向后继续 IRC，逐条标“待人确认”，不能据此声称方向已获人工接受；[机理假设](reaction-plan.md)已签字，阶段导航与结果登记见 [TS 入口](ts.md)。两个方向使用同一 TS 候选的最终几何、原子顺序、电荷、多重度和方法；预先列明可能的反应物/产物与原子映射，不预设 Forward 就是产物。

按**各产物分支内部**的重要性和结构新颖性安排 IRC，不按全局权重筛掉次要分支。以下情形必须做 IRC：

- 引入新的成断键集合或质子转移方式。
- 引入新的活化模式。
- 在所属产物分支内贡献显著。
- 改变最低 TS 排名或明显改变预测的 ee / dr。
- 模式或产物归属存在歧义。

高选择性反应中次要产物的全部 TS 全局权重都可能很小，但它们决定 er 的分母。暂缓 IRC 的候选仍是“未验证”，不能称为已验证；任何“TS 已验证”仍须恰好一个虚频、振动方向经人审核符合目标反应坐标、双向 IRC 走完并识别端点。IRC 两端必须继续独立 Opt+Freq 并确认为极小点，有限步数的路径终点不能直接当作稳定物种。
来源：[T139](../../../docs/redesign-tasks/T139-card-wording.md) A5/X3、[AGENTS.md 第 6 节](../../../AGENTS.md)。

当前 ag 可准备单结构显式坐标输入，并用 `--parent-chk` 声明父 chk 副本。后续方向完成、端点提取和连接比对须另行核对对应工具与证据。若缺少所需能力或证据，停止相关步骤并在 study 记录缺口；本卡不承诺现有 ag 可自动跑通完整 IRC 验证。

## 3. 输入模板

下列 Link0 数值、档位和 walltime 仅为输入骨架示例，须按所选入口与已审阅资源替换。`%nprocshared`、`%mem` 可省略，由 prepare 按实际档位补齐；显式核数须匹配档位，内存仍检查不超过档位的 85%。

方法/基组：见 [acceptance-methods.md](../../auto-g16-study/references/acceptance-methods.md)。
骨架中的 `<方法/基组>` 必须按已审阅方案替换，并补齐适用的色散与溶剂设置。

Gaussian 路线形式为 `irc=(calcfc,maxpoints=<点数>,stepsize=<步长>,forward)`，反方向将 `forward` 改为 `reverse`。例如以下单结构骨架在起点重新算力常数，不读取父 chk；50 和 10 仅是待审阅示例值，不保证走到极小点。

Gaussian 官方 [IRC 手册的 StepSize 与坐标选项](https://gaussian.com/irc/)规定：正值的步长单位为 0.01 Bohr，负值表示以 0.01 amu½·Bohr 为单位；默认路径坐标为质量加权 Cartesian（2026-10-29 核对）。这是关键词语义，不是固定步长的适用性保证；使用时仍核对本机 G16 修订版手册，不能照搬旧版转载。
从 IRC 输出开头读取 Gaussian 实际打印的步长和坐标类型，连同修订版、
原文及日志位置记入 `review.md`；不能把输入中的 StepSize 数字直接当作
某根键的 Å 增量。未打印或无法确认时明确写缺失，核对本机手册与完整输出，
不凭 route 或示例值补写实际单位和坐标类型。

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
方法、色散和溶剂（溶液相含 SMD）必须替换为该 TS 的实际设置。另建 reverse 输入、标签和 Attempt；每个方向均保存完整输入摘要，手动模式提交前展示并确认；授权按 Study 模式规则核对。已有准备接口如下（反方向相应换输入和标签）：

```text
ag prepare --study <study_id> --template gaussian --input <irc-forward.gjf> --tier simple --walltime 24:00:00 --label irc-forward --card irc --parent <ts_id> --relation irc_from --method-basis <与 TS 相同的依据：文献先例 DOI 及位置 / 本课题既有方案及来源（不是文献先例，精度未经验证） / 兜底方法声明>
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

反方向另建 Attempt，改为 `reverse` 和 `%chk=irc-reverse.chk`，引用同一父 chk。**坐标仍须显式写在输入中**；`Geom=Check`/`Geom=AllCheck` 不允许。RCFC 读取先前完整频率计算得到并保存在父 chk 中的笛卡尔 Hessian，不能用优化更新的近似 Hessian 或 xTB 本地导入分析冒充；官方语义见 [IRC：Options For Generating Initial Force Constants](https://gaussian.com/irc/)（2026-10-29 核对），取向要求沿用下面 T25 检查。Guess=Read 也须核对方法、电荷、多重度、原子顺序和几何。

使用 RCFC/ReadFC 前，对父 TS 运行 `ag facts`，坐标取其 `final_input.xyz`
（最终几何的 Input orientation，去掉 XYZ 前两行），保持原子顺序；
`final.xyz` 通常是 Standard orientation，无标准取向时可能退回输入取向，
以 facts 的 `final_geometry_orientation` 为准。缺少 Input 表时不会臆造
`final_input.xyz`；需核对原日志或改用 CalcFC。
prepare 已在 `--parent-chk` + RCFC/ReadFC 时逐原子校验输入与父作业 `final_input.xyz` 的坐标，容差 1e-4 Å，
不做旋转、平移或原子交换；父 TS 的 route 带 `nosymm` 时，两种取向相同，
可用任一导出文件。也可预先让新的 TS Opt+Freq 带 `nosymm`；
仅对子 IRC 加它不能补救父力常数与输入坐标的框架错配。

可按 [TS 搜索的父 checkpoint 证据说明](ts-search.md#父-checkpoint-本地证据)运行 `ag parent-chk-report`，分别核对频率执行、历史复制关联和坐标来源；报告始终不核验 chk 内部力常数，科学适用性仍需人审。日志有 Freq、固定行坐标吻合或历史哈希相同都不能直接证明 RCFC 可用。

prepare 纯本地；submit 的父 chk 摘要、独占复制、源/目标哈希及失败停止要求沿用 [TS 搜索的父 chk 流程](ts-search.md#3-输入模板)。父文件只读，复制失败、SSH 255、超时或哈希变化不重试、不提交，不用本地报告代替提交时核验。

两侧端点坐标经审阅后，要各自再按 [Opt+Freq](opt-freq.md)优化为极小点；可用现有 parent/relation 参数记录 `endpoint_of` 来源。`ag facts <irc_id>` 提取 `irc` 字段及 `irc_end.xyz`；后者只是最后报告路径点，不是已验证的端点。手动模式先请人确认；符合 [AGENTS 自主运行规则](../../../AGENTS.md#自主运行)时，可按计划暂定选择坐标继续端点计算，逐条标“待人确认”，不代替最终端点识别。

## 4. 资源建议

每个方向先评估 simple，再参照 TS 实际耗时考虑 general 或入口其他已配置档位；档位核数、内存及默认值按[资源表达](../../auto-g16-study/references/acceptance-methods.md#资源表达)和所选入口实际配置核对，保存值以 manifest 为准，walltime 仍须明确。计入两次 CalcFC、路径各点和两个端点 Opt+Freq 的成本。MaxPoints 是上限，不是完成证据；增大点数/减小步长会增加代价，需新方案和确认。

## 5. 提交前检查清单

- 起点是按第 2 节完成 TS 及方向核对的同一个几何；两份输入元素和原子行号一致，方向关键词明确且不重复。
- 方法、电荷、多重度、溶剂与 TS 一致，CalcFC 的来源和代价已说明；采用 RCFC 时核对父力常数适用性、`final_input.xyz` 取向（或父 TS 的 `nosymm`）、附件声明和确认哈希。
- 结构、立体警告、方法依据、完整 route、资源档位、walltime、远程目录和输入哈希均已保存，手动模式提交前展示；提交仍须按 [Study 流程](../../auto-g16-study/SKILL.md)取得对应模式的提交授权。
- 端点获取和人工审阅路径已说明；解析或比对证据缺失就记录具体缺口，不把通用终止字段当成 IRC 专用完成标志。

## 6. 结果判据清单

- 两个方向分别从 IRC 输出开头核对实际打印的步长和坐标类型，并将 Gaussian 修订版、打印原文及日志位置记入 review；单位按本机 G16 手册核实，缺证据明确写无法确认，不从输入数值推定。
- 每个方向分别核对完整原日志、路径点、校正器收敛、终止原因和最终几何；核对 `facts.json` 的 `irc.direction`、`point_count`、`path_complete_reported`、`reached_max_points` 和 `corrector_failed`，并回查日志，不能只看 `termination=normal`。这些字段是程序报告的事实，不自动给出下面的科学完成结论。

每个方向必须同时满足以下四条才算“走完”，逐项在 review 记录数值、几何来源和日志行号：

1. 已接受的路径点没有校正器失败，也没有能量跳跃或折返。审阅能量曲线、逐点几何、
   关键键长及 SCF/电子态连续性；有校正器失败或输出截断时不能截掉异常部分声称完成。
2. 最后一个路径点的能量比 TS 至少低 **3 kcal/mol**。这是默认判据，计算方案可另定，
   所用阈值及依据须写进 review；比较同一方法、溶剂与电子态下的电子能，不混入端点 G/qRRHO。
   降能为正但低于阈值、且①工具部分未发现问题、③④均满足时，可记为“由端点优化补证”，
   写明实际降能、阈值和端点证据；阈值不因此调低，①的人工审阅仍须完成。
3. 目标成键或断键的键长已从 TS 值越过它与该侧预期端点值之间的中点。
   记录目标原子对、端点参考来源、TS/最后路径点/预期端点的键长及中点；
   向该侧成键时最后键长须小于中点，断键时须大于中点，多个目标原子对逐项核对。
4. 从最后一个路径点出发，独立的 Opt+Freq 已收敛为极小点，满足频率阶段收敛、
   完整模式数和零虚频；并由下述 `irc-compare` 比对与人工审阅确认是该侧预期物种。

`ag irc-review` 将上述四条按方向核对并导出 JSON、Markdown 和逐点 XYZ；
`reference` 是人指定的该侧预期端点，原子顺序须与 TS 一致，不能预设 forward 的化学身份。

```text
ag irc-review --study <study_dir> --ts <ts_id> --forward <forward_irc_id> --reverse <reverse_irc_id> --pair <I-J> --forward-reference <expected_forward_id> --reverse-reference <expected_reverse_id> --forward-endpoint <forward_opt_id> --reverse-endpoint <reverse_opt_id> --irc-compare analyses/<compare>.json --out analyses/<new_review>.json
```

判据①最高仅为 `tool_checks_passed`；②可为 `met_by_endpoint_optimization`，实际降能仍按路径末点计算。
缺 reference、端点优化或身份报告时对应项为 `unknown`。输出“工具核对完成，待人工审阅”不是验证结论；
须继续核对 SCF/电子态连续性、逐点几何及端点身份。路径数据格式见 [ag-irc-review/1](../../../docs/ag-irc-review-1.md)。

- 达到 MaxPoints 但满足以上四条，算该方向走完；任意一条不满足或缺证据，仍写“IRC 未完成”。两侧必须分别满足四条，保留与同一 TS 的原子映射和来源；缺一侧就不能声称验证。
- 用 `ag graph --study <study_dir> --json` 核对 TS → 两个方向 → 端点优化的 Attempt 来源。`ag graph` 仅为来源图；另用 `ag irc-compare --ts <ts_id> --forward <forward_endpoint_opt_id> --reverse <reverse_endpoint_opt_id> --reactant <reactant_id> --product <product_id> --out <新报告.json>` 获取保留原子编号的连接、质子和立体差异。这里 forward/reverse 传入各侧独立 Opt+Freq 的 Attempt，而非未经优化的最后路径点。工具的“匹配 / 不匹配 / 无法确定”仍须人工审阅，写入 review；来源图不能替代此比较。缺少可审阅的几何或匹配证据就保持未验证。
- 两侧确实连接目标反应物与产物后才赋予化学标签；连接其他物种则如实记录并更新机理假设，不强改标签。任何“验证”结论均须具备双向完成和已识别极小点证据。

## 7. 常见失败与处理

`Maximum number of corrector steps exceded`、很快停止、两个方向折回同一侧、达到 MaxPoints 但未满足第 6 节四条判据，或一侧失败时，保留结果并写明“IRC 未完成”。先核对 TS 的定位精度（残余梯度、曲率及目标模式）、原子映射、RCFC 取向与同一势能面设置；不能先把首点失败归咎于平坦区。

补救的证据、一个最小改动和复验统一见 [失败诊断症状表](failure-diagnosis.md#症状与最小补救)。起点问题排除后才按轨迹证据选择步长、校正次数、点数或算法；固定 StepSize 示例不适用于所有体系，MaxPoints 不能替代校正器收敛，也不用 `ReCorrect=Never` 掩盖失败。参数修改须核对实际 Gaussian 版本与成本。

每次修改均提出新 Attempt，保存完整参数、依据和代价，手动模式经人确认后提交；
这些建议不授权重提旧 Attempt；新 Attempt 的有界补救按 [失败诊断](failure-diagnosis.md)和上述 AGENTS 模式规则处理。

**L3 流程验收实例（T46 之前的历史验收）：**
015/016 用 Standard 坐标读取父 Hessian，双向首点校正失败；
A（017/018，CalcFC）与 B（019/020，父 TS Input 坐标的 RCFC）均接受 forward 11 点、reverse 2 点，随后在第 12/3 点失败。
A/B 部分轨迹高度吻合，证实 Input 坐标读取正确、取向问题已解决，剩余为校正困难；部分轨迹不等于双向完成。
C（021/022）将 StepSize 从 10 缩至 5、MaxCycle 从 20 增至 40；D（023/024）同用 5/40，但改用 CalcAll 逐点重算 Hessian。
C/D 同批提交，并非沿阶梯依次尝试；各组 MaxPoints=50，C 接受 24/6 点后在第 25/7 点仍校正失败，D 则 44/6 点双向正常结束。
在此例中解决校正失败的是逐点重算 Hessian，单靠缩小步长或增加 MaxCycle 不够；D 的 IRC CPU 核时约为 C 的 1.4 倍。
D 两侧末点分别经 027/028 独立 Opt+Freq，均收敛、模式完整且零虚频；irc-compare 与人工审阅确认 forward 为产物复合物、reverse 为反应物复合物。
T79 在 2026-10-16 对本地日志只读核对：D 两侧①工具部分通过，③两对目标键长均越过中点，④由 027/028 与已有 irc-compare 支持。
D forward 末点降能 26.411921 kcal/mol；reverse 为 0.281638 kcal/mol，低于默认 3 kcal/mol，按修订后的②记为“由端点优化补证”，阈值不变。
两侧工具汇总均为“工具核对完成，待人工审阅”；①仍缺完整连续性审阅记录，不能据此声称双向完成。
A/B/C 的已接受点数和后续校正失败、015/016 的首点失败均与上述历史记录一致；这些组没有末点优化证据，④为 unknown。
以上经验仅适用于 B3LYP-D3(BJ)/6-31+G(d) 气相小体系，不作为默认参数。

端点仍有虚频或优化不收敛，转 [失败诊断](failure-diagnosis.md)。双分子步骤与复合物按 [complex](complex.md) 卡片执行，仅开放以已审阅原子对为约束的采样；通用对接搜索不开放。出现两个片段时，按 [complex](complex.md) 卡片识别组分，先请人确认每个片段的身份、电荷与多重度，再决定与复合物还是分离物种比较；不能直接当普通单分子超分子优化，也不能把片段电子能之和叫反应自由能。其他片段数同样先审阅组分并说明适用范围。缺所需能力或证据时写具体阻塞，停止依赖它的工作。

## 8. 常见坑

知识衔接：[GKB-0441：IRC 完成证据与 RCFC 取向陷阱](../../auto-g16-gaussian-learning-library/references/core-job-types.md)。

以下改写自 [archive/skills/auto-g16-ts-irc/SKILL.md](../../../archive/skills/auto-g16-ts-irc/SKILL.md) 的 Safety and scope、Workflow 和 Interpretation gates，仅保留科学经验：

- Forward/Reverse 是数学方向，化学反应物/产物标签由端点比对决定。
- 第一点校正失败要排查起点几何与力常数取向；相同 chk 哈希、起点能量和对齐 RMSD 不能排除 RCFC 坐标系错配。
- 达到 MaxPoints 不自动代表完成或失败；须满足第 6 节四条判据，最后路径点的独立 Opt+Freq 与身份比对不可省略。
- 断开片段有近自由相对平移/转动，不能假定存在唯一有限距离极小点。
