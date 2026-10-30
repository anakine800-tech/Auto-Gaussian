# 自主短卡：离线演练与首个试点验收

2026-10-30 更新。首个试点关闭自主取消、停止核验及取消/改投后继路径；需要时只提醒负责人。已结束且确认失败的作业仍可按规则新建 Attempt 补救。短入口见[自主运行卡](autonomous-run.md)，本页不启用真实计算。

现行 main 的自主能力仅为本地计划、租约和状态记录，提交路径尚未合并。研究会话不能据 AGENTS、候选分支或离线结果尝试自主提交。T186 已固定为 `e2c499415ecb2932752e394c117e280ef64ea90a`，本页已核对其实际 CLI、关闭与提醒语义；最终跨功能组合仍须在真实验证前完成。试点不依赖 T187。Slurm 自主取消/改投移出 V4.8，PBS 留待试点后交付。

## 首个试点验收

关键路径：T185、T186（不含取消）、T190 定稿 → 最终组合验证 → Claude 审阅敏感提交路径及处理意见 → 提交路径合并前真实验证 → T198 非研究试点。放宽输入如纳入范围，仍须完成 T188 对应审阅与验证。真实验证和试点各需具体授权，本轮未执行。

| 项目 | 验收要求 |
| --- | --- |
| 取消需求 | 分支标“需要你看”；简报第一行提醒负责人在 Mac 上点击取消，列原 Attempt、所属集群、理由和证据不足处；远程取消调用数为 0 |
| 改投需求 | 即使排队时间及更优候选满足旧条件，也只按上行提醒；不调用停止核验、不准备或提交取消/改投后继；远程取消调用数为 0 |
| 入口实际关闭 | 最终组合相关测试证明取消、停止核验及后继路径被关闭；旧计划/规则也不能放行。文档文字或未调用不能代替内核拒绝证据 |
| 已结束失败的补救 | 正式结束及失败证据、有效计划/规则、无全局暂停，才可新建 Attempt；同对象同失败最多两次，每次一个最小改动并复验；原 Attempt/声明不重用 |
| 补救拒绝 | 仍运行、UNKNOWN、仅解析失败、第三次同类补救、取消/改投后继不能进入上述补救路径；不改名清零，不因提醒或回执释放占用 |
| 状态与取回 | 唯一 owner；暂停观察、过期观察、60/90 分钟边界与失权不发布；facts 五类返回按卡片分支处理，冲突不 refresh/reparse |
| 预算与路由 | 实际提交消费不与 prepare 意图重复计数；90% 暂停；全机跨 study/轮次额度与账号核数核验；不为普通提交新增取消适配版本门槛 |
| 科学审阅与报告 | 中间判断逐条待人确认，不代替三类签字；简报一页以内，只列完成、阻塞、需负责人决定事项，详细证据私有归档 |

本轮已完成卡片分支走读，以及下节固定 T186 的 CLI/本地提醒和 44 项相关行为核验。单独 T186 的局部证据不替代最终 T185/T186 等组合；T185 接口未变时不为本次文档提前重跑组合。开发中仅跑相关测试，不做 AST 比对；全量只在 CI，以及真实验证前对最终源码组合执行一次。

## 固定 T186 的本轮核验

从上述确切提交独立归档源码，605 文件在核验前后哈希未变，未混入 T187、T185 或 T206/T207。临时 Git 快照仅供本地版本记录，源码身份以原提交和文件清单绑定。实际执行 20 项帮助、9 次本地状态命令，以及 2 次旧自主取消参数的预期拒绝：

- init → plan → 合成 confirm/begin → start → update 保留原分支 → update 加入提醒 → status → finish。正式 plan 接受本模板字段；合成零哈希仅测试解析，不断言真实 T185 路由身份。
- status 原样读回 summary 第一行的 Mac 点击提醒、pending 和对象条目，其他分支未丢失。网络/Transport 调用尝试 0、Attempt 目录 0、study.md 未变；没有真实配置、放行规则或生产动作。
- cancel 的旧 owner 参数与停止核验参数在配置加载前退出 2；没有打开确认框、建立 Transport 或发出取消。普通 cancel 仍保留人工确认入口，不能将它当作自主会话的替代路径。

44 项现有相关测试通过：prepare/submit 旧改投参数和上下文拒绝；旧 reservation/取消记录不释放占用、不成为补救来源；Slurm CANCELLED 不按普通失败处理；已结束失败证据分类及 UNKNOWN/成功/冲突拒绝；正式不完整失败取回；计划字段与方法约束。包含 SCF=13 和重复列表的实际接受用例。部分用例使用固定路由选择器替身，只验证 T186 相关行为，不声称复验 T185 算法。没有运行完整 driver 组合或全量测试。

| 本轮私有证据索引 | SHA-256 |
| --- | --- |
| 20 项 `help.json` | `87be12442953f96e3ec99f150f653027960f48ff995254daed66d2f2abfc03fe` |
| 9 次状态命令与 2 次拒绝 `commands.json` | `13636d19ab04cd52f4387931446a649411f2b7864e25b8d167573e1cfa02e24f` |
| CLI/提醒 `report.json` | `1d25d76eb19cbcf1e3046929e1bb8a2f9722e27c36cd00a8f15285af72aaa7e7` |

上述测试日志、输入、脚本及源码清单私有归档。T186 任务单另报告无 T187 的 13 项提交/补救组合，本轮没有重复执行，也不将其算入上述 44 项。

## 合成分支逐项走读

下表为合成条件及本轮按新卡作出的选择，不是真实集群输出或可直接写入 state 的 schema。没有调用 prepare/submit、远程 status/snapshot/fetch、cancel 或停止核验；“保存/暂停”表示有有效 owner 时将使用正式本地入口，不在本轮改写任何真实 study。

| 合成输入 | 所走分支与理由 |
| --- | --- |
| 无变化；round 已 ended | 无变化正常 finish；已结束则直接退出，不自动 begin 或重开预算 |
| paused 或计划到期，仍有 running Attempt | 只在正式观察租约允许时观察/取回；不 prepare/submit/补救；失权即停止发布 |
| finished；facts=written/unchanged | 取回事实后按原科学卡片审阅，成功解析不等于科学接受 |
| facts=conflict/skipped/failed | conflict 保留双方来源并交人；skipped 核对原因；failed 记录解析阻塞；均不能仅据此补交 |
| 快照缺失/过期，或只有文件大小不变 | 不当作零进展，不放行依赖动作；连续两 wake 过期由模型按留存来源判断后 pause |
| UNKNOWN，列表为空或出现取消不确定记录 | pause，保留原占用/声明及证据，交人核对；不替代提交、不重试取消、不调用关闭的停止核验入口 |
| 两 wake SSH 失败；同 wake 三个不同对象同失败 | update/status 保存恢复 wake、对象、来源及成功/失败结果，模型计数后 pause；重复对象不增加计数，不宣称内核自动聚合 |
| 两个不同 wake 的已有快照均显示疑似无进展 | 分支“需要你看”；首行写“请负责人在 Mac 上点击取消”，附原绑定及理由；不为此追加远程查询，取消调用 0 |
| 未运行、排队 ≥6 h、无 chk、存在更优候选 | 仍只提醒负责人 Mac 点击取消；不改投、不查取消停止、不建立后继，取消调用 0 |
| 已有人工作业取消回执，或旧规则曾允许取消 | 不能借回执/旧规则恢复关闭路径；保留占用与证据并交人，停止核验和后继调用 0 |
| 作业已正式结束并确认失败，已有 0 或 1 次同类补救 | 在计划/规则内选择一个最小改动，拟新建 Attempt；复核预算/资源/字节及授权，原 Attempt 不重复提交；本轮不执行 |
| 相同对象同失败已有 2 次补救；作业仍运行；仅解析失败 | 分别拒绝第三次、拒绝未结束补救、拒绝把解析异常当计算失败；分支交人，其他分支仅在无全局暂停时继续 |
| TS 极小点或目标方向错误 | 最终组合中先记录来源绑定的科学失败证据，判断待人确认；只有作业已结束且其余补救条件成立才拟新 Attempt |
| 放宽输入获得计划/规则允许 | 仍需对应实现、审阅与验证；逐次提醒跳过项和“方法口径未核验”，不因可提交接受科学结果 |
| 实际提交 9/10，另有 prepare 意图 | 90% 暂停，不重复扣意图、不通过新 wake 或改名清零 |
| 60 分钟到点、旧 owner 或未满 90 分钟接管 | 停止发布；接管只按正式租约规则，不改 token 续权 |
| 目标量齐但签字缺项 | 保存全部待确认判断和签字缺项，暂停推进，不宣称 study 完成 |

取消/改投分支的首行示例为：“需要你看：请负责人在 Mac 上点击取消 `<原 Attempt>`（所属集群 `<配置入口>`）；原因 `<已有证据与不确定性>`。本次未执行远程取消。”这是提醒模板，不是发给 CLI 的批准记录，也不触发自动后继。

## 接口核验与缺口

本节参数来自固定 T186 的实际帮助；每行入口均为 ag 子命令，不能把不同入口的参数混用。这里只说明候选源码接口，不构成研究执行指令或 main 已可用声明。T206/T207 单列其来源，不从旧组合恢复取消、停止核验或后继参数。

| 入口 | 当前核验状态及文档处理 |
| --- | --- |
| autonomy start | `--study --plan --owner`；暂停/到期观察加 `--observe-only`，接管加 `--takeover-reason`；结束 wake 不重置 round 额度 |
| autonomy update | `--study --run --token --input`；没有 `--plan-sha256` 参数，正式入口核对当前计划/owner，三项状态整体替换 |
| autonomy check / finish | check 用 `--study --run --token --sha256 --for-action`，注意这里不是 plan-sha256；finish 用 study/run/token/reason |
| prepare / submit | 成组提供 `--autonomous-policy --run --token --plan-sha256 --object-id --job-class`；补救可声明 `--failure-class`，省略或改名不能绕过从正式证据得到的分类；不再接受 reroute-source |
| prepare 的其余输入 | 仍需 study/template、各模板所需输入、walltime/label/method-basis、所选 cluster/资源及必要父来源；本表不替代完整帮助。T188 放宽标记须按其实际集成另核对 |
| status / snapshot / fetch | `--run --token --plan-sha256` 成组；status 可选 id 或 study，snapshot 接 id，可加 study/max-bytes；fetch 接 id，不带 study，可按实际结束证据使用 incomplete |
| route 配置身份 | `--config-identity --json`，不能混入路由参数；需要实际 T185 身份算法，缺失则拒绝。本轮仅核对帮助，不重跑 T185 组合 |
| route 自主建议 | `--study --template --job-class --round-id --run-id --object-id --walltime --autonomous-policy --token --plan-sha256`；这里用 run-id，CREST/xTB 另需 tier，Gaussian 阶梯不带 tier |
| autonomy scientific-review | `--study --attempt --run --token --plan-sha256 --object-id --outcome --reason`；outcome 为 ts_zero_imaginary/ts_wrong_mode，后者另需已有 mode-review 报告；判断仍待人确认 |
| study.md 摘要发布 | T206 `6e1523fe00299f03acf93043bd5873c5bf2bb824` 的 publish-study 已读源码及帮助；从已有 summary/pending 发布固定区块，要求 run/token/plan-sha256；未作为当前 main 能力使用 |
| facts、review init/manifest、mode-review | T207 `aa67c55e0ffb2801cba63de5ee61e5731f1cc70b` 已读源码及帮助；owner 三参数须成组，最终发布沿用 state-dict guard；review check 仍只读、不带 owner |
| 自主取消、停止核验、取消/改投后继 | 无自主执行命令；cancel 仅接 id/json 并保留 Mac 人工确认。旧 owner/停止核验参数被拒绝，旧改投上下文也不能重新开启后继；自主会话只提醒 |

已在隔离合成 study 执行的提醒保存形状：

```sh
ag autonomy update --study '<S>' --run '<R>' --token '<T>' --input '<UPDATE_JSON>'
ag autonomy status --study '<S>' --json
ag autonomy finish --study '<S>' --run '<R>' --token '<T>' --reason '<提醒已保存>'
```

UPDATE_JSON 只有 summary、pending、objects，summary 第一行是上节 Mac 点击提醒；读取旧值后保留未完成分支。这些命令只保存/读取本地记录，不执行取消或提交。

T206/T207 在 T186 合并后改以 main 为基准并复核增量；目前不把固定分支帮助当成已经集成或部署。摘要发布须先 update、再正式发布、最后 finish/end；不接任意正文或路径，人工改动/来源变化/失权拒绝，update 与文档发布不是跨文件原子事务。独立 facts 不自主 refresh/reparse；review manifest 不能自主接受未解决引用，骨架或模式报告不代替科学签字。依赖写入口尚未集成时将待办保存在正式状态，不能直接编辑 state/journal 或用普通编辑器绕过 owner 保护。

跨 wake 失败计数继续由模型依据 update/status 中的可追溯来源判断，再调用 pause，不要求新的聚合接口。逐类耗时/试点标志保存在已有计划文本，不自创结构化字段。

## 历史来源与证据边界

以下均为 2026-10-29 的离线记录，保留用于追溯；完整输入、命令、帮助、输出、脚本、源码及哈希清单已私有归档。详细公开旧记录在本 PR 前序提交 `07ffeec7c18a72e1e8120e2a90fa2eb32f8e7948`。旧取消/改投测试不再是本版验收，也不证明现场兼容。

| 组别 | 固定来源与已执行范围 |
| --- | --- |
| 主线本地记录 | `8ff90e3bcf5f8b99542b2425c65fa09af6bcafb5`；21 项帮助、26 次生命周期（6 次预期拒绝）、另 20 次跨 wake 保存/恢复；无网络、无 Attempt、study.md 未改 |
| 旧四源组合 | T185 `47ac89867132d5271c996f6d56183f1935011af8`、T186 `b8167ee74282ac3a28004969630574b8d31d5b2b`、T187 `80e959938c8888bf1aefe853be43ca276fd81439`、T188 `9bbebcc527d6864c79b7fd02a37599a332c3bdac`；437 文件聚合 `8c90dbe3bc98e985bacb479e85644141c3253510fd62535e16c6678715282c17` |
| 旧组合执行记录 | 32 项帮助、31 次本地 CLI（7 次预期拒绝）、247 项针对性回归；协调方 8826 passed/26 skipped 全量另存，不能算作 T190 重跑或最终组合已通过 |
| 首次取哈希增量 | T186 更新至 `dcf71f026ed9f35603803608185c1c22707d914e`，其余三源不变；437 文件聚合 `a00c4d59f0ca9ab1cc6e3cd85f3763ff3598f41946de415d31dd2b301ae79099` |

旧回归使用真实本地解析/锁/状态与合成 FakeTransport；没有真实提交、取消、改投、查询、配置修改、部署或定时任务。三组来源独立保留，不能用组合 Git HEAD 冒充全部来源。私有归档的 `SHA256SUMS` 哈希为 `1a80a7de67d51620b0a8b988e0ee08dc4e1364b40763a2ab418ad8b0d7544aa6`，不在公开文档写归档绝对路径或临时令牌。

## 首次路由身份补充验证

历史增量实际执行 2 项帮助、7 次本地 CLI（1 次预期混参拒绝）：配置身份 JSON、文本、重复查询，再将真实返回哈希放入[字段模板](autonomous-plan-template.md)，由正式 plan 解析。只替换临时配置位置，不替换实际 T185 身份算法；协调方另有 237 项增量报告，含六项真实身份配对/配置变化测试，均仅绑定该历史来源。

**无写入仅指取哈希阶段**：无计划/规则/monitor，文件及目录未变，写操作、锁、监控、进程与网络尝试 0。后续 init/plan/status 正常写隔离状态、计划及本地锁；未 confirm/begin/start，未写规则。初次夹具误将正常锁文件视为规则文件，修正断言后完整通过，未改产品代码。

该组 report SHA-256 为 `f85c536f61da9e38b669f2b58dbfd21692c62eb072718fd7ffaa06a10397f9c0`。另于 2026-10-30 只读核对 T206/T207 六项帮助，均退出 0；帮助记录 SHA-256 为 `0c82dcc72c0a4bed474b69cd94980b7c6b7f462da3ca4d9b6e799330101c37d0`，不代表两个候选已完成最新组合行为验证。
