# CREST 构象初筛

## 1. 适用范围

主族闭壳层单分子及已构建、审阅的非共价复合物构象搜索，可中性或带电；也可从已审阅的 TS 初猜进行约束构象搜索。不包括金属、开壳层或反应路径搜索；复合物搜索不等于结合自由能计算。

TS 族、关键中间体、复合物必须双路线交叉核对；可旋转键较多也建议走。普通稳定单分子用 CREST + ETKDG；TS/复合物用 CREST + 定向构造约束 CREST（directed），不强用不适用的力场。流程见[conformer-workflow](../../auto-g16-structures/references/conformer-workflow.md)。

## 2. 前置条件

已签字的结构及审阅过的 XYZ；电荷、多重度和溶剂明确；CREST 模板可用。闭壳层 `--uhf 0`，不从 XYZ 推断电荷。

## 3. 输入模板

方案允许的 CREST 程序参数是：`--gfn2`、`--gfnff`、`--mdopt`、`--nci`、`--alpb <溶剂>`、`--chrg <整数>`、`--uhf <整数>`、`--ewin <数>`、`--quick`、`--squick`、`--mquick`。只用当前模板声明实际接受的组合和值，不自行追加参数。

以下窗口已由负责人于 2026-10-14 确认。首选 GFN2-xTB；正丁烷气相验收参数为 `--gfn2 --chrg 0 --uhf 0 --ewin 6 --quick`。溶液相加经过模板验证的 ALPB 溶剂。快速模式选一种；GFN-FF 是另一个方法选项，不能把其能量当 GFN2 能量。

```text
ag prepare --study <study_id> --template crest --input <reviewed.xyz> --tier simple --walltime 04:00:00 --label crest
```

上述是通用 prepare 参数，还须按当前 `ag prepare --help` 将完整 CREST 参数交给模板；它们不是随意透传的 shell 命令。准备后走确认摘要及 `ag submit`。完成后 status → fetch → facts，读取 `crest_conformers.xyz` 等声明输出，调用 `ag dedup` / `ag cluster`。保留 xTB 相对能量 ≤ 6 kcal/mol 的候选并去重；对这些候选先按
[SP](sp.md) 做优化层级 DFT 单点重排；方法/基组：见
[acceptance-methods.md](../../auto-g16-study/references/acceptance-methods.md)，包括溶剂与阴离子弥散方案；
不能按 xTB 排序先截成 20 个。
再将相对最低 DFT 单点能 ≤ 3 kcal/mol 的候选送入 Opt+Freq，研究最多
20 个、验收最多 10 个；优化后重新去重，再算研究所需最终单点及热化学；验收不增设高精度单点。
具体研究/验收的筛选单点层级见[方法表](../../auto-g16-study/references/acceptance-methods.md)。
若候选量超预算，记录未完成的 DFT 重排及覆盖限制，不称为完整筛选。

非手性分子（如正丁烷）聚类时使用 `ag cluster` 的 `--mirror`：将互为镜像的 gauche+ / gauche− 合并为一个代表，简并度为 2，在 DFT 重排后只需对选中的该代表做一个 Opt+Freq。手性分子不要使用 `--mirror`，避免把不同立体异构体混入同一代表；运行前仍核对当前接口支持。

### ETKDG 系综统一到 xTB 能量

ETKDG/MMFF 或 UFF 只负责生成候选；力场能量不能换单位后与 CREST 能量混排。
保留足够候选，先用同一 GFN2-xTB、ALPB 溶剂、电荷及 `--uhf` 做系综优化：

```text
ag prepare --study <study_id> --template crest --input <etkdg-ensemble.xyz> --param=--mdopt --param=--gfn2 --param=--chrg=0 --param=--uhf=0 --tier simple --walltime 04:00:00 --label etkdg-mdopt
```

`--mdopt` 在 ag 中是标志，模板绑定已校验的输入文件，实际执行
`crest --mdopt <输入文件> ... -T <核数>`。输入为 1–1000 帧 XYZ，所有帧
原子数和元素顺序必须一致，坐标必须有限；仍须人核对同元素原子的映射及立体化学。
不带 `--mdopt` 的 CREST/xTB prepare 仍只接受单帧。方法、资源及输入哈希
照常展示，等人授权并点击 Mac 确认后提交。

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

文件只接受单个 `$constrain` / `$end` 块，以及 `force constant=<数>`、`atoms:`（逗号分隔的编号或递增范围，如 `1-3,5`）、`distance:`（2 个编号）、`angle:`（3 个编号）、`dihedral:`（4 个编号）；后三者末项为有限数值或 `auto`。编号从 1 开始且不得超过 XYZ 原子数。其他指令、注释和附加内容均拒绝，包括 `$write`、`$external`、`$set`。

prepare 将原文件字节作为 `constraints.inp` 纳入 bundle 和逐文件 SHA-256 摘要，模板自动加 `--cinp constraints.inp`；不要通过 `--param` 直接传 `--cinp`。提交前同时审阅约束内容、输入结构、完整参数和摘要中的文件哈希。

搜到的结构只是 TS 候选，仍需用 DFT 重新优化为 TS，并逐个按 [TS 卡片](ts.md) 审阅：恰好一个虚频，且振动方向与目标成键/断键坐标一致。需要 IRC 验证时，必须双向完成并识别端点，才能声称验证；CREST 正常终止不能代替 TS 验证。

### 合并与覆盖报告

ETKDG 候选先经上述 `--mdopt`，审阅通过后与同方法 CREST 结果合并，
再按相对合并集合最低 xTB 能量 ≤ 6 kcal/mol 开窗口：

```text
ag dedup --source crest=crest.xyz --source etkdg=attempts/ETKDG_MDOPT/mdopt.xyz --representative lowest --window 6 --charge 0 --out analyses
```

CREST 来源使用 `crest_conformers.xyz` 的绝对 Hartree 注释，不用相对能量表混排。
有定向路线再加 `--source directed=directed.xyz`，但必须先审阅它是否具有相同
Hamiltonian、溶剂、电荷、自旋及约束能量口径；不同约束不自动保证能量可比。
`--representative lowest` 是使用者对同层级能量的显式声明，代码只核验有限
Hartree 能量，不从单位猜方法。代表保留全部来源和逐帧溯源，再做 DFT 单点。
无法统一口径时，省略 lowest 和窗口，沿用仅几何合并，不得混排能量。
DFT 单点后运行
`ag coverage --merged analyses/dedup-TIMESTAMP.json --energies attempts/SP_A attempts/SP_B --window 3 --out analyses/coverage-01.md`。
先处理未匹配项（按输入坐标 1e-4 Å 核对，不靠名称），再读窗口总数、各路线命中数、
最低 5 个来源和单路线独有项；可用 `--top N`、`--json`，输出文件必须新建。
最低构象单路线独有或超过一半窗口构象由某路线独占会警告“采样可能不足”。
覆盖报告不能证明采样已经完备；无警告、空窗口也不能代替人审阅。
几何聚类可选 `--representative medoid`；统一 xTB 标度后的来源合并可用 lowest；未统一标度的几何合并仍用 medoid。

## 4. 资源建议

正丁烷和约 50 原子以内快速验收先用 simple（8 核、12 GB）、04:00:00；更柔性或已有耗时证据时提出 general（22 核、50 GB）、24:00:00。复杂体系确有需要再考虑 complex（44 核、120 GB）；模板负责线程数，不能额外拼接线程参数。

## 5. 提交前检查清单

- XYZ 与签字结构匹配，电荷和 `--uhf` 已显式给定；ALPB 溶剂与 study 一致，气相无溶剂参数。
- 参数在模板白名单内；摘要将 Gaussian route 标“不适用”，改列完整 CREST 参数、资源和目录。
- 窗口、候选上限和快速模式已说明；等人说“提交”及点击系统对话框。

## 6. 结果判据清单

- ETKDG 已经同方法 `--mdopt` 优化后再与 CREST 合并，并按统一 xTB 标度开 6 kcal/mol 窗口。
- CREST 正常终止，`n_conformers` 为非零，能量与输出构象数量对应；不能只凭文件存在就接受。
- 逐一审阅连通性、质子位置和立体化学，排除变化为其他物种的结构并记原因。
- dedup / cluster 输出能追溯代表、成员、相对能量、阈值和筛选原因；截断到数量上限时写明覆盖局限。
- 把代表构象及其简并度展示给人签字。聚类样本数可能含重复采样，不等于物理简并度；复制工具输出时保留这一含义，未确认则不用于最终布居。
- 双路线来源与覆盖报告已审阅，未匹配项、低能独有项和警告已明确记录，覆盖报告不能证明采样已经完备。
- 分列 xTB 能量、筛选 DFT 单点能、优化后去重与最终电子能；快速搜索完成不代表已穷尽全构象空间。

## 7. 常见失败与处理

异常结束、缺构象或解析不一致先停下报告，转 failure-diagnosis。搜索改变物种时先确认化学身份，不能自动进入原物种 DFT 集合；提出新 Attempt，等人确认。

覆盖警告出现时提出扩大采样：去掉 CREST 快速模式并给足 walltime、增加 ETKDG 种子/候选数、加入定向构造；单加 walltime 不会延长已正常结束的采样。新 Attempt 人确认后运行，完成后重新合并、DFT 重排并出新报告。轨迹时长参数不在现有白名单时先走模板审阅，不自行透传。

## 8. 常见坑

知识衔接：[GKB-0420：局部性与构象覆盖](../../auto-g16-gaussian-learning-library/references/core-job-types.md)。

- 排队不代表失败，也不能仅凭排队推断节点满载；不以重复计算解决等待。来源：`skills/auto-g16-rtwin-pbs/references/environment-and-failures.md`。
- 不同初始构象可能在 DFT 后合并，最终布居前还要再去重。来源：`skills/auto-g16-view-rt-win/references/conformer-workflow.md`。
