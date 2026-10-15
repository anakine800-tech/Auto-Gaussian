# T41：ORCA 接入 ag 的调研

调研日期与全部外部链接访问日期：**2026-10-15（北京时间）**。
代码基线：`a820049e2f1581370f09639fc16d14e611a4dea9`。本文是立项建议；没有安装或运行 ORCA、连接集群、改变方法表或新增检查。
文中的仓库路径均为公开仓库相对路径；不记录部署位置、作业身份或研究数据。

## 1. 建议与证据边界

- 优先立项 **ORCA 单点与 DLPNO 高层级抽查**，再评估 r2SCAN-3c 优化/频率，NEB-TS 最后单独立项。理由是高层级单点直接回应任务单所述卡片审阅 S5 的需求，且比完整反应搜索链更容易界定输出与验收。[任务单](../redesign-tasks/T41-research-orca-and-slimming.md)、[交接文档“卡片修订”](../handoff-v4.md)、[MDCI 官方手册](https://www.faccts.de/docs/orca/6.1/manual/contents/modelchemistries/mdci.html)。S5 原始评论未随任务单提供，未把转述冒充已核对的评论原文。
- 截至访问日，官方公开发布页与手册共同指向 **6.1.1**；建议验证目标锁定该修订版，而不是笼统的“ORCA 6”。[发布公告](https://www.faccts.de/orca-6-1-1/)、[6.1.1 前言](https://www.faccts.de/docs/orca/6.1/manual/contents/preface/foreword.html)。
- 学术/个人用途有免费许可入口，但**课题组具体部署和 SCNet 托管许可尚未确认**；这不阻塞文档交付，阻塞后续安装决定。[官方产品页](https://www.faccts.de/orca/)、[安装教程](https://www.faccts.de/docs/orca/6.1/tutorials/first_steps/install.html)。
- 接入不止增加模板：当前 `facts`、单点热修正配对和 `profile` 都有 Gaussian 专用假设。必须分别解决能量类型、输入几何配对、方法与版本比较，才能把 ORCA 单点用于现有自由能曲线。来源：[`facts.py`](../../ag/src/ag/facts.py)、[`thermo.py`](../../ag/src/ag/thermo.py)、[`_profile_sources.py`](../../ag/src/ag/_profile_sources.py)。
- 80–100 原子的耗时不能只按原子数承诺；公开 90 原子例子达到数百小时。当前机器上的峰值内存、磁盘需求和 walltime **未知**，见第 6 节。工程实现、平台可用、科学可接受是三件不同的事。

## 2. 许可、下载与版本

| 问题 | 已证实内容 | 未知与需负责人确认项 |
| --- | --- | --- |
| 学术许可条件 | 官方称学术及个人用途免费，商业用途另行许可；免费不等于开源、可再分发或所有科研合作均适用 | 本次未取得登录下载时的完整现行 EULA，学术身份、合作项目及第三方服务边界须按实际协议核对；不能用旧版转载 EULA 作批准依据 |
| 注册方式 | ORCA Forum 或 FACCTs 下载区创建账户并同意相应许可；论坛登录后进入 Filebase | 注册应由负责人完成；本次没有注册、接受条款或下载二进制 |
| 课题组集群 | 官方支持 Linux 与单节点/多节点 MPI，技术上存在集群部署路线 | 哪些课题组成员可用、管理员安装/备份权限、共享安装目录访问范围未知；“技术上支持”不等于本课题组已获授权 |
| SCNet | 官方资料没有给出针对本平台的部署许可结论 | 自带软件、平台代安装、商业云托管、用户间共享分别是否允许，以及平台现有 ORCA 版本、MPI 与存储政策，均未知；负责人按当前 EULA 与平台协议确认，不自行联系官方或平台 |

本表来源：[FACCTs ORCA](https://www.faccts.de/orca/)、[注册与下载教程](https://www.faccts.de/docs/orca/6.1/tutorials/first_steps/install.html)、[安装手册](https://www.faccts.de/docs/orca/6.1/manual/contents/quickstartguide/installation.html)、[并行手册](https://www.faccts.de/docs/orca/6.1/manual/contents/essentialelements/parallel.html)，均访问于上述日期。产品主页的公开概述不能替代 EULA；没有推断 SCNet 因收费就一定禁止，或因学术目的就一定允许。

6.1.1 是修复版本，官方说明修正了 6.1 的错误与不一致；[详细更新记录](https://www.faccts.de/docs/orca/6.1/manual/contents/appendix/detailedchangelog.html) 是变更追踪来源。**不同版本数值是否一致须验证，不能假设补丁升级只影响界面。** 同一比较层级建议记录完整程序修订版、计算方法、轨道/辅助基组、冻结核、PNO/三激发近似、积分网格、SCF 与溶剂设置；跨版本先对小体系回归。
这是参照现有 `profile` 修订版一致检查的接入建议，未增加现行规则。当前 `_profile_sources.load_species` 要求物种及 SPC 的程序版本一致，且 `route_protocol` 解析 Gaussian route；将来应分别比较几何/频率层与单点层的版本组合，不能简单撤掉原检查，也不能强迫 Gaussian 与 ORCA 使用同一版本字符串。

## 3. 输入、模板、输出与临时文件

### 3.1 输入骨架与参数范围建议

ORCA 输入包含 `!` 关键词行、`%... end` 设置块和几何块。下面是**公开水分子的语法示例**，仅说明单点输入形态，不是已批准的方法或待提交输入：

```text
! HF def2-SVP TightSCF SP
%pal nprocs 1 end
%maxcore 1000
* xyz 0 1
O  0.0000  0.0000  0.0626
H -0.7920  0.0000 -0.4973
H  0.7920  0.0000 -0.4973
*
```

几何头依次给出格式、电荷、多重度；`%pal nprocs` 是进程数，`%maxcore` 是**每进程 MB 数**，不是整个作业内存硬上限。参考：[输入手册 §2.1](https://www.faccts.de/docs/orca/6.1/manual/contents/essentialelements/input.html)、[并行手册 §2.5](https://www.faccts.de/docs/orca/6.1/manual/contents/essentialelements/parallel.html)、[水示例](https://www.faccts.de/docs/orca/6.1/tutorials/first_steps/install.html)。

建议首期只接单节点、显式 Cartesian 几何、主族闭壳层单点。未来任务要将 nprocs/内存与 manifest 资源绑定，白名单限已审阅的方法、基组、PNO 档、溶剂设置；拒绝任意 `%base`、外部程序、任意文件路径和未支持的多步语法。所防事故分别是超分配内存/进程、写出 Attempt、以及暗中增加计算步骤；本文不实现这些检查。ORCA 的外部优化器可调用外部程序，不能因输入是文本就全部放行。[输入手册](https://www.faccts.de/docs/orca/6.1/manual/contents/essentialelements/input.html)、[外部优化器](https://www.faccts.de/docs/orca/6.1/manual/contents/structurereactivity/optimizations.html)。

### 3.2 与现有模板的对应关系

| 接入点 | 当前实现 | 后续 ORCA 工作 |
| --- | --- | --- |
| 模板登记 | `render.declaration`、CLI template choices 只接受三种程序 | 新增受审阅程序体和 TOML，同时接入 render、prepare、输入复核、配置与 doctor；不能只新增文件 |
| 调度与启动 | `_guard.sh` 提供私有 scratch、noclobber、一次运行与退出回执；Slurm 当前使用单 task + 多 CPU | ORCA 驱动由固定配置的完整可执行路径启动一次，它再启动 MPI 模块；官方禁止用 mpirun 启动驱动。单节点 MPI 的调度分配/绑定需验证，不能未经检查照抄现有线程型资源头 |
| 正常标记 | TOML completion；状态与 facts 分别读声明输出 | 官方例子用 stdout 重定向生成主输出，再在其中找 `ORCA TERMINATED NORMALLY`，因此主输出应排第一；stderr 与调度器日志也须保留 |
| 输出声明 | `remote.output_names` 仅接受普通文件名，Slurm 自动转换调度器输出并补 stderr | 首期可固定 `orca.out`、`orca.err`、`job.pbs.out`；Slurm 对应 stdout/stderr；按任务另加明确的 `.gbw`、`.xyz`、`.hess` 等文件名，不能按 glob 全量下载。哪些文件必需、哪些只在 Opt/Freq 生成须分别验证 |
| 完成判定 | 程序回执和科学 facts 分开 | 同时检查退出码、主输出标记、调度器异常、SCF/CC/优化各自收敛；保留 error/incomplete，不将正常退出等同科学通过 |

仓库依据：[开发手册“程序模板”](../DEVELOPING.md)、[`render.py`](../../ag/src/ag/render.py)、[`_guard.sh`](../../ag/templates/_guard.sh)、[`remote.py`](../../ag/src/ag/remote.py)、[`facts.py`](../../ag/src/ag/facts.py) 与 [`ag/templates/`](../../ag/templates/) 中的三组声明/程序体。
外部依据：[并行启动](https://www.faccts.de/docs/orca/6.1/manual/contents/essentialelements/parallel.html)、[输出重定向与正常标记](https://www.faccts.de/docs/orca/6.1/tutorials/first_steps/install.html)、[常见故障](https://www.faccts.de/docs/orca/6.1/manual/contents/quickstartguide/troubleshooting.html)。stdout 的判断来自官方教程，**未在目标版本或调度器实测**；未来 smoke 要分开捕获两个流。对应已发生事故见 [LESSONS“xTB 正常结束标记在调度器输出里”](../LESSONS.md)。

### 3.3 scratch 的实际差异

ORCA 以运行目录组织基于 basename 的中间文件；官方推荐每次新建本地 scratch，并给出复制输入、执行、复制结果、删除 scratch 的包装示例。[并行手册 §2.5.2](https://www.faccts.de/docs/orca/6.1/manual/contents/essentialelements/parallel.html)。**官方清理示例不能搬进 ag**：仓库禁止远程删除/覆盖，且 `GAUSS_SCRDIR` 不能视为 ORCA 通用 scratch 开关。

建议首期在新的 Attempt 内运行，临时文件也留在该隔离范围；MPI 临时目录与程序文件去向须在后续验证中确认。若工作目录本身是共享存储，其 I/O 性能代价未知。若改为在 Attempt 的 scratch 子目录中执行，就必须同步设计父目录回执与声明输出的独占发布，现有 `output_names` 不支持任意嵌套路径，不能随意 copy 覆盖补洞。

ORCA 模块自身会创建并可能删除临时文件，官方故障说明明确讨论这一行为。内部临时文件生命周期与仓库严格“不覆盖、不删除”的兼容性**尚未证明**；后续模板审阅需明确可支持的行为，不能自行宣布硬内核豁免。无论如何不得清理其他 Attempt、共享目录或安装目录。[故障手册“Disk Full”](https://www.faccts.de/docs/orca/6.1/manual/contents/quickstartguide/troubleshooting.html)、[AGENTS 第 3 节](../../AGENTS.md)。

## 4. 多步作业与一次提交

ORCA 存在 `$new_job`，但 6.1 手册已将其标为 deprecated，并警告继承设置可能导致异常结果；官方推荐更强的 Compound，支持 `New_Step`、变量、循环与步骤间几何继承。[多步作业 §2.1.5](https://www.faccts.de/docs/orca/6.1/manual/contents/essentialelements/input.html#jobs-with-multiple-steps)、[Compound §8.2](https://www.faccts.de/docs/orca/6.1/manual/contents/workflowsautomatization/compound.html)。

一次调度器提交可以含多个内部计算，所以“只提交一次”本身并没有禁止多步。但任意 Compound 会使固定模板失去可审阅边界，且混合输出有跨步骤借用能量/频率的风险。**首期建议不开放 `$new_job` 和任意 Compound**：优化、频率、高层级单点用明确的新 Attempt 和现有 parents/relation 表达；不自动继承 `.gbw`，父 chk 专用复制也不自动适用于 GBW。
若以后有明确需求，只新增步骤数和参数固定的受审阅模板；输入摘要列全步骤，facts 按步骤归属记录来源，失败提出新 Attempt 而非重启原 Attempt。以上是未来任务取舍，不是本 PR 新建工作流框架。[AGENTS](../../AGENTS.md)、[开发手册](../DEVELOPING.md)。

## 5. cclib 支持与 ag 的缺口

本仓库声明 `cclib~=1.8.1`，本次只读核查的安装版为 1.8.1。官方支持列表列 ORCA 4.1、4.2、5.0，**不能据此保证 6.1.1**。[cclib 支持范围](https://cclib.github.io/)、[数据属性](https://cclib.github.io/data.html)、[属性说明](https://cclib.github.io/data_notes.html)。下表同时依据本地 1.8.1 `orcaparser.py` 源码，对应公开 [v1.8.1 源码](https://github.com/cclib/cclib/blob/v1.8.1/cclib/parser/orcaparser.py)；公开源码页面本次抓取失败，源码结论来自安装包读取，未假称网页已读成功。

| 所需事实 | 1.8.1 中已有能力 | 仍需做的验证/补足 |
| --- | --- | --- |
| 能量与几何 | 解析 `scfenergies`、`atomcoords`；SCF 与 CC 能量数组使用 eV，几何 Å | ag facts 用 Hartree，需显式换算；源码不直接以 `FINAL SINGLE POINT ENERGY` 作为通用能量读取，部分色散另行加回；不能把所有方法最终总能量塞进 `scf` |
| 频率与振动 | 有 `vibfreqs`、`vibdisps`，并处理非振动零模式 | 6.1.1 布局、模式完整性、单原子/线性分子与缺失模式仍需小分子日志验证；无频率不能报告零虚频 |
| 收敛与结束 | 有 SCF/几何收敛相关属性、`optdone`；读到 `TOTAL RUN TIME:` 会设置 success | success 不是几何/CC 收敛证明。官方明确指出优化未收敛也可能正常结束，需独立核对优化收敛消息与异常尾部 |
| CC 与 DLPNO | `COUPLED CLUSTER ENERGY` 的 `E(TOT)` 写入 `ccenergies`，`E(CCSD(T))` 覆盖末项；元数据记作 CCSD/CCSD(T) | 未发现独立识别 DLPNO、PNO 档或 `(T1)` 专用分支，不能保证所有 DLPNO 输出布局可读；必须辨别参考能、相关能、含 triples 的总能和 `(T)`/`(T1)` |
| 程序/方法来源 | 可以读程序版本和部分关键词 | 输出应保留完整修订版、单位、原文行位置与方法层，缺字段明确未知；为防错拿 SCF 能当 CC 总能，能量映射须逐例与原文对照 |

优化判据来源：[ORCA 几何优化手册](https://www.faccts.de/docs/orca/6.1/manual/contents/structurereactivity/optimizations.html)；CC 近似命名来源：[MDCI 手册](https://www.faccts.de/docs/orca/6.1/manual/contents/modelchemistries/mdci.html)。

ag 当前还有三处独立缺口：`parse_facts` 无 ORCA 分支；`thermo._pairing_evidence` 强制 Gaussian SPC 输入并检查输入哈希/原子顺序/几何；`_profile_sources` 解析 Gaussian route 且要求程序修订版一致。因此“cclib 能读文件”不等于“ag 能使用 ORCA 热修正”。优先保留 Gaussian 频率热修正，再明确实现 ORCA 总电子能替换：`G = E_ORCA + (G_qRRHO,Gaussian − E_Gaussian)`，同一结构、温度、溶剂与标准态口径均经审阅。当前命令**不能直接执行这条跨程序路线**；也不能通过篡改 program 或版本元数据绕过。来源：上述仓库模块和 [thermo 卡片](../../skills-next/auto-g16-recipes/cards/thermo.md)。

## 6. DLPNO-CCSD(T)：输入与资源量级

### 6.1 待审阅的方法建议

关键能垒抽查建议以 `DLPNO-CCSD(T1) TightPNO TightSCF` 作为候选，主族中性体系的基组起点可考虑 `def2-TZVPP def2-TZVPP/C`；使用 RIJCOSX 时另需合适的 J 辅助基组（如 `def2/J`）。`/C` 服务相关部分，不能用 `/J` 顶替。也可选择成套 `cc-pVTZ cc-pVTZ/C`；阴离子、弱相互作用与基组收敛应另审阅弥散及更大基组，不能仅因计算昂贵就认定准确。依据：[MDCI](https://www.faccts.de/docs/orca/6.1/manual/contents/modelchemistries/mdci.html)、[基组与辅助基组](https://www.faccts.de/docs/orca/6.1/manual/contents/essentialelements/basisset.html)。

这里是候选关键词组合，不是新兜底方法。官方优先推荐用 LoosePNO/NormalPNO/TightPNO 档控制精度；TightPNO 的主要 PNO 截断为 `1e-7`，NormalPNO 为 `3.33e-7`。ORCA 输入中的 `(T)` 指半正则近似（文献也称 T0），`(T1)` 指迭代 triples；二者不可混称。对关键 TS 与完整参考物种、竞争通道做相同设置的抽查；PNO、基组和单参考适用性均可能影响结论。不能把换一种 DFT 泛函等同于高层级基准，也不能把单个 TS 的更低能量当成能垒校正。[官方 MDCI §3.10.5](https://www.faccts.de/docs/orca/6.1/manual/contents/modelchemistries/mdci.html)、[现有方法敏感性口径](../../skills-next/auto-g16-study/references/acceptance-methods.md)。

### 6.2 可引用的量级与不能外推的数字

| 证据 | 设置与记录 | 对 80–100 原子预算的含义 |
| --- | --- | --- |
| 原始研究 §7，90 原子 Michael-addition TS | 3155 AO、aug-cc-pVTZ，6 核，NormalPNO 的迭代 triples DLPNO-CCSD(T) 需 **19.6 天（约 470 h）**；该论文将半正则近似另记为 (T0) | 属于目标尺寸的公开例子，说明数百小时/约数周是可能量级；不是本项目分子，也不是 ORCA 6.1.1 当前机器基准 |
| 同一体系、同一硬件、不同 PNO 档 | LoosePNO 为 **21 h** | 同一原子数也会相差一个数量级；不能为了套用 21 h 就将关键抽查降成 LoosePNO，更不能按核数线性外推 |
| 内存与硬件 | 原文 §4 使用 128 GB 内存机器、6 核 Xeon E5-1650 v2；Table 6 中 90 原子 aTZ/Normal 的 **7（26）GB** 是 **LNO-CCSD(T)** 的最小（最佳）内存 | 128 GB 是测试机器容量，不是 ORCA 峰值；7/26 GB 也不是 DLPNO 内存。目标体系峰值内存、磁盘量均未知 |
| ORCA 官方资源建议 | `%maxcore` 是每进程工作内存；需给总内存留余量，手册对 CC 提到至少约 8 GB 的每进程设置建议；并行手册建议 CC 先看 8–16 进程的收益 | 仅可用于选择试验资源，不是 80–100 原子一定装得下或线性加速的保证 |

基准来源：Nagy 与 Kállay，*J. Chem. Theory Comput.* 2019，DOI [10.1021/acs.jctc.9b00511](https://doi.org/10.1021/acs.jctc.9b00511)，[作者存档全文](https://real.mtak.hu/99695/1/LNO_CCSDpT_benchmark.pdf)，§4 与 §7、Table 6（存档正文页 17–18、52–55）。原文使用 ORCA 4.0/4.1，不能当作新版本测速。本次直接核对原文中的运行时间及内存列，未复跑；具体 ORCA 修订号/构建与目标平台性能仍未知。内存与并行建议来源：[输入 §2.1.3](https://www.faccts.de/docs/orca/6.1/manual/contents/essentialelements/input.html)、[并行 §2.5](https://www.faccts.de/docs/orca/6.1/manual/contents/essentialelements/parallel.html)。

**规划推算（非测量）：**若采用每进程 8000 MB，并将各进程 MaxCore 总和控制在作业内存的 75% 左右，8 进程需要至少约 85.3 GB，16 进程至少约 170.7 GB。以 120 GB 为例，8 进程的 64 GB 工作内存较有余量；22 或 44 进程不能仍各配 8 GB。现有 general/complex 固定核数未必适合内存密集的 CC，需要单独评估“少核高内存”的资源档，不能悄悄改变现有档位。没有测量依据支持统一的 24 h/48 h walltime；先经授权做代表性规模与磁盘测量，再报全组总核时。

## 7. 其他功能的价值

| 功能 | 官方依据 | 对本项目的建议与限制 |
| --- | --- | --- |
| r2SCAN-3c | [3c 手册 §3.6.3](https://www.faccts.de/docs/orca/6.1/manual/contents/modelchemistries/3cmethods.html)：r2SCAN、def2-mTZVPP、D4、gCP 的成套组合 | 可评估为大构象集合几何优化/重排的中间层；不可任换基组或再叠一个 D4 后仍称同一 3c 方法。需与既有 DFT 几何/能差比较，方法表修改由负责人决定 |
| NEB-TS | [官方教程](https://www.faccts.de/docs/orca/6.1/tutorials/react/nebts.html)：从反应物和产物几何搜索路径并优化 TS | 可能减少人工 TS 初猜负担；需要端点原子映射、相同组成/电荷/多重度及图像资源预算。NEB/优化成功后仍需恰一虚频、振动方向审阅和双向 IRC 端点识别，不能声称自动验证机理 |

NEB-TS 的多图像并发、输出声明和步骤解析成本明显高于单点；建议在单点/频率证据稳定后另立任务。上述价值判断是针对 ag 的推论，尚无本项目实测。[AGENTS 科学规则](../../AGENTS.md)、[既有 TS 工具调研](ts-tooling.md)。

## 8. 工作量拆分与验收建议

下列 A–E 只是未来任务建议，不预占 T 编号，不创建新抽象/合同。估算为一名熟悉 ag 的开发者有效工作日，不含许可沟通、排队和计算等待。

| 建议任务 | 改动与完成证据 | 估计 |
| --- | --- | --- |
| A：ORCA 单点模板与参数 | 受审阅模板/TOML、输入子集校验、CLI/prepare 复核、配置/doctor、PBS/Slurm 单节点 MPI 资源、明确输出与 scratch；假程序验证成功/非零退出、独占输出/回执、旧 PBS bundle 字节不变；不新增任意 shell 入口 | 3–5 日 |
| B：ORCA facts | 6.1.1 小分子脱敏日志对照；SCF、CCSD、(T)/(T1)、频率/几何/收敛、版本与原文位置；缺失/截断/错误流不能借用旧能量；证明 eV→Hartree 与总能类型正确 | 3–5 日 |
| C：跨程序 SPC 与 profile | 在现有模块中接入 ORCA 输入哈希/几何/状态配对、CC 总能选择、各方法层协议与修订版比较；Gaussian 热修正保持原口径；只读分析不得改已有 facts；混方法/错配/缺版本应明确失败 | 3–5 日 |
| D：单点抽查与 3c 卡片 | 科学适用范围、依据、完整输入、PNO/基组敏感性、热修正和收敛审阅；方法表由负责人确认；Opt/Freq 模板/解析若未实现则卡片不能宣称可执行；NEB-TS 暂不包含 | 1–2 日 |
| E：真实环境验证 | 负责人确认许可和部署后，独立授权小分子串行/并行 SP、CC 单点，再验证 Opt/Freq；逐个平台核对 MPI、scratch、双流日志、退出回执、哈希、异常处理和实际资源；规模测试单独批准 | 1–2 日操作与整理，计算等待未知 |

单点至跨程序自由能可用预计 **11–19 个有效工作日**（A–E 合计），前提是 cclib 缺口可局部处理、安装与 I/O 边界获得确认；若 6.1.1 输出差异广泛，需重估解析工期。r2SCAN-3c 完整 Opt/Freq 若超出上述输入子集需补任务；NEB-TS 另估约 4–7 日开发，另加真实路径验证，不能混进首期承诺。拆分依据是当前模块实际耦合，参照 [DEVELOPING“怎么加功能”](../DEVELOPING.md)。

本次实际阻塞：**环境**——现行部署许可、MPI/临时文件行为与资源量未知；**解析**——6.1.1/DLPNO 与跨程序热修正尚未实现/验证；**科学审阅**——具体方法、阈值、基组和关键反应集合待负责人决定。它们是后续接入的待办，不影响 T41 文档交付。T41 不需要真实环境验证，后续仍遵守每 Attempt 一次提交、Mac 人工确认、UNKNOWN 只读核对及不覆盖不删除。
