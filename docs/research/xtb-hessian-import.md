# xTB Hessian：来源核查与本地导入方案（T163）

来源核查日期：2026-10-28；原子对应核对日期：2026-10-29。
**来源与本地导入规格：部分来源待补；原子对应已与 T162 合并后的最终接口对齐。**
第 1–7 节保留 T163 的来源审计与历史规格；其中“尚未实现/待补”描述 T163 交付时状态。
T176 的当前本地接口、支持范围和验收状态见第 8 节；Hessian 生成器仍未接入。
`g0_modes.read_frequency_attempt` 专读 Gaussian；`xtb.toml` 没有 Hessian 参数或输出声明。
本单未运行 xTB、Gaussian、调度器或远程命令，未改任何 study、Attempt、候选或历史 evidence。

核查结论：普通 xTB `hessian` 是**未质量加权的 Cartesian 二阶导数矩阵**，不是位移向量；
本次审计的非线性分子路径在写出它之前已经投影掉平动/转动。
`hessian.out` 的写出阶段不同；`g98.out` 虽有 Gaussian 外观，其向量也不能直接送进现有 Gaussian 适配器。
详见下列固定版本源码。本页中的“拟支持”均指后续实施候选，不能据此宣称产品已支持。

## 1. 证据范围与定位

以下链接均于核查日实际读取。源码固定为官方 `grimme-lab/xtb` 的 **v6.7.1**，
tag 对应 commit `26b28010e805f7d1aeeef39813feb473e69cc4be`；不外推到其他版本、发行包补丁或连续构建。
在线手册 `latest` 会变化，另核对官方文档仓库 commit
`4c9711315c845a6cb525bb480748a889386bc578` 的 `source/hessian.rst`；它不是 v6.7.1 的发布说明。
例如该文档已有 O1NumHess 内容，本方案没有审计或纳入该路径。

| 编号 | 官方来源、精确位置 | 本次能确认的事实 |
| --- | --- | --- |
| S1 | [频率手册：简单计算、虚频、Advanced options][manual]；[固定文档源码][manual-src] 的同名小节 | `--hess` 在给定结构上求 Hessian，`--ohess` 先优化；非线性例子的 Hessian 已投影；手册列出修改质量的选项，但不证明固定版本中的最终有效质量，见 S7。只是命令来源说明，不是执行建议。 |
| S2 | [v6.7.1 CLI 手册][cli-man] L221–230、377–387、488–500 | `hessian` 为非质量加权 Cartesian Hessian；`xtbhess.coord` 是沿虚频扰动后的结构；结束码与几何警告分开。 |
| S3 | [src/type/calculator.f90][calc] L115–191；[include/xtb.h][api] L119–139、250–260；[molecule.f90][molecule] L85–86 | 正负坐标位移的梯度差除以两倍步长；索引 `3*(atom-1)+component`；坐标 bohr、梯度 Hartree/bohr，故二阶导数 Hartree/bohr²。 |
| S4 | [src/hessian.F90][hess] L139–179、299–383、416–470 | 内部小角度旋转；对称化；`hessian.out` 先写；非线性分子投影后写 `hessian`；随后才乘质量因子和 Hessian 缩放因子、对角化。 |
| S5 | [src/freq/io.f90][freq-io] L29–101 | 两种 Hessian 的精确写法；`hessian` 写完整矩阵，内部 packed 存储不是文件布局。 |
| S6 | [src/freq/project.f90][project] L149–314 | 当前 CLI 调用的是 `trproj`：未质量加权 Cartesian 刚体基、正交化、投影。不能把同文件另一个 `projectHessian` 的质量加权约定套过来。 |
| S7 | [src/mctc/convert.f90][convert] L24–56；[atomic_masses.f90][masses] L24–67；[main.F90][mass-init] L427–431；[constrain_param.f90][mass-options] L1256–1307 | bohr/Å、波数和质量换算；CLI 使用以 u 表示的逐原子 `atmass`。`set_hess` 解析选项时修改质量并回显，但主程序 L427 `read_userdata` 返回后，L431 无条件重新赋默认元素质量；解析回显不证明最终 Hessian 使用了覆盖值。 |
| S8 | [main/property.F90][property] L650–701；[freq/io.f90][freq-io] L196–301；[writer/turbomole.f90][mode-writer] L147–189 | `g98fake2` 直接打印对角化所得向量；另一个 `vib_normal_modes` writer 才显式逐原子除以质量平方根。 |
| S9 | [main.F90][main] L924–944、1057–1084；[hessian.F90][hess] L632–720 | Hessian 之后、扰动结构之前的几何与 `g98.out` 同框架；`--ohess` 另写最终结构；输入 XYZ 或 `xtbhess` 不能自动充当 Hessian 几何。 |
| S10 | [test/unit/test_hessian.f90][test-array] L147–240 | 官方 O,H,H 水分子的 GFN2 测试含几何和 9×9 参考数组，直接调用 calculator；没有经过 CLI 的对称化、投影及文件 writer。 |

读取的 15 份相关源文件在本地临时目录核对了 Git blob SHA-1，与 GitHub 返回值全部一致。
下列 SHA-256 对应这些原始 UTF-8 字节，不是某次计算的输出哈希：

| 文件 | SHA-256 |
| --- | --- |
| `src/hessian.F90` | `00cc9a5885c2d29c68586840b1a06f07545595380087df8bfe228defa67cb54c` |
| `src/freq/io.f90` | `5e9b0c5d95dfa790688d7dc2f2e438b0c08b4c074a2bda16662d0163f8a07499` |
| `src/mctc/convert.f90` | `5347b59fcd3293173414d4934e2c1da7cbafd413e1a555572d36e75c2995d1f1` |
| `test/unit/test_hessian.f90` | `fe2b52de79c910c26425ec4bc38ed5cb60e87f9c92b664193a32788632781798` |
| 文档 `source/hessian.rst` | `392eefa29e9cacf98cecc3ccac49e60566ec6a5fbe913cbd077e9b058d5a6431` |

### 有限来源表：当前拿到了什么

| 材料 | 程序、生成路径、方法/溶剂 | 原子、几何、质量 | 格式/单位与结束证据 | 状态 |
| --- | --- | --- | --- | --- |
| S4/S5 writer | v6.7.1 `numhess` 普通路径；命令语义见 S1/S2；无实际运行的方法或溶剂 | 源码证实逐原子 xyz 次序；没有某次运行的几何或质量记录 | 文件布局和 Hartree/bohr² 来源可追踪；无运行结束证据 | **源码格式证据**，不是实际 Hessian 文件 |
| S10 水分子参考数组 | v6.7.1 测试，`method=2`、步长 `1e-6` bohr；所读测试未设置溶剂；未执行 | N=3，O,H,H；几何在 L152–156；参考数组本身不含质量/同位素 | Fortran `reshape` 的 81 个数，列主序；无 CLI 输出、命令回显或正常结束日志 | **公开源码数值样例**，不是实际文件格式样例；哈希见上表 |
| 第 4 节合成矩阵 | 手写代数例，无计算程序、方法或溶剂 | 明示维数、坐标与人为质量 | 人工按 writer 布局编码，预期谱已知 | **合成推演**；不能改称真实计算 |
| 同次运行的 `hessian`、几何、控制输入和日志 | 未取得完整公开小分子文件包 | 未知 | 原始 Hessian 哈希、完成证据未知 | **真实格式样例待补** |

样例搜索止于上述官方源码/文档和公开 cclib-data 树
（[commit 127b2229d584d54fb84a74e383edb18a271fc283 的 XTB 目录][cclib-tree]）。
后者列有 stdout 样例，没有本次所需的 `hessian` 配套文件；未把它当 Hessian 验证。
没有为补证据生成、请求取回或下载私有研究计算。

## 2. 有限格式与取向边界

### 首个实施候选：v6.7.1 CLI 普通 `hessian`

仅设计 S4 的完整、非周期、非线性分子路径：N≥3，无冻结原子、无偏置 Hessian、无外部计算器替代。
这限制的是已审计的文件语义，不是为研究选择科学方法。线性/单原子、局部 Hessian、约束或外场、
SPH/`--bhess`、新版 O1NumHess、API 数组、其他程序的 Turbomole 文件均不由本页承诺支持。
S4 的线性分支会跳过投影并把排序后的前五项置零；不能把该逻辑搬来处理含负曲率的任意结构。

S5 `wrhess` 的布局为：

- 首行 `$hessian`，写为 80 字符行；读入只容许该标记及其尾部空白。
- 后面有 `(3N)²` 个十进制数；外循环为矩阵行 i，行内列 j 递增，每物理行最多 5 个数。
  每段前 5 个空格，字段 `F15.10`；每个矩阵行重新开始分段，末段不足 5 项。
- 没有原子数、元素、单位、质量、版本或原子标签；该 writer **不写 `$end`**。
  首个严格适配器不猜带行列号、packed 三角、多个数据组或额外尾块的文件；此类变体另补证据。
- `p=3(i−1)+α`，α 为 x/y/z；矩阵轴都是 `x1,y1,z1,x2,y2,z2,…`（S3）。
  维数由已绑定几何的 N 给出，不能从凑平方数反推分子。
- writer 从同一 packed 元素打印对称两半，解析后应精确对称；不自动平均损坏的输入。
  Fortran 内存中的列主序、`rdhess` 的转置读法对对称阵等价，但不改变上述文件写出定义。
- `H` 的单位是 `E_h/a_0²`，未质量加权；非线性普通路径已做 Cartesian 刚体投影。
  `scale_hess` 在写文件之后应用，不能假定文件已包含该缩放（S4 L358–364）。

首个适配器必须先有真实格式样例覆盖实际空白、精度和文件结尾，才可在实施单中启用该格式。
源码证实布局不等于完成了生产文件导入验收。

### 已辨别，但不纳入首个适配器

| 文件/来源 | 源码确认的区别 | 本方案处理 |
| --- | --- | --- |
| xTB `hessian.out` | S4 L321–323 在刚体投影前写对称化矩阵；S5 L29–49 无标记，以每列 `4F16.10` 写完整阵；同样未质量加权 | 不按扩展名自动检测为普通 `hessian`；未取得实际文件，后续另建格式适配与投影验证 |
| xTB `g98.out` | S8 把质量加权阵的本征向量直接传给 `g98fake2`，未在该 writer 除质量；只写 `abs(freq)>0.1` 的模式，位移仅两位小数，部分 Gaussian 栏位是占位值 | 不交给 Gaussian 读取器；可将其几何块作为有来源的取向佐证，不能把显示向量当准确 Cartesian q |
| `vib_normal_modes` | S8 显式除 `sqrt(atmass)`；有行号/段号，列方向是模式，和 Hessian 格式不同 | 属于已求出的模式；需频率及几何配套证据，当前不导入 |
| `xtb_normalmodes` / 局域模式、未知 `.hess` | 二进制或另一种模式来源，不由文件名确定单位/排列 | 不支持、不尝试猜测 |

### 几何必须与矩阵共用框架

S4 在 Hessian 前依次旋转 `0.0001/0.0002/0.0003` 度（`rotmol` L632–660）；
S9 的主程序还可能做 CMA 变换，`--ohess` 则先改变几何。
因此仅有原输入 XYZ、相同元素顺序或对齐后很小的 RMSD 都不构成取向证明。
`xtbhess` 是扰动结构，也不能作未扰动 Hessian 的配对几何。

要求绑定同次频率阶段的坐标来源、原子顺序和提取位置。S8 的 `g98.out` 几何块直接使用该阶段
`mol%xyz` 并乘 `0.52917726`，坐标打印至 6 位小数；若由它导出 XYZ，需同时绑定原始
`g98.out` 和派生 XYZ 的字节哈希、提取说明及精度。不能只留下派生坐标哈希而丢掉源文件。
若使用 `--ohess` 的最终几何，需核对同次运行和写出阶段；不把任何同名 `xtbopt.xyz` 自动配对。
首个实现不尝试从输入重演所有内部旋转，也不凭 Kabsch 旋转 Hessian 来“修好”未知取向。

## 3. 转换约定及尚未锁定的数值边界

以下是由 S3–S8 推导的**拟实施转换**，不是一次 xTB 运行结果。

1. 读原始 H，检查布局、维数、有限数和对称性；保留原矩阵及其已有的投影语义。
   坐标由其明示单位换成 Å 给后续 Wilson B 使用；H 保持 `E_h/a_0²`。
   若仅为推导换到 `E_h/Å²`，`H_Å = H_bohr / (0.52917726)²`，不能反乘。
2. 绑定每原子实际质量 `m_i`（u），要求有限且正；M 对角线上每个质量重复三次。
   S7 默认质量表不是整数质量数。必须分开记录**请求的质量、解析阶段回显和最终有效质量**：
   固定 v6.7.1 的 `set_hess` 虽修改 `atmass` 并打印 `mass changed`，但
   [主程序 L427–431][mass-init] 在 `read_userdata` 返回后无条件执行
   `atmass = atomic_mass(mol%at) * autoamu`，覆盖刚解析的质量值。
   因此该路径的选项存在、覆盖请求或解析回显都不能单独作为最终有效质量来源。
   有效数组必须绑定到实际版本/调用路径及其生效依据：默认表需追踪上述初始化顺序；
   已证实走该初始化路径时，明确记录请求值被默认值覆盖，不将二者不同本身误记为未知。
   非默认质量需有默认初始化之后仍保留并实际传入 Hessian 的证据，不能由先前回显代替。
   来源不足或互相矛盾时记有效质量未知，按第 6 节不生成模式；不能静默选用请求值、
   默认值或 RDKit/Gaussian 表来消解矛盾。本单未运行同位素计算，也不外推其他版本行为。
3. `K = s M^(−1/2) H M^(−1/2)`，s 是该次 Hessian 的明确正缩放因子。
   常见的 s=1 仍要有来源；热化学频率缩放、SPH 的逐模式校正与此不是一回事。
   对称本征分解 `K e_k = λ_k e_k`，`e_k^T e_k=1`。
4. 因质量按 u 而非电子质量输入，按 S4 L419 与 S7 的常数得到：

   ```text
   C = 219474.63067 / sqrt(1.660539040e-27 / 9.10938356e-31)
     = 5140.487128718148 cm^-1
   frequency_k = sign(λ_k) * C * sqrt(abs(λ_k))
   ```

   λ 的数值单位对应 `E_h/(a_0² u)`；该式等价于先把质量换为原子单位再乘 `autorcm`。
   不再乘额外的 2π，也不再除一次质量换算。固定这些版本常数是为可复核，不能静默换常数表后声称逐值重现 xTB。
5. 用于 G0 的 Cartesian 位移为 `d_k = M^(−1/2)e_k`，再定义
   `q_k = d_k/||d_k|| × 1 Å`。其整体长度是显示/投影约定，不是振动振幅或零点振幅。
   必须先去质量权重再归一；只归一 e 会改变不同质量原子的相对位移。
   q 与几何始终同一取向，`δc=Bq` 的距离为 Å、角度为 rad；沿用 T138 的整体正负号选择。
6. 负 λ 保留负波数来表示虚频；精确零为零，不能取绝对值后伪装成实频。
   记录所有原始 λ 和有符号频率。S4 的 `0.01 cm^-1` 是其零频识别值；手册中的
   `imagmin` 或热化学 imaginary cutoff 不是 G0 的 TS 合格阈值。
   简并子空间内本征向量可任意混合；比较子空间/谱，不要求每条向量符号、顺序逐字一致。

**平动/转动：** 普通非线性 `hessian` 已按 S6 投影，不重复修改 H，不盲删最小六个特征值
（它们可能含真正的负曲率）。由同框架几何构造平移和绕质心旋转的 Cartesian 刚体基 F，
在质量加权空间用 `sqrt(M) F` 的正交基核对对应零频子空间；应为六维，振动空间为 `3N−6`。
质心与几何中心的原点选择仅改变平移基的线性组合，不改变完整刚体子空间。
只有已辨识的外部运动从 G0 振动模式列表中排除；保留完整谱及被排除项的依据。
不能把所有小负值抹成零，或把投影出来的六个零解释为 Hessian 精度/驻点证明。

**待补数值边界：** 文件矩阵舍入为 10 位小数，配对几何可能只有 6 位小数；
“近零模式集合与刚体子空间一致”的残差界、近线性/简并时的处理还须用配对原始样例核定。
此处没有设一个未经验证的接受阈值。后续实施单应记录几何精度、刚体秩、子空间残差，
在无法分开刚体模式与低频内振动时返回 `external_modes_unresolved` 并不发布可排序模式。
这些未定项使首个适配器尚不能启用；合成推演的 `1e-14` 谱断言只是浮点算术检查。

## 4. 已执行的本地推演与样例检查

2026-10-28，在临时目录使用 NumPy 2.4.6，仅做矩阵运算与读取公开源码；没有调用 xTB。

**合成推演 A：两站点代数模型，不是线性分子导入支持声明。**
坐标为 `(-0.5,0,0)`、`(0.5,0,0)` Å，人为质量为 1、4 u；
`v=(1,0,0,-1,0,0)^T`，`H=0.04 vv^T E_h/a_0²`，s=1。

```text
H = [[ .04, 0, 0, -.04, 0, 0],
     [   0, 0, 0,    0, 0, 0],
     [   0, 0, 0,    0, 0, 0],
     [-.04, 0, 0,  .04, 0, 0],
     [   0, 0, 0,    0, 0, 0],
     [   0, 0, 0,    0, 0, 0]]
```

| 检查 | 解析预期 | 实际 |
| --- | --- | --- |
| 维数、对称性 | 6×6，`max abs(H-Hᵀ)=0` | 相同 |
| K 的特征值 | 五个 0，一个 `0.04(1+1/4)=0.05` | `[0,0,0,0,0,0.05]` |
| 正模式波数 | `C sqrt(0.05)` | `1149.447865727649 cm^-1` |
| H 换为 −H | 一个负 λ，波数保留负号 | `−1149.447865727649 cm^-1` |
| s=0.25 | 波数减半 | `574.723932863824 cm^-1` |
| 去质量权重再归一 | `q=(4,0,0,-1,0,0)/sqrt(17)`，允许整体反号 | 非零分量 `0.970142500145332, −0.242535625036333` |
| 换到 Å 再换回 | `H_Å[1,1]=0.04/a²`，返回 H | `0.142842566537891`；回转一致 |

人工编码采用第 2 节 writer 布局：首行标记补空格至 80 字符；按行每段最多 5 项，前缀
5 个空格，每项宽 15、小数 10 位；每行 LF，无 `$end`。共 693 bytes，SHA-256：
`2f644bcfe1583bb630347613ed9d80c5b068dac47804ac91b5f37e3bf91452f3`。
读回 36 个数与 H 完全相同。这个哈希绑定**人工合成文件**，不提供 xTB 文件运行来源。

**合成推演 B：非线性三站点。** 坐标 `(0,0,0),(1,0,0),(0,1,0)` Å，质量 16、1、1 u。
用 `sqrt(M) F` 的 SVD 补空间 Q 构造 `K=Q diag(-0.04,0.09,0.16) Qᵀ`，
再令 `H=sqrt(M) K sqrt(M)`。刚体秩实际为 6；读回质量加权阵的谱为一个 −0.04、
六个数值零（最大绝对值 `1.78e-17`）、0.09、0.16，和预期在 `1e-14` 内一致。
三条非零波数为 `−1028.097425743630, 1542.146138615444, 2056.194851487259 cm^-1`。
它验证了非线性刚体空间及负曲率保留，不验证真实文件的舍入容差。

**公开源码样例检查 C，非真实格式样例。** 按 Fortran 列主序只读提取 S10 的 GFN2
`hessian_ref`，得到 81 个有限数、9×9 阵；最大反对称差为 `0.010721480510816`。
它位于 `calc%hessian` 的原始数值导数层，不能冒充经过 S4 对称化/投影的序列化 `hessian`。
本次未将它强行对称化或用于模式验收；也未执行上游测试来生成新文件。

## 5. 来源声明、原子对应及本地输出

拟议入口（尚不存在）：`ag import-xtb-hessian --study <S> --source <声明文件>`。
声明只服务这次本地分析，不新增通用来源框架、科学签字或全局准入。
为了防止把不同计算、不同取向或不同原子编号的数据拼起来，每次输入至少携带下列有限信息：

| 项目 | 必须保留的内容 |
| --- | --- |
| 程序与计算来源 | 程序、可对应到已审计代码的版本/构建信息；原命令或输入回显及其出处；方法、溶剂、电荷/电子态分别记录，未知明确标记，不能从文件名推断 |
| 几何 | N、元素和逐原子次序；同 Hessian 框架的几何文件、单位、精度、源段定位；派生 XYZ 还需其上游原始文件 |
| Hessian | 原始文件、显式格式、`E_h/a_0²`、未质量加权、投影状态、完整/冻结/偏置状态、s 值和出处 |
| 质量/同位素 | 长度 N 的正有限有效质量（u），绑定实际版本、调用路径和最终生效依据；覆盖请求/解析回显单列，不作为有效值证明。固定 v6.7.1 的默认初始化覆盖顺序见第 3 节；缺最终依据时记未知，不补默认同位素 |
| 计算结束与驻点 | 该次 stdout/stderr 或已有回执的来源、正常/失败/未知状态；优化/梯度依据独立记录；文件存在不代表正常结束，正常结束不代表驻点 |
| 原子对应 | 候选身份、候选存档 XYZ 原始字节哈希、映射声明原始字节；沿用 T162 的候选 → 来源、1-based 完整双射及未核实语义，见下节；xTB 分析来源适配留待后续实施 |
| 字节绑定 | Hessian、几何、几何上游源文件、质量/来源/映射声明、所引用结束证据逐一保存原始字节 SHA-256；解析后的数值摘要不能替代这些哈希 |

输入按声明的本地文件读取，不执行声明里的命令，不下载 URL，不读取远程目录。
一次读取的字节同时用于哈希和解析，发布前复查引用仍匹配；变化则不发布分析。
在新建的 `analyses/xtb-hessian-<唯一标识>/` 独占保存分析报告及可复核的输入快照/引用，
记录转换器版本、常数、完整谱、Cartesian 位移约定、来源与未知项。
不放到原 Attempt 的 `outputs/`，不刷新 facts，不追加 candidate-result，不更新历史 evidence。
再次分析新建记录，不覆盖旧结果；输出保留 source_program=xtb，不能伪装成 Gaussian Attempt。

### 与 T162 已审阅接口的对应

以下核对固定在 [T162 PR #359][t162-pr] 已审阅并合并的最终提交
`8fea723c861d2073028f20effc8e27f3c79159c1`，依据其 [映射读取与绑定][t162-mapping]、
[模式投影][t162-modes] 和 [批量错误处理][t162-batch]；已在 main 合并提交
`a921a48750fe2426c06694ef75a3d2fc4bc11a89` 复核三份文件字节一致。
**T162 的 `frequency` 目标仍只接受 Gaussian Attempt。** 其 xTB/CREST 支持仅指参考输入几何，
不表示已能读取 xTB 频率；以下现有目标字段不能直接用作新的 xTB analyses 来源。

`--atom-mapping` 读取至多 1 MiB 的普通本地 JSON，拒绝符号链接。顶层仅含 `mappings` 列表，
每项恰含 `object`、`candidate`、`candidate_sha256`、`target`、`candidate_to_target`。
`candidate_sha256` 为候选存档 XYZ **原始字节**的 64 位小写 SHA-256；
`target` 恰含 `kind`、`attempt`、`source`。各目标的 `source` 字段如下：

| 当前目标 | 精确来源描述符 |
| --- | --- |
| `reference`，Gaussian 普通输入 | `file=attempts/<ID>/manifest.json`、`sha256`（manifest 原始字节）、`json_pointer=/science/geometry` |
| `reference`，Gaussian QST 输入 | 同上，但 `json_pointer=/science/structures/0/geometry`，明确第一段几何 |
| `reference`，xTB/CREST 输入 | `file`（输入 XYZ 的 study 相对路径）、`sha256`（XYZ 原始字节）、`frame=1`、`manifest_sha256` |
| `frequency`，Gaussian 选定频率段 | `file`（日志的 study 相对路径）、`sha256`（日志原始字节）、`start_line`、`end_line`（含首尾的 1-based 行号）、`section_sha256`（保留原换行的段字节） |

先按现有诊断规则选择并读取实际来源，再逐字段核对 `target`；映射文件里的路径不用于打开文件，
`attempt` 不用于选择来源。同一候选每种 `kind` 最多一项；参考和频率分别声明，
即使来自同一 Attempt 也不互用、组合或自动传递。输入文件不填写自己的哈希；
运行时计算 `mapping_sha256`，报告保留条目 `json_pointer=/mappings/<从零开始的序号>`、
候选哈希、实际 `target`、方向及有效置换。

方向固定为 `candidate_to_target[i-1] = j`，即**候选原子 i → 来源原子 j，两侧均从 1 开始**。
必须覆盖两侧全部 N 个原子，恰含 1…N 各一次；拒绝部分对应、重复、越界、布尔值、浮点数、
字符串整数及对应元素不一致。为区别正逆方向，取三个同元素站点的合成声明 `[2,3,1]`：
候选距离 `[1,2]` 转为来源 `[2,3]`，候选角度 `[1,2,3]` 转为来源 `[2,3,1]`；
其逆置换是 `[3,1,2]`，不能误用。反应坐标的原始声明始终使用候选编号。

投影只转换内坐标索引，用**来源原几何、原位移**计算 Bq，不旋转、反射或重排这两份数组。
配对后的几何视图仅用于正规旋转 Kabsch RMSD；RMSD 大不拒绝，小也不证明身份。
报告 `coordinates_spec` 保留候选编号，`frequency_coordinates_spec` 保留转换后编号；
每条 delta 的 `candidate_atoms` / `atoms` 分别指候选 / 频率来源。
不凭 scan/QST 出身、父 Attempt、相同元素序列或图对称性推断映射。

- `unverified`：缺少当前目标的声明或没有可用目标。候选仍可显示原有诊断；
  无有效频率映射时 `available=false`，不输出投影、最佳模式或依赖身份的 RMSD，
  缺映射本身不新增科学拒绝或模式标记。化学对应有多解且人未确定时也不猜一份声明。
- `declared_verified`：仅表示格式、完整双射、元素和来源绑定已校验；
  重复元素仍可能由人填错，**不证明化学身份对应**，报告保留人工审阅的 limitation。
- 声明无效属于错误，不能降为 `unverified`：字段、双射、元素或重复目标错误为
  `invalid_atom_mapping`；候选哈希、目标身份/字节/定位不符，以及声明指向未选定或不可用目标，
  为 `atom_mapping_binding_mismatch`。单候选退出 1；可定位到候选的批量错误以
  `stage=atom_mapping` 纳入 `errors`，退出 2、保留其他成功报告，`--record` 零写入。
  文件不可读、顶层或条目身份无法解析，以及实际来源自身损坏/越界仍整批失败；先读来源，
  不让声明错误掩盖坏日志、坏向量、坏台账或源文件哈希损坏。

未来 xTB 适配须保留上述方向、完整双射、字节绑定和状态/错误语义，但应另为新的本地分析记录
实现来源描述符，绑定本节要求的 Hessian、同框架几何、有效质量及声明原始字节。
**不得伪造 Gaussian Attempt，或把 analyses 标识塞进当前 `target.attempt` 来绕过类型限制。**
该适配及参数形式由后续实施单完成；T163 只确定兼容要求，不扩展 T162 的当前接口。
[G0 当前能力说明](../g0.md#模式投影) 已链接本规格；现有 CLI 的类型边界不因本设计改变。

## 6. 不足与失败的具体行为

这些检查只防止错误的本地模式解释，不成为 DFT 提交前置条件，也不新增候选拒绝规则。

| 输入情形 | 拟议行为及所防事故 |
| --- | --- |
| 缺同框架几何、单位、可核验版本/格式来源、有效质量或缩放信息 | 导入错误；不生成模式，避免单位、质量、取向错配；质量覆盖仅有解析回显而无最终生效依据仍算缺失，不能靠改文件名或照抄回显补齐 |
| 维数/元素数不一致、非有限数、非正质量、非对称矩阵、格式歧义或多余内容 | 导入错误；报告具体类别，不截断、不补零、不擅自对称化 |
| 输入哈希与声明不符、读取/发布期间变化、输出路径已存在 | 导入错误；保留旧数据，不重试覆盖或用新字节沿用旧身份 |
| 冻结、偏置、周期、线性、外部引擎或其他未审计变体 | 不支持的来源；列出缺项，不把矩阵外观相同当成语义兼容 |
| 原子对应声明缺失，或化学对应多解且未明确声明 | 沿用 T162 的 `unverified`，候选模式不可用；不猜映射、不做身份相关投影、RMSD 或模式排序，其他候选诊断可继续 |
| 已提供声明但字段/双射/元素/目标不唯一，或与实际来源绑定不符 | 分别沿用 `invalid_atom_mapping` / `atom_mapping_binding_mismatch` 语义；不降为未核实或悄悄选择另一来源，单候选/批量边界见第 5 节 |
| 刚体子空间/低频内部运动分不开、数值求解不收敛 | 模式不可用，保留诊断；不盲删负模式，不发布部分可靠的假象 |
| 方法、溶剂或正常结束证据缺失，但矩阵数学来源完整且不矛盾 | 明确未核实；可保留带警示的数值推演，不能标成已正常完成的科学结果；不把未知溶剂写成气相 |
| 已知异常结束或来源相互矛盾 | 不发布可用模式；文件即使完整也不能代表该次成功结果 |
| 非驻点或驻点证据缺失 | 分别标 non_stationary / unknown；只作诊断，沿用非驻点提示，不借另一计算的 Opt 或完成码证明驻点 |
| 无虚频、多虚频、低频负值或方向不一致 | 保留事实与 T138 诊断语义，不设科学通过阈值，不禁止 DFT |

## 7. 最小后续实施与交付缺口

后续另核任务号；T163 不扩成工具实现。最小路线为：

1. 沿用第 5 节已对齐的 T162 规则，先取得第 1/2 节所缺的小分子文件包；
   以一个已审计版本、一种明确格式、同框架几何和有效质量实现本地解析与转换。
2. 本地入口独占写新的 analyses 记录；纯文件读写，不初始化 Transport。
   在实施单中锁定第 3 节尚未定的数值容差及对应未知行为。
3. 增加 G0 显式读取该分析的入口（例如拟议 `--modes-analysis`，名称由实施单确认），
   与 `--modes-attempt` 互斥；Gaussian 原有来源、打印位移处理和旧报告读取保持兼容。
   按第 5 节新增分析来源适配，不把 xTB 的 `g98.out` 或 analyses 记录填成 Gaussian Attempt，
   不自动更换批量模式来源。
4. 合成验收包括：A/B 的单位、质量权重、正负谱与刚体空间；同一 e 先后两种归一方式的差异；
   质量覆盖回显随后被默认初始化覆盖时，不能将回显认定为最终有效质量；
   非自反原子置换、重复元素未知对应；刚体旋转时坐标与向量共同变换后 Bq 不变；
   截断/多余数值/非有限/非对称/哈希变化均无模式产物；来源未知明确展示；旧 Gaussian 行为不变。
5. 真实格式验收只消费明确来源的本地已有文件，核对字节、布局、取向、谱及精度边界。
   记录真实格式证据与合成算术证据的不同结论，不把两者相互替代。

最小补充资料是**同次、公开或获准使用的非研究小分子**完整 `hessian`，配对频率阶段几何
（可附 `g98.out` 作为几何源）、版本/构建、命令与控制输入、实际质量/缩放、stdout/stderr
及结束证据；每个原始文件都有 SHA-256。未知项逐一列明即可，不要求新的科学签字。
若只有矩阵，仍不能关闭取向、来源及刚体数值边界缺口。

新增 xTB Hessian **生成模板、上传/取回或远程命令**另立一单，重新核对模板参数白名单、
文件声明、非研究验证对象和合并前真实验证。这里没有选定研究方法，也没有任何执行授权。
T162 依赖、rebase 和文档入口已整合；本单 PR 在监督方审阅实际 head 前保持 draft。
源码和推演已可审阅，实际文件格式验收未完成，不能写“xTB Hessian 功能已支持”。

[manual]: https://xtb-docs.readthedocs.io/en/latest/hessian.html
[manual-src]: https://github.com/grimme-lab/xtb_docs/blob/4c9711315c845a6cb525bb480748a889386bc578/source/hessian.rst
[cli-man]: https://github.com/grimme-lab/xtb/blob/26b28010e805f7d1aeeef39813feb473e69cc4be/man/xtb.1.adoc#L221-L230
[calc]: https://github.com/grimme-lab/xtb/blob/26b28010e805f7d1aeeef39813feb473e69cc4be/src/type/calculator.f90#L115-L191
[api]: https://github.com/grimme-lab/xtb/blob/26b28010e805f7d1aeeef39813feb473e69cc4be/include/xtb.h#L250-L260
[molecule]: https://github.com/grimme-lab/xtb/blob/26b28010e805f7d1aeeef39813feb473e69cc4be/src/type/molecule.f90#L85-L86
[hess]: https://github.com/grimme-lab/xtb/blob/26b28010e805f7d1aeeef39813feb473e69cc4be/src/hessian.F90#L299-L383
[freq-io]: https://github.com/grimme-lab/xtb/blob/26b28010e805f7d1aeeef39813feb473e69cc4be/src/freq/io.f90#L29-L101
[project]: https://github.com/grimme-lab/xtb/blob/26b28010e805f7d1aeeef39813feb473e69cc4be/src/freq/project.f90#L149-L314
[convert]: https://github.com/grimme-lab/xtb/blob/26b28010e805f7d1aeeef39813feb473e69cc4be/src/mctc/convert.f90#L24-L56
[masses]: https://github.com/grimme-lab/xtb/blob/26b28010e805f7d1aeeef39813feb473e69cc4be/src/mctc/param/atomic_masses.f90#L24-L67
[main]: https://github.com/grimme-lab/xtb/blob/26b28010e805f7d1aeeef39813feb473e69cc4be/src/prog/main.F90#L924-L944
[mass-init]: https://github.com/grimme-lab/xtb/blob/26b28010e805f7d1aeeef39813feb473e69cc4be/src/prog/main.F90#L427-L431
[mass-options]: https://github.com/grimme-lab/xtb/blob/26b28010e805f7d1aeeef39813feb473e69cc4be/src/constrain_param.f90#L1256-L1307
[property]: https://github.com/grimme-lab/xtb/blob/26b28010e805f7d1aeeef39813feb473e69cc4be/src/main/property.F90#L650-L701
[mode-writer]: https://github.com/grimme-lab/xtb/blob/26b28010e805f7d1aeeef39813feb473e69cc4be/src/io/writer/turbomole.f90#L147-L189
[test-array]: https://github.com/grimme-lab/xtb/blob/26b28010e805f7d1aeeef39813feb473e69cc4be/test/unit/test_hessian.f90#L147-L240
[cclib-tree]: https://github.com/cclib/cclib-data/tree/127b2229d584d54fb84a74e383edb18a271fc283/XTB
[t162-pr]: https://github.com/anakine800-tech/Auto-Gaussian/pull/359
[t162-mapping]: https://github.com/anakine800-tech/Auto-Gaussian/blob/8fea723c861d2073028f20effc8e27f3c79159c1/ag/src/ag/g0_mapping.py#L25-L134
[t162-modes]: https://github.com/anakine800-tech/Auto-Gaussian/blob/8fea723c861d2073028f20effc8e27f3c79159c1/ag/src/ag/g0_modes.py#L281-L312
[t162-batch]: https://github.com/anakine800-tech/Auto-Gaussian/blob/8fea723c861d2073028f20effc8e27f3c79159c1/ag/src/ag/g0.py#L387-L449


## 8. T176 本地导入接口

当前实现为纯本地有限适配器；真实格式包的独立格式/数值审阅和公开副本的独立敏感/数据审阅均已通过。
已只读导入同次真实非研究水包及脱敏 fixture，数值谱与独立重建一致；科学验收不在本单范围内。
PR 继续保持 draft，待最终 head 的独立代码审阅及 CI。

```sh
ag import-xtb-hessian --study '<STUDY>' --source ./local-source.json --out analyses/xtb-example
```

只接受 conda-forge osx-64 `xtb 6.7.1 gfortran_h7141999_5` 的普通 GFN2 CLI 路径，
stdout banner 必须为 `6.7.1 (edcfbbe)`；包归档声明 SHA-256 必须为
`2945f0ffa63ad5369ac7e32449c9e195b4204c9a2f57557a174f187d1f4ad2fa`。
原包记录作为 `build` 文件保留；包记录/声明的一致性不验证计算文件的真实性。
该构建有 1072、1133、1278、1374、version 五个补丁，不称为未修改的上游二进制。
已只读核对这些补丁涉及 tblite/PTB/DIPRO、链接、优化器显示和 Meson 版本；
不修改 `wrhess/g98fake2`、`trproj`、默认质量重新赋值或普通 GFN2 Hessian 转换路径。
补丁字节 SHA-256 随输出 `program.patches` 保留；上游源码版本继续固定为第 1 节的 commit。
未承诺其他平台、构建、周期、冻结、约束、偏置、SPH、外部计算器或非默认有效质量。

源声明中所有 `files` 都相对于声明文件目录，禁止 `..`、符号链接、非普通文件和越界路径。
每个文件必须给出原始字节 SHA-256；不执行命令、不加载运行程序、不联网。
下列哈希为占位，实际使用须填写原始文件字节哈希：

```json
{
  "schema": "ag-xtb-hessian-source/1",
  "files": {
    "hessian": {"file": "hessian", "sha256": "<SHA-256>"},
    "geometry": {"file": "g98.out", "sha256": "<SHA-256>"},
    "stdout": {"file": "stdout.txt", "sha256": "<SHA-256>"},
    "stderr": {"file": "stderr.txt", "sha256": "<SHA-256>"},
    "input": {"file": "water.xyz", "sha256": "<SHA-256>"},
    "command": {"file": "execution.json", "sha256": "<SHA-256>"},
    "build": {"file": "package-record.json", "sha256": "<SHA-256>"}
  },
  "program": {"version": "6.7.1", "source_commit": "26b28010e805f7d1aeeef39813feb473e69cc4be", "build": "build"},
  "generation": {"command": "command", "controls": [], "path": "cli-numhess"},
  "hessian": {"format": "xtb-v671-wrhess", "unit": "hartree/bohr^2", "mass_weighted": false, "projected": true},
  "geometry": {"format": "xtb-g98", "unit": "angstrom"},
  "masses": {"effective_u": [15.99940492, 1.00794075, 1.00794075], "basis": "v671-cli-default-reset"},
  "scale": 1,
  "method": "GFN2-xTB", "solvent": "gas",
  "termination": "normal", "stationarity": "unknown"
}
```

`command` 是原始捕获的单行调用文本，或含 `argv` 字符串数组的原执行 JSON。
调用参数必须与 stdout 的 `program call` 一致；JSON 中的命令从不用于执行。
有限参数：`--hess` 或 `--ohess [级别]` 恰好一种，另接受 GFN2、chrg、uhf、alpb、gbsa、input、acc、parallel、norestart。
原始输入 XYZ 也绑定，不能代替 Hessian 后的 `g98.out` 几何。显式控制输入须列在 `controls` 中；
仅识别 `$hess` 的质量请求和 `$end`，其解析回显单列，实际有效质量必须与固定源码默认表一致。
默认初始化在这些请求之后覆盖质量，故请求/回显与有效数组不同可解释为 reset，不能直接用请求质量。
Hessian scale 当前只接受已绑定 stdout 中的默认值 1；非默认缩放需另补最终生效证据，不能只凭五位回显猜真实系数。
数值内核对任意正缩放因子的代数正确性由合成测试检验，不等于该来源范围均已支持。

可选 `files.result` 保存原有执行回执：若提供，必须含匹配 argv、`executed=true`、整数 `returncode=0` 和 `timed_out=false`。
任何已知非零退出、超时、错误终止文字或相互矛盾的来源均拒绝。正常结束缺失时，
`termination=unknown` 仍可生成警示数学诊断；缺 marker 不能填写 normal。
方法仅可为 GFN2-xTB 或 null；溶剂可为 gas、`ALPB:<名称>`、`GBSA:<名称>` 或 null，须不与参数矛盾。
这些描述仍标为未独立核实，未知项保留 null；不把未知溶剂当气相。
驻点只允许 unknown 或 non_stationary，Hessian 阶段的未优化警告会标为后者。

输出目录必须是 study `analyses/` 的新直接子目录；已有目录拒绝覆盖。
保留 `source.json` 原字节、逐文件原字节副本 `input-NNN`、结果 `analysis.json` 和结果字节绑定 `binding.json`。
所有输入写入并落盘后，独占链接发布 analysis.json；写入失败保留私有残片，不发布半份可用记录。
读取时核对分析、声明和全部原始副本哈希，重新解析来源、谱与刚体空间，并验证保存的模式满足
质量加权正交性、本征方程残差、Cartesian 单位归一及带符号频率关系。
等价整体符号与打印精度内简并子空间变化不视作错误；直接编辑结果而未匹配字节绑定必拒绝。
这些本地哈希防止不一致，不能证明恶意重写整套文件后的真实性；G0 映射另绑定实际 analysis.json 原字节。

### 打印精度与刚体分离

保留全部 `3N` 个特征值、带符号波数及去质量权重后的 Cartesian 位移。以质量加权平移/旋转基
的 SVD 核对六维刚体空间；每列归一后计算秩，原点取质心，几何不旋转、不对齐。
Hessian 每项舍入界为 `εH=0.5×10⁻¹⁰`，g98 坐标为 `εx=0.5×10⁻⁶ Å`。
Hessian 的谱范数误差上界为 `δK=3N·s·εH/min(m)`，另加随维数/谱范数变化的浮点舍入项。
旋转列误差界为 `2√(3Σm)·εx`；归一列与最小奇异值给出刚体子空间扰动界。
只接受恰好六维的零谱簇，并核对它与几何刚体基的子空间残差和 `K·R` 残差；
内部谱间隙必须足以使对应扰动界小于 1。不是按频率大小删除六项，也不复投影 H。
低频内部模式落入舍入界、近线性秩不足、取向不符或谱间隙不足均返回 `external_modes_unresolved`，
保留完整谱但不提供可排序的内部模式。小负内部值若可分离则照实保留。
可用模式另与同次 g98 四位小数的波数比较。上游 `g98fake2` 在打印前只保留
`|f| > 0.1 cm⁻¹` 的项；导入器按 `λ±δK` 的频率区间及半个打印末位核对可见子集。
完全位于闭区间 [−0.1, +0.1] 内的项可省略，完全在外的项必须显示；跨越边界的项允许
省略或显示与区间相容的值，保留一一对应，不把边界不确定解释为可以删除内部模式。
显示值虽可舍入为 ±0.1000，±0.0999 则不可能来自严格超过阈值的四位打印。
所有项被隐去时允许 writer 的空频率行；缺失整个频率块、缺少必显项、重复或矛盾仍拒绝。
该规则仅核对配套证据，完整内部谱始终不变；不读取 g98 两位小数的质量加权显示向量。
没有用水分子的单次误差反推固定阈值。

真实水包的初步只读导入：内部波数约为 1538.898353、3642.665507、3651.164333 cm⁻¹；
外部舍入频率约 −0.031 至 +0.045 cm⁻¹，均保留。g98 的内部四位输出与重建区间一致。
合成测试单独覆盖不同质量、缩放、负/软/简并谱、五原子几何、打印边界扰动、映射和路径/发布失败。
真实格式 fixture 位于 `ag/tests/fixtures/xtb_hessian_v671_water/`；数值原件与脱敏副本的哈希对应明确保留。
当前未决：最终 head 的独立代码审阅及 CI。
