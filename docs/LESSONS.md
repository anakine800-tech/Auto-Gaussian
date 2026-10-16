# 开发与现场经验

每条最多五行：现象、原因、修复 PR、以后的写法。新经验追加这里，每周清理时合并重复条目。
只保留可复用的结论和公开 PR 链接；现场原始记录留在仓库外。工程修复不等于科学验收。
以下区分现场故障、审阅发现和风险预防；没有查到根因或专门修复 PR 时明确写出，不补造结论。

## walltime 强杀与不完整取回
现象：PBS 强杀无退出回执，Slurm TIMEOUT 缺声明输出，原 fetch 无法取回；目录权限不足还会被 `test ! -e` 误报缺失（本地合成复现）。
原因：完整取回要求与异常结束证据不同；“未看到文件”不等于确认不存在。
修复：T47 显式 `fetch --incomplete`，严格只读存在性检查、结束证据和哈希绑定记录；真实强杀与 chk 可读性验证仍待执行，不冒充已通过。
以后：先 status 核对结束证据，再不完整取回和 facts；由人决定新 Attempt 接续，不能自动重提或把部分结果用于热化学/能量剖面。

## PBS 残留作业
现象：程序结束，PBS 仍显示 R，旧 status 无法让结果进入可取回状态。
原因：调度器记录寿命与程序寿命不同，单靠 R/C 判断不够。
修复：[#212](https://github.com/anakine800-tech/Auto-Gaussian/pull/212) 加开始/退出回执、输出观察及残留标记；[#214](https://github.com/anakine800-tech/Auto-Gaussian/pull/214) 补取回提示。
以后：优先核对绑定的退出回执；残留不自动清理，只能人确认后 cancel 确切作业。

## Unknown Job Id 与两次观察
现象：Torque 的 `Unknown Job Id Error` / 返回码 153 被旧解析器拒绝；第一次观察还被误报 interrupted。
原因：真实错误方言未覆盖，且一次静态输出不能证明程序已经结束。
修复：[#213](https://github.com/anakine800-tech/Auto-Gaussian/pull/213) 识别该方言；[#214](https://github.com/anakine800-tech/Auto-Gaussian/pull/214) 增加 awaiting_second_observation。
以后：旧无回执作业需完成标记和至少相隔 60 秒的两次稳定观察，读标记后再 stat；PBS 仍有 R/C 时另查会话进程，SSH 255 不算作业消失。

## freq 段报几何未优化
现象：优化收敛且虚频为零，频率段却出现 `Non-Optimized Parameters` 或收敛项 NO。
原因：只看优化阶段的表，会把频率阶段几何判据遗漏。
修复：[#214](https://github.com/anakine800-tech/Auto-Gaussian/pull/214) 按段解析 freq_step_converged，并补 Opt/Freq 与诊断卡片。
以后：独立检查频率段四项阈值，缺失记未知；从最终几何提出同方法的新优化 Attempt，不能沿用未通过判据的热修正。

## SSH 255 与只读重试
现象：连接中断或超时使查询失败，提交响应也可能丢失。
原因：传输失败不能说明调度器未接收请求；重发写操作可能重复计算。
修复：[#209](https://github.com/anakine800-tech/Auto-Gaussian/pull/209) 限只读传输等 15 秒重试一次；[#212](https://github.com/anakine800-tech/Auto-Gaussian/pull/212) 脱敏并保留首次失败证据。
以后：submit/cancel 及其内部读取均不自动重试；提交结果未知只读核对，不把重试成功抹成“从未出错”。

## CREST 返回 0，却没有构象集合
现象：T20 报告 CREST 退出码为 0，但未生成可审阅的构象集合。
原因：返回码只证明进程报告成功；本次所查已合并 PR 未给出该现场缺失集合的具体根因，不能猜测参数或版本原因。
修复依据：[#208](https://github.com/anakine800-tech/Auto-Gaussian/pull/208) 的 crest-screen 已要求正常终止、非零 n_conformers 和能量/构象数量对应；未查到该事故的专门修复 PR。
以后：同时核对声明输出、完整 XYZ 帧和能量数量；缺集合就报告科学结果不完整，不因 sacct COMPLETED 或返回码 0 接受，也不自动重跑。

## squeue 补空格与作业名截断
现象：用户名带填充空格时解析失败，长作业名被截断后无法关联 Attempt。
原因：默认列宽和未逐列去空白的解析不匹配真实输出。
修复：[#232](https://github.com/anakine800-tech/Auto-Gaussian/pull/232) 使用明确的 squeue/sacct 列宽并逐列 strip。
以后：样例虚构身份但保留填充/截断形态；严格比较完整作业名和属主，不放宽成前缀匹配。

## 本机多个集群的作业号混淆
现象：monitor 把 Slurm 记录交给 PBS 作业号校验器；跨集群同号可能错误关联。
原因：先扫 status 再判断集群，会使用错误解析器，也让其他集群的坏记录阻断当前扫描。
修复：[#229](https://github.com/anakine800-tech/Auto-Gaussian/pull/229) 引入提交绑定；[#235](https://github.com/anakine800-tech/Auto-Gaussian/pull/235) 统一 local_record，先按 manifest 过滤。
以后：按 manifest 选集群/调度器，再核对 submission/status；裸作业号只按 default PBS 解释，错误要指明 Attempt。

## 平台 env.sh 的副作用
现象：加载平台 Gaussian 环境后 scratch 被改到安装目录，还会向 ag 根外共享文件追加记录。
原因：env.sh 同时执行平台记账和目录设置，不只是声明运行变量。
修复：[#234](https://github.com/anakine800-tech/Auto-Gaussian/pull/234) 用固定 scnet-a03 模板设置必要变量，禁止与 module 初始化混用。
以后：审阅环境脚本的全部副作用；scratch 保持在新 Attempt 内，不直接 source 未审阅的平台脚本。

## Slurm 自动重排队
现象/风险：调度器 requeue 可让同一 Attempt 再次运行和收费；T16 将其列为防范场景，所查 PR 未记载实际重复收费事故。
原因：本地只调用一次 sbatch，不能阻止调度器自动重新执行。
修复：[#229](https://github.com/anakine800-tech/Auto-Gaussian/pull/229) 脚本固定 `--no-requeue`，复用单次运行 guard。
以后：渲染测试保留 no-requeue 和单次执行断言；UNKNOWN 预留不释放，不新增自动重提或重排队入口。

## 远端 Python 版本兼容
现象：[#230](https://github.com/anakine800-tech/Auto-Gaussian/pull/230) 审阅发现 chk 助手使用 Python 3.7 才有的 `text=True`，不能在目标最低版本 3.6 运行。
原因：按本机 Python 编写远端脚本，没有检查远端 API 下限；这是审阅发现，不冒充已发生的现场崩溃。
修复：#230 改为读 bytes 后 decode，并检查 Python/描述符环境；[#232](https://github.com/anakine800-tech/Auto-Gaussian/pull/232) 把不使用 chk 时的缺环境改为警告。
以后：固定脚本同时检查语法和 API 的最低版本；真正使用父 chk 时，环境不满足仍在提交前拒绝。

## 提交者邮箱泄露本机标识
现象：T20 指出 Git 提交者邮箱会泄露本机标识；文件 diff 干净仍不能保证提交元数据安全。
原因：Git 可继承本机邮箱；作者和提交者字段独立，不能只查一个。
修复/核查：[#224](https://github.com/anakine800-tech/Auto-Gaussian/pull/224) 核查所有登记 worktree 的生效邮箱及提交身份均为 noreply；该 PR 未修改邮箱或重写历史。
以后：提交前本机核对 author/committer 的 noreply 身份，PR 不贴真实邮箱、主机标识或核查路径；不能声称该核查已清除历史泄漏。

## 本机 main 未同步
现象：PR 已合并，但本机 Skills 和 ag 仍停留在旧版本，前端也可能从旧检出启动。
原因：合并只更新远端 main；本机检出、软链接目标和运行环境不会自动快进。
修复：T24 补充合并后同步要求；本机同步操作另有记录，不把文档修改当作部署完成。
以后：每次合并后后端和前端 main 均 `git pull --ff-only`；真实计算只用后端 main 的 `.venv/bin/ag`，前端从固定目录运行。

## rcfc 的坐标系错配
现象：L3 用父 TS 的 Standard 坐标读取力常数时，双向 IRC 均首点校正失败；正确 Input 坐标的 RCFC 与独立 CalcFC 部分轨迹高度吻合并越过首点，随后仍有校正失败。
原因：输入坐标与父作业 Input 框架的 Cartesian 力常数/模式错配；副本哈希、相同起点能量及对齐 RMSD 不能证明取向一致，不宣称这是所有失败的唯一根因。
修复：[#240](https://github.com/anakine800-tech/Auto-Gaussian/pull/240) 导出 final_input.xyz 与实际取向，在 prepare 读取父力常数时按固定原子顺序检查 1e-4 Å 容差；已有几何文件只沿用相同字节，不覆盖。
以后：RCFC/ReadFC 用 final_input.xyz，或预先在父 TS 加 nosymm；取向正确后再逐级审阅 StepSize、MaxCycle、CalcAll/ReCalc。L3 的 T46 前流程验收经过及按现行判据的状态已回写 [irc 卡片第 7 节](../skills-next/auto-g16-recipes/cards/irc.md#7-常见失败与处理)，A/B 对照已证实 Input 坐标读取正确；部分轨迹不等于双向完成。

## PBS 槽位写成逗号组合范围
现象：pbsnodes 与 exec_host 出现 `0-7,12-25` 这类写法，核数解析失败，提交与监控都退回严格模式。
原因：解析器只认单个数字、`a-b` 和 `n*k`，没覆盖真实调度器的组合写法。
修复：[#243](https://github.com/anakine800-tech/Auto-Gaussian/pull/243) 支持逗号分段并拒绝重叠；解析失败仍走严格模式。
以后：解析失败一律退回更保守的上限，不放宽；数组作业号目前仍会触发严格模式。

## 分析命令改写已签字的 facts.json
现象：在 L2 签字后重跑 thermo，三份 facts.json 被重写，哈希与签字绑定值不符。
原因：thermo 调用 facts 解析时顺带写文件，而新版本给 facts 增加了字段。
修复：[#247](https://github.com/anakine800-tech/Auto-Gaussian/pull/247) 分析命令只在内存解析；`ag facts` 比较时排除 ag_provenance，内容相同不改写，不同时需 `--refresh` 并归档旧版；新增 `ag review manifest`。
以后：已签字的证据只能归档后更新；签字前先生成证据清单。

## scan-peak 误选扫描边界一侧的点
现象：L3 的 Gaussian C–F 扫描，旧 scan-peak 选中贴近起点的第 2 点，由它出发的 TS 优化没有回到已验证 TS。
原因：气相离子–分子反应中，分离一侧的能量高于势阱里的局部峰；挑全局最高点就会选错。
修复：[#248](https://github.com/anakine800-tech/Auto-Gaussian/pull/248) 只选严格局部极大，无峰时拒绝导出；同一扫描重选得到第 9 点，与 TS 的 RMSD 约 0.002 Å。
以后：扫描峰只是初猜；浅能垒体系的 xTB 扫描可能完全没有峰，此时应改用 DFT 扫描，不能据此断言真实反应无能垒。

## xTB 正常结束标记在调度器输出里
现象：xTB 扫描 17 点全部收敛、退出码 0，facts 仍判为 incomplete。
原因：xTB 把 `normal termination of xtb` 写到 stderr，PBS 合并进 job.pbs.out，而 ag 既不取回该文件，也只在 xtb.out 里找标记。
修复：[#249](https://github.com/anakine800-tech/Auto-Gaussian/pull/249) 取回调度器输出并从中识别标记，调度器报告 kill 或超时时判为 error。
以后：新程序模板要核对完成标记实际写在哪个流里，并把该文件列入声明输出。

## 已取回的作业无法补取新声明的文件
现象：T34 给 xTB 新增了声明输出，但已取回的作业无法补取，fetch 因已有文件拒绝整次取回。
原因：fetch 只允许 finished 状态，且任一目标已存在就拒绝。
修复：[#251](https://github.com/anakine800-tech/Auto-Gaussian/pull/251) 新增 `ag fetch --add-missing`：先核对全部远端哈希和本地已有文件，只补缺失文件，不改状态。
以后：模板增加声明输出后，旧作业用 `--add-missing` 补取，再 `ag facts --refresh`；不手工从服务器下载放进 outputs。

## 跨来源去重丢失极性氢朝向
现象：外部审阅用乙醇合成坐标复现：只改 C–C–O–H 二面角的两个构象被合并，并被标为两条路线共同找到。
原因：去重只比较重原子 RMSD；跨来源合并又不看能量。
修复：[#246](https://github.com/anakine800-tech/Auto-Gaussian/pull/246) 默认让 N/O/S/P 上的氢参与 RMSD，lowest 模式加能量容差，记录两种 RMSD。
以后：涉及氢键或参与反应的氢必须参与构象区分；分子很大时整体 RMSD 会稀释单个氢的差异，需要另看关键二面角。

## Gaussian 后段未结束却沿用前段事实
现象：T42 前全文解析复用前段事实；T42 合并后只读诊断又发现 IRC 的 `# OF POINTS`/`# OF STEPS` 误切段，及 negligible-forces 完成措辞漏识别。
原因：把任意 `#` 行当 route；只认带句点的精确完成字符串，缺少真实输出形态的合成回归。
修复：T42 分段并记录来源；T42b 仅识别短横线包围的完整 route 块、行首完成/停止措辞，并保留单段异常作业自身的末次 SCF 能量。
以后：切分和 route 提取共用规则，保留 Gaussian 行首单空格但拒绝引用/深缩进；核对来源段，异常终止独立记录，既有 facts 差异人工审阅、不自动 refresh。

## RCFC 与中断的优化
现象：没有做 Freq 的中断优化用 RCFC 接续，在初始化阶段终止。
原因：RCFC 读取 Freq 写入 chk 的笛卡尔力常数；此次中断优化的对应记录长度为 0，优化更新的近似 Hessian 不能代替它。
修复：按已验证接续方案，用 `final_input.xyz` + 父 chk 的 `Guess=Read Opt=(TS,CalcFC)` 新建 Attempt；强杀后先按 T47 不完整取回。
以后：复用 RCFC 前确认父 chk 有适用的 Freq 力常数；接续仍须新 Attempt 和人工提交确认，不保证任意中断 chk 可读。

## MaxCycles 不等于不超 walltime
现象：设置 MaxCycles 后，优化仍可能被 walltime 强杀。
原因：MaxCycles 只限制优化步数，不限制初始 Hessian、每步 SCF 或最终 Freq 的耗时。
修复：按 `walltime ≥ 1.3 × (t_CalcFC + t_step × MaxCycles + t_Freq)` 估算总时限。
以后：各项用本体系首个作业的实测值校准，小分子的耗时不能外推；估算留余量仍不保证必然按时完成。

## SSH 报 Operation not permitted
现象：Codex 沙箱禁止联网时，SSH 以 255 退出并报告 `Operation not permitted`。
原因：此次是会话联网权限限制，不是网络或集群故障；不能仅凭 255 对所有 SSH 失败归因。
修复：先检查会话联网权限，确认拒绝来自沙箱后按权限流程处理。
以后：开发会话不连接集群；运行会话遇到 SSH 报错先停止报告，不因猜测网络原因而反复尝试。

## 验证方案先对照卡片
现象：OPS-3 的第二项验证拿 RCFC 接续没有 Freq 的中断优化，方案不适用。
原因：设计前没有逐条对照 irc 卡片的父 Freq 力常数限制（当时第 63 行）。
修复：保留失败结论，改为已验证的 `final_input.xyz` + `Guess=Read Opt=(TS,CalcFC)` 新 Attempt；不把设计不适用算作环境故障。
以后：设计真实验证前逐条核对相关卡片限制，再审阅完整输入、资源和验收目标，获批准后执行。

## 证据清单误读中文说明与目录引用
现象：证据清单把路径后的中文说明当作文件名，签字 JSON 引用目录时报缺失。
原因：裸路径边界吞入中文或排除中文前缀，引用解析只接受文件；JSON 长说明还会被作文件路径检查。
修复：T49 以 ASCII 字符界定裸路径、不限制扩展名，展开 analyses 内引用的目录；长说明不访问文件系统，非法显式引用定位到文件与字段；保留符号链接与越界拒绝。
以后：引用证据时用反引号或链接包裹路径；需要引用一批文件时可以直接引用目录，空目录仍报错。

## CREST/xTB 的 OpenBLAS 警告撑大日志
现象：SCNet 小分子 CREST 的 `job.slurm.err` 出现约 159 万行 OpenBLAS/OpenMP 警告，约 194 MB；`crest.out` 无该警告。
原因：OpenMP 并行中调用 pthread OpenBLAS，嵌套并行反复报警；不能把其他程序错误一并忽略。
修复：T50 固定 `OPENBLAS_NUM_THREADS=1` 和 `OMP_MAX_ACTIVE_LEVELS=1`，保留原 OpenMP 核数；单次真实验证中 stderr 降为 0 字节；无手性小分子按获批镜像口径完成结构与能量对应，待监督方复核。
以后：按 CREST/xTB 官方线程建议审阅模板，BLAS 与 OpenMP 分开控制；离线渲染通过不等于真实运行或科学验收。随机采样的真实验证，按“结构对应和能量接近”来验收，不要求逐帧一致。无手性体系的构象对照要允许镜像；手性体系（如 HSS）不做镜像合并，与已签的能量口径一致。

## 证据引用的解析基准不完整
现象：ag 的 topology 等 JSON 记录 Attempt 相对裸文件名，study 快照保存根目录相对引用，证据清单误按源目录查找而失败。
原因：只覆盖分析文件间的引用，没有覆盖 ag 自身输出和 study 快照的解析基准。
修复：T49b 跳过源 JSON 目录中不存在的 file/source/path/definition 裸名；文本允许 study 根目录回退并记录 resolved_from，两处指向不同文件时报歧义。
以后：显式引用、安全边界及已签清单不展开保持不变；复扫对照文件数与哈希，并包含另一台电脑的已签 study，由负责人运行、逐项记录后统一汇总。

## 排队额度被节点核验锁死，SSH 连接失败缺少时间线
现象：PBS 集群总核数大于单作业上限时，配置的排队额度不生效；Slurm 的总额度也不能独立提高。另有一次 SSH 连接被拒绝，原因未明。
原因：把单作业上限与硬件保证绑定，使排队额度退回严格模式；缺少逐次连接诊断记录。
修复：T51 将单作业与运行加排队总额度分开，提交不读节点；每次 SSH/scp 追加本地结构化日志，只记错误类别，不保存连接信息或 stderr。
以后：以全部本人作业和尚未读回的本地预留检查额度；运行时机由调度器决定。此条取代前述 PBS 槽位解析事故的“退回严格模式”建议，节点解析仅用于监控显示。日志写入失败不能改变提交或只读重试语义；真实 SSH 报错仍须停止并报告，不能按类别猜测后自动重提。

## 说明性引用阻断签字证据清单
现象：T49/T49b 后，说明性文件名、卡片链接和跨 study 引用仍使四个已签 study 的清单生成失败。
原因：把所有引用解析失败都当作缺失证据；普通 JSON 的 study 根相对路径也缺少回退。
修复：T64 按经批准的 v3 口径，缺失/越界列明后显式确认；analyses 外现存引用和无 analyses 同名文件的裸名只记信息，普通 JSON 支持根目录回退且拒绝歧义。
以后：不猜测同名文件、不静默忽略新类别；study 内链接、专用证据指针及收集期间哈希变化仍硬拒绝，复扫分别对照收录文件哈希和分类数量。

## 远程观察改动真实验证失败
现象：T62 第 1 项合并后，HSS 在组内集群的运行中作业查询中，`receipt` 对 `ag-start.json` 持续返回 `unreadable`，未显示底层原因；离线测试未发现该问题。
原因：现场底层原因尚未查明；合并前仅有离线证据，不能证明目标集群兼容。
修复：T65 将三个观察命令及 status 的对应处理恢复至 `f34f732`，保留 T62 其余改动。
以后：远程命令改动必须先在非研究 study 上做真实验证再合并；离线通过不能替代目标环境验证。
