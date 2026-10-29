# 常用 Gaussian 作业：扫描、单点、优化、TS、IRC 与频率

## 目录

- [势能面与扫描](#势能面与扫描)
- [单点能和 SCF](#单点能和-scf)
- [几何优化](#几何优化)
- [过渡态](#过渡态)
- [IRC](#irc)
- [频率与热化学](#频率与热化学)

## 势能面与扫描

### GKB-0401 驻点

- 类型：概念
- 关键词：stationary point；minimum；first-order saddle point；Hessian
- 梯度为零的位置是驻点；局域极小点的相关曲率为正，一级鞍点有一个负曲率方向。
- 与频率的关系：稳定极小点期望没有虚频；一级鞍点候选期望一个虚频。
- 不能据此推出：任意“一个虚频”结构就是目标反应过渡态。

### GKB-0402 刚性与柔性扫描

- 类型：操作
- 关键词：scan；rigid scan；relaxed scan；opt=modredundant
- 刚性扫描：只改变指定变量；可用 Z-matrix 变量、步数和步长设置 `scan`。
- 柔性扫描：扫描变量受控，其余自由度在每一步优化；常用 `opt=modredundant` 和坐标后的 `S` 指令。
- 输出解释：步数不含初始结构；一个变量扫 N 步会有 N+1 个结构。
- 风险：扫描路径依赖初始结构、步长、约束和电子态，不能自动视为最低能反应路径。

## 单点能和 SCF

### GKB-0410 单点能

- 类型：操作
- 关键词：SP；single point；energy
- 零基础解释：固定几何，只计算该结构上的能量或性质。
- 常见用途：结构检查、性质和轨道分析，或在较低层级优化结构上进行较高层级能量计算。
- 必须记录：单点方法/基组/溶剂、几何来源和几何层级，通常写成 `single-point//geometry`。

为防止将后 HF 的参考 SCF 能量误当最终总能量，读数时先定位实际完成的作业段，再核对字段：

| Gaussian 原生结果 | 电子能量字段的含义 | ag 当前边界 |
|---|---|---|
| HF 或受支持的普通 DFT | `SCF Done` 对应所求 SCF 能量；仍须核对色散、溶剂项及输出说明 | `facts.energies.scf` 取该段 cclib `scfenergies` 的末项；字段存在不等于科学验收 |
| MP2 / MP3 / MP4 | `EUMP2` / `EUMP3` / 相应 `UMP4(...)` 为各目标方法总能量；前面的 SCF 能量只是参考层级 | facts 不把这些相关总能量映射为 `energies.scf`；thermo/profile 拒绝 |
| CCSD / CCSD(T) | 收敛后的 `E(CORR)` / `CCSD(T)` 分别对应目标总能量，不能只取前面的 MP2 或 SCF 值 | 同上，尚无可供 thermo/profile 使用的后 HF 能量接口 |
| 双杂化（以 B2PLYP 为例） | `E(B2PLYP)` 含微扰相关贡献，区别于 SCF 部分及单独的 `E2(B2PLYP)` | thermo/profile 拒绝双杂化，不因名称含 DFT 就接受 |

Gaussian 原文核对（2026-10-29）：G16 Rev. C.01 在线手册
[MP Methods，Examples / Double-Hybrid Methods](https://gaussian.com/mp/) 与
[CCD and CCSD，Examples](https://gaussian.com/cc/)。这些示例验证字段含义，不证明某方法适合具体研究。
ag 实现定位为 [`_parse_outputs.py` 的 `_parse_gaussian_section` / `parse_gaussian`](../../../ag/src/ag/_parse_outputs.py)
及 [`_profile_sources.py` 的 `SCF_ENERGY_METHODS`、`protocol`、`section_source`](../../../ag/src/ag/_profile_sources.py)；
[`thermo.py`](../../../ag/src/ag/thermo.py) 与 profile 共用该协议检查。
白名单只接受明确支持的 HF/DFT SCF 能量方法，未知方法及自定义基组等协议仍拒绝；它不是研究方法推荐表。
更换 route 不会扩展解析支持，也不能通过改写 facts 将后 HF 结果伪装成受支持的 SCF 结果。
能量层级与性质所用密度分别核对，见 [GKB-0111](theory-and-methods.md#gkb-0111-后-hf-方法)。

### GKB-0411 SCF 不收敛排查候选

- 类型：排障
- 关键词：SCF convergence；NoVarAcc；NoIncFock；Fermi；XQC；QC
- 先检查：结构是否合理、电荷和多重度是否正确、初猜是否适合、是否存在近简并/对称性破缺、基组是否过度弥散。
- 可审查的候选包括 `SCF=NoVarAcc`、更密 DFT 网格、`NoIncFock`、`Fermi`、`XQC/QC` 和循环数设置。
- 使用边界：这些选项是诊断候选，不是固定顺序的万能配方；强行数值收敛不能证明得到正确电子态。

## 几何优化

### GKB-0420 优化目的和局部性

- 类型：概念/操作
- 关键词：Opt；geometry optimization；local minimum；initial geometry
- 目的：寻找势能面上的局部极小点。
- 核心边界：一次优化通常只找到初始构象附近的局部极小点；合理初始结构和构象覆盖至关重要。

### GKB-0421 优化成功证据

- 类型：输出判断
- 检查：四项收敛指标、最终结构、点群/连接关系、电子态和后续频率。
- Gaussian 会报告最大力、RMS 力、最大位移和 RMS 位移的收敛状态；GaussView 可辅助查看优化轨迹。
- 成功不等于全局最低点；还需要构象和可能反应通道比较。

### GKB-0422 优化排障候选

- 类型：排障
- 排障候选：调整初始结构、坐标系统、步长；审查 GDIIS、CalcAll/CalcFC/ReadFC；增加最大步数；DFT 使用更密积分网格；必要时关闭对称性。
- 诊断顺序：先看几何轨迹和失败位置，再判断是坏初始结构、坐标奇异、电子问题、势能面平坦还是数值设置。
- 禁止做法：在不了解原因时叠加所有关键词，或把超出步数当作唯一问题。

## 过渡态

### GKB-0430 TS、QST2 和 QST3

- 类型：操作
- 关键词：Opt=TS；QST2；QST3；CalcFC；NoEigenTest
- 常见路线：
  - TS：提供一个 TS 初猜；
  - QST2：提供反应物和产物结构；
  - QST3：提供反应物、产物和 TS 初猜。
- `CalcFC/ReadFC`提供初始力常数；`NoEigenTest`取消优化过程中的本征值测试，不是对最终 TS 验证的替代。
- 运行边界：结构对应、原子顺序、电荷/多重度和反应通道必须人工确认。

### GKB-0431 TS 验证证据链

- 类型：验证 SOP
- 本项目的完整证据链包括恰好一个虚频、相应负曲率方向、正确的振动模式，以及双向 IRC 和端点身份；有限初猜模式诊断不能代替正式 TS/Freq 验收。
- 安全解释：
  1. 优化收敛；
  2. 恰好一个虚频，不以经验大小区间代替模式审阅；
  3. 振动矢量沿目标成键/断键或重排方向；
  4. 正反 IRC 两向均完成；
  5. 端点再优化并确认身份；
  6. 与同一参考态下的其它通道比较；完成判定仍须按 Study 流程人工签字。

### GKB-0432 TS 初猜策略与边界

- 类型：操作原则
- 初猜策略包括从扫描近峰结构出发、对形成/断裂键做受限或部分优化，以及直接构造 TS 初猜。
- 并非所有化学过程都有经典核坐标 TS；电子转移、无垒过程和解离过程可能需要不同模型。
- 不能据此推出：扫描最高点就是 TS，或没有找到 TS 就证明机理不存在。

## IRC

### GKB-0440 IRC 的作用

- 类型：概念
- 关键词：IRC；intrinsic reaction coordinate；MEP
- IRC 是质权坐标下从 TS 向相邻极小点延伸的最低能路径。
- 用途：观察结构变化、由 TS 寻找端点、检查 TS 是否连接预期反应物和产物。
- 不能据此推出：IRC 是有限温度真实动力学轨迹，或端点自动等于已知稳定构象。

### GKB-0441 IRC 输入和成功判断

- 类型：操作/验证
- 起点应是已优化的 TS，计算层级通常与 TS 优化一致；常用选项包括 `CalcFC/RCFC`、`Forward/Reverse`、`MaxPoints`、`StepSize`、`Recalc`、`GradientOnly`、`EulerPC` 和 `LQA`。
- 成功证据：两侧路径合理延伸；能量和结构连续；端点结构被提取、分别优化和识别；不是只看到作业正常结束。
- 常见异常：过早报告到达极小点、两方向折返到同一侧、步长/校正失败；TS 定位不够精确是需要优先检查的原因之一。
- `RCFC` 取向陷阱：恢复的笛卡尔力常数/位移必须与显式坐标处于同一参考系。Input 与 Standard orientation 即使刚体对齐后是同一几何，也不能直接互换；波函数重取向提示或 chk 哈希相同不证明 Hessian 已同步旋转。
- L3 A/B 对照：A 用 Standard 取向重新 `CalcFC`，B 用父 TS 的 Input 取向配合 `RCFC`。两组已接受的部分轨迹高度吻合，均越过旧错配输入的首点失败，支持取向修正有效；两组后来仍发生校正器失败，未获得完整端点，不能据此声称 IRC、端点一致性或父 chk 复用的科学验收通过。
- 使用前核对父 TS 的取向、原子顺序、同一几何和力常数适用性；无法确认同框架时，提出在当前几何重新 `CalcFC` 的新 Attempt，经人确认再算。A/B 同时改变取向和力常数来源，不能把部分吻合解释为唯一因果证明。

## 频率与热化学

### GKB-0450 频率计算的三个主要目的

- 类型：操作
- 目的：判断驻点性质；获得 ZPE 和热化学校正；计算 IR、Raman、VCD 等振动光谱。
- 关键前提：应在平衡结构上计算，并让优化和频率使用相同方法、基组和关键数值设置。

### GKB-0451 虚频处理

- 类型：排障/验证
- 稳定结构出现虚频时：先看频率大小和振动模式，再检查优化阈值、积分网格、坐标/对称性、初始构象和是否实际位于鞍点。
- TS 出现一个虚频时：仍要查看振动方向和 IRC；多个虚频通常表明高阶鞍点或未收敛到目标 TS。
- 不能只用正负号计数，不查看矢量。

### GKB-0452 频率校正与光谱

- 类型：方法
- 谐振近似常高估频率，经验缩放因子依赖方法和基组；IR 强度与偶极矩变化相关，Raman 活性与极化率变化相关。
- 缩放因子必须与方法/基组匹配，不能用笼统范围代替经过核验的具体数值。
- 光谱频率校正与热化学设置分开记录；研究默认和 thermo/profile/GoodVibes 入口差异见[方法表](../../auto-g16-study/references/acceptance-methods.md#数值设置与热化学依据)，本节不指定新因子。
- Gaussian `Scale` 用于热化学处理；`freqchk` 的官方例子明确缩放不改写所报频率本身。不能把 `Frequencies` 行当成已乘该因子的光谱峰位。核对于 2026-10-29：[Scale，Description](https://gaussian.com/scale/)；[freqchk，Examples](https://gaussian.com/freqchk/)。
- 区分 `IR Inten`（km/mol）与 `Raman Activ`（Å⁴/amu），后者是散射活性，不能直接标为实验 Raman 强度。G16 手册的 Raman 选项对 HF 默认启用，对 DFT/MP2 可显式请求；输出和可用导数仍按具体方法、版本核对。原文为 [Freq，Requesting Specific Spectra / Pre-resonance Raman 示例](https://gaussian.com/freq/)（G16 Rev. C.01，2026-10-29 核对）。

### GKB-0453 温度、同位素和热化学数据

- 类型：操作/输出
- 在 Born–Oppenheimer 近似下，同位素不改变电子势能面，但会影响涉及质量的频率与热化学；`temperature=x`改变热化学温度，不改变电子能量。
- Gaussian 原生可用 `Iso` 或 `Freq=ReadIsotopes` 指定质量，后者的质量顺序须与原子顺序一致；有适用的已保存频率力常数时，`Freq=ReadFC` 可重新做模式及热化学分析。更换质量会改变质权 Hessian 的本征问题，不能只给原频率换一个同位素标签。
- 原文为 [Freq，ReadFC / ReadIsotopes](https://gaussian.com/freq/)（G16 Rev. C.01，2026-10-29 核对）；这些是 Gaussian 原生学习说明，不新增 ag 的同位素、IR/Raman 执行或解析支持。实际研究仍需核对质量、方法、温压和证据来源，不能沿用未经核对的热修正。
- 输出关注：ZPE、thermal correction to Energy/Enthalpy/Gibbs Free Energy 及对应电子能量加校正项。
- 常见组合思路：用较低或中等层级优化和频率获得热校正，再在同一结构做较高层级单点。
- 未覆盖：标准态转换、低频准谐处理、构象系综和浓度效应；用于研究时必须另行处理。
