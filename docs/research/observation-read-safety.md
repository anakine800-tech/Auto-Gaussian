# T175：远程观察缺失分类与回执读取安全

核查基线：`20840ee7a51dae4e4da1c75dd6eef63052d47802`，2026-10-29。
实现范围见 [T175 工单](../redesign-tasks/T175-observation-read-safety.md)。
本单修复 T167 的两个当前缺陷，不解释历史 unreadable 现场的未知根因。
当前仅完成本地实现与离线验证准备；独立审阅、当前 head 的 Linux CI 和必要真实验证均为合并条件。

## 实现选择与新增运行时前提

| 方案 | 可以解决的部分 | 无法覆盖的部分 / 兼容影响 |
| --- | --- | --- |
| 继续使用 sh/test/stat/head | 保留旧基础环境；增加目录类型/搜索权限检查可拒绝部分 EACCES/ENOTDIR | test 的真假及 stat 的非零码不能可靠给出 errno；按英文 stderr 判 ENOENT 已排除。检查后 shell 重定向没有 O_NOFOLLOW/O_NONBLOCK，FIFO 替换仍可能阻塞。 |
| 借用 log_snapshot 的固定描述符与身份比较 | 打开后核对设备/inode，再从固定描述符读，可防多种替换 | 原实现依赖 Linux procfs；不是普通 status 已有前提。打开前换为 FIFO 仍可阻塞。macOS 对照中 BSD stat 对普通路径和 dev-fd 路径给出不同设备号，正常样例即拒绝；这不是 Linux 的实测结论。 |
| 本单固定 Python 标准库助手 | 数值 errno；逐级 descriptor-relative/no-follow；回执 nonblocking 打开、fstat 身份检查和有界缓冲 | **新增必要前提：远端 Python ≥3.6，Linux O_PATH/O_DIRECTORY/O_NOFOLLOW/O_NONBLOCK，以及 open/stat 的 dir_fd、stat 的 no-follow 支持。** 不依赖 procfs、第三方包或安装步骤。缺能力明确失败。 |

本轮协调在比较具体原型后选定第三条路线；这是协调方依据本轮自主开发授权作出的实现选择，
不是用户单独指定了 Python 版本，也不授权部署或安装服务器依赖。
助手仅由 receipt/output 固定命令发送；不调用父 chk 的 metadata/copy 分支，不扩展父 chk API。
Python 使用 `-I -S -B`，隔离 Python 环境扩展和 site 初始化，并禁止写入字节码缓存。

兼容依据和边界：当前父 chk 实现以 Python 3.6 为下限；doctor 明确允许父 chk 缺能力时仅警告。
因此父 chk 的存在、doctor 总体 ok、曾成功 snapshot 或开发机能运行 Python，均不能证明普通观察的新前提已满足。
已有公开资料未提供本单各目标入口的当前 Python/O_PATH 完整实测；必须逐目标补验证。
Slurm status 现有路径只查询 identity/squeue/sacct，本单不为它新增 receipt/output 调用；它成功不构成助手兼容证明。

O_PATH 打开目录只要求路径搜索权限，不要求列目录。普通 output 只 stat 声明文件，
文件 mode 000 但元数据可见时仍可观察；不升级为内容读取。
测试的 macOS 适配明确用 O_RDONLY 代替 O_PATH，只证明该适配下的文件系统/身份逻辑；
只有真实 Linux 测试可证明只具搜索权限的目录兼容。

## 缺失、失败和身份固定时点

- 仅逐级无跟随 stat 的 **ENOENT** 可输出 absent。确认缺失前重新核对已打开的祖先绑定及该缺失项；
  EACCES、ENOTDIR、EIO、链接、非普通文件、身份变化和运行时能力缺失均非零失败。
- 普通观察保留“祖先确实不存在 → absent”的兼容语义。不会把“进入失败”解释成祖先不存在。
  严格 incomplete 仍要求父目录存在、可进入，且存在文件可读；没有引入普通观察的祖先缺失分支。
- 从根目录逐级打开描述符，检查每级不是链接并保留设备/inode/类型；打开前后及读取后重新核对各级绑定。
  回执先取得 leaf 元数据，再以 O_RDONLY/O_NOFOLLOW/O_NONBLOCK 相对最后的目录描述符打开。
  **首次内容读取前**比较 fstat 与检查时的设备/inode/类型/大小/mtime_ns/ctime_ns。
- 固定描述符读取最多 4097 字节，用第 4097 字节识别超限；只接受不超过 4096、与最初大小一致、
  最后 fstat/路径/祖先复核仍一致的全部原始字节。增长、缩短、读到部分后失败都不输出部分 JSON。
  等长普通替换、链接替换、父目录替换和 FIFO 替换均拒绝；检查后变成 FIFO 不会阻塞打开。
- metadata 按远端进程本地时区输出当地时间、9 位纳秒及 `%z`，保持与严格观察的 GNU `stat %y` 一致，
  包括夏令时和分钟偏移；不改变 60 秒或 300 秒规则。
- 普通模板和 Multiwfn 使用同一固定助手、同一分类和固定声明列表；不遍历目录、不使用 glob。
  全部行成功后才输出；最大布局 1002 项的合成短路径命令小于 36 KiB，仍小于 64 KiB。
  过长配置使生成命令达到 64 KiB 时拒绝；没有重新展开逐文件脚本。
- 错误仅输出 `observation <阶段> <固定类别或 errno 名>`，不含路径或原始异常文本；沿用现有 transport 脱敏。
  不新增用户开关、自动回退、重试或状态。

回执 JSON 格式和本地解析保持不变：两个文件名白名单、PBS/Slurm 确切作业绑定、带时区时间、重复键拒绝、
退出返回码 0–255。UNKNOWN 的原有核对路径不改。

## 观察失败与本地状态

`require_ok` 在三个解析入口消费 stdout 前检查返回码；stdout 看似合法但 rc 非零也拒绝。
PBS 节点位置的原有记录会写 status.json，现延后至全部必要观察完成后调用，
包括旧无回执完成标记之后的第二次 output 观察；没有改变位置判定规则。
分类/读取失败时，正常已绑定作业的 status.json 原始字节、observation、unchanged_since 和
incomplete_observations 保持不变。已 finished/fetched 的历史结果不被错误覆盖。

**SSH 故障另有既有诊断语义：** transport 的 SSH 255/超时可能保留 ssh_error 并重写同一生命周期的状态记录。
本单不删除该诊断、不改 transport；此类故障要求不推进生命周期或缺失/稳定证据，不能宣称状态文件总是逐字节不变。

`incomplete_output_observation` 的函数文本相对基线逐字不变，SHA-256 为
`aa9d35fa25ee3094e845541b2eaada18aac764ba5d9bbdb6e4283957ccf94b34`。
fetch._presence、下载、发布、结束证据和补取策略均未修改。

## 本地复现与测试记录

所有夹具均为临时目录和合成水体系；没有读取真实配置、连接集群或修改研究。
基线复现：48 个真实文件系统场景（两个回执、output、incomplete × 12 布局）；
非 root 有效权限与 EACCES/ENOTDIR 独立核对，无权限跳过。
两个回执与普通 output 在父/祖先 mode 000、ENOTDIR 共 9 例错误 absent；严格 incomplete 均拒绝。
两个回执 × 等长文件/链接/父目录替换共 6 例，基线均读到并被解析器接受替换内容。
macOS 仅对原 GNU stat 调用作 BSD 大小适配，不能当作 Linux 基线工具验证。

Python 最小原型：72 个文件系统、24 个确定性替换、10 个边界/读取错误场景通过。
shell 对照：固定描述符正常路径因 BSD dev-fd 设备号不同而失败；打开前 FIFO 替换达到 2 秒测试超时。
保留该失败，没有用此 shell 原型声称替换保护或 Linux 兼容已通过。

正式回归在 `ag/tests/test_remote_observation.py`：

| 覆盖 | 实测方法 |
| --- | --- |
| 12 布局 × 两调度器文件列表 × 四条观察路径 | 完整生成命令；权限用真实内核 errno，条件不成立明确 skip |
| 两回执 × 四种替换 × 三个确定时点 | 打开前/打开后/首次 read 前注入；记录前后身份；断言没有读出替换内容 |
| 4096/超限/增长/缩短/部分读取后 EIO | 固定描述符、真实本地文件、确定性 read 注入 |
| Python/OS 能力不足、元数据 EACCES/ENOTDIR/EIO | 数值 errno 与错误阶段断言，不用诊断文字伪造权限 |
| 三路解析、合法/缺失/无法核实/非零/合法 stdout 非零/SSH 255/响应丢失 | PBS/Slurm 合成绑定和假 Transport |
| Multiwfn 1/3/50 帧、2/3/4 片段 | 实际 layout 生成，最大 1002 文件，全体成功或无部分 stdout |
| PBS 初次和旧完成二次观察、带节点绑定、finished/fetched、cancelled incomplete | status.json 原始字节比对，拒绝下载；Slurm 实际 status 调用列表另行断言 |
| 参数引用、路径越界、链接、纳秒和回执解析兼容 | 固定命令语法、Python 3.6 语法解析、实际生成命令 |
| 非 UTC 的 status → strict presence → incomplete | Linux 原样运行两种生成命令并逐字对照 GNU stat；UTC、+08:00、+05:45、纽约冬/夏时间 |

开发中相关回归曾通过 902 项、跳过 9 项（Linux O_PATH/GNU stat/ps）。
随后加入 `-I -S -B` 时，macOS 测试包装器错误地取了自己的 `-c` 参数，导致 77 例失败；
已按实际参数位置修正包装器，产品读取逻辑未因此回退。
提交 `f4ff6f7ffb9bbbdbbc201cc13c0c2e80a1106b09` 全量为 **6780 passed、21 skipped（352.49 s）**；
20 项 Linux 专用测试及 1 项私有日志 opt-in 未执行。
独立审阅随后发现普通输出改用 UTC 与 strict 的本地时区字符串不一致，会阻断不完整取回；
现恢复 GNU stat 原有时区表达，保留严格比较，并增加上述跨路径回归。修复后结果在 PR 中绑定执行提交记录。

推送前按工单执行一次后端全量：
`PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`。
Python 借用已有依赖环境，导入位置须核对为本工作树 ag/src；不采用主检出的 editable 导入。
Linux CI 必须原样运行完整固定命令及 O_PATH/search-only 权限用例；skip 不计为通过。
Python 3.6 语法/API 下限检查不等于已在目标 Python 3.6 运行。

## 合并前真实验证与剩余限制

当前真实验证 **未执行**；没有本单对象级远程授权，不恢复监控，不为验证制造服务器恶意夹具。
独立审阅绑定当前完整 head 后，协调方须在私有验证表补齐已结束非研究对象、绑定入口/确切作业、声明文件、
生成命令原文、执行提交和次数；未补齐不能执行。公开 PR 只汇总版本、路径类别、次数与覆盖缺口。

| 每个拟支持目标的最小调用 | 计划次数 | 预期与覆盖 |
| --- | --- | --- |
| 固定 receipt，已存在普通 start 回执 | 1 | 同一普通文件、有界原始 JSON、作业绑定解析；同时证明该目标运行时能力 |
| 固定 receipt，已存在普通 exit 回执 | 1 | 原始 JSON、时区/退出码/确切作业绑定 |
| 固定 output_observation，已结束非研究 Attempt 的全部声明文件 | 1 | 元数据与自然缺失项；没有自然缺失则如实列缺口，不制造文件 |
| 正式 ag status（PBS 非研究对象，备选） | 0 | 本次选独立审阅的固定 Command 入口，避免改写原对象状态；Slurm status 不替代前三项 |

本单未改 strict incomplete 命令，无新增该路径现场调用要求；提供字节比较与离线拒绝回归。
PBS 网络恢复属于延期事项；不因本单重试。目标必要验证不能完成时保留待验证 PR，不能合并或部署。
每次获准调用失败立即停止；不重试、不扩大读取、不安装依赖、不改现有远端对象。
权限、链接/FIFO/目录替换和 I/O 负例只在本地/隔离 CI 制造；成功现场路径不能代替这些负例。

身份比较不提供文件系统事务快照，也不声称对抗可任意修改内核/挂载的特权进程；
描述符绑定保证读取来自已核对的普通文件，复核检测本单覆盖的路径/文件替换。
网络文件系统的具体属性缓存和目标运行时兼容仍须独立审阅及真实验证。
