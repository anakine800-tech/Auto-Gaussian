# CREST 构象初筛

## 要点

- TS 族、关键中间体、复合物必须双路线交叉核对；TS/复合物用已审阅初猜的约束 CREST + 定向构造约束 CREST，不强用不适用的力场。（[见第 1 节](#1-适用范围)）
- XYZ 须匹配签字结构，电荷和 `--uhf` 显式给定；完整参数、窗口与快速模式说明后，按 [Study 流程](../../auto-g16-study/SKILL.md)取得对应模式的提交授权。（[见第 5 节](#5-提交前检查清单)）
- 须正常终止、构象数非零、能量与构象数量对应，并逐一审阅连通性、质子位置和立体化学。（[见第 6 节](#6-结果判据清单)）
- 代表构象及简并度须生成证据清单后请人签字；聚类样本数不等于物理简并度，未确认不用于最终布居。（[见第 6 节](#6-结果判据清单)）
- 按方案审阅来源和比较分支，记录未匹配项、低能独有项和警告；覆盖报告不能证明采样已完备。（[见第 6 节](#6-结果判据清单)）

## 1. 适用范围

主族闭壳层单分子构象搜索，可中性或带电；也可从已审阅的 TS 初猜进行约束构象搜索。双分子步骤与复合物按 [complex](complex.md) 卡片执行，仅开放以已审阅原子对为约束的采样；通用对接搜索不开放。不包括金属、开壳层或反应路径搜索；复合物搜索不等于结合自由能计算。

TS 族、关键中间体、复合物必须双路线交叉核对；可旋转键较多也建议走。
适用 RDKit 的关键中间体用 CREST + ETKDG；普通稳定单分子按已签方案决定
是否补 ETKDG，不一律要求，也不删掉研究已要求的来源。TS/复合物用已审阅
初猜的约束 CREST + 定向构造约束 CREST（directed），两路共享引擎，不强用
不适用的力场。来源要求与能量比较分支见[分支表](../../auto-g16-structures/references/conformer-workflow.md#分支选择)。

## 2. 前置条件

已签字的结构及审阅过的 XYZ；电荷、多重度和溶剂明确；CREST 模板可用。闭壳层 `--uhf 0`，不从 XYZ 推断电荷。

CREST 准备前先运行 `ag route --template crest --tier <档位> --walltime <HH:MM:SS> --study <study>`，优先查赠送入口 `scnet-test`；本机默认顺序设为 `scnet-test → default → newhpc`，实际以 `ag route` 的研究覆盖顺序、模板许可和快照建议为准。按建议显式选 `--cluster`；偏离时在 study.md 写明原因，未签字允许的入口从该研究顺序跳过。无路由配置时沿用研究已批准安排；使用本次计划的 walltime；省略时未核对时限，入口未配置上限不代表无限制。超限入口不能回退推荐；容量未知须保留说明，容量足够或排队建议均不保证实际启动时间。后续 Gaussian 另查自己的路由建议；ag 不自动改入口，已有 Attempt 不迁移，提交批准规则不变。

## 3. 输入模板

方案允许的 CREST 程序参数是：`--gfn2`、`--gfnff`、`--mdopt`、`--nci`、`--alpb <溶剂>`、`--chrg <整数>`、`--uhf <整数>`、`--ewin <数>`、`--quick`、`--squick`、`--mquick`。只用当前模板声明实际接受的组合和值，不自行追加参数。

以下窗口已由负责人于 2026-10-14 确认。首选 GFN2-xTB；示例（L1 正丁烷气相流程验收）：`--gfn2 --chrg 0 --uhf 0 --ewin 6 --quick`。正式研究的电荷、`--uhf`、溶剂及是否使用 `--quick` 按体系填写；溶液相加经过模板验证的 ALPB 溶剂。使用快速模式时只选一种；GFN-FF 是另一个方法选项，不能把其能量当 GFN2 能量。

```text
ag prepare --study <study_id> --template crest --input <reviewed.xyz> --param=--gfn2 --param=--chrg=0 --param=--uhf=0 --param=--ewin=6 --param=--quick --tier simple --walltime 04:00:00 --label crest --card crest-screen --method-basis <构象筛选依据：文献先例 DOI 及位置 / 本课题既有方案及来源（不是文献先例，精度未经验证） / 兜底方法声明>
```

上述完整 prepare 示例对应中性闭壳层气相快速验收；替换路径、方法依据并核对入口和资源后使用。正式研究按已审阅方案修改 `--param`，其值受模板白名单校验，不是随意透传的 shell 命令。准备后走确认摘要及 `ag submit`。完成后 status → fetch → facts，读取 `crest_conformers.xyz` 等声明输出，调用 `ag dedup` / `ag cluster`。保留 xTB 相对能量 ≤ 6 kcal/mol 的候选并去重；对这些候选先按
[SP](sp.md) 做优化层级 DFT 单点重排；方法/基组：见
[acceptance-methods.md](../../auto-g16-study/references/acceptance-methods.md)，包括溶剂与阴离子弥散方案；
不能按 xTB 排序先截成 20 个。
再将相对最低 DFT 单点能 ≤ 3 kcal/mol 的候选送入 Opt+Freq，研究最多
20 个、验收最多 10 个；优化后重新去重，再算研究所需最终单点及热化学；验收不增设高精度单点。
上述是普通极小点的预算筛选；按 [SP 卡片](sp.md) 为每个来源、每种氢键模式保留 1–2 个窗外独特验证对象，并检查窗口放宽后的结论。TS 通道不套用此剪枝规则。
这里描述 xTB 预筛路径；若各来源按自己的窗口直接进入统一 DFT 重排，采用下文
仅几何合并分支，不要求先做 mdopt，也不对混合低层能量开共同窗口。
具体研究/验收的筛选单点层级见[方法表](../../auto-g16-study/references/acceptance-methods.md)。
若候选量超预算，记录未完成的 DFT 重排及覆盖限制，不称为完整筛选。

非手性分子（如正丁烷）聚类时使用 `ag cluster` 的 `--mirror`：将互为镜像的 gauche+ / gauche− 合并为一个代表，简并度为 2，在 DFT 重排后只需对选中的该代表做一个 Opt+Freq。手性分子不要使用 `--mirror`，避免把不同立体异构体混入同一代表；运行前仍核对当前接口支持。

### ETKDG 系综统一到 xTB 能量

ETKDG/MMFF 或 UFF 只负责生成候选；力场能量不能换单位后与 CREST 能量混排。
本节适用于选择共同 xTB 能量筛选的 A 分支；B 分支仅几何合并后直接统一 DFT。
研究示例中的系综须记录实际帧数、保留上限及依据；本地生成显式填写
`--num-conformers N_REQUESTED --max-keep N_KEEP`（换成本研究已审阅整数），
不能让默认 10 个提前截断。下列输入须为该已审阅系综；用同一 GFN2-xTB、
ALPB 溶剂、电荷及 `--uhf` 做逐帧优化，mdopt 本身不增加独立采样路线：

```text
ag prepare --study <study_id> --template crest --input <etkdg-ensemble.xyz> --param=--mdopt --param=--gfn2 --param=--alpb=<与 CREST 路线相同的溶剂> --param=--chrg=0 --param=--uhf=0 --tier simple --walltime 04:00:00 --label etkdg-mdopt --card crest-screen --method-basis <构象筛选依据：文献先例 DOI 及位置 / 本课题既有方案及来源（不是文献先例，精度未经验证） / 兜底方法声明>
```

GFN 层级、ALPB 溶剂、电荷和 `--uhf` 必须与参与合并的 CREST 来源逐项一致，
否则不得使用 `lowest`。上例溶剂占位符须替换为模板接受的实际溶剂值；
只有参与合并的全部来源均为气相时，才一致省略 `--alpb`。

`--mdopt` 在 ag 中是标志，模板绑定已校验的输入文件，实际执行
`crest --mdopt <输入文件> ... -T <核数>`。输入为 1–1000 帧 XYZ，所有帧
原子数和元素顺序必须一致，坐标必须有限；仍须人核对同元素原子的映射及立体化学。
不带 `--mdopt` 的 CREST/xTB prepare 仍只接受单帧。方法、资源及输入哈希
逐个保存完整摘要，手动模式提交前展示；按 [Study 流程](../../auto-g16-study/SKILL.md)取得对应模式的提交授权后提交。

CREST 3.0.2 的该模式取回 `crest.out`、`crest_ensemble.xyz` 和 `ensemble_energies.log`；XYZ 按输入顺序
逐帧写 Hartree 能量和优化几何；不要求普通搜索的 `crest.energies` 或
`crest_conformers.xyz`。依据：[optimization.f90](https://github.com/crest-lab/crest/blob/v3.0.2/src/algos/optimization.f90#L131-L232)、
[文件名常量](https://github.com/crest-lab/crest/blob/v3.0.2/src/classes.f90#L49-L51)、
[优化循环输出](https://github.com/crest-lab/crest/blob/v3.0.2/src/algos/parallel.f90#L327-L333)、
[XYZ 写出格式](https://github.com/crest-lab/crest/blob/v3.0.2/src/strucreader.f90#L644-L665)。
完成 status → fetch → facts；`facts.json` 记录逐帧 `conformer_energies_hartree`，
`ensemble_geometry` 指向 Attempt 下的 `mdopt.xyz`，注释是 Hartree 能量，
可直接作为 `ag dedup --source etkdg=.../mdopt.xyz`。`final.xyz` 仅为最低能帧。
失败帧在 CREST 中标 `+1.0 !failed`，解析拒绝导出；缺帧、坏能量或坐标也须停下核对。
正常终止和帧数吻合仍不替代几何、连通性、立体化学及优化收敛的科学审阅。

### 非共价复合物与定向构造

复合物构建、已审阅原子对约束、参考态与后续审阅按 [complex](complex.md) 卡片执行；`--nci` 不替代原子对约束。

催化剂与底物复合物、离子对、氢键聚集体可用 `--param=--nci`。
它引入包围初始复合物的椭球壁势及调整的 MTD 偏置，减少片段解离；
几何优化阶段移去壁势。[官方 NCI 说明](https://crest-lab.github.io/crest-docs/page/examples/example_3.html)。
`--nci` 本身不将构象能量窗口改成 30 kcal/mol；3.0.2 的 NCI 分支没有设置 ewin，
普通构象搜索默认 6 kcal/mol。显式传 `--param=--ewin=6` 并核对输出实际窗口；
若需扩大窗口，在方案中给出依据，不能把 NCI 或快速模式当成全覆盖保证。
[参数说明](https://crest-lab.github.io/crest-docs/page/documentation/keywords.html)、
[3.0.2 参数源码](https://github.com/crest-lab/crest/blob/v3.0.2/src/confparse.f90)。
定向构造由结构 Skill 按相互作用/进攻方向假设搭建审阅 XYZ，再做约束 CREST；
来源标为 directed，保留约束偏向与共用引擎的局限。不自写 MD 或退火引擎。

### 约束构象搜索

做 TS 构象搜索时，固定正在形成或断裂的键的距离，以免搜索离开目标反应区域。先与人核对 TS 初猜、XYZ 原子编号和目标距离，再用 `--constraints <文件>` 交给 `ag prepare --template crest`。例如将以下内容保存为本地约束文件（编号和值须按实际结构修改）：

```text
$constrain
  force constant=0.5
  distance: 1, 2, auto
$end
```

`auto` 采用输入结构中的距离，也可填目标距离（Å）；angle、dihedral 的值以度为单位。这里的“固定”是约束势，搜索后仍需检查实际键长。[xTB 约束语法说明](https://xtb-docs.readthedocs.io/en/latest/xcontrol.html#constraining-potentials)。

`--cinp` 传入的约束会贯穿 MD、MTD、优化和单点各阶段，不只是采样时生效；
与 NCI 在优化阶段移除的壁势分清。见 [CREST 约束说明](https://crest-lab.github.io/crest-docs/page/examples/example_4.html)。
记录程序版本、力常数及单位（此 xTB 输入约定为 Eh/Bohr²，示例 0.5 不是通用推荐）、
原子编号、目标值与输出/几何测得的实际值及偏差；`auto` 也须记下数值。
距离记 Å、角/二面角记度；不能把约束当成严格冻结，角约束按程序定义解释，
不自行将力常数换成每平方度。不同约束方案下的搜索能量不能混排；如需统一比较，
须在同一已审阅设置下另算可比能量，保留原搜索来源和偏置，不靠单位一致判断。

文件只接受单个 `$constrain` / `$end` 块，以及 `force constant=<数>`、`atoms:`（逗号分隔的编号或递增范围，如 `1-3,5`）、`distance:`（2 个编号）、`angle:`（3 个编号）、`dihedral:`（4 个编号）；后三者末项为有限数值或 `auto`。编号从 1 开始且不得超过 XYZ 原子数。其他指令、注释和附加内容均拒绝，包括 `$write`、`$external`、`$set`。

prepare 将原文件字节作为 `constraints.inp` 纳入 bundle 和逐文件 SHA-256 摘要，模板自动加 `--cinp constraints.inp`；不要通过 `--param` 直接传 `--cinp`。提交前同时审阅约束内容、输入结构、完整参数和摘要中的文件哈希。

**约束、带偏置的低层采样中出现通道泄漏，不证明真实体系中两条通道快速互变，不能用来支持 Curtin–Hammett 条件。**
Curtin–Hammett 的快速互变条件须有独立动力学依据，结合 [kinetics](kinetics.md) 的选择性与可逆性模型审阅。
来源：[T139](../../../docs/redesign-tasks/T139-card-wording.md) A6、[审计第 11 节](../../../docs/research/ts-guess-audit.md)。

搜到的结构只是 TS 候选；正式 DFT TS 优化前释放采样约束、移除冻结段，重新优化为 TS，并逐个按 [TS 卡片](ts.md) 审阅：恰好一个虚频，且振动方向与目标成键/断键坐标一致。需要 IRC 验证时，必须双向完成并识别端点，才能声称验证；CREST 正常终止不能代替 TS 验证。

### 合并与覆盖报告

**A：统一 xTB。** ETKDG 候选先经上述 `--mdopt`，审阅通过后与同方法 CREST 结果合并，
再按相对合并集合最低 xTB 能量 ≤ 6 kcal/mol 开窗口：

```text
ag dedup --source crest=crest.xyz --source etkdg=attempts/ETKDG_MDOPT/mdopt.xyz --representative lowest --de 0.05 --hydrogens polar --window 6 --charge 0 --out analyses
```

CREST 来源使用 `crest_conformers.xyz` 的绝对 Hartree 注释，不用相对能量表混排。
有定向路线再加 `--source directed=directed.xyz`，但必须先审阅它是否具有相同
Hamiltonian、溶剂、电荷、自旋及约束能量口径；不同约束方案的搜索能量不得混排；相同约束下的偏置能也不能当作无约束能。
`--representative lowest` 是使用者对同层级能量的显式声明，代码只核验有限
Hartree 能量，不从单位猜方法；合并还要求能差小于 `--de`（默认 0.05 kcal/mol）。代表保留实际合并成员的来源和逐帧溯源，再做 DFT 单点。
**B：仅几何合并。** 按各自已审阅窗口保留的候选可直接进入统一 DFT 重排；
无需先 mdopt，不使用 lowest、window 或 de。例如：

```text
ag dedup --source crest=crest.xyz --source etkdg=etkdg.xyz --hydrogens polar --charge 0 --out analyses
```

代表按输入顺序保留，几何相近不保证等能，也不保证首个代表最低能。
这是几何去重，不是能量筛选；不同方法或不同约束方案的搜索能量不混排。
两分支都记录各来源实际保留数、上限及依据，保留原始帧和窗外验证对象；
对全部保留代表做同层级 DFT 筛选 SP 后才比较跨来源能量及覆盖。
预算不足时列出未完成项，不用优化数量上限提前截断。既有方案指定的分支
或来源若需改变，先给出具体差异和依据供确认，不改旧代表集合或签字。
`--hydrogens heavy|polar|all` 默认 polar：重原子及 N/O/S/P 上的氢参与 RMSD，
避免把 OH 等转子合并并误标为多路线共同找到；甲基氢默认不参与。
涉及氢键或参与反应的氢必须参与构象区分；若包含 C–H 等非 polar 氢，选择 all。
JSON 记录 hydrogens；每次合并记录 heavy_rmsd 与实际判定的 rmsd（均为 Å）。
coverage 与 cluster 继承该模式；无模式字段的旧 JSON 按 heavy 解释，不能恢复已丢失的氢朝向，应重新去重。
DFT 单点后运行
`ag coverage --merged analyses/dedup-TIMESTAMP.json --energies attempts/SP_A attempts/SP_B --window 3 --out analyses/coverage-01.md`。
先处理未匹配项（按所选原子的输入坐标 1e-4 Å、原子顺序核对，不靠名称），再读窗口总数、各路线命中数、
最低 5 个来源和单路线独有项；可用 `--top N`、`--json`，输出文件必须新建。
最低构象单路线独有或超过一半窗口构象由某路线独占会警告“采样可能不足”。
覆盖报告不能证明采样已经完备；无警告、空窗口也不能代替人审阅。
几何聚类可选 `--representative medoid`；统一 xTB 标度后的来源合并可用 lowest；未统一标度的几何合并仍用 medoid。

## 4. 资源建议

按体系规模、柔性和既有耗时选择档位与 walltime。资源示例：约 50 原子以内的快速验收用 simple（8 核、12 GB）、04:00:00；更柔性或已有耗时证据时用 general（22 核、50 GB）、24:00:00；复杂体系确有需要再考虑 complex（44 核、120 GB）。这些不是通用默认，实际档位按所选入口配置，保存值以 manifest 为准；详见[资源表达](../../auto-g16-study/references/acceptance-methods.md#资源表达)。walltime 须满足入口上限；模板负责线程数，不能额外拼接线程参数。

## 5. 提交前检查清单

- XYZ 与签字结构匹配，电荷和 `--uhf` 已显式给定；ALPB 溶剂与 study 一致，气相无溶剂参数。
- 参数在模板白名单内；摘要将 Gaussian route 标“不适用”，改列完整 CREST 参数、资源和目录。
- 窗口、候选上限和快速模式已说明；按 [Study 流程](../../auto-g16-study/SKILL.md)取得对应模式的提交授权。

## 6. 结果判据清单

- 已按分支表审阅来源要求与比较分支：A 的 ETKDG 经同方法 `--mdopt` 后才与 CREST 作统一 xTB 能量筛选；B 仅几何合并，再统一 DFT 重排，不混排低层能量。单 CREST 方案将 ETKDG 项注明不适用及依据，不伪造第二来源。
- CREST 正常终止，`n_conformers` 为非零，能量与输出构象数量对应；不能只凭文件存在就接受。
- 逐一审阅连通性、质子位置和立体化学，排除变化为其他物种的结构并记原因。
- dedup / cluster 输出能追溯代表、成员、能量口径、氢模式、两种 RMSD、阈值和筛选原因；仅几何合并不填共同相对能量，确认氢键或反应相关氢未被忽略，截断时写明覆盖局限。
- dedup 重复记录中 `mapping=identity|symmetry` 分别表示原编号 / 等价置换；芳香环翻转可经等价映射合并。映射超限会报错，不接受截断的 RMSD；改为 heavy 前确认被忽略的氢不影响构象判别。
- 审阅 `algorithm` 的顺序依赖与 `boundary_pairs`：代表间 < 2 倍 RMSD 阈值、已并入项 > 阈值一半；这些是复核候选，不自动改变归属。能量不可比的来源模式按输入顺序，配对能差为 null。
- `ag dedup --mirror report` 的 `mirror_pairs` 只比较已保留代表、报告普通和镜像 RMSD，不合并；手性体系的镜像对不是同一构象，`stereo_changed` 仍排除。非手性镜像简并计数继续按 `ag cluster --mirror` 判读。
- 先运行 `ag review manifest --study <dir>` 生成证据清单，再把代表构象及其简并度展示给人签字，并记录清单路径及 SHA-256。聚类样本数可能含重复采样，不等于物理简并度；复制工具输出时保留这一含义，未确认则不用于最终布居。
- 方案要求的双路线来源与覆盖报告已审阅，逐来源保留数量、上限、依据、未匹配项、低能独有项和警告已记录；缺来源写明缺口，覆盖报告不能证明采样已经完备。
- 约束搜索记录力常数/单位、目标值、实际值与偏差；核对 MD/MTD/优化/单点均受影响，不混排不同约束搜索能量，TS 后续释放采样约束。
- 普通极小点、非共价复合物、受约束 TS 候选按 [分类后续路线](reaction-plan.md#候选分类与路径边界)分别处理。
- 分列 xTB 能量、筛选 DFT 单点能、优化后去重与最终电子能；快速搜索完成不代表已穷尽全构象空间。

## 7. 常见失败与处理

异常结束、缺构象或解析不一致按 [AGENTS 自主运行规则](../../../AGENTS.md#自主运行)区分模式处理，读取 `crest_diagnostics` 的 summary、status、parse_error 和带 SHA-256／行号的 sources，转 failure-diagnosis。解析未完成时保留诊断 facts 但命令仍失败，不接受空构象数或缺失几何。搜索改变物种时先确认化学身份，不能自动进入原物种 DFT 集合；新 Attempt 按 [失败诊断](failure-diagnosis.md)处理。

覆盖警告出现时提出扩大采样：去掉 CREST 快速模式并给足 walltime、增加 ETKDG 种子/候选数、加入定向构造；单加 walltime 不会延长已正常结束的采样。新 Attempt 按上述模式规则取得授权后运行，完成后重新合并、DFT 重排并出新报告。轨迹时长参数不在现有白名单时先走模板审阅，不自行透传。

## 8. 常见坑

本节历史来源链接固定到 `v3-frozen`，仅用于追溯经验出处；现行执行以本卡为准，不沿用冻结文档中的流程。

知识衔接：[GKB-0420：局部性与构象覆盖](../../auto-g16-gaussian-learning-library/references/core-job-types.md)。

- 排队不代表失败，也不能仅凭排队推断节点满载；不以重复计算解决等待。来源：[environment-and-failures.md（v3-frozen）](https://github.com/anakine800-tech/Auto-Gaussian/blob/v3-frozen/skills/auto-g16-rtwin-pbs/references/environment-and-failures.md)。
- 不同初始构象可能在 DFT 后合并，最终布居前还要再去重。来源：[conformer-workflow.md（v3-frozen）](https://github.com/anakine800-tech/Auto-Gaussian/blob/v3-frozen/skills/auto-g16-view-rt-win/references/conformer-workflow.md)。
