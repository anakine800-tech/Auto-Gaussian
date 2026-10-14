# TS 优化与频率

## 1. 适用范围

主族闭壳层、同一势能面的过渡态候选优化与频率审核。适用于人提供并审阅过的单结构初猜；不做自动反应发现、金属、开壳层或跨自旋面搜索。通过本卡只得到方向经审阅的一阶鞍点候选，路径验证还需 [IRC](irc.md)。

## 2. 前置条件

[机理假设](reaction-plan.md)已由人签字，目标步骤、反应物/产物身份和原子对应明确；结构与代表构象集合已确认。预先列出正在形成、断裂或迁移的原子对（按输入行号，从 1 开始），并说明方法依据、溶剂、电荷、多重度。初猜来源可选（科学策略提炼自 [旧设计 R10](../../../archive/docs/end-to-end-reaction-computation-workflow.md)）：

- Hessian 引导的单结构初猜：已有合理 TS 状几何时，用反应坐标与曲率信息判断适用性；CalcFC 不能弥补错误原子映射。
- 沿反应坐标做一维弛豫扫描：记录坐标、范围、步长、冻结项及选点依据，能量最高点仅是初猜，具体做法见下。
- QST2/QST3：端点须有相同原子组成、实际行顺序与对应；QST3 还需 TS 初猜。使用已支持的 QST 多结构输入，逐组审阅实际坐标与位移摘要。
- 类比已知 TS：记录 DOI/结构来源、映射及差异；类比几何不意味着该方法或机理已获验证。
- 扫描初猜可用 `ag scan-peak`；全自动 TS 搜索不在当前范围，工具给的结构仍需人工审阅。

### 初猜来源：一维弛豫扫描

优先选目标反应**正在形成的键**的两个原子编号，以距离逐步缩短的方向扫描；
断键、键角或二面角只有在机理假设支持时才选。范围从合理接近构型跨过预期
成键区域，避免初始原子重叠；先粗扫再围绕候选峰细扫。例如成键距离可先试
每步 0.1 Å，再依据曲线改为 0.02–0.05 Å；这些是探索起点，不能代替体系判断。
质子转移或同步成断键用单一坐标可能偏离路径，保留其他通道与构象的比较。

先用 xTB 便宜预扫描，再以候选区域做同一坐标的 DFT 弛豫扫描，或将审阅后
的候选直接作为 DFT TS 优化初猜。xTB 的约束是势能惩罚，实际几何值可能偏离
目标值；facts 同时报告两者，能量为 xtbscan.log 中扣除约束偏置的 Hartree 值。
[`xTB 约束/扫描语法`](https://xtb-docs.readthedocs.io/en/latest/xcontrol.html)示例：

```text
$constrain
  distance: 1, 2, auto
$scan
  1: 3.0,1.4,17
$end
```

这里的 `1` 是内部坐标约束序号（不包括 force constant 或 atoms 项）；先替换
为已审阅的原子编号。仅允许一条 scan、1–100 点，prepare 会自动启用 verbose
以保留逐点收敛证据。scan-peak 至少需要三点；虽然校验接受单点，
[xTB 6.7.1 插值](https://github.com/grimme-lab/xtb/blob/v6.7.1/src/constrain_param.f90)
的分母为点数减一，实际扫描应避免单点设置。`ag prepare --template xtb --input <起始.xyz>
--constraints <扫描.inp> --param=--gfn=2 --param=--opt` 再加通用 study、tier、
walltime、label 和 method-basis 参数。SCNet 使用已配置的 `--cluster`，仍须
人在 Mac 点击提交确认；不通过卡片拼接远程命令。

DFT 输入用 `opt=modredundant`，采用默认 Å 坐标（不带 Units 选项，避免摘要
单位与扫描范围错配）；显式坐标后留空行，再写一个段，例如：

```text
B 1 2 S 16 -0.1
A 3 1 2 F
```

上述原子编号必须按结构替换，F 项只在有科学依据时保留。B/A/D 分别为键、角、
二面角；最多一个 S，1–50 步，距离单位 Å、角度单位度；Gaussian 包含初始点，
终值为初值加步数乘步长。F 不写附加值。不得与 TS/QST2/QST3 混用扫描段。
prepare 摘要显示编号、元素、初值、步数、步长、终值和冻结坐标，逐项审阅。

取回后运行 `ag facts <attempt>`，再运行
`ag scan-peak <attempt> --out <新文件.xyz> [--json]`。查看所选点两侧各两个点
（边缘处只列存在的点）的实际坐标值、能量和收敛状态，并检查全部扫描曲线：

- “范围不够，峰可能在范围外”：端点能量不低于所选内部点；端点不会导出，扩大
  有物理依据的范围后提出新 Attempt，不能把单调曲线里的内部最高点当成峰。
- “可能跳到了另一条路径或另一个构象”：相邻能差超过 20 kcal/mol，或按原子编号
  对齐的全原子 RMSD 超过 0.5 Å。仅为启发式提示；检查结构、电子态和坐标步长，
  不能自动删除这些点或断言机理改变；平滑曲线也不能证明同一路径。
- “有未收敛的点或收敛证据缺失”：这些点不参与选择；缺点可能隐藏真正最高点。
  回看原日志并人工决定是否重新设计扫描；不自动重提。

scan_points.xyz 保存各已报告点的最终几何；未收敛点只是最后迭代几何，未计算点
无几何。文件已存在且相同则沿用，不同则停止核对；scan-peak 的输出必须是新文件。
用最高点做 `opt=(ts,calcfc)` 时，**将该 XYZ 的原子坐标显式写入 Gaussian 输入**
（去掉 XYZ 的原子数和注释两行），重新展示方法、电荷与多重度及立体警告；
移除扫描/冻结段，不使用 `Geom=Check/AllCheck`。随后仍需 Freq、恰好一个虚频、
振动方向人工审核及双向 IRC 端点识别，扫描最高点自身不能判定 TS。

按 R10 为每个基元步骤与立体通道列出催化态、结合方式、构象、接近拓扑、
离子对/添加剂排布；不能只手工造一个 major 和一个 minor 就声称覆盖完整。
路径/链式搜索仅在工具支持并可审阅时作为候选策略，不编造执行接口。

涉及质子转移时，比较直接迁移与有化学依据的显式溶剂或质子穿梭分子辅助
路线；说明分子数、质子供受体与来源，并按 reaction-plan 的 R03/R06 配平
参考态，不能仅给 TS 加水而让反应物参考态少一个水分子。

**柔性 TS：先固定反应中心，再做构象搜索（T13-4）。** 固定有依据的成断键
距离/关键角度，探索外围可转键、结合方式及穿梭分子排布；保留约束与
几何来源，再解除搜索约束做真正 TS 优化、Freq、方向审核及双向 IRC。
约束构象不是已经验证的鞍点；使用 [CREST 卡片](crest-screen.md) 的
`--constraints` 准备经审阅的约束搜索，不把普通无约束 CREST/RDKit 极小点
搜索冒充该步骤，也不强套极小点的窗口剪掉整条 TS 通道。
TS 族必须双路线：约束 CREST 与按特定相互作用/进攻方向假设定向构造后
约束 CREST（directed）；关键中间体、复合物同样必须，可旋转键较多也建议。
按 [构象工作流](../../auto-g16-structures/references/conformer-workflow.md)
合并来源、做同层级单点并读 coverage 的未匹配项、最低构象来源和低能独有项。
出现“采样可能不足”时讨论延长 CREST、对适用极小点增加 ETKDG 种子或补
定向构造，经人确认扩大后重出报告；覆盖报告不能证明采样已经完备。

保留所有失败搜索、错误鞍点、振动模式塌缩、组分脱离及重复收敛，记录
步骤/通道、初猜策略、构象来源、实际结果与后续处置（R10）。有限预算只能
支持有限覆盖；失败的搜索不等于该机理不存在。

## 3. 输入模板

方法/基组：见 [acceptance-methods.md](../../auto-g16-study/references/acceptance-methods.md)。
骨架中的 `<方法/基组>` 必须按已审阅方案替换，并补齐适用的色散与溶剂设置。

单结构 route 示例 `opt=(ts,calcfc,noeigentest) freq`。以下仅为[研究方法](../../auto-g16-study/references/acceptance-methods.md)的输入骨架，填入已审阅的显式坐标，保留空行；正式方法须另有文献依据或明确兜底声明。

```text
%chk=ts.chk
%nprocshared=8
%mem=10GB
#p <方法/基组> opt=(ts,calcfc,noeigentest) freq

<TS 步骤与构象编号>

<charge> <multiplicity>
<element> <x> <y> <z>

```

阴离子弥散、色散和溶剂按方法表及已签方案填写，展示最终完整 route。决定结论的关键能垒按方法表
做不同类型泛函的单点敏感性，包含 TS 和完整参考物种；连接到 [profile](profile.md)。`NoEigenTest` 仅关闭优化中的曲率检查，不免除最终 Hessian、虚频数量和方向审阅。

```text
ag prepare --study <study_id> --template gaussian --input <ts.gjf> --tier simple --walltime 24:00:00 --label ts-c01 --method-basis <DOI及位置或兜底方法说明>
```

有真实上游 Attempt 才使用已有 `--parent` / `--relation` 参数；人提供的外部结构在 study 记录来源，不虚构 parent。复用父 chk 时，同时声明 `--parent <parent_id> --relation ts_from --parent-chk <parent_id>:<父输入中声明的chk文件名>`。父 Attempt 必须为 finished/fetched，submit 确认前和确认后都核对调度器中已无该作业；父子必须在同一集群。

例如经审阅可复用波函数与力常数时，使用以下 Link0/route 替换上面的相应行，标题、电荷多重度和**显式坐标仍须写在输入中**：

```text
%oldchk=parent.chk
%chk=ts-reuse.chk
%nprocshared=8
%mem=10GB
#p <方法/基组> guess=read opt=(ts,rcfc,noeigentest) freq
```

RCFC 需要父 chk 中确有适用的力常数；仅复用波函数可用 `guess=read opt=(ts,calcfc) freq`。核对父 chk 的方法、几何、原子顺序、电荷与多重度是否适用；哈希相同不代表科学上适用。`Geom=Check` 和 `Geom=AllCheck` 继续拒绝，`%chk` 必须不同于固定的 `%oldchk=parent.chk`。

RCFC/ReadFC 复用时，先对父 Attempt 运行 `ag facts`，显式坐标取
`final_input.xyz`（最终几何的 Input orientation，去掉 XYZ 前两行），保持原子顺序，
不能直接拿通常为 Standard orientation 的 `final.xyz`。facts 分别记录取向；
未打印 Input 表时不臆造该文件，须核对原日志或改用 CalcFC。
prepare 已对 `--parent-chk` + RCFC/ReadFC 按固定原子顺序校验输入与父作业 `final_input.xyz` 的坐标，每个原子的偏差
不得超过 1e-4 Å，不做旋转/平移对齐。旧导出文件相同则沿用，不同则停止人工核对。
若后续要复用本 TS 的力常数，可在计算该 TS 时加入 `nosymm`，使两种取向一致；
父 route 已带 `nosymm` 时可取任一导出坐标，仍须匹配父几何。
仅在子作业加 `nosymm` 不能修正父 chk 已有的框架；取向匹配不替代力常数适用性审阅。

prepare 只做本地声明；submit 在 Mac 弹窗前只读取得父 chk 大小与 SHA256，并显示父 ID、来源文件名、大小、哈希前 12 位及目标 parent.chk。确认后专用操作独占创建副本，源/目标哈希都须等于确认值；父文件只读。远端需 Python ≥ 3.6 和 Linux /proc 支持固定描述符助手，缺少即停止；先运行 `ag doctor --cluster <cluster>` 查看 Python 版本和 /proc 支持。复制失败、255、超时或哈希改变均记 failed_presubmit，不 qsub、不重试、不删除副本；报告后由人决定新 Attempt。

## 4. 资源建议

小体系首先提出 simple（8 核 / 12 GB，`%mem=10GB`），24:00:00；规模或已有耗时支持时提出 general（22 核 / 50 GB，`%mem=42GB`），48:00:00。complex（44 核 / 120 GB，`%mem=100GB`）需具体资源理由。CalcFC 与 Freq 均有 Hessian 成本；每个 TS 构象分别估计，不把加核当作收敛修复。

## 5. 提交前检查清单

- 假设签字、初猜来源、目标成键/断键原子对、构象覆盖与原子映射均明确，结构无未解释近接触。
- 身份、电荷、多重度、立体化学与目标一致；route 的方法、色散、溶剂与比较物种一致。
- 坐标和占位符已替换；核数匹配档位，内存不超过 85%，chk 仅文件名；当前输入不依赖尚未支持的额外段；使用父 chk 时核对附件声明和确认摘要。
- 按 [确认摘要](../../auto-g16-study/references/confirmation-summary.md)展示结构、立体警告、方法依据、完整 route、资源、walltime、远程目录、输入哈希；等人确认并亲手点击提交对话框。

## 6. 结果判据清单

- `termination=normal`、`opt_converged=true`、`freq_step_converged=true`；缺失/不通过则读原日志，不能推定通过。Opt 和 Freq 都已完成，完整模式数应为非线性 3N−6 / 线性 3N−5。
- **恰好一个虚频**：`n_imag=1`，按原始负频计数，小负频也不能删掉凑数。零或多个虚频均不满足 TS 判据。
- **振动方向对应目标键变化**：逐项核对 `facts.json` 的 `imag_modes[].pairs[].atoms`、`elements`、`distance`、`distance_change_rate` 与目标原子对。全局振动正负号任意，须查看同一方向上成键缩短/断键伸长等协调变化，不能仅靠频率大小或单个符号判断。
- 当前 `imag_modes` 只列距离小于 3.5 Å 的原子对中变化率绝对值最大的五对；缺目标对并不证明它不动。结合原日志完整位移与几何人工审核（必要时看动画/正负位移），缺证据写不通过并停下，不杜撰模式查看命令。
- 确認最终身份与预期一致；柔性 TS 列出审阅过的构象和未覆盖部分，不将单个 TS 的能量直接当作唯一反应能垒。
- `review.md` 写清判据、事实位置与人的方向审核意见；更新 study 假设。通过后只提出双向 IRC，未完成端点识别不能写“已验证 TS/机理”。

## 7. 常见失败与处理

零虚频说明落到极小点或尚缺完整证据；多虚频可能是高阶鞍点或软模问题；方向错误可能是另一步反应。分别核对完整输出和结构，重审初猜/构象或假设，转 [失败诊断](failure-diagnosis.md)；提出新 Attempt，等人确认。

需要多维扫描、白名单外输入段或尚未支持的自动初猜时，写明具体缺口并暂停该步骤。真实作业异常先停止报告；不在原 Attempt 重跑，不用旧 Skill 执行。

## 8. 常见坑

知识衔接：[GKB-0431、GKB-0422：TS 验证与优化排障](../../auto-g16-gaussian-learning-library/references/core-job-types.md)。

以下科学经验改写自 [archive/skills/auto-g16-ts-irc/SKILL.md](../../../archive/skills/auto-g16-ts-irc/SKILL.md) 的 Safety and scope、Workflow、Interpretation gates；仅追溯经验，不恢复其历史流程：

- Opt 结束时抓到的截断日志不能当作完整 Freq；须查完整模式数及位移。
- 一个负频只是候选，键变化方向审核和双向 IRC 端点识别不可省略。
- QST 同元素原子交换也可能改变反应映射；外部映射表不能修复实际输入行顺序。`End of file in ZSymb` 后不要反复试换空行提交。
- 父 chk、几何和原子顺序不一致会把 IRC 引向错误起点；RCFC 坐标取 `final_input.xyz`，或预先在父 TS 使用 `nosymm`。副本哈希、对齐 RMSD 及相同起点能量均不能证明坐标框架正确。
- 解离片段的近自由平移/转动可能导致优化困难，不默认把多个孤立片段当普通单分子极小点。
