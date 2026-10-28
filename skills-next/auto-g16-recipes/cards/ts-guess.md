# TS 初猜准备与诊断

## 要点

- 初猜来自扫描、端点、手工或文献，来源与原子对应须可审阅；见[前置条件](#2-前置条件)。
- 局部峰、QST 草稿、约束构象和 G0 排名均不等于已找到 TS；见[输入模板](#3-输入模板)。
- G0 是本地诊断，不是门禁；批量局部错误单列且不登记，不能把错误当 clean；见[结果判据](#6-结果判据清单)。
- 某组模板或低层路线失败不排除整个通道；候选审阅后转 TS 搜索、Freq 和 IRC；见[失败处理](#7-常见失败与处理)。

## 1. 适用范围

主族闭壳层、同一势能面的 TS 初猜准备、来源登记和本地诊断。不做自动反应发现、金属、开壳层或跨自旋面搜索；通过本卡只得到待审阅初猜。下一阶段是 [TS 搜索与频率](ts-search.md)，统一覆盖与签字边界见 [TS 总入口](ts.md)。

## 2. 前置条件

[机理假设](reaction-plan.md)已由人签字，目标步骤、反应物/产物身份和原子对应明确；结构与代表构象集合已确认。预先列出正在形成、断裂或迁移的原子对（按输入行号，从 1 开始），并说明方法依据、溶剂、电荷、多重度。初猜来源可选（科学策略提炼自 [旧设计 R10](../../../archive/docs/end-to-end-reaction-computation-workflow.md)）：

- Hessian 引导的单结构初猜：已有合理 TS 状几何时，用反应坐标与曲率信息判断适用性；CalcFC 不能弥补错误原子映射。
- 沿反应坐标做一维弛豫扫描：记录坐标、范围、步长、冻结项及选点依据，局部极大仅是初猜，具体做法见下。
- QST2：已优化端点的完整映射、正规旋转、歧义处理及草稿复核见[TS 初猜工作流](#ts-初猜工作流)。QST3 仍需额外 TS 初猜，使用已有多结构输入并逐组审阅。
- 类比已知 TS：记录 DOI/结构来源、映射及差异；类比几何不意味着该方法或机理已获验证。
- 扫描初猜可用 `ag scan-peak`；全自动 TS 搜索不在当前范围，工具给的结构仍需人工审阅。

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

覆盖状态和失败记录沿用 [TS 入口](ts.md#覆盖与失败记录)，catalog 写入沿用其[共同前置](ts.md#2-前置条件)；有限预算和失败搜索都不能证明通道不存在。

## 3. 输入模板

方法/基组只见 [acceptance-methods.md](../../auto-g16-study/references/acceptance-methods.md)，示例中的方法、原子编号、范围与文件名均须按已审阅方案替换。

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
按 Study 流程取得聊天批准记录、匹配长期规则或 Mac 人工确认；不通过卡片拼接远程命令。

DFT 输入用 `opt=modredundant`，采用默认 Å 坐标（不带 Units 选项，避免摘要
单位与扫描范围错配）；显式坐标后留空行，再写一个段，例如：

```text
B 1 2 S 16 -0.1
A 3 1 2 F
```

上述原子编号必须按结构替换，F 项只在有科学依据时保留。B/A/D 分别为键、角、
二面角；一维用一个 S，1–50 步，距离单位 Å、角度单位度；Gaussian 包含初始点，
终值为初值加步数乘步长。F 不写附加值。不得与 TS/QST2/QST3 混用扫描段。
prepare 摘要显示编号、元素、初值、步数、步长、终值和冻结坐标，逐项审阅。

取回后运行 `ag facts <attempt>`，再运行
`ag scan-peak <attempt> --out <新文件.xyz> [--point <序号>] [--json]`。
候选只取内部严格局部极大：该点及左右紧邻点均已收敛且有能量，该点能量严格高于两侧。
工具列出全部候选的原扫描序号（从 1 开始）、实际坐标值、Hartree 能量与相对能；
相对能以全部已收敛扫描点最低能为零，单位 kcal/mol。默认导出最高的局部峰，
用 `--point` 可指定其他局部峰；非候选序号拒绝。无合格局部极大时拒绝导出，
审阅扫描范围、坐标及收敛证据；单调曲线、平台或只有边界高点都不回退到全局最高点。
**scan-peak 的结果只是 TS 初猜。气相离子–分子反应里，全局最高点常常不是 TS**：
分离方向的高能端可能高于势阱内的局部反应峰，不能凭全局能量排名定位 TS。
查看所选点两侧各两个点
（边缘处只列存在的点）的实际坐标值、能量和收敛状态，并检查全部扫描曲线：

- “范围不够，峰可能在范围外”：端点能量不低于所选局部峰；端点不会导出。
  结合分离渐近区与完整曲线判断，必要时扩大有物理依据的范围并提出新 Attempt；
  该提示不证明内部局部峰错误，也不能把单调曲线里的内部最高点当成峰。
- “可能跳到了另一条路径或另一个构象”：相邻能差超过 20 kcal/mol，或按原子编号
  对齐的全原子 RMSD 超过 0.5 Å。这些阈值只决定是否列出启发式提示，不是科学判据；检查结构、电子态和坐标步长，
  不能自动删除这些点或断言机理改变；平滑曲线也不能证明同一路径。
- “有未收敛的点或收敛证据缺失”：这些点及紧邻它们的点不参与选择；缺点可能隐藏局部峰。
  回看原日志并人工决定是否重新设计扫描；不自动重提。

scan_points.xyz 保存各已报告点的最终几何；未收敛点只是最后迭代几何，未计算点
无几何。文件已存在且相同则沿用，不同则停止核对；scan-peak 的输出必须是新文件。
生成草稿前先看 `ag scan-path <attempt>` 的诊断，按下方“TS 初猜工作流”生成并审阅草稿；扫描局部极大自身不能判定 TS。

### 初猜来源：Gaussian 二维弛豫扫描

两个坐标明显耦合（如成键同时伴随质子或硼转移）时，可在同一
`Opt=ModRedundant` 段写两条 S 行；先用较粗网格定位区域，例如：

```text
B 1 2 S 2 -0.1
A 3 1 2 S 2 5.0
```

原子编号、范围和步长须按已审阅结构替换；两坐标不能共用全部原子。
一维、二维 S 行的步长均须含小数点（如 `5.0`，不能写 `5`）；整数写法会在 Gaussian L101 报错。
每维 1–20 步，总点数 `(n1+1)×(n2+1)` ≤ 144；上例为 3×3、9 点。
每点都是约束优化，耗时随总点数增长，相当于把一个一维扫描重复另一维的点数次；
提交前核对两维起点、终点、单位、资源与 walltime。xTB 仍只允许一条扫描行。
`ag facts` 用几何实测值定位网格，缺点为 null；坐标无法唯一匹配或重复占格即报错，
此时停下核对，不放宽容差。鞍点候选要求自身及上下左右均收敛，沿一维严格极大、
另一维严格极小；边界不列出，无候选也不能据此断言不存在 TS。
二维导出必须显式 `ag scan-peak <attempt> --point 2,2 --out <新文件.xyz>`，
编号从 1 开始，顺序对应两条 S 行；只有列出的候选允许导出，不自动选择。
候选只是 TS 初猜，仍需解除扫描约束、TS 优化、Freq、振动方向人工审阅及双向 IRC 端点识别。

### TS 初猜工作流

下列尖括号均为占位符，按已审阅方案填写；生成文件须用新名字。命令与参数按当前实际 `--help` 核对。catalog 写入沿用 [共同前置](ts.md#2-前置条件)；`--upgrade-catalog` 只是格式升级确认，不能替代部署或研究写入授权。

1. **定义对象与通道。** `ag catalog object-suggest <study> --attempt <参考Attempt>` 只提供建议；人确认各对象期望组成、电荷与多重度，通道化学定义由人写。

   ```sh
   ag catalog object <study> --id <对象> --name <名称> --formula <组成> --charge <电荷> --multiplicity <多重度>
   ag catalog channel <study> --object <对象> --id <通道> --name <名称> --definition '<化学定义>' --product-branch <产物标签>
   ```
   采样中新发现的通道加 `--discovered`，人确认定义后用 `ag catalog channel <study> --object <对象> --id <通道> --update --confirm`；没有确认不抹掉“待确认通道”。来源：[catalog v2](../../../docs/ag-catalog-2.md)。

2. **产生候选。**一维扫描先看沿程诊断，逐段审阅成键与构象变化，再从合格局部峰生成草稿。点几何存档与文件沿用规则见[一维扫描说明](#初猜来源一维弛豫扫描)；以下两条扫描命令的预期成断键声明保持一致：

   ```sh
   ag scan-path <扫描Attempt> --study <study> --expect-bond <I-J>
   ag scan-peak <扫描Attempt> --study <study> --out <新XYZ> --gaussian-ts <新GJF> --route '# <方法/基组> Opt=(TS,CalcFC) Freq' --expect-bond <I-J>
   ag qst-endpoints <study> --reactant <反应物Attempt> --product <产物Attempt> --mapping <完整映射JSON> --route '# <方法/基组> Opt=(QST2,CalcFC) Freq' --out <新QST2_GJF>
   ```
   峰附近有警告先人工审阅，不自动换峰；一维可用 `--point <序号>` 指定另一个合格局部峰；沿程点多为受约束非驻点，成键差异不证明极小点身份；诊断阈值只决定是否列出。scan-path 不支持二维，二维 scan-peak 仍须显式 `--point <i,j>` 并人工审阅。
   QST 两端须已 fetched 且优化收敛，映射文件含完整 `product_to_reactant`；对称等价排列歧义报错后，人改映射或以 `--keep-mapping --reason '<理由>'` 明确保留。只做正规旋转和平移，不镜像、不推断映射；审阅 RMSD、位移、每段电荷多重度及实际行顺序。新取向不能读取旧 chk 的 Cartesian 力常数。
   生成命令不自动 prepare 或提交；扫描草稿的电荷、多重度取自 manifest。人须逐项审阅几何、方法、电荷与多重度及立体警告。草稿不含 Link0，也未选择资源；人先明确档位与 walltime，prepare 可补缺失的 `%nprocshared` 和 `%mem`，其他所需 Link0 仍由人明确填写。route 由人或卡片从已审阅方法表填写，扫描草稿拒绝扫描/冻结关键词和父 chk 力常数读取。手工或文献结构也按同样要求审阅，再走第 3 步。随后仍须解除扫描约束，完成 TS 优化、Freq、恰好一个虚频的检查、振动方向人工审核及双向 IRC 端点识别；扫描局部极大自身不能判定 TS。
   来源：[T133](../../../docs/redesign-tasks/T133-scan-peak-ts-input.md)、[T134](../../../docs/redesign-tasks/T134-endpoint-qst2.md)、[T136](../../../docs/redesign-tasks/T136-scan-path.md)。

3. **登记候选。**默认不登记候选；可在第 2 步 scan-peak 或 qst-endpoints 命令末尾加 `--register-candidate --object <对象> --candidate-id <候选> --target-channel <通道>`；或者独立登记已审阅的 XYZ：

   ```sh
   ag catalog candidate <study> --object <对象> --id <候选> --xyz <XYZ> --origin <来源类别> --target-channel <通道>
   ```
   `--origin` 可为 scan、qst、template-transform、path-search、manual、literature；有父 Attempt 才加 `--parent-attempt <父Attempt>`。文献来源必须加 `--doi <DOI>`，并记录 `--si-location '<SI位置>'`；登记只核验 DOI 格式，来源内容须人工核实。
   登记只是来源记录，不是科学判断；不重复登记同一候选。QST 自动存档的是映射对齐后的产物端点，并非已找到的 TS。生成命令的 `--dry-run` 只预览登记，仍写草稿；登记失败保留导出，先核对现场，不自动重跑生成。
   来源：[catalog v2](../../../docs/ag-catalog-2.md)、[T133](../../../docs/redesign-tasks/T133-scan-peak-ts-input.md)、[T134](../../../docs/redesign-tasks/T134-endpoint-qst2.md)。

4. **G0 诊断。**默认只报告；按候选所属对象核对完整性。元素序列一致不证明同元素身份；没有参考或期望未知记未核对，手工来源可加 `--reference-attempt <参考Attempt>`。

   ```sh
   ag g0 <study> --object <对象> --candidate <候选> --windows <窗口JSON> --json
   ag g0 <study> --object <对象> --candidate <候选> --windows <窗口JSON> --modes-attempt <频率Attempt> --reaction-coordinate distance:<I-J>:forming --atom-mapping <映射JSON> --json
   ```
   T162 的 `--atom-mapping` 文件顶层为 `mappings`；每项按 object/candidate 和候选 SHA-256 绑定目标，完整 `candidate_to_target` 表示候选 i → 目标 j，两侧均从 1 开始。reference 与 frequency 分别声明并绑定实际来源哈希；频率目标还绑定所选日志段、行范围及段哈希。先按既有参数/结果规则选择来源，映射文件不替你选择 Attempt；格式见 [显式原子对应](../../../docs/g0.md#显式原子对应t162)。
   `declared_verified` 只表示双射、元素与来源绑定校验通过，化学身份仍须人审；不能用元素序列、同源标签或 RMSD 自动推断映射。缺映射时身份为 `unverified`，不增加科学拒绝或提交门槛；缺有效 frequency 映射时模式不可用，不输出方向投影、最佳模式或依赖身份的 RMSD。
   只有输入完整性和几何损坏两类硬拒绝；普通冲突、距离超窗和立体差异仅标记，不自动改归属。报告 rejected/flagged/clean 不等于科学验收，clean 只表示未发现问题。**G0 是本地诊断，不是门禁；提交与否由负责人决定。**
   窗口文件须在 study 的 `analyses/` 下，相对路径以 study 为基准；顶层只允许 `channels`、`all`、`reaction_coordinates`。距离窗口应用 all + 候选原登记目标通道 + 命令行 `--window`；反应坐标取 `reaction_coordinates[目标通道]`，再追加可重复的 `--reaction-coordinate kind:atoms:role`，编号从 1 开始。distance 角色为 breaking/forming，angle 为 increasing/decreasing/report；通道 ID 须合法。
   适用距离窗口及 distance 反应坐标声明的原子对列在 `geometry.reaction_center_pairs`（原子、元素、距离、成键状态），不标普通冲突，但仍适用两条几何硬拒绝：距离 < 0.5 Å 或 < 0.5 × 共价半径之和。有窗口仍检查超窗；没有模式数据也适用反应中心规则，angle 坐标不声明原子对。
   有已取回 Gaussian 频率结果及经审阅映射时用第二条命令，反应坐标始终用候选编号：断键伸长、成键缩短。工具只转换坐标索引，使用频率原几何与原位移，不旋转、反射或重排；逐坐标投影并考虑模式整体正负号。审阅全部虚频及来源，重叠度只供排序，不设科学阈值。非驻点频率只供诊断；本期不读取 xTB Hessian。
   批量从第一条命令把 `--candidate <候选>` 换成 `--all` 或 `--channel <通道>`，需要模式时另加 `--atom-mapping <映射JSON>`，不加 `--modes-attempt`；模式来源取候选最新一条 Attempt 非空的结果，跳过 diagnosed 等空 Attempt 记录，不按 outcome 筛选。全为空时记“无模式数据”；选中的 Attempt 未取回或没有 Gaussian Freq 段也记无模式数据，不再回退；未声明反应坐标时不做投影，但已提供的映射及所选来源仍须核对绑定。顺序只是建议。显式 `--record` 才写 diagnosed，归属 none、Attempt 为空，不能借此保留旧的最新归属；历史结果仍可查。
   来源：[G0 文档](../../../docs/g0.md)（T137/T138/T161/T162）、[T139](../../../docs/redesign-tasks/T139-card-wording.md) B4/X4。[T163 调查规格](../../../docs/research/xtb-hessian-import.md)只规定后续本地导入方案，导入器未实现、真实配套文件和数值边界仍待补；不能把 xTB `g98.out` 当 Gaussian 频率输入。

   T161/T162：批量对明确分类的频率分段歧义、可定位到单候选的映射声明或绑定错误保留其他成功项，单列 errors 并返回 2；有局部错误时 `--record` 不写任何候选结果。单候选仍直接报错。映射文件读取或顶层身份错误、存档/来源本身损坏、非法路径及其他解析错误仍停止整批；错误不记 clean。

## 4. 资源建议

G0、草稿导出和登记是本地操作，不自动启动计算。扫描及约束 CREST 属单独 Attempt，按点数、约束优化成本及既有耗时估算；资源取所选入口实际档位。Gaussian 草稿的 Link0 补齐与 T154 默认档位说明见 [TS 搜索资源](ts-search.md#4-资源建议)，不从草稿推定资源或提交授权。

## 5. 提交前检查清单

- 核对结构、电荷、多重度、目标原子对、完整映射与立体警告；所有占位符已替换。
- 核对扫描坐标、单位、点数、收敛和完整曲线；二维必须显式选择合格候选，约束采样不能当作真正 TS 优化。
- 本地导出用新文件名，登记来源及对象/通道正确；文献内容经人工核实，不以 DOI 格式通过代替。
- 涉及实际扫描/CREST 提交时按 [确认摘要](../../auto-g16-study/references/confirmation-summary.md)展示结构、方法依据、完整输入、资源、walltime、远程目录和输入哈希，经现行 Study 流程授权；候选诊断不授权提交。

## 6. 结果判据清单

- 初猜几何、原子行序、电荷多重度与已审阅来源对应；QST 映射/对齐及歧义已人工核对，候选不是已验证 TS。
- 扫描候选满足本卡的局部选点与收敛规则；记录警告、完整曲线及未覆盖部分，不以能量排名判定 TS。
- G0 的 rejected/flagged/clean、unchecked、无模式数据与操作错误分别报告；批次不完整时列出失败候选，不能声称全批完成或已登记。
- 反应坐标与模式来源可核对；元素序列相同不证明同元素身份，投影与排名不替代方向人工审阅。
- 记录真实结果及失败来源；明确后续步骤：移除扫描/冻结约束后，按 [TS 搜索](ts-search.md)完成优化、完整 Freq、恰好一个虚频与方向审核，再按 [IRC](irc.md)双向完成并独立验证端点。初猜卡通过不等于 TS 科学签字。

## 7. 常见失败与处理

**一组模板和变换全部冲突，只说明这组模板和变换失败，不构成排除该通道的依据。**在台账登记失败类型；有已登记候选可用 `candidate-result --outcome other` 并在 note 写明模板/变换和冲突，不设通道排除；无可登记几何时先保留本地失败记录，不虚构候选。

**低层优化塌缩到端点，只说明这条低层路线失败；通道应改用其他方法继续，不能据此排除。**已登记候选使用 `ag catalog candidate-result <study> --object <对象> --candidate <候选> --outcome minimum --note '低层路线失败（<方法>）'`，有关联 Attempt 时补 `--attempt <结果Attempt>`，不声明 excluded。

xTB 无虚频或方向不对只降优先级或转为直接做 DFT，不排除候选；G0 的 Gaussian 模式标记 `mode:no_imaginary_mode`、`mode:sign_inconsistent` 同样不导致 rejected。还须审阅 `mode:multiple_imaginary_modes`、`mode:most_negative_not_best`、`mode:non_stationary_frequencies`；这些类别不表示本期支持 xTB Hessian。
来源：[T139](../../../docs/redesign-tasks/T139-card-wording.md) A7/A8/X4、[catalog v2](../../../docs/ag-catalog-2.md)、[G0 模式标记](../../../docs/g0.md#模式投影)。

需要三维及以上扫描或 xTB 多维扫描、白名单外输入段或尚未支持的自动初猜时，写明具体缺口并暂停该步骤。真实作业异常先停止报告；不在原 Attempt 重跑，不用旧 Skill 执行。

## 8. 常见坑

知识衔接：[GKB-0431、GKB-0422：TS 验证与优化排障](../../auto-g16-gaussian-learning-library/references/core-job-types.md)。原指南及其更正见 [TS 初猜工具指南](../references/ts-initial-guess-guide.md)。

- QST 同元素原子交换也可能改变反应映射；外部映射表不能修复实际输入行顺序。
- 全局最高能量、G0 clean 或约束构象都不能当作已验证 TS；光滑扫描也不证明同一路径。
- `--dry-run` 只预览候选登记，仍生成草稿；登记失败不自动重跑导出。
