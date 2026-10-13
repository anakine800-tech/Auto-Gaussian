# Gaussian 输入、运行与输出阅读

## 目录

- [输入文件五部分](#输入文件五部分)
- [结构表示](#结构表示)
- [建模和运行](#建模和运行)
- [输出证据](#输出证据)
- [GaussView](#gaussview)

## 输入文件五部分

### GKB-0301 基本骨架

- 类型：操作
- 关键词：Gaussian input；gjf；Link 0；Route Section；charge multiplicity
- Gaussian 输入的核心由 Link 0 命令、route section、标题、电荷与多重度、分子说明/坐标五部分组成，部分任务还需要附加输入块。

```text
%chk=job.chk
# method/basis job-keywords

descriptive title

charge multiplicity
coordinates

optional additional input
```

- 空行是语法的一部分：route、标题和坐标区之间按格式分隔；额外输入块的位置由关键词决定。
- 不能直接复制示例中的 `B3LYP/6-31G*`；它只是示例方法，不是默认推荐。

### GKB-0302 Link 0

- 类型：操作
- 关键词：%chk；%mem；%nproc；checkpoint；rwf
- `%chk`：指定检查点文件；其中可保存几何、轨道和力常数等信息，并用于重启或后续任务读取。
- `%mem`、CPU 和 `%rwf`的写法与资源值必须按实际 Gaussian 版本和执行平台核对，不能照搬旧版 Windows 示例。
- 成功证据：输出开头回显的资源和检查点路径与计划一致，文件实际生成并可读取。

### GKB-0303 Route section

- 类型：操作
- 关键词：route section；#P；method/basis；job type
- route 以 `#` 开始，指定方法、基组和作业类型；大小写通常不敏感，可使用 `keyword=option` 或括号选项。
- `#N`是常规输出级别，`#P`请求更详细输出。
- 检查顺序：方法 → 基组/ECP → 作业类型 → 溶剂/色散/积分网格 → SCF/优化选项 → 对称性 → 额外输入块。

### GKB-0304 电荷和自旋多重度

- 类型：操作/安全边界
- 关键词：charge；multiplicity；2S+1；open shell
- 自旋多重度定义为 `2S+1`；闭壳层水常见为 `0 1`，H3O+ 常见为 `1 1`，NO 基态常见为 `0 2`，但实际体系必须独立确认。
- 必须确认：总电子数与电荷是否一致；未成对电子数是否支持所选多重度；是否存在多个竞争自旋态。
- 禁止做法：根据几何外观、文件名或常见价态静默猜测电荷和多重度。

## 结构表示

### GKB-0310 Cartesian、Z-matrix 和混合坐标

- 类型：操作
- 关键词：Cartesian；Z-matrix；internal coordinates；mixed coordinates
- Cartesian：元素符号和 `x y z`；坐标数值宜明确写成十进制数。
- Z-matrix：用已出现原子的序号定义键长、键角和二面角，可用变量保持对称关系。
- 混合坐标：部分原子用 Cartesian，部分用内坐标。
- 适用边界：坐标格式正确不等于连接关系、构象或立体化学正确；复杂分子需要结构来源和构象检查。

### GKB-0311 虚原子和鬼原子

- 类型：概念/操作
- 关键词：dummy atom；X；ghost atom；Bq
- `X`：作为内坐标参考点，本身不参加电子结构计算。
- `Bq`：在指定位置保留基函数而没有真实原子；也可用于环中心、NICS 或 counterpoise 相关设置。
- 风险：`X`、`Bq` 和带 `-Bq` 的原子写法用途不同，不能互换。

### GKB-0312 初始结构来源

- 类型：操作原则
- 关键词：initial geometry；crystal structure；conformer search
- 简单结构可按合理参数或图形软件构建；复杂结构宜优先使用晶体数据或相似可靠结构，并进行适当构象搜索。
- 不能据此推出：数据库结构适合目标溶剂、氧化态或配体状态；所有构象只需优化一次。

## 建模和运行

### GKB-0320 GaussView 创建任务

- 类型：操作
- 常见流程：构建结构 → `Calculate`/Gaussian Setup → 选择 job type、method、basis、title、charge/spin → 保存 `.gjf` 或提交任务。
- 版本边界：菜单、截图和控件来自 GaussView 5.0.9/Gaussian 09；在新版界面中只沿用概念，不依赖像素位置。
- 必查项目：连接、立体化学、单位、电荷、多重度、方法、基组、任务类型和额外选项。

### GKB-0321 Gaussian 09W 运行

- 类型：操作
- 旧版 Gaussian 09W 的常见流程是打开或编辑输入，点击 Run，指定输出文件并保存后开始计算。
- 限制：这是本地 Windows GUI 旧版本流程，不适用于 PBS、Linux 命令行或当前配置的远程执行技能。
- 实际运行时必须使用目标环境对应的执行技能；本知识库负责解释，不授权或代替任务提交。

## 输出证据

### GKB-0330 输出阅读顺序

- 类型：输出 SOP
- 关键词：Gaussian output；Standard orientation；SCF Done；Normal termination
- 顺序：
  1. 软件版本、日期和实际 route；
  2. 标题、电荷、多重度和原子数；
  3. 实际基组/ECP 与 5D/6D、7F/10F；
  4. 输入/标准取向的最终结构；
  5. SCF 或相关方法能量及收敛；
  6. 作业特有证据，如优化四项阈值、频率、IRC 端点；
  7. 错误信息和终止状态。

### GKB-0331 `Normal termination` 的含义

- 类型：判断边界
- 关键词：Normal termination；Error termination
- 正常完成的 Gaussian 09 输出通常在末尾显示 `Normal termination of Gaussian 09`；其他版本的文字可能略有差异。
- 只表示程序按该作业路径结束；不能单独证明结构、电子态、过渡态、IRC 或科学结论正确。

### GKB-0332 优化和频率证据

- 类型：输出判断
- 优化：检查最大力、RMS 力、最大位移和 RMS 位移是否达到阈值，并确认最终几何合理。
- 频率：读取 `Frequencies --`、强度和振动矢量；稳定点期望没有与化学运动对应的虚频，TS 候选期望一个目标反应模式的虚频。
- 单一频率计数仍不够：必须查看振动模式，并在反应研究中用 IRC 或等价证据检查连接性。

## GaussView

GaussView 可用于构建结构、选择元素与官能团、查看点群、放置环中心 Bq、显示手性、检查优化轨迹、振动、光谱、虚频模式和 IRC 路径。

使用时注意：

- GUI 显示是辅助证据，不替代输出文本和数值检查；
- 具体按钮名称和位置随 GaussView 版本变化，操作前应按实际界面确认；
- 打开优化输出时可选择读取中间结构查看轨迹，但最终结论应以实际输出与目标任务证据为准；
- 显示的点群、键和原子连接需要人工复核，尤其是金属配合物、弱配位和 TS。
