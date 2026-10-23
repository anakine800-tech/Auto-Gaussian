# Gaussian 报错速查

本表用于从已有本地日志定位下一步诊断，不按 Link 号自动选择修复。
`Error termination via Lnk1e in .../l9999.exe` 中的路径用省略号表示；
结合报错前文、当前 Opt/Freq/IRC 段与 `facts.error_hint` 的来源行，
Link 号只表示终止位置，同一位置可能有不同原因。

改编自 `archive/skills/auto-g16-rtwin-pbs/references/environment-and-failures.md`
的日志定位/输入/内存经验，以及 `archive/docs/ts-freq-irc-design.md` 第 9 节的
TS、路径与端点失败语义；其旧传输、重试、取消和 checkpoint 流程不适用。

| 报错特征（必须结合前文） | 常见原因或待查假设 | 首选处理 | 对应的 ag 操作/卡片 |
|---|---|---|---|
| `l9999.exe`；`Number of steps exceeded` 或优化未完成 | 达到优化步数上限、停滞，或其他受控终止；仅有 Link 号不能定因 | 先看步数、能量/梯度与四项收敛趋势；接近收敛才考虑加步数，停滞先审阅几何/Hessian | [失败诊断第 2–3 级](../../auto-g16-recipes/cards/failure-diagnosis.md#第-2-级最小数值收敛调整)；经人决定用 `ag prepare` 新建 Attempt，以 `--parent <id> --relation retry_of` 留来源 |
| `l9999.exe`；`Wrong number of Negative eigenvalues` | TS 曲率与目标不符，可能初猜或 Hessian 不合适 | 回查负本征值和目标反应坐标，不能只加 MaxCycles 或关闭曲率检查来宣称成功 | [TS](../../auto-g16-recipes/cards/ts.md)；有完整合格频率段时用 `ag mode-review`，无频率则记录缺口；新初猜需新 Attempt |
| `l502.exe`；`Convergence failure` | SCF 不收敛；可能错误电荷/多重度、近接触、振荡或电子态问题 | 按已有阶梯核对输入与 SCF 轨迹，再提出单一收敛调整 | [失败诊断第 2 级](../../auto-g16-recipes/cards/failure-diagnosis.md#第-2-级最小数值收敛调整)；新 Attempt，不把未收敛能量放入 thermo/profile |
| `l103.exe`；`Optimization stopped`、步数耗尽，或 `Bend failed` / 坐标定义失败 | 优化停止也可能来自近线性角、内坐标奇异或坏几何；步数耗尽也常由 l9999 收尾 | 区分步数上限与坐标问题；检查原子接触和最后完整几何，不机械地延长所有作业 | [失败诊断第 2–4 级](../../auto-g16-recipes/cards/failure-diagnosis.md)；按原驻点类型新建 Attempt，TS 不改成普通极小点优化 |
| `l123.exe`；`Maximum number of corrector steps exceeded` | IRC 校正失败；可能起点/父力常数取向不符，或步长/局部曲率不适合 | 优先核对 TS、父 Freq、Input 坐标系；再按 IRC 卡片审阅步长与力常数方案 | [IRC 第 7 节](../../auto-g16-recipes/cards/irc.md#7-常见失败与处理)；复用时通过 `ag prepare --parent-chk <id>:<chk文件名>`；RCFC 用 `final_input.xyz`，不得用 Standard 坐标替代 |
| `l1.exe`；`QPErr`、语法错误或输入处理失败 | route/Link0/输入段格式问题，或启动时资源/环境异常；l1 不是“内存不足”的同义词 | 按具体文本定位语法、空行与资源；没有内存证据就不调大内存 | [失败诊断第 1 级](../../auto-g16-recipes/cards/failure-diagnosis.md#第-1-级纠正已定位的输入错误)；修改输入后新建 Attempt |
| `End of file in ZSymb`（常见于输入读取段） | 坐标/电荷多重度/空行缺失，QST 多结构块不完整 | 检查已支持的输入格式和原子对应，不猜补科学信息 | [失败诊断第 1 级](../../auto-g16-recipes/cards/failure-diagnosis.md#第-1-级纠正已定位的输入错误)；`ag prepare` 校验新输入 |
| `galloc`、`malloc failed`、明确 memory allocation 错误，或调度器 OOM | Gaussian 内存分配失败或请求超出作业可用内存；也须排查环境 | 对照 `%mem` 与档位限制，区分 Gaussian 报错和调度器 OOM；按证据提出资源调整 | [失败诊断第 5 级](../../auto-g16-recipes/cards/failure-diagnosis.md#第-5-级有证据的资源或方法升级)；新 Attempt 的 `--tier` 与输入一致 |
| chk 读取失败、缺力常数或记录长度异常 | 文件不完整、不兼容，或父作业根本未完成所需 Freq | 安全复制成功不代表内容可读；无可用 Freq Hessian 不用 RCFC，核对可用几何与波函数方案 | [中断处理](../../auto-g16-recipes/cards/failure-diagnosis.md#作业被强杀)及 [IRC](../../auto-g16-recipes/cards/irc.md)；适用时新 Attempt 声明 `--parent-chk`，不手工覆盖 chk |
| 只有截断日志、walltime/强杀记录，无完整正常终止 | 作业中断或完成证据缺失，不能按 Link 号猜测 | 按已有状态/取回流程核实，部分结果不进入热化学或剖面 | [作业被强杀](../../auto-g16-recipes/cards/failure-diagnosis.md#作业被强杀)：人要求核对后 `ag status`，满足条件才 `ag fetch --incomplete` 与 `ag facts` |

没有单独新建恢复流程：真实意外的停止/报告、UNKNOWN、SSH、哈希不一致见
[不确定状态与失败](unknown-and-failures.md)；同一问题已修两次仍失败的处理、
最小改变与后续科学验收见 [失败诊断](../../auto-g16-recipes/cards/failure-diagnosis.md)。
表内操作都是人决定继续后的对应入口；新 Attempt 不等于获准提交，提交仍须按 Study 流程取得聊天批准记录、匹配长期规则或 Mac 人工确认。
