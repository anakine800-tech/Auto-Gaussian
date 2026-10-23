# T13a：TS 工具复用调研

调研日期：2026-10-14。范围：autodE 本机 xTB 初猜实测、ARCHE 论文和源码审阅、T13 实施建议。只新增本文；未修改运行代码或 Skills，未连接集群、未提交作业、未运行 Gaussian。当前主分支没有 T13a 独立任务单，以本次任务指令为范围依据。

## 1. 结论与当前阻塞

- **autodE 可以完全在本机调用 xTB 生成路径及候选初猜；Gaussian 和联网都不是该底层接口的运行时依赖。** 安装包和获取源码需要下载，安装完成后的两例计算在操作系统禁止网络访问的环境中结束。
- **两例没有证明自动 TS 搜索可用。** SN2 未找到内部峰，初猜为空；aza-Michael 得到了候选，但有三个虚频，且并非可接受的驻点。不要把“有 XYZ”升级为“找到 TS”，更不能声称 IRC 验证。
- T13 建议先实现人工初猜的 TS/Freq、QST2/QST3 输入校验、父 chk 安全复制、双向 IRC 与端点比对。autodE 作为结构 Skill 的可选本机脚本，暂不作为可靠默认初猜工具，也不增加自动搜索或自动重提流程。
- ARCHE 的“提出可区分的假设 → 计算客观证据 → 修正计算或假设”适合写入现有卡片；其控制器不适合移植。作者代码是**学术及非商业研究限定的源码可见发布**，不能按 MIT 代码直接并入本仓库。新版随附 MiniChem 有独立 MIT 部分，但其内嵌作者工具与 ASH 另有条款。

**当前阻塞分类**：科学审阅——两例均无合格 TS，Michael 初猜混合了成键、质子转移及额外不稳定运动；结构——仍需人工选择并核对端点和原子映射。环境——本机 xTB 路线已跑通；提交、Gaussian 精修、双向 IRC 均不在本次执行范围。调研完成不等于 T13 功能完成或 study 科学验收。

## 2. 固定版本与证据边界

| 对象 | 本次读取或运行的版本 |
|---|---|
| Auto-Gaussian 基线 | `9014326a73867a60285824eedc594a44b620979b` |
| autodE | 1.4.5，源码 `e7e71b33d8659fe921c16f877f9c1adddc4f9cff` |
| xTB | 6.7.1，conda-forge 构建 `gfortran_h7141999_5`，`osx-64` |
| 原始 ARCHE | `cb8d8b7bf5334e7b11580748c9ca0f1922ecca51` |
| 论文当前链接的 Arche-Harness | `853a2e2ab108d6e640b65c0f2be92ef98abd511d` |
| 论文 | [arXiv:2609.11147v1](https://arxiv.org/abs/2609.11147v1)，全文及 SI；重点正文 Methods、SI A1 与 A3 |

论文描述 Retrieval/Hypothesis/Planner/Execution/Reflection；当前链接仓库的主要入口已改为 Investigation/Task Review。两者分开审阅，不能用新版能力替论文旧实现背书。没有运行 ARCHE 的模型 API、GPU 后端或执行服务。

## 3. autodE：能调用的 API 与不能假设的开关

源码证据：[methods](https://github.com/duartegroup/autodE/blob/e7e71b33d8659fe921c16f877f9c1adddc4f9cff/autode/methods.py)、[NEB](https://github.com/duartegroup/autodE/blob/e7e71b33d8659fe921c16f877f9c1adddc4f9cff/autode/neb/original.py)、[CI-NEB](https://github.com/duartegroup/autodE/blob/e7e71b33d8659fe921c16f877f9c1adddc4f9cff/autode/neb/ci.py)、[TSguess 包装器](https://github.com/duartegroup/autodE/blob/e7e71b33d8659fe921c16f877f9c1adddc4f9cff/autode/neb/neb.py)、[XTB wrapper](https://github.com/duartegroup/autodE/blob/e7e71b33d8659fe921c16f877f9c1adddc4f9cff/autode/wrappers/XTB.py)。

### 3.1 最小调用边界

```python
import autode as ade
from autode.methods import XTB
from autode.neb import CINEB

ade.Config.n_cores = 2
ade.Config.lcode = "xtb"
ade.Config.XTB.gfn_version = 2
# 本机 xTB 可执行文件由调用者在私有运行配置中解析并固定。
xtb = XTB()
# r、p 是同一原子顺序、同一总电荷和多重度的完整反应复合物。
neb = CINEB.from_end_points(r, p, num=9)
neb.calculate(method=xtb, n_cores=2,
              etol_per_image=ade.values.PotentialEnergy(0.05, units="kcal mol-1"))
guess = neb.peak_species  # 无内部峰时为 None；绝不替换成最高端点。
if guess is not None:
    guess.print_xyz_file(filename="ts_guess.xyz")
    guess.calc_hessian(method=xtb, numerical=True,
                       use_central_differences=True, n_cores=2)
```

更短的入口是 `autode.neb.neb.get_ts_guess_neb(r, p, method=XTB(), name="guess", n=9)`，返回 `TSguess` 或 `None`；它使用默认 NEB 容差。本次直接使用 `CINEB`，便于保留整条路径与指定容差。

**没有“关闭高精度”的通用布尔开关。** `get_hmethod()` 只从 ORCA、G09、G16、NWChem、QChem 选择，`Config.hcode=None` 表示自动选择，并非禁用；`Config.hcode="xtb"` 也不是合法高精度选择。正确办法是只调用上述显式 `method=XTB()` 的接口，不调用 `Reaction.calculate_reaction_profile()` 或默认 TS 搜索链。本次额外设置无效 `hcode="disabled"`，使误走高精度选择时抛错；这只是本次防误调用哨兵，不是上游支持的禁用配置。

`Species.calc_hessian()` 遇到不提供 Hessian 的后端可对梯度做数值差分。本次明确指定中心差分、默认位移 0.002 Å；不会因需要频率而自动切换 Gaussian。频率由 autodE 质量加权及平移转动投影得到，**不是 Gaussian 频率，也不是直接调用 xTB 原生 `--hess`**。

### 3.2 输出及源码限制

- 原生 NEB 输出：`neb_init.xyz`、`neb_optimised.xyz` 多帧轨迹、`neb_optimised.pdf` 能量图，以及逐图像的 `.xyz`、`.out`、`.grad` 计算记录。
- 候选导出需显式调用 `print_xyz_file()`，本次命名 `ts_guess.xyz`。包装器返回对象，不意味着已写出独立 TS 文件。
- 本次脚本另存 `summary.json`、`hessian.npy`、每个虚频的正负位移 XYZ；这些是测试记录，不是 autodE 的固定标准输出。端点优化还产生 xcontrol 文件及优化后 XYZ。
- `CINEB.from_end_points()` 文档要求原子顺序一致，但入口检查只比较排序后的元素集合，**不能防同元素原子互换**。原子映射必须由上游核对。
- `NEB._minimise()` 默认 `max_n=30` 传给 SciPy 的 `maxfun`，不是严格 30 次 xTB 调用或完整收敛保证。`calculate()` 返回 `None`，不向调用者暴露优化器 `success`，仍可写优化后轨迹；`peak_species` 只检查路径内部峰。
- 本次没有保留优化器 `success/message`，不能据正常进程退出声称 NEB 收敛；未来适配器必须记录这一信息和候选梯度。为防把未收敛峰当 TS，这比仅检查文件存在更必要。
- wrapper 会使用临时目录并移动/删除自己的临时产物，不能拿这套执行器去操作服务器数据；本次仅在独立本机实验目录使用。

### 3.3 安装、依赖与许可证

autodE 安装到该 worktree 自己的 `.venv`（Python 3.11.15，未启用共享 site-packages），共享 chem 解释器仅用于创建 venv，没有向共享环境安装包。xTB 原生程序及动态库装入该 worktree 独立的辅助 conda 前缀；autodE 显式引用该程序，不依赖共享 chem 中的 xTB。

源码 `setup.py` 编译三个 Cython/C++ 扩展；直接 `pip install` 源码**并未声明完整运行依赖**，还要安装上游 `requirements.txt`。本次安装并导入成功，`pip check` 通过。

| 依赖 | 实测版本 / 重量判断 |
|---|---|
| RDKit | 2025.9.3，结构操作的主要二进制依赖 |
| NumPy / SciPy | 2.4.6 / 1.17.1，数值优化、Hessian |
| NetworkX / Matplotlib / Pillow | 3.6.1 / 3.11.2 / 12.3.0，图与绘图 |
| Cython / loky | 3.3.0 / 3.7.0，构建及进程池 |
| xTB 及运行库 | 下载约 22.7 MB，安装占用约 105 MiB |
| 本次整个 venv | 约 702 MiB；含 pytest、PDF 读取、cclib、GoodVibes 等调研/测试附加包，**不是 autodE 最小体积** |

不需要 PyTorch、CUDA、模型权重或 LLM API。首次加载本机二进制库明显慢于后续运行，计时表从脚本导入完成后开始，不能代表冷启动总延迟。autodE 属中等重量科学 Python 依赖，适合隔离的可选工具环境，不应并入 ag 必装依赖。

[autodE MIT 许可](https://github.com/duartegroup/autodE/blob/e7e71b33d8659fe921c16f877f9c1adddc4f9cff/LICENSE.md)允许复用和修改，但复制实质代码必须保留版权及许可。优先固定版本调用，少量适配代码自行编写。xTB 的包元数据为 LGPL-3.0-or-later，见[上游许可说明](https://github.com/grimme-lab/xtb)；它及其他依赖的再分发不能由 autodE 的 MIT 许可代替。本文没有复制 ARCHE 实现代码或再分发第三方二进制。

## 4. 本机实测：正常执行，科学结果未通过

### 4.1 固定实验设置

两个例子都是公开小分子模型，GFN2-xTB、气相、单重态。SN2 总电荷 −1，6 原子；aza-Michael 总电荷 0，12 原子。每个调用最多 2 个本机计算核，BLAS 线程设 1。CI-NEB 为 9 图像，IDPP 初始插值，每图像能量容差 0.05 kcal/mol。数值 Hessian 在解除约束的候选上计算。

端点准备是**受约束的路径种子，不是已证明的反应物/产物极小值**：

- SN2：手工背面进攻几何，固定种子 C–Cl/C–F 距离分别为 1.8/3.1 Å 和 3.3/1.4 Å，先用 xTB 优化其他自由度，再移除约束。
- Michael：`C=CC=O.N` 加显式氢，RDKit ETKDGv3，种子 `20261014`，UFF 优化；将 NH₃ 沿丙烯醛重原子平面法向放到 β-C 外。分别以 Cβ–N=3.2 Å 和 1.5 Å 约束优化。产品种子优化时 H12 从 N 转移至 Cα，成为中性 β-氨基醛连接形式。因此这是**包含成键及质子转移的简化总加成路径**，不是已经隔离出的单独亲核进攻基元步骤，更不能代表某研究课题的目标反应。

启动计算时使用 macOS `sandbox-exec` 的 `deny network*`，继承到子进程；本机连接探针得到预期的 `PermissionError`。另禁止 Gaussian、ORCA、SSH、文件传输和 PBS 提交/取消程序的启动。所有实际电子结构调用显式指定上述 xTB。下载源码和安装包发生在这一步之前。

### 4.2 结果与计时

| 例子 | 端点准备 | CI-NEB | Hessian | 总计 | 结果 |
|---|---:|---:|---:|---:|---|
| F⁻ + CH₃Cl → CH₃F + Cl⁻ | 19.66 s | 12.42 s | 未运行，无候选 | 32.07 s | `peak_species=None`，无 TS 初猜，无虚频方向可报 |
| NH₃ + 丙烯醛 aza-Michael | 1.07 s | 10.91 s | 2.20 s | 14.18 s | 有内部峰，3 个虚频，拒绝作为已验证 TS |

计时含端点构建及文件 I/O，不含依赖安装和导入；两个例子启动有时间重叠，不是硬件性能基准。均为单次搜索，没有为了得到阳性结果改方法重跑。只对 Michael 导出的同一候选追加一次单点梯度诊断，没有再优化。

SN2 的 9 个存储图像能量（Hartree）为：

```text
-13.137465305879  -13.140516639630  -13.143512168095
-13.145473327813  -13.146983432649  -13.155303545825
-13.181851983780  -13.191078706001  -13.191248177365
```

此路径单调降低，没有内部峰。这是“此方法、此端点、此设置没有找到峰”，**不能推导真实 SN2 无势垒，也不能推导 xTB 或 autodE 对所有 SN2 都失败**。没有把端点或中间图像冒充 TS，也没有对不存在的初猜编造频率。

Michael 内部峰为零基图像 6。候选 Cβ–N=1.80625 Å、Cβ–Cα=1.50202 Å、Cα–C(=O)=1.49776 Å、C=O=1.21517 Å。投影后 3 个虚频为 **−1530.25、−621.22、−128.25 cm⁻¹**；六个平移转动零模不计入。虚频较多且几何有明显畸变，NEB 内部峰不能当作一阶鞍点。

以下用 `d r_ij/dq = r̂_ij · (v_j − v_i)` 描述正向模式；模式整体正负号可任意翻转，须看相对方向。数值按 autodE 输出的归一化位移计算，不能解释成实际振幅或反应概率。编号见候选 XYZ。

| 模式 / cm⁻¹ | 主要键长导数 | 科学解释 |
|---|---|---|
| −1530.25 | N5–H12 −0.94250；Cα2–H12 +0.84530；Cβ1–N5 +0.26153 | 主要是 N 与 Cα 间质子转移，伴随 C–N 变化；反向对应 N–H 断裂、Cα–H 形成 |
| −621.22 | N5–H10 +0.76773；Cβ1–N5 +0.29748 | 额外 N–H 不稳定运动，不是独立证明目标成键的模式 |
| −128.25 | N5–H10 −0.95912；Cβ1–N5 +0.93333 | C–N 变化与另一个 N–H 运动混合，不能单凭这一模判定目标 TS |

追加的候选单点梯度检查（同一 GFN2-xTB、导出的五位小数坐标）给出梯度 RMS **0.04895 Hartree/Å**、最大绝对分量 **0.16622 Hartree/Å**，电子能量 −16.710429621714 Hartree。这进一步表明该候选远非驻点；虚频不能用于正式 TS 定性。

没有运行 IRC，也没有动画人工签字。模式审查是位移向量及键长导数的数值检查；非驻点处这些频率只用来诊断候选的曲率。

### 4.3 得到的候选结构

下列 XYZ 仅为 **Michael 未通过候选**。1=Cβ，2=Cα，3=醛基 C，4=O，5=N，12=发生转移的 H。坐标为 Å，固定原子编号，无立体选择性结论。

```xyz
12
aza-Michael candidate; charge=0 mult=1; NOT validated TS
C     -1.31136   -0.15747    0.03149
C      0.10847   -0.34201   -0.42249
C      1.19518   -0.26477    0.60532
O      1.11614   -0.25686    1.81788
N     -2.03919   -1.77300    0.38199
H     -1.39735   -0.01025    1.10658
H     -1.92969    0.47698   -0.62471
H      0.38092    0.20811   -1.34266
H      2.18933   -0.21683    0.03176
H     -2.09534   -3.13497    0.38296
H     -2.89836   -1.47280   -0.25894
H     -0.45942   -1.70099   -0.22664
```

原始候选 XYZ SHA-256：`c9bf21936d0e0d1dcafb7ebd92dc180d81218689640dea53d96b8f32dd44f00f`。上文为便于公开阅读替换了注释行，哈希对应本地原文件；不把重新排版的文本冒充原字节。

## 5. ARCHE：循环、工具注册表及可借用边界

### 5.1 “假设 → 计算 → 修正”如何组织

论文正文 Methods（18–21 页）与 SI A1（S4–S9）把任务拆为：检索文献背景；提出并排序竞争假设；Planner 将假设转换为有输入、输出及依赖的计算步骤；执行器运行工具并返回结构、能量、频率及诊断；Reflection 判断证据是否区分假设。技术失败返回计算设置修正，计算完成但与实验/假设不符则返回假设修正；需要改结构时可交给人。通用模型负责化学探索，ARCHE-Chem 提供 Gaussian 方法及故障解释。

[原始 controller](https://github.com/Arvin0313/ARCHE/blob/cb8d8b7bf5334e7b11580748c9ca0f1922ecca51/src/chemistry_multiagent/controllers/chemistry_multiagent_controller.py)将阶段结果保存为 JSON；默认反思最多 3 轮，遇到尚未完成的 Gaussian 任务保存等待状态。[ReflectionAgent](https://github.com/Arvin0313/ARCHE/blob/cb8d8b7bf5334e7b11580748c9ca0f1922ecca51/src/chemistry_multiagent/agents/reflection_agent.py)聚合规则和专家信号，返回 `accept`、`revise_workflow`、`revise_hypothesis`、`stop`，控制器据此重复规划或假设阶段。

**不能照搬的真实风险**：原始 controller 在 ReflectionAgent 不可用时默认 `accept`；ExecutionAgent 仍有返回模拟成功的接口，也有真实执行与 replay 分支。工具名存在或步骤状态成功不构成科学证据。本仓库必须保留事实解析、LLM 科学审阅和人签字的分离，失败/UNKNOWN 不自动重提。

[新版 controller](https://github.com/JetAstra/Arche-Harness/blob/853a2e2ab108d6e640b65c0f2be92ef98abd511d/src/chemistry_multiagent/controllers/investigation_v2_module_controller.py)的 `_select_next_module()` 则路由检索、研究问题、假设生成/选择、Investigation、Task Review；`RepairRequired` 返回调查，`RegenerateHypotheses` 返回假设生成，`Accepted/Unanswerable/Stopped` 终止。它使用持久工作记忆及独立会话，不能把这些新版实现归到论文原始实验，也没必要引入 ag 的文件状态架构。

### 5.2 工具注册表：论文理想接口与两个代码版本

| 来源 | 实际设计 | 对我们的启发 / 限制 |
|---|---|---|
| 论文 SI A3（S19–S22） | 原子工具 + 常用多步骤工具；条目描述名称、功能、inputs、outputs、parameters；Planner 按输入输出类型组合，格式不兼容时插入转换步骤 | 卡片写清前置产物、输出与适用边界即可，不需要新增通用工作流语言 |
| [原始 toolpool](https://github.com/Arvin0313/ARCHE/blob/cb8d8b7bf5334e7b11580748c9ca0f1922ecca51/src/chemistry_multiagent/tools/toolpool.json) | 实际 7 条，主要字段为 `tool_name`、`tool_path`、`description`；pipeline 标志拼作 `pipline`，示例值是字符串 | 不等于论文所示完整类型约束，不可当作安全执行白名单 |
| [原始 ExecutionAgent](https://github.com/Arvin0313/ARCHE/blob/cb8d8b7bf5334e7b11580748c9ca0f1922ecca51/src/chemistry_multiagent/agents/execution_agent.py) | `ToolDefinition` 加 input/output format 与 pipeline 标志；加载时从描述文本猜格式；名称/描述匹配工具，执行时另做参数适配与部分函数签名检查 | 可借鉴“格式转换显式化”，不能借它的模糊匹配来授权执行；部分 Python 接口仍是模拟 |
| [新版 MiniChem models](https://github.com/JetAstra/Arche-Harness/blob/853a2e2ab108d6e640b65c0f2be92ef98abd511d/third_party/minichem_toolbox/src/minichem_toolbox/models.py) 与 [registry](https://github.com/JetAstra/Arche-Harness/blob/853a2e2ab108d6e640b65c0f2be92ef98abd511d/third_party/minichem_toolbox/src/minichem_mcp_tools/registry.py) | `ActionSpec` 声明操作、输入、主要输出、可选 backend 和联网需求；`BackendSpec` 声明可执行程序、模块、资源、参数白名单；由 catalog 校验再注册到 FastMCP，支持渐进发现或全量暴露 | “能做什么”和“由谁执行”分开值得参考；运行时可用性与注册存在分开。无需移植 MCP 服务、目录冻结、持久数据库或一整套抽象 |

新版 registry 明确要求不自动 fallback；但其可编程分析、native software 执行层仍比 ag 模板范围广。不能因为它有参数校验就替代 ag 的 Mac 人工确认、一次 Attempt 一次提交及远程不覆盖控制。

### 5.3 映射到卡片和 ag

| ARCHE 职责 | Auto-Gaussian 对应 | 本次建议 |
|---|---|---|
| Retrieval / 方法依据 | literature Skill | DOI、直接先例/类比、方法适用边界 |
| Hypothesis / 选择可区分的计算 | study Skill 与人 | 在 study 目标和 review 写竞争解释及下一条所需证据 |
| Planner / 转换链 | recipes 卡片 + structures Skill | TS/Freq、IRC 前置条件，结构映射，明确输入输出 |
| Execution | `ag prepare/submit/status/fetch` | 保留现有模板与确认；不移植 ARCHE 提交器 |
| 输出解析 | `ag facts` | 客观收敛、频率、位移、能量、端点几何 |
| Reflection | LLM 按卡片写 review | 区分环境/计算设置问题与科学假设问题；提出新 Attempt 后等人确认 |
| 构象、热化学、关系图 | `ag dedup/cluster/thermo/graph` | 继续复用已有确定性工具 |

### 5.4 哪些代码可直接借用

| 候选 | 技术判断 | 许可与决定 |
|---|---|---|
| autodE 的 NEB、IDPP、XTB wrapper、数值 Hessian | 可固定版本调用；应加很薄的本机适配，补足映射与收敛证据 | MIT，允许保留许可后复用；本次优先推荐依赖调用 |
| 原始 ARCHE 的 toolpool 加载、ReflectionAgent、controller | 思路可化为卡片；代码与自动循环、模拟分支、环境配置耦合 | [作者许可证](https://github.com/Arvin0313/ARCHE/blob/cb8d8b7bf5334e7b11580748c9ca0f1922ecca51/LICENSE)限学术非商业，保留许可/署名、标识修改、不能扩展授权；商业或服务用途需书面许可，无专利授权。**不直接并入本仓库 MIT 代码** |
| 原始 TSPipeline 的 `run_cineb` | [实际入口](https://github.com/Arvin0313/ARCHE/blob/cb8d8b7bf5334e7b11580748c9ca0f1922ecca51/src/chemistry_multiagent/tools/23_TSPipeline/run.py)导入 ASH 版；[ASH 版](https://github.com/Arvin0313/ARCHE/blob/cb8d8b7bf5334e7b11580748c9ca0f1922ecca51/src/chemistry_multiagent/tools/23_TSPipeline/tools/RunCINEB_ash.py)用 `FairchemTheory`、`uma-s-1p1`、CUDA，函数未显式返回或写出声明的 XYZ；[另一版](https://github.com/Arvin0313/ARCHE/blob/cb8d8b7bf5334e7b11580748c9ca0f1922ecca51/src/chemistry_multiagent/tools/23_TSPipeline/tools/RunCINEB.py)实际也用 FAIRChem，虽有“XTB”注释 | 不是可直接使用的轻量本机 xTB 方案；作者许可与模型/ASH 许可分别核对，不采用 |
| 新版 MiniChem 原生 `ActionSpec/BackendSpec` 及 catalog 基础代码 | 这些小型声明结构有技术复用可能，但 ag 现有模板声明已满足较小范围 | [MiniChem 独立 MIT](https://github.com/JetAstra/Arche-Harness/blob/853a2e2ab108d6e640b65c0f2be92ef98abd511d/third_party/minichem_toolbox/LICENSE)允许保留声明复用。没有足够收益，T13 不引入整包 |
| MiniChem 内嵌作者工具与 ASH | 不能被外层 MIT 一概覆盖 | [内嵌作者工具许可](https://github.com/JetAstra/Arche-Harness/blob/853a2e2ab108d6e640b65c0f2be92ef98abd511d/third_party/minichem_toolbox/src/minichem_toolbox/vendor/arche_author_tools/LICENSE)仍限非商业；[ASH 许可](https://github.com/JetAstra/Arche-Harness/blob/853a2e2ab108d6e640b65c0f2be92ef98abd511d/third_party/minichem_toolbox/vendor/ash-0.95/LICENSE)为 GPL v2 文本。不能整包按 MIT 移植 |

许可证判断依据是固定提交的 LICENSE，不依赖 GitHub 的“public”标记；原始 README 中“许可证待定”的文字与当前 LICENSE 不一致，不能据此假定无条件授权。这里仅陈述许可文本与工程采用决定，不对尚未定义的商业发行方式作法律结论。

## 6. T13 建议方案与工作量

以下均为建议，尚未实现、未获真实集群验证。估计为一名熟悉现有代码的工程师的工作日，包含针对性测试和文档，不含排队、人工化学审阅及科研收敛时间。

### 6.1 本机初猜放结构 Skill 脚本：2–3 日

将 autodE 薄适配放结构 Skill 的辅助脚本，由卡片选择并调用；**不新增 ag 自动 TS 搜索子命令**。ag 继续承担安全生命周期和确定性结果处理。TS/Freq 的独立卡片与失败诊断补充约 0.5–1 日。

输入采用成对 XYZ + 小型 JSON 元数据：电荷、多重度、显式原子映射、预期成断键、质子迁移、溶剂、xTB 版本、图像数及随机种子；可附带保留键序和立体信息的 SDF。XYZ 本身不保存键序、电荷和立体身份，不能单独作为全部语义。

输出：候选 XYZ（允许为空）、整条路径 XYZ、JSON 中记录版本、输入哈希、方法、耗时、峰索引、优化器收敛状态、梯度、虚频数及位移、目标键长变化，失败原因原样保留。模式正负位移文件用于人工检查，不自动给“已验证 TS”标签。

本机限制直接针对本次看到的默认高精度选择和 wrapper 临时文件行为：显式固定 xTB 可执行程序；运行前验证本机可用；阻止网络和远程程序启动；不读取 ag 远程配置；不允许传入任意电子结构后端或执行命令；输出目录必须新建。缺 xTB、缺峰或非收敛时返回问题，不自动切换 Gaussian、联网下载模型或重跑。安装作为独立的显式步骤。

### 6.2 QST2 / QST3 校验：1.5–2 日

现有 `ag.gaussian_input.validate()` 只接受 route、title、单个电荷/多重度和 Cartesian 坐标；多于三个段落直接拒绝，Link0 只允许 nprocshared/mem/chk。因此**现在不能通过 QST2/QST3，也不能通过 oldchk**。需要改确定性解析器，不能只删掉“多余段落”检查。

建议第一版仅支持单一电子态的 Cartesian QST：识别 Opt 参数中 QST2 或 QST3，分别要求 2 或 3 组“标题 + 电荷/多重度 + 坐标”，顺序为反应物、产物、TS 初猜；其余任务仍沿用单结构规则。不得同时写 `TS` 与 QST2/QST3，不接受同时 QST2 和 QST3。官方 [GaussView 文档](https://gaussian.com/wp-content/uploads/dl/gv6.pdf)也强调这类任务的原子编号一致性。

校验所有结构的原子数、逐行元素、电荷/多重度、坐标有限性；同元素原子交换必须借助显式 atom map 和人审阅，元素序列相同只是必要条件。防止漏读第二结构、映射错误、额外输入节及文件指令越界。继续拒绝未支持的 Link1、includes、External、任意尾部节和扩展坐标语法。扩展后返回多结构摘要并哈希**整个输入文件**，确认摘要必须展示全部结构。测试覆盖缺块/多块、错序、不同电子态、原子映射、非有限数及旧单结构回归。

不在本次推荐中强行加入 Gen/ECP、ModRedundant、混合自旋或 QST2/QST3 的全部高级变体；需要时单列真实使用案例。

### 6.3 跨 Attempt chk 复制：2–3 日

当前 `ag.remote` 没有父文件复制白名单；必须新增专用操作，**不能让 LLM 拼接通用远程复制命令**。建议：

1. 本地准备新 Attempt，记录父 Attempt ID、关系、源 chk 的普通文件名、源文件 SHA-256/大小、新目录内目标文件名。源引用不能是用户任意路径；从两个 manifest 和配置根解析，拒绝越界及符号链接。
2. 只允许已确认完成、不会继续写入的父结果。确认前只读取得父文件哈希并进入确认摘要；这些引用信息纳入确认 bundle 的固定材料。来源变化需要新 Attempt 与新确认，不能静默替换。
3. 人在 Mac 点击后，保留一次性声明与核数核验，创建全新目标目录。专用复制助手以独占创建目标文件的语义写入；目标已存在立即失败，禁止截断、覆盖、清理或移动源文件。普通 `cp -n` 跳过已有目标的行为不能被当作复制成功；若采用平台复制命令，仍需验证退出语义与目标字节。
4. 防符号链接检查需要覆盖目录链和文件打开时刻；T13 应选择可审阅的固定实现，测试目标抢占及链接替换，而不把“先 test 再 cp”当作原子保证。复制后对目标和源复核 SHA-256，与确认值一致才能 qsub。失败留下证据；传输结果不确定时只读核对，不再提交。
5. Gaussian 使用新目录内的 `parent.chk` 作为 `%oldchk`，新 `%chk` 使用不同普通文件名；父文件不会成为 Gaussian 写目标。oldchk 仅在已声明且已校验的父附件存在时允许，不允许任意文件引用。

上述新增检查防的是父 chk 在确认后改变、同名覆盖、目录穿越及复用错误波函数/力常数。不是新增治理体系；继续使用 manifest 的 parents/relation 与现有确认流程。

首版 IRC 可显式提供 TS Cartesian 几何、电荷/多重度，结合经审阅的 chk 力常数读取方案，避免为省坐标而一次性放开所有 `Geom=AllCheck` 输入变体。若确需无坐标输入，另建严格语法分支，从已验证父事实构建确认摘要，不能绕过结构展示。[ASE 官方 Gaussian/IRC 示例](https://ase.gitlab.io/ase/ase/calculators/gaussian.html)展示分离 oldchk/new chk 及 forward/reverse 的 RCFC 用法；正式模板仍应按实际 Gaussian 版本验证。

### 6.4 IRC 两端比对：1.5–2.5 日

从已审阅的单虚频 TS 出发，forward/reverse 用不同新 Attempt。`ag facts` 给出两方向的完成情况、步数、末端几何及能量；到达步数上限或仅“正常终止”不等于到达目标极小值。按卡片决定是否需要在各端点继续 Opt+Freq，新增计算仍需人确认。

优先复用现有 `ag.geometry` 的有限数 XYZ 读取、图/立体身份和 RMSD 工具，写小的本地端点比较函数即可：核对元素、电子态、显式映射；分别将两端与目标反应物/产物比较，并允许 forward/reverse 对调；比较连通图、成断键、质子归属、立体化学和必要的几何差异。碎片应按映射匹配，不能因平移/转动或片段分离导致的大 RMSD 误判，也不能仅凭小 RMSD 宣称同一化学物种。

输出“匹配 / 不匹配 / 无法确定”及依据。XYZ 推键在延长键、离子对、过渡结构中可能歧义，应报告距离和候选连接，交给 LLM 与人判断，不能自动修改预期产物。只有两个方向完成、端点被识别、目标连接和模式都审阅后，才可写“IRC 验证”。

### 6.5 实施顺序与总量

| 项目 | 工作量 | 优先级 |
|---|---:|---|
| TS/Freq、IRC 卡片及确认摘要要求 | 0.5–1 日 | 先实现人工初猜闭环 |
| QST2/QST3 多结构解析与回归 | 1.5–2 日 | 直接解决当前输入限制 |
| 父 chk 复制、确认哈希、oldchk 受限支持 | 2–3 日 | IRC 复用的安全前提 |
| 双向 IRC 结果提取与端点比较 | 1.5–2.5 日 | 解决科学验收证据缺口 |
| 可选 autodE 本机薄适配 | 2–3 日 | 实验性，不能阻塞人工初猜路线 |
| ARCHE 思路映射及条款记录 | 0.5 日 | 卡片内完成，不迁移控制器 |
| 合计 | **8–12 日** | 不含真实集群试验等待与人工审阅 |

初猜适配若要求证明对多种 Michael 机理稳定产出 TS，工作量无法由这两个负例估定，应作为后续科学方法调研，而不是把 2–3 日工程封装估时当作科学成功承诺。

## 7. 验证与交付

- 隔离环境安装、autodE 导入、xTB 版本核对、依赖一致性检查通过。
- 两例本机计算进程均正常结束；原始 xTB 输出未见 `ERROR` 标记。科学状态分别为无峰和多虚频候选，未重试搜索、未使用 Gaussian、未联网计算。
- `ag` 单元测试：**434 passed, 2 skipped，56.26 s**。跳过项为显式 opt-in 私有日志与仅 Linux 的远程命令方言测试；没有运行真实远程验证。
- 针对现有解析器的本机只读调用确认：QST2/QST3 均被额外输入节检查拒绝；oldchk 被 Link0 白名单拒绝，与源码审阅一致。
- 本次没有添加镜像实现的测试，也没有改业务代码。提交只包含本文；原始运行输出、环境、下载源码及 PDF 留在本机，不提交含机器信息的日志。


## 附录：可复查的 NEB 输入

以下为两例实际进入 NEB 的端点，原子顺序与候选一致。注释已简化，不含运行环境信息。每个 XYZ 仅保留原程序导出的五位小数；正文 Hessian 使用了内存中的更高精度坐标，因此从文本重跑允许数值末位及优化轨迹变化，不能承诺相同文件哈希。此处供重跑 NEB/Hessian，不包含端点准备阶段计时。

### sn2_reactant.xyz

原文件 SHA-256：`d0b2de6d7f39685a92fb7788d015b09da1d6fdec6e9bd09a800f93dce0358b3c`

```xyz
6
sn2 reactant; charge=-1 mult=1
C     -0.00587    0.00000    0.00000
Cl     1.79369   -0.00002    0.00000
F     -3.10510   -0.00000    0.00000
H     -0.35423    1.02543   -0.00000
H     -0.35425   -0.51271    0.88806
H     -0.35425   -0.51271   -0.88806
```

### sn2_product.xyz

原文件 SHA-256：`eb4f4fe034b0170be8321cc600512f7417ee4f365edfe5975bf4a536c42163e5`

```xyz
6
sn2 product; charge=-1 mult=1
C      0.00822    0.00000   -0.00000
Cl     3.30795   -0.00000    0.00000
F     -1.39048   -0.00004    0.00000
H      0.35140    1.03014   -0.00000
H      0.35145   -0.51505    0.89212
H      0.35145   -0.51505   -0.89212
```

### michael_reactant.xyz

原文件 SHA-256：`ddee94c48d4feb26bf06d2bf16419fa69e43f4be40f024e97cbe160f4e142895`

```xyz
12
michael reactant; charge=0 mult=1
C     -1.09324    0.27558   -0.46776
C      0.20281    0.49746   -0.25640
C      1.08176   -0.48525    0.38029
O      0.76176   -1.57959    0.77669
N     -2.12874   -2.56511    0.58035
H     -1.56248   -0.65344   -0.17197
H     -1.71910    1.01518   -0.93961
H      0.67444    1.42624   -0.54887
H      2.13040   -0.14287    0.48220
H     -2.63317   -2.75900    1.43790
H     -2.26031   -3.36181   -0.03277
H     -1.13943   -2.52691    0.81380
```

### michael_product.xyz

原文件 SHA-256：`44ef099a44b0203ee6d5a817871ca56fcfbb2bd6a4e7473305d78d1849b1b55d`

```xyz
12
michael product; charge=0 mult=1
C     -1.17253   -0.07835    0.27824
C      0.11918   -0.74070   -0.18489
C      1.33961    0.06240    0.14637
O      1.35415    1.12352    0.70194
N     -2.31502   -1.01612    0.04025
H     -1.12269    0.10485    1.35242
H     -1.30002    0.88583   -0.23141
H      0.10609   -0.90565   -1.26626
H      2.28181   -0.42341   -0.18072
H     -2.45212   -1.12990   -0.95899
H     -3.16285   -0.61262    0.42215
H      0.21426   -1.72403    0.28237
```

### 复查调用

将上述对应两个 XYZ 保存为 `reactant.xyz` 和 `product.xyz`，在全新的本机工作目录运行第 3.1 节代码前构造：

```python
r = ade.Molecule("reactant.xyz", charge=charge, mult=1)
p = ade.Molecule("product.xyz", charge=charge, mult=1)
assert r.atomic_symbols == p.atomic_symbols
```

其中 SN2 的 `charge=-1`，Michael 的 `charge=0`；设置经过核对的本机 `Config.XTB.path`，在与本次相同的断网执行限制下运行。结果读取 `guess.frequencies` 和 `guess.normal_mode(k)`；逐个负频模式以原几何加减 `0.3 * normal_mode(k)` 导出正负位移。数值方向判断使用第 4.2 节公式。不要调用整条反应 profile，不把缺峰替换为其他结构，不复用旧计算目录以免命中缓存。
