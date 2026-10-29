# T175：远程观察缺失分类与回执读取安全

## 合并后状态（2026-10-29）

[T175 #370](https://github.com/anakine800-tech/Auto-Gaussian/pull/370) 已合并至
`c1a0d084fd5f53d1fb4ab15dd3c57c12ad447a8f`。最终 head
`df809cc5e9e3ba8a45f515c2c738cc81e48b282d` 的独立复核与五项 CI 通过；
其 `ag/` tree 与下述现场执行代码相同。两个独立复现缺陷已修复；历史 unreadable 根因无法判定。
原 10 条现场观察后，新增 8 条获准调用已完成，各一次、无重试；具体补充证据与边界见下节。
下文的 draft/等待最终 CI 等措辞记录合并前时点，不再是当前待办；原始实现、测试与现场记录保留。
完整最终状态见 [T175 结案](../redesign-tasks/T175-observation-read-safety.md#最终状态t178-核对2026-10-29)。

## 合并后补验（2026-10-29）

协调方在负责人明确批准八条命令各执行一次后，按独立审阅的固定计划完成五个动作、八次调用。
执行产品提交为 `c1a0d084fd5f53d1fb4ab15dd3c57c12ad447a8f`，`ag/` tree 为
`aa1473904ce274f92afbff69d55d1cacec92afbd`，与合并前执行代码相同。
每条只调用一次，无重试；五个动作全部通过预定判据。原 Attempt 控制文件、study journal 和配置哈希不变。
T178 仅只读核对保存结果与计划/运行器哈希，没有新增远端调用。

| 补验路径 | 固定调用数 | 实际结果 |
| --- | --- | --- |
| 新增 Slurm 入口的旧 CREST 对象 | 3 | start/exit 回执正常，退出回执的作业身份和零退出码核验通过；5 项声明输出均存在 |
| 既有 PBS 入口的 Multiwfn 对象，隔离副本调用正式 status.check | 4 | 双回执正常；固定确切作业查询的 qstat 返回 153，由正式逻辑识别为已知作业缺失；17 项声明输出均存在；副本 fetched 状态保持 |
| 同一 PBS 入口的 xTB 输出 | 1 | 3 项声明输出均存在，未形成自然缺失输出证据 |

七条回执/输出 helper 返回码为 0；一条 qstat 返回码为 153，不能将八条笼统写成全部 rc=0，
也不能把正常的调度器记录缺失解释为 Attempt UNKNOWN。Slurm 三条调用出现已审阅的精确 SSH 提示，
按固定计划核对一致后接受，没有降低 SSH 或产品检查；原始输出保留在私有证据目录。
读取回执及声明输出元数据，没有下载输出文件、提交/取消作业或修改远程文件。
正式 status 的本地状态/journal 作用仅在隔离副本，原对象保持只读。
副本只更新 observation.at、scheduler_observed_at、updated_at 三个观察时间字段，
隔离 journal 追加 status/query 和 state/fetched 两条记录；不是副本所有字节不变。
常规 SSH 脱敏诊断日志按现行行为追加，配置文件哈希不变不代表配置目录内没有日志写入。
qstat 的身份范围来自固定确切作业命令；脱敏后的消息只证明已知缺失格式，不能独立证明回显作业身份。

本次新增 4 个正常回执，3 次输出观察共确认 25 项存在的声明输出，自然缺失声明输出仍为 0。
合计原 10 次与新增 8 次调用，helper 已在两个 PBS、两个 Slurm 入口取得现场证据。
Multiwfn 现有 fetched 对象的正式 status 路径已覆盖，不能据此声称完整新作业生命周期已验证。
另一个 PBS 入口和实际 fetch 仍未覆盖；自然声明输出 absent 仍未命中，回执 absent 与 qstat 作业缺失均不能代替。
权限、链接/FIFO/目录替换与 I/O 负例继续使用本地/隔离 CI 证据，不在服务器制造。
历史 unreadable 根因仍无法判定。下文合并前记录保留当时覆盖范围，其中未覆盖 Multiwfn 等描述由本节补充。

## 合并前记录（原文）

核查基线：`20840ee7a51dae4e4da1c75dd6eef63052d47802`，2026-10-29。
实现范围见 [T175 工单](../redesign-tasks/T175-observation-read-safety.md)。
本单修复 T167 的两个当前缺陷，不解释历史 unreadable 现场的未知根因。
实现、独立代码复核与 Linux CI 已通过；2026-10-29 已完成 10 次既有非研究对象的固定只读观察。
执行代码均为 `24df151817489ce8a4176269e0758386eb2b2dc3`，每条命令仅执行一次。
独立覆盖复核支持保留以下缺口的有界合并；PR 暂留 draft，等待最终提交的 CI 与协调方复核。
声明输出自然缺失及其他未覆盖入口不计为通过，不将本记录表述为全部现场分支验收。

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
本轮已在两个 PBS 入口和一个 Slurm 入口实际执行本单固定助手；各次返回码均为 0，原产品解析通过。
这证明被执行路径所需的版本/OS 能力检查及读取操作可用，不能外推到未覆盖入口或负例路径。
同轮已保存的 PBS doctor 父 chk 探测记录 Python 3.6.8；它只是独立环境来源。
本单助手不输出解释器版本，不能把 doctor 版本当作本次命令直接报告的版本；Slurm 的精确版本未另行查询。
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

本节的开发夹具均为临时目录和合成水体系；这些离线测试没有读取真实配置、连接集群或修改研究。
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

执行代码 `24df151817489ce8a4176269e0758386eb2b2dc3` 的最终离线证据：

- 本地全量 **6782 passed、26 skipped（327.19 s）**；25 项 Linux 专用、1 项私有日志 opt-in。
- [Linux CI](https://github.com/anakine800-tech/Auto-Gaussian/actions/runs/40747899946)：
  后端 **6279 passed、2 skipped**，Skills **527 passed**；两项跳过为私有日志 opt-in 与 macOS-only plutil。
  T175 新测试模块 **255 项全通过、0 跳过**，含实际 O_PATH 搜索权限及五组时区的 GNU stat/incomplete 对照；全部五项 CI 成功。
- [独立代码及增量复核](https://github.com/anakine800-tech/Auto-Gaussian/pull/370#issuecomment-6477636748)
  绑定同一完整提交；代码复核通过不代替下述现场覆盖审阅。

现场验证后，按协调方指示 rebase 到 `c73298d3acbd1d7795be0cea38ab40af8e4892af`，只同步已合并文档/Skills 并补充本说明。
原执行提交与重放后的 `ag/` Git tree 均为 `aa1473904ce274f92afbff69d55d1cacec92afbd`，
代码、模板和 `ag/tests` 的全部文件逐字一致；未追加集群调用。最终提交号与 CI 结果在 PR 中单独记录，
不能把历史执行提交改写成后续文档提交。

## 合并前真实验证与剩余限制

2026-10-29，协调方在具体对象/固定命令审阅后执行下表 10 次观察；每条仅一次，无重复调用。
使用三个入口、四个已结束的非研究验证对象，正式 receipt/output Command 与旧准备表的字节和哈希完全相同。
PBS 连接及正常监控已由相应会话恢复，本单不修改配置或服务；先前“网络仍阻塞、现场零调用”的记录已被本轮证据更新。

| 验证路径 | 次数 | 原产品解析与实际覆盖 |
| --- | --- | --- |
| PBS 正常对象：start、exit、声明输出 | 3 | 两个已存在回执解析通过；一次输出观察中 2 个声明文件均存在 |
| PBS 旧记录：start、exit、声明输出 | 3 | 两回执合法 absent，覆盖旧记录兼容/自然回执缺失；一次输出观察中 2 个声明文件均存在 |
| Slurm 正常对象：start、exit、声明输出 | 3 | 两个已存在回执解析通过；一次输出观察中 3 个声明文件均存在 |
| Slurm 输出缺失候选：声明输出 | 1 | 原产品解析通过，但 5 个声明文件全部存在；候选未形成现场输出缺失证据 |

全部命令返回码为 0。首条原 runner 因 SSH 客户端的后量子密钥交换提示而在解析前停止，原 failed/STOP 保留。
协调方离线用原 `status.read_receipt` 对已保存 Result 正式解析通过，未再次读取该回执。
独立续行 runner 仅允许剩余九行，额外绑定首次结果和离线复核哈希；stderr 只接受空文本或逐字一致的已保存三行提示。
其他 stderr、非零返回、超时、非法输出和绑定变化仍立即停止；SSH 与产品校验未修改。
续行九行均通过。汇总时再次仅离线重放十份保存结果，原产品解析 **10/10 通过**；这不新增远程调用。

现场证据合计：4 个正常回执、2 个自然缺失回执、4 次输出观察（12 个声明文件存在，**0 个声明输出缺失**）。
Transport 使用单次模式，未调用 record_to、status.check 或 fetch；所有原 manifest/status/submission 控制字节前后不变。
stdout、诊断、授权、对象/作业绑定、命令与配置哈希仅保留在私有验证目录，公开记录不含对象身份或原始输出。

**剩余现场覆盖：声明输出自然缺失。** 工单“真实环境验证”第 2 条包含已有对象中自然存在的缺失声明文件。
receipt 的 absent 与 output_observation 的声明列表/元数据协议是不同路径，不能用前者代替后者。
第 4、5 条同时要求如实记录缺少自然负例及未覆盖平台，由独立审阅判断适用范围。
本项没有现场通过证据。协调方独立覆盖复核已依据第 4、5 条支持当前有界合并范围，不要求扩大本轮现场调用；
这一结论不补造缺失证据、不改变未测入口的兼容声明，也不授权部署或新计算。
若验收仍要求现场覆盖该分支，最小增量是另外确认一个既有、已结束非研究对象确有自然缺失声明输出，
审阅其绑定和固定命令后单次执行 output_observation；当前没有确认该候选，不自动扩查、造负例或新增调用。
当前未发现代码、连接或控制文件一致性方面的新阻塞；PR 暂留 draft，等待最终提交 CI 与协调方复核。

其他适用范围限制交独立审阅判断：

- 另有未选定对象的入口，不能由这三个入口的成功推断其运行时兼容；旧 PBS 入口的正常已存在回执读取也未单独覆盖。
- Multiwfn 布局、权限、链接/FIFO/目录替换及 I/O 负例仍是本地/隔离 CI 证据，不在服务器制造这些夹具。
- 本次直接执行修改后的 receipt/output 固定 Command；没有声称完成整个 status/fetch 生命周期现场验证。
- strict incomplete 命令保持字节不变，已有比对及跨时区回归证据，无需因此新增该路径现场调用。

身份比较不提供文件系统事务快照，也不声称对抗可任意修改内核/挂载的特权进程；
描述符绑定保证读取来自已核对的普通文件，复核检测本单覆盖的路径/文件替换。
正常现场观察不证明所有网络文件系统属性缓存或并发替换行为；未覆盖限制仍须独立审阅。
