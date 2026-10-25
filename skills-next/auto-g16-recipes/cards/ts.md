# TS 优化与频率

## 要点

- 用于主族闭壳层同一势能面的 TS 候选优化与频率审核；通过本卡只得到方向经审阅的一阶鞍点候选，路径验证还需 IRC。（[见第 1 节](#1-适用范围)）
- 机理假设须已签字，结构与代表集合已确认，目标原子对及映射明确；失败搜索不等于该机理不存在。（[见第 2 节](#2-前置条件)）
- 提交前展示结构、立体警告、方法依据、完整 route、资源、walltime、远程目录与输入哈希，按 Study 流程取得聊天批准记录、匹配长期规则或 Mac 人工确认。（[见第 5 节](#5-提交前检查清单)）
- Opt 和 Freq 须完整收敛，按原始负频计数恰好一个虚频，并人工审核协调的目标键变化；不能删小负频凑数。（[见第 6 节](#6-结果判据清单)）
- 中断优化没有 Freq 时不能用 RCFC 接续；缺少 `final_input.xyz` 或 chk 不可读时停止报告，不猜几何或自动重提。（[见第 7 节](#7-常见失败与处理)）

## 1. 适用范围

主族闭壳层、同一势能面的过渡态候选优化与频率审核。适用于人提供并审阅过的单结构初猜；不做自动反应发现、金属、开壳层或跨自旋面搜索。通过本卡只得到方向经审阅的一阶鞍点候选，路径验证还需 [IRC](irc.md)。

## 2. 前置条件

[机理假设](reaction-plan.md)已由人签字，目标步骤、反应物/产物身份和原子对应明确；结构与代表构象集合已确认。预先列出正在形成、断裂或迁移的原子对（按输入行号，从 1 开始），并说明方法依据、溶剂、电荷、多重度。初猜来源可选（科学策略提炼自 [旧设计 R10](../../../archive/docs/end-to-end-reaction-computation-workflow.md)）：

- Hessian 引导的单结构初猜：已有合理 TS 状几何时，用反应坐标与曲率信息判断适用性；CalcFC 不能弥补错误原子映射。
- 沿反应坐标做一维弛豫扫描：记录坐标、范围、步长、冻结项及选点依据，局部极大仅是初猜，具体做法见下。
- QST2：已优化端点的完整映射、正规旋转、歧义处理及草稿复核见下方“TS 初猜工作流”。QST3 仍需额外 TS 初猜，使用已有多结构输入并逐组审阅。
- 类比已知 TS：记录 DOI/结构来源、映射及差异；类比几何不意味着该方法或机理已获验证。
- 扫描初猜可用 `ag scan-peak`；全自动 TS 搜索不在当前范围，工具给的结构仍需人工审阅。

### 初猜来源：一维弛豫扫描

优先选目标反应**正在形成的键**的两个原子编号，以距离逐步缩短的方向扫描； 断键、键角或二面角只有在机理假设支持时才选。范围从合理接近构型跨过预期 成键区域，避免初始原子重叠；先粗扫再围绕候选峰细扫。例如成键距离可先试 每步 0.1 Å，再依据曲线改为 0.02–0.05 Å；这些是探索起点，不能代替体系判断。 质子转移或同步成断键用单一坐标可能偏离路径，保留其他通道与构象的比较。

先用 xTB 便宜预扫描，再以候选区域做同一坐标的 DFT 弛豫扫描，或将审阅后 的候选直接作为 DFT TS 优化初猜。xTB 的约束是势能惩罚，实际几何值可能偏离 目标值；facts 同时报告两者，能量为 xtbscan.log 中扣除约束偏置的 Hartree 值。 [`xTB 约束/扫描语法`](https://xtb-docs.readthedocs.io/en/latest/xcontrol.html)示例：

```text
$constrain
  distance: 1, 2, auto
$scan
  1: 3.0,1.4,17
$end
```

这里的 `1` 是内部坐标约束序号（不包括 force constant 或 atoms 项）；先替换 为已审阅的原子编号。仅允许一条 scan、1–100 点，prepare 会自动启用 verbose 以保留逐点收敛证据。scan-peak 至少需要三点；虽然校验接受单点， [xTB 6.7.1 插值](https://github.com/grimme-lab/xtb/blob/v6.7.1/src/constrain_param.f90) 的分母为点数减一，实际扫描应避免单点设置。`ag prepare --template xtb --input <起始.xyz> --constraints <扫描.inp> --param=--gfn=2 --param=--opt` 再加通用 study、tier、 walltime、label 和 method-basis 参数。SCNet 使用已配置的 `--cluster`，仍须 按 Study 流程取得聊天批准记录、匹配长期规则或 Mac 人工确认；不通过卡片拼接远程命令。

DFT 输入用 `opt=modredundant`，采用默认 Å 坐标（不带 Units 选项，避免摘要 单位与扫描范围错配）；显式坐标后留空行，再写一个段，例如：

```text
B 1 2 S 16 -0.1
A 3 1 2 F
```

上述原子编号必须按结构替换，F 项只在有科学依据时保留。B/A/D 分别为键、角、 二面角；一维用一个 S，1–50 步，距离单位 Å、角度单位度；Gaussian 包含初始点， 终值为初值加步数乘步长。F 不写附加值。不得与 TS/QST2/QST3 混用扫描段。 prepare 摘要显示编号、元素、初值、步数、步长、终值和冻结坐标，逐项审阅。

取回后运行 `ag facts <attempt>`，再运行 `ag scan-peak <attempt> --out <新文件.xyz> [--point <序号>] [--json]`。 候选只取内部严格局部极大：该点及左右紧邻点均已收敛且有能量，该点能量严格高于两侧。 工具列出全部候选的原扫描序号（从 1 开始）、实际坐标值、Hartree 能量与相对能； 相对能以全部已收敛扫描点最低能为零，单位 kcal/mol。默认导出最高的局部峰， 用 `--point` 可指定其他局部峰；非候选序号拒绝。无合格局部极大时拒绝导出， 审阅扫描范围、坐标及收敛证据；单调曲线、平台或只有边界高点都不回退到全局最高点。 **scan-peak 的结果只是 TS 初猜。气相离子–分子反应里，全局最高点常常不是 TS**： 分离方向的高能端可能高于势阱内的局部反应峰，不能凭全局能量排名定位 TS。 查看所选点两侧各两个点 （边缘处只列存在的点）的实际坐标值、能量和收敛状态，并检查全部扫描曲线：

- “范围不够，峰可能在范围外”：端点能量不低于所选局部峰；端点不会导出。 结合分离渐近区与完整曲线判断，必要时扩大有物理依据的范围并提出新 Attempt； 该提示不证明内部局部峰错误，也不能把单调曲线里的内部最高点当成峰。
- “可能跳到了另一条路径或另一个构象”：相邻能差超过 20 kcal/mol，或按原子编号 对齐的全原子 RMSD 超过 0.5 Å。这些阈值只决定是否列出启发式提示，不是科学判据；检查结构、电子态和坐标步长， 不能自动删除这些点或断言机理改变；平滑曲线也不能证明同一路径。
- “有未收敛的点或收敛证据缺失”：这些点及紧邻它们的点不参与选择；缺点可能隐藏局部峰。 回看原日志并人工决定是否重新设计扫描；不自动重提。

scan_points.xyz 保存各已报告点的最终几何；未收敛点只是最后迭代几何，未计算点 无几何。文件已存在且相同则沿用，不同则停止核对；scan-peak 的输出必须是新文件。 生成草稿前先看 `ag scan-path <attempt>` 的诊断，按下方“TS 初猜工作流”生成并审阅草稿；扫描局部极大自身不能判定 TS。

### 初猜来源：Gaussian 二维弛豫扫描

两个坐标明显耦合（如成键同时伴随质子或硼转移）时，可在同一 `Opt=ModRedundant` 段写两条 S 行；先用较粗网格定位区域，例如：

```text
B 1 2 S 2 -0.1
A 3 1 2 S 2 5.0
```

原子编号、范围和步长须按已审阅结构替换；两坐标不能共用全部原子。 一维、二维 S 行的步长均须含小数点（如 `5.0`，不能写 `5`）；整数写法会在 Gaussian L101 报错。 每维 1–20 步，总点数 `(n1+1)×(n2+1)` ≤ 144；上例为 3×3、9 点。 每点都是约束优化，耗时随总点数增长，相当于把一个一维扫描重复另一维的点数次； 提交前核对两维起点、终点、单位、资源与 walltime。xTB 仍只允许一条扫描行。 `ag facts` 用几何实测值定位网格，缺点为 null；坐标无法唯一匹配或重复占格即报错， 此时停下核对，不放宽容差。鞍点候选要求自身及上下左右均收敛，沿一维严格极大、 另一维严格极小；边界不列出，无候选也不能据此断言不存在 TS。 二维导出必须显式 `ag scan-peak <attempt> --point 2,2 --out <新文件.xyz>`， 编号从 1 开始，顺序对应两条 S 行；只有列出的候选允许导出，不自动选择。 候选只是 TS 初猜，仍需解除扫描约束、TS 优化、Freq、振动方向人工审阅及双向 IRC 端点识别。

按 R10 为每个基元步骤与立体通道列出催化态、结合方式、构象、接近拓扑、 离子对/添加剂排布；不能只手工造一个 major 和一个 minor 就声称覆盖完整。 路径/链式搜索仅在工具支持并可审阅时作为候选策略，不编造执行接口。

涉及质子转移时，比较直接迁移与有化学依据的显式溶剂或质子穿梭分子辅助 路线；说明分子数、质子供受体与来源，并按 reaction-plan 的 R03/R06 配平 参考态，不能仅给 TS 加水而让反应物参考态少一个水分子。

**柔性 TS：先固定反应中心，再做构象搜索（T13-4）。** 固定有依据的成断键 距离/关键角度，探索外围可转键、结合方式及穿梭分子排布；保留约束与 几何来源，再解除搜索约束做真正 TS 优化、Freq、方向审核及双向 IRC。 约束构象不是已经验证的鞍点；使用 [CREST 卡片](crest-screen.md) 的 `--constraints` 准备经审阅的约束搜索，不把普通无约束 CREST/RDKit 极小点 搜索冒充该步骤，也不强套极小点的窗口剪掉整条 TS 通道。 TS 族必须双路线：约束 CREST 与按特定相互作用/进攻方向假设定向构造后 约束 CREST（directed）；关键中间体、复合物同样必须，可旋转键较多也建议。 按 [构象工作流](../../auto-g16-structures/references/conformer-workflow.md) 合并来源、做同层级单点并读 coverage 的未匹配项、最低构象来源和低能独有项。 出现“采样可能不足”时讨论延长 CREST、对适用极小点增加 ETKDG 种子或补 定向构造，经人确认扩大后重出报告；覆盖报告不能证明采样已经完备。

### 覆盖与失败记录

覆盖结论统一为 **在声明的通道范围与采样预算内稳定**；列明通道范围、预算及未覆盖部分，未再找到新结构不能证明全局完备。 catalog 的“候选 / 采用 / 退役”是对象采用状态，不是通道覆盖状态。通道六态按下列优先顺序派生：

| 通道状态 | 含义及来源 |
|---|---|
| 已验证（verified） | 负责人声明并附原话，声明时至少有最新归属 verified 的候选指向该通道；仍须满足第 6 节与双向 IRC 科学要求。 |
| 低置信度排除（excluded_low_confidence） | 负责人以 `excluded-low-confidence` 声明并附理由、原话；只表达有限证据下的判断。 |
| 待确认通道（pending_confirmation） | 采样中新发现，以 `--discovered` 登记且尚未确认；优先于候选归属派生。 |
| 暂定找到（待负责人确认，tentative_found） | 有候选最新归属 tentative 或 verified 指向本通道，但没有有效通道声明；候选 verified 本身不等于通道已验证。 |
| 已尝试未找到（attempted_not_found） | 有关联候选、但不满足以上状态；登记本身即可派生，不保证已运行计算，须查 ledger 的实际结果。 |
| 未尝试（untried） | 无有效声明、无待确认发现、无关联候选。 |

候选通过目标通道或历史任一次归属关联；“暂定找到”只看最新归属，不回退到旧 verified。`cleared` 需负责人原话，撤销声明后按发现/候选规则重算；整体 coverage 不改变通道状态。通道确认可用 `channel --update --confirm`，无需原话，不等于科学验证；具体命令见下节。 保留失败搜索、错误鞍点、模式塌缩、组分脱离及重复收敛，记录步骤/通道、初猜策略、构象来源、实际结果和后续处置；失败搜索不等于机理不存在。涉及写入时：**v4.6.0 在两台电脑部署完成之前，真实研究 study 不写 v2 事件**。
来源：[catalog v2 第 5 节](../../../docs/ag-catalog-2.md#5-通道派生与查询)、[T139](../../../docs/redesign-tasks/T139-card-wording.md) A4/X3/X4。

### TS 初猜工作流

下列尖括号均为占位符，按已审阅方案填写；生成文件须用新名字。G0 接口须在 T137、T138 合入后以实际 `--help` 核对；当前未具备的步骤先保留为待办，不自造接口。每个写入步骤均受部署限制；`--upgrade-catalog` 只是明确确认格式升级，不能替代部署。

1. **定义对象与通道。** `ag catalog object-suggest <study> --attempt <参考Attempt>` 只提供建议；人确认各对象期望组成、电荷与多重度，通道化学定义由人写。**v4.6.0 在两台电脑部署完成之前，真实研究 study 不写 v2 事件**。

   ```sh
   ag catalog object <study> --id <对象> --name <名称> --formula <组成> --charge <电荷> --multiplicity <多重度>
   ag catalog channel <study> --object <对象> --id <通道> --name <名称> --definition '<化学定义>' --product-branch <产物标签>
   ```
   采样中新发现的通道加 `--discovered`，人确认定义后用 `ag catalog channel <study> --object <对象> --id <通道> --update --confirm`；没有确认不抹掉“待确认通道”。来源：[catalog v2](../../../docs/ag-catalog-2.md)。

2. **产生候选。** 一维扫描先看沿程诊断，再从合格局部峰生成草稿；两条命令的预期成断键声明保持一致：

   ```sh
   ag scan-path <扫描Attempt> --study <study> --expect-bond <I-J>
   ag scan-peak <扫描Attempt> --study <study> --out <新XYZ> --gaussian-ts <新GJF> --route '# <方法/基组> Opt=(TS,CalcFC) Freq' --expect-bond <I-J>
   ag qst-endpoints <study> --reactant <反应物Attempt> --product <产物Attempt> --mapping <完整映射JSON> --route '# <方法/基组> Opt=(QST2,CalcFC) Freq' --out <新QST2_GJF>
   ```
   峰附近有警告先人工审阅，不自动换峰；沿程点多为受约束非驻点，成键差异不证明极小点身份；诊断阈值只决定是否列出。scan-path 不支持二维，二维 scan-peak 仍须显式 `--point <i,j>` 并人工审阅。
   QST 两端须已 fetched 且优化收敛，映射文件含完整 `product_to_reactant`；对称等价排列歧义报错后，人改映射或以 `--keep-mapping --reason '<理由>'` 明确保留。只做正规旋转和平移，不镜像、不推断映射；审阅 RMSD、位移、每段电荷多重度及实际行顺序。新取向不能读取旧 chk 的 Cartesian 力常数。
   生成命令不自动 prepare 或提交；扫描草稿的电荷、多重度取自 manifest，逐项核对。草稿不含 Link0；prepare 前须补匹配档位的 `%nprocshared`，`%mem` 可由 prepare 补齐。route 从已审阅方法表填写，扫描草稿拒绝扫描/冻结关键词和父 chk 力常数读取。手工或文献结构也按同样要求审阅，再走第 3 步。
   来源：[T133](../../../docs/redesign-tasks/T133-scan-peak-ts-input.md)、[T134](../../../docs/redesign-tasks/T134-endpoint-qst2.md)、[T136](../../../docs/redesign-tasks/T136-scan-path.md)。

3. **登记候选。** 可在第 2 步生成命令末尾加 `--register-candidate --object <对象> --candidate-id <候选> --target-channel <通道>`；或者独立登记已审阅的 XYZ：

   ```sh
   ag catalog candidate <study> --object <对象> --id <候选> --xyz <XYZ> --origin <来源类别> --target-channel <通道>
   ```
   `--origin` 可为 scan、qst、template-transform、path-search、manual、literature；有父 Attempt 才加 `--parent-attempt <父Attempt>`。文献来源必须加 `--doi <DOI>`，并记录 `--si-location '<SI位置>'`；登记只核验 DOI 格式，来源内容须人工核实。
   登记只是来源记录，不是科学判断；不重复登记同一候选。QST 自动存档的是映射对齐后的产物端点，并非已找到的 TS。生成命令的 `--dry-run` 只预览登记，仍写草稿；登记失败保留导出，先核对现场，不自动重跑生成。**v4.6.0 在两台电脑部署完成之前，真实研究 study 不写 v2 事件**。
   来源：[catalog v2](../../../docs/ag-catalog-2.md)、[T133](../../../docs/redesign-tasks/T133-scan-peak-ts-input.md)、[T134](../../../docs/redesign-tasks/T134-endpoint-qst2.md)。

4. **G0 诊断。** 默认只报告；按候选所属对象核对完整性，只比较元素序列，不能检出同元素原子交换。没有参考或期望未知记未核对；手工来源可加 `--reference-attempt <参考Attempt>`。

   ```sh
   ag g0 <study> --object <对象> --candidate <候选> --windows <窗口JSON> --json
   ag g0 <study> --object <对象> --candidate <候选> --windows <窗口JSON> --modes-attempt <频率Attempt> --json
   ```
   只有输入完整性和几何损坏两类硬拒绝；普通冲突、距离超窗和立体差异仅标记，不自动改归属。报告 rejected/flagged/clean 不等于科学验收，clean 只表示未发现问题。**G0 是本地诊断，不是门禁；提交与否由负责人决定。**
   有已取回 Gaussian 频率结果时用第二条命令，窗口 JSON 的 `reaction_coordinates` 按目标通道声明 distance 的 breaking/forming（断键伸长、成键缩短）。逐坐标投影并考虑模式整体正负号；审阅全部虚频及模式来源，重叠度只供排序，不设科学阈值。非驻点频率只供诊断；本期不读取 xTB Hessian。
   批量把 `--candidate <候选>` 换成 `--all` 或 `--channel <通道>`；顺序只是建议。显式 `--record` 才写 diagnosed，归属 none、Attempt 为空，不能借此保留旧的最新归属；历史结果仍可查。**v4.6.0 在两台电脑部署完成之前，真实研究 study 不写 v2 事件**。
   来源：`docs/g0.md`（T137/T138）、[T139](../../../docs/redesign-tasks/T139-card-wording.md) B4/X4；最终标记与参数须按合并实现核对。

5. **准备与提交。** 按第 3–5 节审阅完整输入与摘要，照常运行：

   ```sh
   ag prepare --study <study> --template gaussian --input <GJF> --tier <档位> --walltime <时限> --label <标签> --method-basis '<方法依据>' --card ts
   ag submit <新Attempt>
   ```
   按 [AGENTS.md 3.4](../../../AGENTS.md) 取得当前会话明确批准并绑定记录、匹配已设长期规则或由人点击 Mac 对话框；前两种分别显式加 `--approval <批准ID>` 或 `--policy <规则名>`，不能从 G0 推定授权。每个 Attempt 至多提交一次，UNKNOWN 仅只读核对。来源：[AGENTS.md 3.1–3.5](../../../AGENTS.md)。

6. **登记结果。** 审阅后记录实际 outcome 与归属；暂定归属不需原话，已验证归属需负责人原话并满足第 6 节及 IRC 要求：

   ```sh
   ag catalog candidate-result <study> --object <对象> --candidate <候选> --outcome <实际结果> --attempt <结果Attempt> --assign tentative --channel <通道>
   ag catalog member <study> --object <对象> --attempt <已验证Attempt> --role ts
   ag catalog candidate-result <study> --object <对象> --candidate <候选> --outcome accepted --attempt <已验证Attempt> --assign verified --channel <通道> --quote '<负责人原话>'
   ```
   verified 还要求 Attempt 是本对象成员、已 fetched、facts 可读且 n_imag=1；这些机器检查不证明方向或双向 IRC 已验收。accepted 本身不等于 verified；产物不唯一用 `--assign undetermined --channel <候选通道一> --channel <候选通道二>`，并列全体可能通道。**v4.6.0 在两台电脑部署完成之前，真实研究 study 不写 v2 事件**。
   来源：[catalog v2](../../../docs/ag-catalog-2.md)、[T139](../../../docs/redesign-tasks/T139-card-wording.md) A9/B6/X3/X4。

7. **通道声明与覆盖结论。** 先查 `ag catalog ledger <study> --object <对象> --channel <通道> --json`，以实际尝试结果支撑“已尝试未找到”，区分仅登记、诊断与已计算失败。负责人审阅后才声明：

   ```sh
   ag catalog channel-status <study> --object <对象> --channel <通道> --status <声明类别> --quote '<负责人原话>'
   ag catalog coverage <study> --object <对象> --statement stable --scope '<通道范围>' --budget '<采样预算>' --quote '<负责人原话>'
   ```
   声明类别为 verified / excluded-low-confidence / cleared；排除另需 `--reason '<理由>'`，三者都需原话，不能因一次低层失败而排除。整体结论只写“在声明的通道范围与采样预算内稳定”，撤销用 `--statement withdrawn`，保留 scope/budget/quote。原话逐字来自本 study 当前对话，CLI 不能验证发言身份。
   **v4.6.0 在两台电脑部署完成之前，真实研究 study 不写 v2 事件**。来源：[catalog v2](../../../docs/ag-catalog-2.md)、[T139](../../../docs/redesign-tasks/T139-card-wording.md) B7/X3/X4。

## 3. 输入模板

下列示例中的 `%mem` 可省略，由 ag 自动填写；显式填写时仍检查不超过档位内存的 85%。

方法/基组：见 [acceptance-methods.md](../../auto-g16-study/references/acceptance-methods.md)。 骨架中的 `<方法/基组>` 必须按已审阅方案替换，并补齐适用的色散与溶剂设置。

Hessian 策略是按体系与成本选择的可选路径，不强制两阶段计算：

- **路径 A**：直接在完整方法下做 `Opt=(TS,CalcFC) Freq`，初始 Hessian 与目标势能面一致， 是稳妥的基线路径；初始完整 Hessian 的成本较高，最终 Freq 仍不可省。
- **路径 B（较大体系推荐）**：先用小基组做 `Opt=(TS,CalcFC) Freq`， 例如方法表中不含弥散的同泛函组合，具体组合及适用性由计算方案签字确定。 审核恰好一个虚频且方向正确后，以它为父 Attempt，通过下述 `--parent-chk` 和 `Opt=(TS,RCFC) Freq` 在完整方法下重新优化并计算最终频率； 显式坐标取父 `final_input.xyz`，沿用下述取向和父 chk 校验。 小基组 TS 只作中间步骤，不进入剖面；完整方法仍按方法表保留所需弥散、色散与溶剂， 其最终 TS 必须重新满足第 6 节，后续 IRC 使用完整方法的 TS 与 Hessian。

单结构基础 route 为 `opt=(ts,calcfc) freq`。以下仅为[研究方法](../../auto-g16-study/references/acceptance-methods.md)的输入骨架，填入已审阅的显式坐标，保留空行；正式方法须另有文献依据或明确兜底声明。

```text
%chk=ts.chk
%nprocshared=8
%mem=10GB
#p <方法/基组> opt=(ts,calcfc) freq

<TS 步骤与构象编号>

<charge> <multiplicity>
<element> <x> <y> <z>

```

阴离子弥散、色散和溶剂按方法表及已签方案填写，展示最终完整 route。决定结论的关键能垒按方法表 做不同类型泛函的单点敏感性，包含 TS 和完整参考物种；连接到 [profile](profile.md)。`NoEigenTest` 仅在初始 Hessian 已确认有且只有一个负本征值、且对应目标反应方向时使用，在 review 和提交摘要写明曲率/初猜诊断依据及理由；它关闭优化中的曲率检查，不免除最终 Hessian、虚频数量和方向审阅，不能作为常规默认。

```text
ag prepare --study <study_id> --template gaussian --input <ts.gjf> --tier simple --walltime 24:00:00 --label ts-c01 --method-basis <文献先例 DOI 及位置 / 本课题既有方案及来源（不是文献先例，精度未经验证） / 兜底方法声明>
```

有真实上游 Attempt 才使用已有 `--parent` / `--relation` 参数；人提供的外部结构在 study 记录来源，不虚构 parent。复用父 chk 时，同时声明 `--parent <parent_id> --relation ts_from --parent-chk <parent_id>:<父输入中声明的chk文件名>`。父 Attempt 必须为 finished/fetched，submit 确认前和确认后都核对调度器中已无该作业；父子必须在同一集群。

例如经审阅可复用波函数与力常数时，使用以下 Link0/route 替换上面的相应行，标题、电荷多重度和**显式坐标仍须写在输入中**：

```text
%oldchk=parent.chk
%chk=ts-reuse.chk
%nprocshared=8
%mem=10GB
#p <方法/基组> guess=read opt=(ts,rcfc) freq
```

RCFC 需要父 chk 中确有适用的力常数；仅复用波函数可用 `guess=read opt=(ts,calcfc) freq`。核对父 chk 的方法、几何、原子顺序、电荷与多重度是否适用；哈希相同不代表科学上适用。`Geom=Check` 和 `Geom=AllCheck` 继续拒绝，`%chk` 必须不同于固定的 `%oldchk=parent.chk`。

RCFC 读取父 Freq 保存的 Cartesian Hessian；`Opt=(TS,ReadFC)` 可在内部坐标兼容、 力常数来源明确时选用，不能把它和 RCFC 当成无条件互换的同义词。 路径 B 采用完整小基组 Freq 的 Hessian，不把优化更新的近似 Hessian 冒充它。 更换基组时，`Guess=Read` 是否适用须单独审阅；只复用 Hessian 时可移除该选项。 选项语义见 [Gaussian Opt 手册转载](https://www.conflex.co.jp/gaussian_support/opt.php)，使用前核对实际版本。

RCFC/ReadFC 复用时，先对父 Attempt 运行 `ag facts`，显式坐标取 `final_input.xyz`（最终几何的 Input orientation，去掉 XYZ 前两行），保持原子顺序， 不能直接拿通常为 Standard orientation 的 `final.xyz`。facts 分别记录取向； 未打印 Input 表时不臆造该文件，须核对原日志或改用 CalcFC。 prepare 已对 `--parent-chk` + RCFC/ReadFC 按固定原子顺序校验输入与父作业 `final_input.xyz` 的坐标，每个原子的偏差 不得超过 1e-4 Å，不做旋转/平移对齐。旧导出文件相同则沿用，不同则停止人工核对。 若后续要复用本 TS 的力常数，可在计算该 TS 时加入 `nosymm`，使两种取向一致； 父 route 已带 `nosymm` 时可取任一导出坐标，仍须匹配父几何。 仅在子作业加 `nosymm` 不能修正父 chk 已有的框架；取向匹配不替代力常数适用性审阅。

prepare 只做本地声明；submit 在授权前只读取得父 chk 大小与 SHA256，并显示父 ID、来源文件名、大小、哈希前 12 位及目标 parent.chk。确认后专用操作独占创建副本，源/目标哈希都须等于确认值；父文件只读。远端需 Python ≥ 3.6 和 Linux /proc 支持固定描述符助手，缺少即停止；先运行 `ag doctor --cluster <cluster>` 查看 Python 版本和 /proc 支持。复制失败、255、超时或哈希改变均记 failed_presubmit，不 qsub、不重试、不删除副本；报告后由人决定新 Attempt。

## 4. 资源建议

小体系首先提出 simple（8 核 / 12 GB，`%mem=10GB`），24:00:00；规模或已有耗时支持时提出 general（22 核 / 50 GB，`%mem=42GB`），48:00:00。complex（44 核 / 120 GB，`%mem=100GB`）需具体资源理由。CalcFC 与 Freq 均有 Hessian 成本；每个 TS 构象分别估计，不把加核当作收敛修复。

`MaxCycles` 只限制步数，不能保证不超 walltime。按 `walltime ≥ 1.3 × (t_CalcFC + t_step × MaxCycles + t_Freq)` 估算， 各项须用本体系**首个作业实测校准**，不能外推小分子的耗时；计入额外 Hessian 重算成本。

## 5. 提交前检查清单

- 假设签字、初猜来源、目标成键/断键原子对、构象覆盖与原子映射均明确，结构无未解释近接触。
- 身份、电荷、多重度、立体化学与目标一致；route 的方法、色散、溶剂与比较物种一致。
- 坐标和占位符已替换；核数匹配档位，内存不超过 85%，chk 仅文件名；当前输入不依赖尚未支持的额外段；使用父 chk 时核对附件声明和确认摘要。
- 按 [确认摘要](../../auto-g16-study/references/confirmation-summary.md)展示结构、立体警告、方法依据、完整 route、资源、walltime、远程目录、输入哈希；按 Study 流程取得聊天批准记录、匹配长期规则或 Mac 人工确认。

## 6. 结果判据清单

- `termination=normal`、`opt_converged=true`、`freq_step_converged=true`；缺失/不通过则读原日志，不能推定通过。Opt 和 Freq 都已完成，完整模式数应为非线性 3N−6 / 线性 3N−5。
- **恰好一个虚频**：`n_imag=1`，按原始负频计数，小负频也不能删掉凑数。零或多个虚频均不满足 TS 判据。
- **低频残余**：记录末次已完成频率段的 `Low frequencies ---` 第一行及原日志行号，核对平动、转动残余。 TS 的真实虚频可能排在这些残余之前，软振动也可能混排；必要时连同后续行及投影后的频率、模式辨认， 不能把首行所有数都当残余或按数值大小直接删除真实虚频。依据：[Gaussian 振动分析说明 §2.1](https://gaussian.com/wp-content/uploads/dl/vib.pdf)。 **辨认出的平动、转动残余**绝对值超过约 20 cm⁻¹ 时，在 review 标为“残余偏大”，提示几何收敛或积分网格可能不足、 热化学中的低频熵不可信，不直接接受；提出更严收敛标准或积分网格重新优化并做 Freq 的新 Attempt，经人确认后提交。 缺该行或无法区分模式则写缺证据。它不是 `facts.json` 的 `frequencies_low`（cclib 提取的最低几个振动频率），不能用该字段代替。
- **振动方向对应目标键变化**：逐项核对 `facts.json` 的 `imag_modes[].pairs[].atoms`、`elements`、`distance`、`distance_change_rate` 与目标原子对。全局振动正负号任意，须查看同一方向上成键缩短/断键伸长等协调变化，不能仅靠频率大小或单个符号判断。
- 当前 `imag_modes` 只列距离小于 3.5 Å 的原子对中变化率绝对值最大的五对；缺目标对并不证明它不动。先用 `ag mode-review <attempt> --study <dir> --pair 1-2 --pair 2-3 --mode 1 --amplitude 0.3 --out analyses/mode-review.json`（替换为目标原子编号，输出须为新文件）报告目标对距离变化并导出正负位移 XYZ，再人工审核协调方向；振幅为最大原子位移 Å，模式按频率升序编号。取向或频率段证据不足时写不通过并停下，命令不判定反应坐标是否正确。
- 出现长键、断键、强电荷转移、SCF 多个解或近简并迹象时，审查电子态并提出独立 Stable 诊断，按 [失败诊断](failure-diagnosis.md#电子态与-stable-诊断) 审阅 T30 的 `wavefunction_stability` 及原文行；未诊断不算稳定，稳定也不证明闭壳层方法足够。需要非限制性或多参考方法时明确超出本卡范围。
- 确认最终身份与预期一致；柔性 TS 列出审阅过的构象和未覆盖部分，不将单个 TS 的能量直接当作唯一反应能垒。
- 可用 [TS 立体标签](../../auto-g16-structures/SKILL.md#ts-立体标签) 按已签参照产物与原子映射标注构型并核对催化剂，通道建议须人工确认，不替代本节判据。
- `review.md` 写清判据、事实位置与人的方向审核意见；更新 study 假设。IRC 按各产物分支内部的重要性和结构新颖性安排，不按全局权重；暂缓的候选仍为“未验证”。未双向完成并识别端点不能写“已验证 TS/机理”。

按**各产物分支内部**的重要性和结构新颖性安排 IRC，不按全局权重筛掉次要分支。以下情形必须做 IRC：

- 引入新的成断键集合或质子转移方式。
- 引入新的活化模式。
- 在所属产物分支内贡献显著。
- 改变最低 TS 排名或明显改变预测的 ee / dr。
- 模式或产物归属存在歧义。

高选择性反应中次要产物的全部 TS 全局权重都可能很小，但它们决定 er 的分母。暂缓 IRC 的候选仍是“未验证”，不能称为已验证；任何“TS 已验证”仍须恰好一个虚频、振动方向经人审核符合目标反应坐标、双向 IRC 走完并识别端点。IRC 两端必须继续独立 Opt+Freq 并确认为极小点，有限步数的路径终点不能直接当作稳定物种。
来源：[T139](../../../docs/redesign-tasks/T139-card-wording.md) A5/X3、[AGENTS.md 第 6 节](../../../AGENTS.md)。

TS 后分岔或产物分支不能唯一确定时，候选结果的归属用 `undetermined` 并列出候选通道；这些 TS 不放入 profile 的简单选择性定义，每个 TS 必须唯一归属，不能把同一 TS 重复塞入多个产物。报告标注“简单 TS 能垒比不适用”。单条 IRC 不能排除另一分支；本期不做轨迹计算。 涉及上述 catalog v2 登记时：**v4.6.0 在两台电脑部署完成之前，真实研究 study 不写 v2 事件**。
来源：[T139](../../../docs/redesign-tasks/T139-card-wording.md) A9/X4、[catalog v2](../../../docs/ag-catalog-2.md)、[审计第 11 节](../../../docs/research/ts-guess-audit.md)。


## 7. 常见失败与处理

**中断后接续：** 被强杀时，先按[失败诊断的“作业被强杀”](failure-diagnosis.md#作业被强杀) 核对结束证据，显式 `ag fetch <attempt> --incomplete`，再用 `ag facts` 提取 `final_input.xyz`。 经人审阅后，用该显式几何和父 chk 准备新 Attempt，采用 `Guess=Read Opt=(TS,CalcFC)`， 重新计算初始力常数并完成最终 Freq；沿用第 3 节 `--parent-chk` 声明、同集群与哈希校验，提交仍须人确认。 RCFC 只适用于父 chk 中确有 Freq 写入的适用笛卡尔力常数；没有 Freq 的中断优化不能用 RCFC 接续。 缺少 `final_input.xyz` 或 chk 不可读时停止报告，不猜几何、不自动重提。

零虚频说明落到极小点或尚缺完整证据；多虚频可能是高阶鞍点或软模问题；方向错误可能是另一步反应。分别核对完整输出和结构，重审初猜/构象或假设，转 [失败诊断](failure-diagnosis.md)；提出新 Attempt，等人确认。

起点与目标方向合理但难收敛时，若 Hessian 更新不足，可在方法支持解析二阶导数时用 `RecalcFC=N` 在第一步及此后每 N 步重算，说明额外 Hessian 成本；若步长过大、优化振荡或越过目标区域，可减小 `MaxStep`。 参数与依据写进 review，每次修改都作为新 Attempt，经人确认后提交；不能用 `NoEigenTest` 掩盖错误曲率。

**一组模板和变换全部冲突，只说明这组模板和变换失败，不构成排除该通道的依据。** 在台账登记失败类型；有已登记候选可用 `candidate-result --outcome other` 并在 note 写明模板/变换和冲突，不设通道排除；无可登记几何时先保留本地失败记录，不虚构候选。

**低层优化塌缩到端点，只说明这条低层路线失败；通道应改用其他方法继续，不能据此排除。** 已登记候选使用 `ag catalog candidate-result <study> --object <对象> --candidate <候选> --outcome minimum --note '低层路线失败（<方法>）'`，有关联 Attempt 时补 `--attempt <结果Attempt>`，不声明 excluded。

xTB 无虚频或方向不对只降优先级或转为直接做 DFT，不排除候选；G0 的 Gaussian 模式标记 `mode:no_imaginary_mode`、`mode:sign_inconsistent` 同样不导致 rejected。还须审阅 `mode:multiple_imaginary_modes`、`mode:most_negative_not_best`、`mode:non_stationary_frequencies`；这些类别不表示本期支持 xTB Hessian。

涉及上述台账写入时：**v4.6.0 在两台电脑部署完成之前，真实研究 study 不写 v2 事件**。
来源：[T139](../../../docs/redesign-tasks/T139-card-wording.md) A7/A8/X4、[catalog v2](../../../docs/ag-catalog-2.md)、`docs/g0.md`（T138 标记须按最终实现核对）。

不得将 `Stable=Opt` 机械地加到所有计算里；它可能改变电子态，不能以较低能量自动接受新态。

需要三维及以上扫描或 xTB 多维扫描、白名单外输入段或尚未支持的自动初猜时，写明具体缺口并暂停该步骤。真实作业异常先停止报告；不在原 Attempt 重跑，不用旧 Skill 执行。

## 8. 常见坑

知识衔接：[GKB-0431、GKB-0422：TS 验证与优化排障](../../auto-g16-gaussian-learning-library/references/core-job-types.md)。

以下科学经验改写自 [archive/skills/auto-g16-ts-irc/SKILL.md](../../../archive/skills/auto-g16-ts-irc/SKILL.md) 的 Safety and scope、Workflow、Interpretation gates；仅追溯经验，不恢复其历史流程：

- Opt 结束时抓到的截断日志不能当作完整 Freq；须查完整模式数及位移。
- 一个负频只是候选，键变化方向审核和双向 IRC 端点识别不可省略。
- QST 同元素原子交换也可能改变反应映射；外部映射表不能修复实际输入行顺序。`End of file in ZSymb` 后不要反复试换空行提交。
- 父 chk、几何和原子顺序不一致会把 IRC 引向错误起点；RCFC 坐标取 `final_input.xyz`，或预先在父 TS 使用 `nosymm`。副本哈希、对齐 RMSD 及相同起点能量均不能证明坐标框架正确。
- 解离片段的近自由平移/转动可能导致优化困难，不默认把多个孤立片段当普通单分子极小点。
