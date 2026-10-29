# T189：诊断卡与现行计算能力说明

## 分支与目标

后端 `codex/t189-scientific-cards`，一单一 PR；对应 V4.8 W10。T182 先合并，本单只补科学说明与已实现能力，不另写自主运行规则。
防范事故：过时的工具说明阻止使用已交付功能，缩放因子说明与代码冲突，或将经验建议误当普遍判据。

## 允许改动的路径

- `skills-next/auto-g16-study/references/acceptance-methods.md`：只纠正设置支持范围，不改研究默认方法/因子/窗口。
- `skills-next/auto-g16-recipes/cards/failure-diagnosis.md`、`profile.md`、`ts-guess.md`、`sp.md`、`opt-freq.md`、`complex.md`、`irc.md`：本单列明的说明与交叉引用。
- `skills-next/auto-g16-recipes/references/ts-initial-guess-guide.md`：已实现本地 Hessian/模式诊断。
- `skills-next/auto-g16-gaussian-learning-library/references/` 下 Markdown：原生能力、方法密度及学习资料；只改本单所需主题。
- `docs/redesign-tasks/T189-scientific-cards.md`：本单。

## 要做的

1. 对照 thermo/profile/GoodVibes 实现分别解释研究默认值、各入口支持设置、选非默认值的来源。频率与ZPE因子用途分开；Gaussian scale 与输出 Frequencies 的关系须以官方资料核实。保持默认1.0。
2. TS初猜卡和指南对照已交付 `ag import-xtb-hessian`、G0单候选模式分析与 docs/g0.md；说明有限本地诊断不等于合格TS、不能当Gaussian力常数复用。
3. 负能垒诊断依次核对相邻极小点、遗漏中间体、字段、Opt/SP层级和分离物种/复合物参考态，不一律判错。
4. SP正常完成但存在长键、强电荷转移或多SCF解迹象时引用稳定性诊断，不统一加Stable=Opt。
5. 失败诊断卡集中一张简短“症状→证据→一个最小改动→复验”表：优化振荡/Hessian/曲率/末期步长/内坐标/对称性/步数不足；SCF先排结构、电荷、多重度；IRC先查TS定位精度，再考虑步长、点数与算法。这是后续自主入口卡引用的唯一补救表，不在多处复制。
6. SP/学习库区分Gaussian原生能量字段、性质所用密度与ag当前解析/thermo/profile支持范围；改变route不等于支持后HF。
7. opt-freq增加complex反向链接；complex定义相互作用能、结合电子能、结合自由能，明确片段几何选择及符号。
8. 固定步长、NoEigenTest、经验虚频范围只作有条件经验；IR/Raman、同位素、后HF密度分析仅进学习库。保留恰好一虚频、方向审阅、双向IRC端点识别与人工签字。
9. 私有培训稿只用于理解和定位，用自己的话改写；引用文献回到原始来源核实DOI/页码/适用边界，无法核实明确留缺口，不复制整段讲义。

## 不允许

不改代码、测试、方法默认值、签字判据或真实研究；不运行量化/集群；不扩大本版到ORCA、开壳层或完整Gen/ECP支持。不改旧卡片快照或历史研究结论。

## 测试

纯文档：隔离环境 `PYTHONPATH=ag/src python -m pytest skills-next -q -rs`；核对代码/CLI、文献、链接、285行/八节卡片格式。代码回归交当前head CI。精确暂存，通用与本机私有词表敏感扫描、差异检查、noreply身份。

## 真实环境验证

纯文档，不需要。科学建议来源核实与实际体系验收分开，不宣称新方法已验证。

## 停止条件与交付

范围外或方法口径变更须报告；同一问题两次未解决停止。PR首行 `Task: T189`，列每项对应位置与原始出处、实际测试和未核实信息。与T182改同卡：先rebase再复核判据与规则一致。协调会话独立审阅并合并，开发会话不合并。

## 本次修订与核实（2026-10-29）

最初基于 `4fce3cf7305bd57eb31525e54bb3edcc70b71986` 独立完成科学内容并创建 PR #376；
T182（PR #375）合并后，按协调方指示变基至 `origin/main` 的
`694d43633b505512cbfa24f851c240973e6c38e8`。已读新 AGENTS，五张冲突卡片逐处合并：
保留科学修订和唯一补救表，沿用 T182 的模式权限、中间判断与最终签字边界，
将其“积分网格改变须人确认、不得自主执行”原有要求保留在集中表前；不另写自主规则。

| 工单项 | 修订位置与核对依据 |
| --- | --- |
| 1 频率/ZPE | acceptance-methods 的“数值设置与热化学依据”、profile 第 2 节；对照 thermo.py、profile.py、_profile_sources.py。默认仍均为 1.0；独立 ZPE 因子在 GoodVibes 4.3.0 不传入 H/G，已注明限制。 |
| 2 本地模式 | ts-guess 第 3 节、ts-initial-guess-guide；对照 xtb_hessian.py、g0.py 和 docs/g0.md。限定已实现构建、来源绑定与单候选，不作为 Gaussian 力常数或 TS 合格证据。 |
| 3 负能垒 | profile 第 7 节、failure-diagnosis“负能垒先核对定义”；按连接的极小点→遗漏中间体→字段→Opt/SP 层级→分离/复合物参考态诊断。 |
| 4 SP 电子态 | sp 第 7 节引用 failure-diagnosis“电子态与 Stable 诊断”；只在疑点下诊断，不普遍加 Stable=Opt。 |
| 5 补救表 | failure-diagnosis“症状与最小补救”；opt-freq、irc、ts-guess 和指南统一引用，所有选项调整保留原 TS/极小点优化类型。 |
| 6 原生能力 | sp 第 2 节、学习库 core-job-types 的 GKB-0410 与 theory-and-methods 的 GKB-0111；对照 cclib SCF 读取与当前方法白名单，不增加后 HF 支持。 |
| 7 复合物 | opt-freq 第 1 节反链 complex；complex“IRC 端点与能量整理”定义三种能量、片段几何、符号及 CP 边界。 |
| 8 条件经验 | failure-diagnosis、irc、TS 指南保留条件与最终验收；IR/Raman、同位素、后 HF 密度说明仅在学习库。 |
| 9 资料边界 | 私有材料仅作理解定位；新增文字自行组织，公开文件只保留原始公开来源和实现定位。 |

原始来源核实清单（官网 HTML 按章节定位，不虚构 PDF 页码）：

- [Gaussian Scale](https://gaussian.com/scale/) Description、[FreqChk](https://gaussian.com/freqchk/) Examples：热化学缩放与打印频率的区别。
- [GoodVibes v4.3.0 thermo.py](https://github.com/patonlab/GoodVibes/blob/v4.3.0/goodvibes/thermo.py) `ThermoOptions/calc_bbe`：独立因子与 H/G 计算；同时核对已安装同版源码。
- [明尼苏达频率因子数据库](https://comp.chem.umn.edu/freqscale/) Introduction：谐频、基频、ZPE 分类；Alecu 等 [DOI:10.1021/ct100326h](https://doi.org/10.1021/ct100326h)，2872–2887 页仅核实书目信息，未采用或核实具体非默认因子。
- [Gaussian Opt](https://gaussian.com/opt/) 力常数、收敛、步长与坐标选项；[SCF](https://gaussian.com/scf/) XQC；[IRC](https://gaussian.com/irc/) 路径、算法与初始力常数；[Stable](https://gaussian.com/stable/) Description / Opt。补救顺序为项目诊断建议，不是关键词对症保证。
- [Gaussian MP](https://gaussian.com/mp/) Examples / Double-Hybrid Methods、[CC](https://gaussian.com/cc/) Examples、[Density](https://gaussian.com/density/) Description / Current / MP2 / CC、[Freq](https://gaussian.com/freq/) ReadFC / ReadIsotopes / Requesting Specific Spectra / Pre-resonance Raman：原生字段与性质能力，不证明 ag 已支持这些分析。
- [Gaussian Counterpoise](https://gaussian.com/counterpoise/) Description / Examples：片段基组校正；本卡显式约定能量符号与几何，未改变 CP 工作流。
- [Gaussian Vibrational Analysis](https://gaussian.com/wp-content/uploads/dl/vib.pdf) §2 p.2、[xTB 固定提交 g98fake2](https://github.com/grimme-lab/xtb/blob/26b28010e805f7d1aeeef39813feb473e69cc4be/src/freq/io.f90#L196-L301)：驻点/同层级要求与显示向量边界；不证明任一候选合格。

验证与保留边界：

- 临时隔离 venv，复用已安装依赖；Python 3.11.15、pytest 9.1.1、RDKit 2026.03.3、GoodVibes 4.3.0；`PYTHONPATH=ag/src python -m pytest skills-next -q -rs`：527 passed。
- 学习库 `audit_library.py`：72 knowledge cards 通过；变基后改动文档 222 个本地链接及锚点通过，七张计算卡保留八节、最多 283 行。
- `git diff --check`、精确暂存后的通用/本机私有词表扫描与 noreply 身份核对；后端全量回归交当前 head 的 CI。
- 无新方法默认、因子、窗口或签字判据变更；未修改代码/测试，未运行量化、连接集群或修改研究、真实配置与服务。
- 科学审阅边界：官网版本说明不替代目标安装版本核验；具体非默认因子与实际体系的精度、电子态、TS/IRC 均未在本单验证。T182 后的重叠文本已复核，最终 head 仍交协调方独立审阅，不据本文宣称研究完成。
