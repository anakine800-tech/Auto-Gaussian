# T167：历史 unreadable 追溯与本地复现

调查日期：2026-10-28；核查基线：`e24a5bd1d9045e3b783d8ef25f02e430ad4dc3c5`。
本单仅交付调查报告；不修改产品代码、真实 study、现有 Attempt 或生产配置，不连接集群。

## 结论与证据边界

1. **原事故根因：证据不足，尚未确定。** T65 的现场转达记录支持“T62 后出现 unreadable、回退后指定观察路径恢复”，不支持“已经证明是权限、CentOS、引号或 locale 问题”。不能将历史事故描述为当前仍在故障。
2. **当前可独立复现的缺陷：存在。** `receipt` 和普通 `output_observation` 把父目录不可进入（真实 EACCES）及中间路径非目录（ENOTDIR）当成 `absent`；`incomplete_output_observation` 在这些布局中非零退出，未接受为缺失。T62 在这些合成场景能区分，但这不解释它为何在原现场失败。
3. **受控竞态：存在独立的检查/读取窗口。** 四个版本的 receipt 在检查完成、head 打开文件前，被换成另一普通文件或符号链接后，都读到了替换内容且返回 0。此结果来自本地确定性注入，不能推断现场发生过替换，也不代表任意竞态都已覆盖。
4. **建议另开有限实施单。** 优先修复错误的缺失证据；receipt 的文件身份与链接替换检查需明确纳入该单或单独立项。不得直接恢复整个 T62，也不需要重构 transport 或状态机。未来修复合并前必须有非研究对象的真实验证；本调查既不需要也不授权该验证。

证据分为：Git 中的实现事实、开发者报告、审阅要求的转述、负责人现场转达、本次本地实际运行、代码推演。下文逐项标明。协调方提供的私有 108 场景汇总仅作只读交叉核对；公开结论使用本次独立复核，不提交其文件或位置。

## 证据时间线

时间均为北京时间（UTC+08:00）；PR 时间由 GitHub UTC 转换，提交时间取 Git 对象。

| 时间/节点 | 可追踪来源 | 证据类型与能支持的结论 |
| --- | --- | --- |
| 10-16 11:52:33，改前 `f34f732c769bf0a47383ca3108347927586780ab` | [提交](https://github.com/anakine800-tech/Auto-Gaussian/commit/f34f732c769bf0a47383ca3108347927586780ab)，`ag/src/ag/remote.py` 的三个函数 | 实现事实：receipt/普通 output 使用 `test ! -e`；incomplete 已有 T47 父目录检查。 |
| T62 初始实现 `c6ea5eb` → 修订 `817c98c` | [T62 工单](../redesign-tasks/T62-small-fixes.md)“第 1 项”“审阅补充 v2”；[初始提交](https://github.com/anakine800-tech/Auto-Gaussian/commit/c6ea5eb)、[修订提交](https://github.com/anakine800-tech/Auto-Gaussian/commit/817c98c) | 实现事实：ENOENT 模式从 `*': No such file or directory'` 放宽为 `*'No such file or directory'`。工单与回复转述审阅要求，不充当原始审阅意见。 |
| 10-16 12:32:14，#278 评论 | [comment 6208131526](https://github.com/anakine800-tech/Auto-Gaussian/pull/278#issuecomment-6208131526) | **开发者报告**：本地 shell 的带/不带引号示例都能匹配原模式；不声称复现现场问题。报告离线测试 2387 passed、3 skipped，真实验证待执行。不是现场恢复证据。 |
| 10-16 12:36:41，T62 合并 `0b79950ea70209cbd39ae4f34380075e4066e8a9` | [PR #278](https://github.com/anakine800-tech/Auto-Gaussian/pull/278)、[提交](https://github.com/anakine800-tech/Auto-Gaussian/commit/0b79950ea70209cbd39ae4f34380075e4066e8a9)；提交自身时间为 12:36:40 | 实现事实：三个命令新增 `ls -d` 分类，status 新增 unreadable 分支；其余五项不在本次调查范围。 |
| 10-16 16:09:47，#281 创建 | [PR #281 正文](https://github.com/anakine800-tech/Auto-Gaussian/pull/281)；[既有经验](../LESSONS.md#远程观察改动真实验证失败) | **现场回报的开发者转述**：运行中 PBS 作业的 `ag-start.json` 持续被 receipt 报 unreadable、看不到底层原因。没有现场原始 stdout/stderr、命令返回码或文件权限记录。 |
| 10-16 16:18:07，T65 回退 `bc024f6de2b856275931981a94efb81f3444d8af` | [提交](https://github.com/anakine800-tech/Auto-Gaussian/commit/bc024f6de2b856275931981a94efb81f3444d8af)、#281 diff | 实现事实：本次 `git diff f34f732 bc024f6 -- ag/src/ag/remote.py ag/src/ag/status.py ag/tests/test_core.py` 为空；删除 T62 的权限测试文件，保留 T47 测试与 T62 其余功能。 |
| 10-16 17:38:43，#281 验证评论 | [comment 6212639207](https://github.com/anakine800-tech/Auto-Gaussian/pull/281#issuecomment-6212639207)；运行版本 [36e6c1f](https://github.com/anakine800-tech/Auto-Gaussian/commit/36e6c1f6fe4f8f47f1d687372b66575c91e17a06) | **负责人转达监督方确认**：先对原异常对象观察一次，再对三个已提交对象各观察一次，均正常 running、输出增长、无 unreadable。只证明这些观察路径恢复；原始现场日志明确未附，不能据此作根因判定或科学验收。 |
| 10-28，当前 `e24a5bd…` | [当前 remote.py](https://github.com/anakine800-tech/Auto-Gaussian/blob/e24a5bd1d9045e3b783d8ef25f02e430ad4dc3c5/ag/src/ag/remote.py#L155)、[status.py](https://github.com/anakine800-tech/Auto-Gaussian/blob/e24a5bd1d9045e3b783d8ef25f02e430ad4dc3c5/ag/src/ag/status.py#L94) | 本次代码核查和本地复现。receipt、incomplete、read_receipt、outputs 与改前/回退版逐函数文本一致；普通 output 判断未变，但新增了 Multiwfn 专用循环，不能说整个文件与回退版一致。 |

可访问的两个 PR discussion 各返回一条上述评论，review 列表为空。没有取得带 `ag-review head=…` 的原始历史审阅评论；不把开发者“请复审”算作独立审阅通过。当前仓库未找到单独的 T65 任务文件，回退范围以 #281 的正文与实际 diff 为据。历史“合并后顺带使用研究对象验证”的安排仅作证据，不沿用为现行授权。

## 四版本命令与解析对照

以下只比较三个固定观察命令。`path_checks` 逐级执行 `test ! -L`，并不确认目录可进入；权限不足时它本身不能确证后续路径无链接。

| 路径 | 改前 f34f732 / 回退 bc024f6 / 当前 e24a5bd | T62 合并版 0b79950 |
| --- | --- | --- |
| receipt | `! -e` 为真即 `absent`；否则 `-f`、两次大小 ≤4096、中间 `head -c 4096`。无显式 `-r`，head 失败以非零返回。 | `LC_ALL=C ls -d -- <file> 2>&1` 成功后要求 `-f && -r`；否则为 unreadable。ls 失败只认英文 ENOENT 后缀为 absent，其余 unreadable。大小/head 失败仍走非零，未统一变成 unreadable。 |
| 普通 output | `! -e` 为真即 `<name> absent`，否则 `-f` 后 stat size/mtime。不验证内容可读。 | ls 分类与 receipt 同；要求 `-f && -r`，输出 `<name> unreadable`。 |
| incomplete | 先 `-d && -x` 检查父目录；存在时要求 `-f && -r` 再 stat；缺失时再次检查目标非链接与父目录可进入。失败非零。 | 相同父目录边界，ls 分类；无法核实输出 unreadable **并返回 1**。父目录不存在也拒绝，不能套用普通 output 的 absent 语义。 |
| 静态链接/非普通文件 | 已存在链接被 `path_checks` 拒绝；目录/FIFO 不能通过 `-f`。 | 静态链接同样非零拒绝；目录/FIFO 是 unreadable（incomplete 非零，其余返回 0）。 |
| 竞态 | 多次按路径查询，无打开前后文件身份绑定；receipt 的大小上限不检测同尺寸替换。 | 新增 ls/-r 不关闭该窗口。静态链接拒绝不等于读取时绝不跟随后来替换的链接。 |

当前 Multiwfn 循环同样使用 `test ! -e`（[源码 L191 起](https://github.com/anakine800-tech/Auto-Gaussian/blob/e24a5bd1d9045e3b783d8ef25f02e430ad4dc3c5/ag/src/ag/remote.py#L191)），权限误判在代码上同源；本次矩阵使用 Gaussian 合成 manifest，**未实际执行 Multiwfn 布局**。其他模板/调度器的文件名展开也不据此宣布全覆盖。

本地解析运行 48 例：4 版本 × receipt/output/incomplete × 正常、absent、零退出 unreadable、非零失败。实际函数由对应 Git 版本提取，Transport 只返回合成 `Result`，不创建 SSH 对象。

| 输入 | 三个非 T62 版本 | T62 |
| --- | --- | --- |
| 合法内容/元数据、rc=0 | 三路正常解析 | 相同 |
| `absent\n` 或各声明输出的 absent 行、rc=0 | receipt 返回 None；另外两路把相应项记为 None | 相同 |
| unreadable、rc=0 | ValueError，不能作为合法缺失/元数据 | receipt/output 抛 `_UnreadableObservation`；incomplete 仍 ValueError |
| rc=1，即使 stdout 看似有效 | `require_ok` 先抛 TransportError | 相同；实际 T62 incomplete 的 unreadable 即走此路 |

T62 的 `status.check` 在初次回执、输出及旧作业完成复核处捕获 `_UnreadableObservation`，返回旧状态附说明、追加 journal，不写 status.json；这是代码核查，原测试也覆盖这些分支。本次没有把整套历史 CLI/状态迁移重新跑一遍。当前版把 `absent` 接受为 None；如果两次输出均误报缺失且调度器仍为 R，按当前 `status.check` 的 60 秒稳定规则**可能进入 stalled**（代码推演，未做真实作业验证）。不能因此声称文件已丢失、作业完成或不完整取回能绕过检查。

stderr 的丢失点在远端命令内：T62 将 ls 的 stdout/stderr 收进变量，再只打印标记；外层可得到 `rc=0, stdout=unreadable, stderr=''`。`require_ok` 遇到 0 不抛异常，status 只得到文件名。这解释了“无法看到底层原因”的实现机制，但不能恢复当时被吞掉的具体诊断。现有 transport 的 stderr 脱敏/日志无法还原已被 shell 丢弃的内容。非零 stat/head 与 SSH 255 是不同路径，不能由一个 unreadable 词推定 SSH 故障或重试。

## 本次真实本地文件系统矩阵

环境：macOS / Darwin 25.6.0，非 root，`sh` 为 Bash 3.2.57，系统 BSD ls/head/test；未安装 GNU stat，未运行 Linux 容器或集群。目录与文件全部来自新建临时目录，路径 resolve 后无宿主临时目录链接干扰。文件归当前进程所有，不读取生产配置。

**元数据边界：**完整命令来自实际实现，仅 `stat` 通过 shell 函数适配：大小与错误来自本机真实 `stat -f %z`，mtime 用固定合成值补 GNU 格式。ls/test/head、chmod、内核 EACCES/ENOENT/ENOTDIR 均真实发生；这不是完整 Linux 命令验证，也不能验证 GNU stat 的输出格式。权限测试逐例核对 `os.access` 与 `Path.stat()` 的实际 errno，未用伪造 stderr 代替 OS 权限。

144 例 = 4 版本 × 3 命令 × 12 布局。下表把结果完全一致的改前/回退/当前压成一组；列顺序 R=receipt（ag-start.json）、O=output（首项 water.log）、I=incomplete（water.log）。O 的另一声明文件 job.pbs.out 为普通可读文件；父目录变化时两项一起受影响。

记法：`P0`=存在/返回0，`A0`=absent/0，`U0`=unreadable/0，`U1`=unreadable/1，`E1`=空 stdout/1。只有 `E1*` 有 stderr（head 的 Permission denied），其余本表 stderr 为空。

| 布局（case）与独立期望 | 实际有效权限/内核观察（R/O 目标一致） | 改前、回退、当前 R/O/I | T62 R/O/I |
| --- | --- | --- | --- |
| present：普通可读文件，应成功 | 父 x=true，文件 r=true，stat 成功 | P0 / P0 / P0 | P0 / P0 / P0 |
| missing：仅目标缺失，应 absent | 父 x=true，目标 r=false，ENOENT | A0 / A0 / A0 | A0 / A0 / A0 |
| file_000：文件 mode 000，读取应拒绝；元数据仍可能可见 | 父 x=true，目标 r=false，stat 成功 | E1* / P0 / E1 | U0 / U0 / U1 |
| parent_000：父目录 mode 000，不得确认为缺失 | 父 x=false，目标 r=false，EACCES | **A0 / A0** / E1 | U0 / U0 / U1 |
| ancestor_000：父目录上一级 mode 000，不得确认为缺失 | 父 x=false，目标 r=false，EACCES | **A0 / A0** / E1 | U0 / U0 / U1 |
| parent_missing：父目录确实缺失；严格 I 应拒绝 | 父 x=false，目标 r=false，ENOENT | A0 / A0 / E1 | A0 / A0 / U1 |
| not_directory：父目录位置换为普通文件，不应混同 ENOENT | 父 x=false，目标 r=false，ENOTDIR | **A0 / A0** / E1 | U0 / U0 / U1 |
| symlink：目标链接到临时目录内普通文件，应拒绝 | 父 x=true，目标 r=true，stat 跟随成功 | E1 / E1 / E1 | E1 / E1 / E1 |
| dangling_symlink：断链，应拒绝而非缺失 | 父 x=true，目标 r=false，stat 跟随 ENOENT | E1 / E1 / E1 | E1 / E1 / E1 |
| parent_symlink：父目录链接到同临时根下的保存目录，应拒绝 | 父 x=true，目标 r=true，stat 跟随成功 | E1 / E1 / E1 | E1 / E1 / E1 |
| directory：目标为目录，应拒绝 | 父 x=true，目标 r=true，stat 成功 | E1 / E1 / E1 | U0 / U0 / U1 |
| fifo：目标为 FIFO，应拒绝且不阻塞读取 | 父 x=true，目标 r=true，stat 成功 | E1 / E1 / E1 | U0 / U0 / U1 |

`file_000` 的 O=P0 仅表示取得元数据，不证明内容可读；单凭此项不另判“读取成功”的产品缺陷。现有 [test_incomplete_fetch.py](https://github.com/anakine800-tech/Auto-Gaussian/blob/e24a5bd1d9045e3b783d8ef25f02e430ad4dc3c5/ag/tests/test_incomplete_fetch.py#L297) 仍覆盖严格观察的权限边界，不能推断三个命令都获得了同等保护。

协调方旧 108 例使用 ag-exit.json 与合成 stat 元数据；本次使用 ag-start.json、真实尺寸适配，并增加断链、父目录链接、FIFO。原有九种布局的退出码/类别/stderr 有无逐项一致。回执两个固定文件名走同一判断模板，但这不等于原现场内容已复现。

## 错误文本与工具兼容性：合成测试

针对 T62 执行 30 例（3 命令 × 下列 10 种诊断）。只有 ls 被函数替换为输出指定文本、返回 2；父目录实际可进入，命令的其余 shell 结构仍执行。**这些不是 OS 错误、非英文系统或不同 GNU ls 版本的现场复现。**

| ls 合成诊断 | R/O 标记与 rc | I 标记与 rc |
| --- | --- | --- |
| `ls: cannot access <file>: No such file or directory` | absent / 0 | absent / 0 |
| 同上但文件名带单引号 | absent / 0 | absent / 0 |
| 只有 `No such file or directory` | absent / 0 | absent / 0 |
| `Permission denied` | unreadable / 0 | unreadable / 1 |
| `Input/output error` | unreadable / 0 | unreadable / 1 |
| 非英文“没有那个文件或目录” | unreadable / 0 | unreadable / 1 |
| ENOENT 后多句点 | unreadable / 0 | unreadable / 1 |
| ENOENT 后另起一行 warning | unreadable / 0 | unreadable / 1 |
| warning 在前，最后以英文 ENOENT 收尾 | absent / 0 | absent / 0 |
| 空诊断 | unreadable / 0 | unreadable / 1 |

30 例外层 stderr 均为空，因为命令替换已收集它。匹配依赖整个文本的尾部，不解析 errno；末尾多行/工具 wrapper 可能改变分类。普通 ls 的调用已显式 `LC_ALL=C`，因此不能仅以登录环境语言解释原事故；需要当时实际二进制/函数解析、shell、环境和原始诊断才能判断。已有带/不带引号样例能匹配，不能把文件名引号当作已证实根因。改前/回退/当前不用此 ls 文本分支，不受这项后缀匹配直接影响。

## 受控文件替换

8 例 = 4 版本 × 两种替换。完整 receipt 命令不改，只用本地 `head()` 包装函数在调用真实 head 之前，原子替换临时目录内的 ag-start.json。第一种替换为等长合法 JSON（作业标识相同，仅合成时间不同）；第二种换为指向同一临时目录内另一个合法 JSON 的链接。替换前所有 path_checks/-f/首个大小检查已执行，T62 的 ls/-r 也已执行。

所有版本两种情况均：返回 0、stderr 空、读得替换后的内容、lstat inode 变化。没有在其他目录放置或读取对象。此为**受控调度注入 + 真实本地替换/读取**，不是概率性并发压力测试；未验证任意父目录替换、远程文件系统或 GNU stat 行为。该现象表明“前后 ≤4096”不是文件身份核验；当前 parser 对同一合成作业与合法新时间仍能接受，不检查 inode。output/incomplete 也有多次路径查询窗口，但本次没有对这两路运行替换注入，不扩大声称。

## 原事故假设审计

| 假设 | 解释路径与必要前提 | 支持、反证与状态 |
| --- | --- | --- |
| 父目录权限/文件读取权限不足 | ls EACCES 或 `-r` 失败 → unreadable；要求当时确有不可进入/不可读条件 | 本地路径成立；没有现场权限、ACL、身份或诊断。回退可能只是隐藏未知，但恢复转达又报告回执可读。**可疑但未证实**，不能单一归因。 |
| ENOTDIR、EIO 或其他 ls 失败 | 非 ENOENT 后缀 → unreadable | ENOTDIR 本地真实复现，EIO 仅合成文本；没有原现场对应证据。**机制可解释，现场证据不足**。 |
| locale、工具包装或诊断格式不同 | 尾部不等于英文 ENOENT → unreadable | 非英文/尾部变化在合成测试成立；`LC_ALL=C` 削弱“仅因登录语言”的解释，标准两种引号格式无差异。未取得现场工具版本/实际诊断。**未证实**。 |
| 链接/文件替换 | ls 成功后、`-f/-r` 前换成非普通文件可能 unreadable；其他时序可能非零或读到替换内容 | 静态链接早在 guard 被拒绝，不能直接解释 rc=0 的 unreadable；receipt 读取窗口本地成立但输出不同。**不能据此解释原事故**。 |
| head/stat/GNU 格式或 SSH 故障 | 工具失败走非零，SSH 255 走 transport 错误/只读重试 | 与 T62 明确输出 unreadable 的两个分支不同；无原始返回码，不能排除转述省略细节。**单独不足以解释**，不新增远程试探。 |

## 最小后续范围与缺失证据

建议以已独立复现的“不可判断被记成缺失”为后续实施依据，不要求先找到历史根因：

- 限于 receipt、普通 output（明确检查当前 Multiwfn 分支）及其 status 解析/错误说明、相关离线测试。保留 incomplete 的可进入父目录要求与失败拒绝；不将 `parent_missing` 的普通观察行为机械复制给严格取回。
- 使用不依赖人类语言错误后缀的缺失/错误区分；无法核实不能追加虚假的稳定/缺失证据。诊断保留受限、脱敏的失败阶段与类别，不能把原始路径或私有 stderr 写进公开材料。具体实现须另单审阅，不在本报告预定新的通用抽象。
- receipt 的读取应绑定已检查的普通文件身份并拒绝链接替换；这项可在有明确范围的同单解决或单独开单。最小回归包括等长替换、检查后链接替换、超限/读取失败，不能只增加一次静态 `test ! -L` 后宣称原子安全。
- 测试至少覆盖上述十二布局、两种替换、三路解析的错误分支、旧状态字节与观察证据不误推进、真实 GNU 工具执行。对目标上可成立的权限场景核对实际有效权限；root 或特殊 ACL 使场景不成立时标跳过，不能伪造权限 stderr。

未来实施单须在合并前写清非研究验证对象、确切命令、允许读取的声明文件、执行版本、授权来源及预期分类。普通成功/缺失至少验证实际 `ag status` 路径；严格观察或 receipt 身份检查若有改动，分别验证其实际路径。需制造权限/替换布局时，另行明确批准非研究夹具的创建与每步动作；不修改现存研究/Attempt，不借现行禁止服务器改删的规则之外自行造现场。没有获批对象或安全夹具就记待验证、保留 draft，不用本地结果冒充通过。UNKNOWN、SSH 错误、哈希不一致、非预期作业状态或任何意外写入均立即停止报告，不重试或扩大查询。本调查未授权提交、取消、远程采样或部署。

无法追溯的历史部分：原故障那次实际执行的完整命令与 checkout/import 来源；原始 stdout/stderr/退出码；目标回执当时是否存在、是否普通文件、权限/ACL/有效身份；路径每级类型与可进入性；实际 shell、ls/stat/head 版本及解析方式；准确时序与是否发生替换。没有这些材料，不能区分“合法拒绝原有访问问题”与“工具兼容性导致误判”。本单不继续追索真实研究或扩大远程诊断。

## 重做方法与交付验证

下面两段 Python 是本次本地临时脚本的完整复现正文，保留在报告内以免新增产品诊断入口。只用于已读过本报告的开发者在本地临时目录运行；不要发送到服务器或替换 ag 模板。需要当前基线项目依赖、非 root macOS 环境、可读取四个 Git 对象；Linux 应另用真实 GNU stat 运行并记录为新的证据，不能照搬本次适配器冒充 Linux 结果。

从仓库根目录，将附录 A/B 分别保存到同一临时目录为 `reproduce.py` / `extra.py`；运行 `PYTHONPATH=ag/src python <临时目录>/extra.py`。B 会先运行 A 一次；A 输出 144 条矩阵到自身目录的 matrix.json，B 输出 48/30/8 条到 extra.json。所有夹具在临时目录创建、结束后本地清理，输出无真实身份或路径。命令生成提取历史函数，Gaussian 声明列表由当前 `ag.render` 提供（四版的 water.log/job.pbs.out 展开一致），不代表完整历史安装包重跑。

交付验证：`PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs` 为 **5974 passed、19 skipped（336.38 秒）**。18 项跳过需要 GNU/Linux stat、ps 或 procfs，交由 Linux CI；1 项私有日志 opt-in 未启用。暂存的两个文档通过有效私有词表扫描（0 errors）、`git diff --cached --check`，author/committer 均核实为 GitHub noreply；两段附录语法检查通过。本地开发者自审不能替代独立监督方审阅。真实验证状态：本单不适用、未执行；未来实施单仍待其自身授权与证据。

### 附录 A：文件系统矩阵

```python
import ast
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import tempfile
from types import SimpleNamespace

VERSIONS = ['f34f732', '0b79950', 'bc024f6', 'e24a5bd']
CASES = ['present', 'missing', 'file_000', 'parent_000', 'ancestor_000',
         'parent_missing', 'not_directory', 'symlink', 'dangling_symlink',
         'parent_symlink', 'directory', 'fifo']
FUNCTIONS = ['path_checks', 'contained', 'attempt_dir', 'filename',
             'receipt', 'output_names', 'output_observation', 'incomplete_output_observation']
# macOS only: real size and filesystem errors; mtime format is synthetic.
STAT = '''stat() { case "$2" in
  '%s') /usr/bin/stat -f %z "$4";;
  '%s %y') ag_size=$(/usr/bin/stat -f %z "$4") || return;
    printf '%s 2026-01-01 00:00:00.000000001 +0000\\n' "$ag_size";;
  *) return 99;; esac; }; '''
if os.geteuid() == 0:
    raise SystemExit('Requires a non-root process; do not report root permission probes')

def namespace(rev):
    source = subprocess.check_output(['git', 'show', f'{rev}:ag/src/ag/remote.py'], text=True)
    tree = ast.parse(source)
    funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in FUNCTIONS]
    from ag.study import identifier
    ns = dict(PurePosixPath=PurePosixPath, quote=shlex.quote, re=re, identifier=identifier,
              Command=lambda operation, text, timeout=60: SimpleNamespace(text=text))
    exec(compile(ast.Module(body=funcs, type_ignores=[]), f'{rev}:remote.py', 'exec'), ns)
    return ns

def command(ns, cfg, m, kind):
    if kind == 'receipt':
        return ns['receipt'](cfg, m, 'ag-start.json').text
    if kind == 'output':
        return ns['output_observation'](cfg, m).text
    return ns['incomplete_output_observation'](cfg, m, 'water.log').text

def category(text, kind):
    if not text:
        return 'empty'
    line = text.splitlines()[0]
    value = line.removeprefix('water.log ') if kind == 'output' else line
    return value if value in ('absent', 'unreadable') else 'present'

def probe(p):
    try:
        p.stat()
        return 'exists'
    except OSError as e:
        return errno.errorcode[e.errno]

def fixture(base):
    cfg = {'remote': {'ag_root': str(base / 'ag')}}
    m = {'study_id': 'water', 'attempt_id': 'water-001-sp',
         'remote_dir': 'water/water-001-sp', 'template': 'gaussian',
         'inputs': [{'name': 'water.gjf'}]}
    d = base / 'ag' / m['remote_dir']
    d.mkdir(parents=True)
    for name in ('water.log', 'job.pbs.out'):
        (d / name).write_text('data')
    (d / 'ag-start.json').write_text('{"PBS_JOBID":"123.fixture","started_at":"2026-01-01T00:00:00Z"}')
    return cfg, m, d

rows = []
for rev in VERSIONS:
    ns = namespace(rev)
    for kind in ('receipt', 'output', 'incomplete'):
        for case in CASES:
            with tempfile.TemporaryDirectory(prefix='t167-case-') as tmp:
                cfg, m, d = fixture(Path(tmp).resolve())
                target = d / ('ag-start.json' if kind == 'receipt' else 'water.log')
                blocked = None
                if case == 'missing':
                    target.unlink()
                elif case in ('file_000', 'parent_000', 'ancestor_000'):
                    blocked = {'file_000': target, 'parent_000': d, 'ancestor_000': d.parent}[case]
                    blocked.chmod(0)
                elif case in ('parent_missing', 'not_directory', 'parent_symlink'):
                    saved = d.with_name('saved')
                    d.rename(saved)
                    if case == 'not_directory':
                        d.write_text('not a directory')
                    elif case == 'parent_symlink':
                        d.symlink_to(saved, target_is_directory=True)
                elif case in ('symlink', 'dangling_symlink', 'directory', 'fifo'):
                    target.unlink()
                    if case == 'symlink':
                        target.symlink_to(d / 'job.pbs.out')
                    elif case == 'dangling_symlink':
                        target.symlink_to(d / 'missing')
                    elif case == 'directory':
                        target.mkdir()
                    else:
                        os.mkfifo(target)
                try:
                    effective = dict(parent_x=os.access(d, os.X_OK), target_r=os.access(target, os.R_OK),
                                     stat=probe(target))
                    if case in ('parent_000', 'ancestor_000'):
                        assert not effective['parent_x'] and effective['stat'] == 'EACCES'
                    if case == 'file_000':
                        assert not effective['target_r'] and effective['stat'] == 'exists'
                    p = subprocess.run(['sh', '-c', STAT + command(ns, cfg, m, kind)],
                                       capture_output=True, text=True, timeout=5)
                    rows.append(dict(version=rev, kind=kind, case=case, code=p.returncode,
                                     category=category(p.stdout, kind), stderr=bool(p.stderr), **effective))
                finally:
                    if blocked:
                        blocked.chmod(0o700 if case != 'file_000' else 0o600)
Path(__file__).with_name('matrix.json').write_text(json.dumps(rows, indent=2))
print('matrix scenarios:', len(rows))
for case in CASES:
    print(case, [[(r['code'], r['category'], r['stderr']) for r in rows
                  if r['version'] == rev and r['case'] == case] for rev in VERSIONS])
```

### 附录 B：解析、诊断与受控替换

```python
import ast
from datetime import datetime
import json
import os
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from ag.transport import Result, require_ok

ns = runpy.run_path(str(Path(__file__).with_name('reproduce.py')))
fixture, command, namespace, STAT = [ns[k] for k in ('fixture', 'command', 'namespace', 'STAT')]
out = {'parser': [], 'diagnostic': [], 'race': []}
for rev in ns['VERSIONS']:
    remote_ns = namespace(rev)
    env = dict(remote=SimpleNamespace(**remote_ns), require_ok=require_ok, datetime=datetime, json=json, re=re)
    for file, names in [('status.py', ['_UnreadableObservation', 'read_receipt', 'outputs']),
                        ('fetch.py', ['_presence'])]:
        source = subprocess.check_output(['git', 'show', f'{rev}:ag/src/ag/{file}'], text=True)
        tree = ast.parse(source)
        nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names]
        exec(compile(ast.Module(body=nodes, type_ignores=[]), f'{rev}:{file}', 'exec'), env)
    with tempfile.TemporaryDirectory(prefix='t167-parse-') as tmp:
        cfg, m, d = fixture(Path(tmp).resolve())
        for kind in ('receipt', 'output', 'incomplete'):
            for case in ('present', 'absent', 'unreadable', 'failure'):
                value = '4 2026-01-01 00:00:00.000000001 +0000' if case == 'present' else case
                raw = (d / 'ag-start.json').read_text() if kind == 'receipt' and case == 'present' else value + '\n'
                if kind == 'output':
                    raw = ''.join(f'{n} {value}\n' for n in remote_ns['output_names'](m))
                fake = SimpleNamespace(run=lambda _, raw=raw, case=case: Result(1 if case == 'failure' else 0, raw, 'synthetic error' if case == 'failure' else ''))
                try:
                    if kind == 'receipt':
                        result = env['read_receipt'](cfg, m, fake, 'ag-start.json', '123.fixture')
                    else:
                        result = env['outputs' if kind == 'output' else '_presence'](cfg, m, fake)
                    label = 'None' if result is None or all(v is None for v in result.values()) else 'parsed'
                except Exception as e:
                    label = type(e).__name__
                out['parser'].append([rev, kind, case, label])

DIAGNOSTICS = [
    'ls: cannot access <file>: No such file or directory',
    "ls: cannot access '<file>': No such file or directory",
    'No such file or directory',
    'ls: <file>: Permission denied',
    'ls: <file>: Input/output error',
    'ls: <file>: 没有那个文件或目录',
    'ls: <file>: No such file or directory.',
    'ls: <file>: No such file or directory\nwarning',
    'warning\nls: <file>: No such file or directory',
    '',
]
with tempfile.TemporaryDirectory(prefix='t167-messages-') as tmp:
    cfg, m, d = fixture(Path(tmp).resolve())
    for kind in ('receipt', 'output', 'incomplete'):
        for i, diagnostic in enumerate(DIAGNOSTICS):
            fake_ls = 'ls() { printf "%s\\n" "$T167_DIAGNOSTIC" >&2; return 2; }; '
            p = subprocess.run(['sh', '-c', STAT + fake_ls + command(namespace('0b79950'), cfg, m, kind)],
                               capture_output=True, text=True, env={**os.environ, 'T167_DIAGNOSTIC': diagnostic})
            out['diagnostic'].append([kind, i, p.returncode, ns['category'](p.stdout, kind), bool(p.stderr)])

for rev in ns['VERSIONS']:
    for replacement in ('regular', 'symlink'):
        with tempfile.TemporaryDirectory(prefix='t167-race-') as tmp:
            cfg, m, d = fixture(Path(tmp).resolve())
            target = d / 'ag-start.json'
            original = target.read_text()
            changed = original.replace('2026-01-01T00:00:00Z', '2026-01-02T00:00:00Z')
            assert len(original) == len(changed)
            other = d / 'synthetic-other.json'
            other.write_text(changed)
            substitute = d / 'substitute'
            if replacement == 'symlink':
                substitute.symlink_to(other)
            else:
                substitute.write_text(changed)
            inode = target.stat().st_ino
            mutation = 'from pathlib import Path; import sys; Path(sys.argv[1]).replace(sys.argv[2])'
            hook = 'head() { ' + ' '.join(map(shlex.quote, [sys.executable, '-c', mutation, str(substitute), str(target)])) + '; command head "$@"; }; '
            p = subprocess.run(['sh', '-c', STAT + hook + command(namespace(rev), cfg, m, 'receipt')], capture_output=True, text=True)
            out['race'].append([rev, replacement, p.returncode, p.stdout == changed,
                                target.lstat().st_ino != inode, bool(p.stderr)])
Path(__file__).with_name('extra.json').write_text(json.dumps(out, indent=2))
for k, values in out.items():
    print(k, len(values))
    print(values)
```
