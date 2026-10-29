# 自主短卡：离线唤醒演练

2026-10-29 的合成走读与真实本地记录。未连接集群，未提交、取消、改投、安装、部署或建立定时任务；本页不证明现场兼容、科学正确或自主启用。短入口见[自主运行卡](autonomous-run.md)。

## 来源和验收状态

| 来源 | 固定提交 / 状态 |
| --- | --- |
| 当前主线及 T184 | `8ff90e3bcf5f8b99542b2425c65fa09af6bcafb5`，本地生命周期已演练 |
| T185 | `47ac89867132d5271c996f6d56183f1935011af8` |
| T186 | `b8167ee74282ac3a28004969630574b8d31d5b2b` |
| T187 | `80e959938c8888bf1aefe853be43ca276fd81439` |
| T188 | `9bbebcc527d6864c79b7fd02a37599a332c3bdac` |
| 四源组合 | 按 `frozen-combination-manifest.json` 与 `source-snapshot.before.json` 的文件映射逐项核验；437 文件聚合 SHA-256 为 `8c90dbe3bc98e985bacb479e85644141c3253510fd62535e16c6678715282c17` |
| 首次路由身份增量 | T186 `dcf71f026ed9f35603803608185c1c22707d914e`；其余三源不变。437 文件聚合为 `a00c4d59f0ca9ab1cc6e3cd85f3763ff3598f41946de415d31dd2b301ae79099`；只适用后述增量验证，不重标旧全量结果 |

组合来源由协调方固定，T190 在独立临时副本演练，未改动协调方全量测试检出。副本本地快照提交 `8ce2230ab7f30d19b047d64cd19d12387f8eb74d` 只使计划能记录干净源码，不单独代表四个源提交；来源以完整文件映射为准。全部离线结果均不代替敏感路径的现场验证。

## 已执行的主线本地演练

实际版本：ag `4.7.0`，上述主线提交，ag 源码 `dirty=false`；Python `3.11.15`、RDKit `2026.3.3`、GoodVibes `4.3.0`。没有修改或安装依赖。

使用仓库外临时 `synthetic-water` study 与只含 `local.studies_root` 的临时配置。直接进入实际 CLI；测试夹具只将 CLI 配置加载绑定到该文件，并拦截 SSHTransport、socket 和非 git 子进程。计划/轮次原话显式标 `SYNTHETIC FIXTURE ONLY`，不是真人运行批准。时间边界段只替换时钟，其余版本、解析、文件锁、日志和状态发布使用真实实现。

21 次实际 `--help` 均退出 0：autonomy 的 init、plan、confirm、begin、status、start、check、update、pause、resume、finish、end、recover，以及 status、snapshot、fetch、facts、prepare、submit、cancel、route。这里验证的是主线帮助；绝不据此声明新增组合选项存在。

以下命令形状均来自上述实际帮助；尖括号在演练中由返回的 ID/哈希和合成文件替换，令牌不公开：

```sh
ag autonomy init --study '<S>'
ag autonomy plan --study '<S>' --input '<PLAN_JSON>'
ag autonomy confirm --study '<S>' --plan '<P>' --sha256 '<H>' --quote '<合成确认原话>'
ag autonomy begin --study '<S>' --plan '<P>' --quote '<合成新轮次原话>'
ag autonomy start --study '<S>' --plan '<P>' --owner '<SESSION>'
ag autonomy status --study '<S>'
ag autonomy update --study '<S>' --run '<R>' --token '<T>' --input '<UPDATE_JSON>'
ag autonomy pause --study '<S>' --reason '<原因>'
ag autonomy check --study '<S>' --run '<R>' --token '<T>' --sha256 '<H>' --for-action prepare
ag autonomy check --study '<S>' --run '<R>' --token '<T>' --sha256 '<H>' --for-action observe
ag autonomy resume --study '<S>' --run '<R>' --token '<T>' --reason '<合成明确恢复>'
ag autonomy finish --study '<S>' --run '<R>' --token '<T>' --reason '<本次结束>'
ag autonomy end --study '<S>' --round '<ROUND>' --reason '<本轮结束>'
ag autonomy start --study '<S>' --plan '<P>' --owner '<NEXT>' --takeover-reason '<过期接管原因>'
```

共 26 次本地命令，其中 6 次预期拒绝；结果如下。无报错被改写为成功。

| 实际输入/顺序 | 实际输出与对短卡的检验 |
| --- | --- |
| init → plan → confirm → begin → start | 未确认计划与授权轮次分开；记录新 round/run，尚无 Attempt |
| 同状态再 status | study 内全部文件哈希不变；`submission_counts_verified=false`，不能把意图当实际提交数 |
| update 写入合成 facts 冲突分支 → pause | `phase=paused`，待决定事项保留；仅保存判断，不写 facts |
| paused 下 check prepare / observe | 前者退出 1：`Autonomy is paused or ended; new actions are blocked`；后者退出 0 |
| finish → 再 start | finish 留 `phase=paused` 且 lease 为空；新 wake 沿用同 round、summary/pending，预算未新开 |
| 旧 run/token 再 check | 退出 1：`Stale or incorrect run owner` |
| 合成明确 resume → finish → end → start | end 后 start 退出 1：要求明确 begin；不会由唤醒自动开始新轮 |
| 新合成轮，开始后 3599 / 3600 秒 check | 3599 秒通过；3600 秒退出 1，不能续权 |
| 5399 / 5400 秒显式 takeover | 5399 秒拒绝：`Another run holds the lease`；5400 秒取得新令牌，旧令牌 check 再拒绝 |
| 新 owner finish → end | 正常收尾；整个合成 round 为 ended |

成功演练记录：网络/Transport 尝试 0，Attempt 目录 0，study.md 字节未变。夹具早期曾因配置注入位置错误退出；成功记录使用 CLI 实际加载点，不把失败预跑计入以上 26 次。保留的原始本地文件含临时路径和令牌，不提交；本页提供可公开的输入形状、输出和校验摘要：

| 本地证据文件 | SHA-256 |
| --- | --- |
| `help.json` | `0797c0868f95e2b0a223326616440f1b77614c9d886932740cd46724b23f2bf4` |
| `local-commands.json` | `4d30a04a85be9f11c971b585f9febe9d93f5f37d363531449c517f117809907c` |
| `report.json` | `b3196e20ad016bdf2b717065b93d31e1d358821f06757e62e1b90ee820aa4fd8` |

### 跨 wake 证据保存的补充实测

同一主线版本又执行 20 次正式本地 CLI 命令，网络尝试和 Attempt 均为 0。合成源文件显式标 `synthetic=true`，将文件名/SHA-256 随观察结果放进 update 的 `objects`；不是让模型写内核消费字段。实测顺序为：

1. 第一 wake 保存 SSH 失败/监控过期及其来源，finish；第二 wake start 后 status 原样恢复第一份记录。
2. 第二 wake 保存同类合成失败及不同 run ID，模型选择“两次连续失败”分支后调用 pause；status 返回 paused 且两份来源仍在，finish 不丢记录。
3. 另一个合成 wake 显式恢复用于独立场景，保存 water-a、water-b、water-c 三个对象的同类失败，water-a 另有重复报告。模型按三个不同对象判断，调用 pause；status 保留全部旧观察和三对象来源，随后 finish/end。

这证明正式 update/status/pause 足以承载卡片判断及恢复，不证明内核会自动数数。成功观察也应在同一记录中保留，用于中断连续失败；只留失败消息会误把不连续失败当连续。具体来源无法读取或核验时不能推进依赖动作。

补充记录 `commands.json` SHA-256：`1694f3cbabc6d6ee8ca18ffaf8d487860ff22e9be1dc51143823a43d9394ce99`；`report.json`：`55016934694b035ba5999bd3bf93b929bb4e2f8fd74502cfbb930a3f1d2f8be0`。原始文件仍只保留本地，版本与上节一致。

## 本次固定组合的实际验证

在上述 437 文件一致的独立副本中重新执行，ag `4.7.0`、Python/RDKit/GoodVibes 版本同主线演练。本地快照 commit 只用于记录副本，四源身份仍按文件映射。通过测试专用 `Path.home` 隔离机器级台账；不改进程 HOME、不读取实际放行配置、不安装依赖。

- **32 次实际帮助**：前述 21 项，加 autonomy 的 scientific-review/manual-writers/release-writer，以及 autonomy 总入口、review 总入口及 init/check/manifest、mode-review、clusters、capacity。全部退出 0；下节逐项列出 owner 参数与例外。
- **31 次实际本地 CLI**（7 次预期拒绝）：重跑生命周期，并从本计划模板读取 submission_policy、仅替换合成路由哈希与有效期后由正式 plan 接受。保留真实版本和不可变计划；新加计划过期后 pause → start 的 observe-only → check observe 通过 / check prepare 拒绝 → finish/end。60/90 分钟和计划过期使用合成时钟，其他逻辑真实。网络/Transport 尝试 0、Attempt 目录 0、study.md 未变。
- **247 项现有回归通过**：207 项动作/发布/放宽输入回归，23 项自动 facts 回归，17 项实际提交预算与放宽输入规则回归。使用真实本地状态、声明、文件、解析器和正式函数/CLI，调度器响应与传输为合成 FakeTransport；不声称真实集群提交、取消或改投已跑通。

| 分支 | 实际回归证据入口（固定组合中的现有测试） |
| --- | --- |
| 正式改投、同实例停止、单次后继及跨 study 旧占用 | `test_autonomy_submission.py::test_actual_reroute_stop_and_single_successor`、`test_autonomy_cancel.py::test_real_reroute_stop_successor_with_other_stopped_study` |
| 取消 accepted 未停止 / UNKNOWN 不释放，不重试；候选不匹配、90% 预算拒绝 | `test_real_reroute_unstopped_source_keeps_occupation`、`test_real_reroute_candidate_policy_is_checked_before_cancel`、`test_real_reroute_ninety_percent_consumption_pause_refuses_cancel`、`test_driver_unknown_never_releases_or_retries` |
| start=end 的正例与有正向运行反证的拒绝 | `test_stopped_accepts_bound_terminal_instance_and_records_race_boundary`、`test_stopped_reroute_rejects_positive_runtime_even_with_equal_start_and_end` |
| 无进展取消、超时/取消后正式不完整取回、TS 科学失败 | `test_actual_no_progress_cancel_and_bounded_successor`、`test_formal_incomplete_fetch_is_a_bounded_terminal_remedy`、`test_normal_ts_review_is_bound_pending_and_uses_same_failure_class` |
| 失权后取回/facts 不发布；有效 owner 可发布；第三次补救拒绝、全机四作业额度 | `test_fetch_publication_refuses_owner_lost_during_download`、`test_auto_facts_never_swallows_owner_loss_or_writes_error_journal`、`test_current_observer_publishes_fetch_and_facts_only_inside_guard`、`test_third_actual_remedy_rejects_before_new_reservation`、`test_driver_cross_root_competitors_reserve_only_fourth_global_job` |
| 自动 facts 的 written/unchanged/skipped/conflict/failed | `test_fetch_facts.py` 全部 23 项；保留旧 facts 的字节/mtime/来源，解析失败不倒退成功取回状态 |
| prepare/旧意图不额外消费；实际提交不可重用 | `test_autonomy.py` 的四项实际 prepare/submit 消费测试：`test_actual_prepare_guard_does_not_spend_legacy_intent_budget`、`test_actual_prepare_with_full_intent_count_keeps_submission_budget`、`test_actual_prepare_still_rejects_consumed_submission_budget`、`test_submission_consume_is_separate_from_intents_and_never_reusable` |
| 放宽输入仍守方法/收敛边界 | `test_gaussian_relaxed.py`、`test_relaxed_attempt.py` 及 `test_autonomy_policy.py` 六项 allow_relaxed/收敛下限测试 |

回归前后独立副本与原组合文件映射均无变化。另读取协调方全量报告：8826 passed、26 skipped，退出 0，before/after 均为上述 `8c90dbe3…5282c17`，源码与两来源工作树无漂移；这是协调方全量证据，不是 T190 重跑一遍。

| 本地组合证据 | SHA-256 |
| --- | --- |
| 24 项核心帮助 `help.json` | `7e318fe541b708384bb9a1b5b5439fe0d941f1d06dcce1dec2e56f0e59f5e4e4` |
| 8 项补充帮助 | `6a8e131cdc9f79e70d8a3fc84705efdf4bdc6c9a816e81ef1bf704951437fef5` |
| 31 次 `local-commands.json` | `41a331bb269cb59932100228e75d13738089260e4719f692bdf18a3ec24ed906` |
| 本地命令 `report.json` | `71ba072c9c8e996a8a9987abe057f3ee5ba0e62f8c2c3f3eea6afa113a886b43` |
| 207 项动作回归日志 | `51a922e552fce7465d3b9c41d55f5de444c0c02d1416fe86955585930475cba6` |
| 23 项自动 facts 回归日志 | `57db95297ddd2c289d1ea14e7fb46bf5954a7f6cd993160e08194eb5cbfde281` |
| 17 项预算/放宽规则回归日志 | `54d80847ae8ea43bc4ad57b947abe2be10e22c1aadc4db77669f324db06c4807` |
| 协调方全量结果摘要 | `71791e42c483ca8442b7af08e3aab086597bc9ad0bc4e1c41d0f52247cf11b25` |

## 首次路由身份补充验证

对上述增量组合另建独立副本，前后核对全部 437 文件无漂移；本地干净快照 `a99532965d897a52f0f5f5df11a99f36f206c7fd` 仅用于版本记录。与旧映射相比，受测源码只变 route.py 与 test_route.py；保留旧组合及其 247 项/全量证据，不重复执行或扩大它们的适用提交。

实际执行 **2 次帮助、7 次本地 CLI（1 次预期拒绝）**：route 与 autonomy plan 帮助；route 的 config-identity JSON、文本、重复 JSON 查询；混入 template 参数拒绝；随后在隔离合成 study 中 init → plan → status。取哈希前不存在 study、计划、规则或监控快照；只把正式配置加载器指向临时合成配置，不替换身份算法。三个成功查询均与实际 T185 身份函数一致，返回值原样写进本模板的 submission_policy，由正式 plan 完整解析并保存。

取哈希阶段拦截文件写入、创建/改名/删除、锁、监控/路由选择、进程及网络，调用尝试均为 0，文件字节和目录集合前后相同。后续 init/plan/status 按设计写本地状态、计划及 `autonomy-submit.lock`；不把这一阶段说成无写入。完整演练网络/Transport 尝试 0、Attempt 0、study.md 未变、规则文件 0，未 confirm/begin/start。夹具初次误把 status 正常创建的锁文件当成规则文件；修正这一断言后完整通过，不修改产品代码。

另核对协调方增量报告：237 passed，退出 0，前后映射均为 `a00c4d59…ae79099`，来源无漂移。其中现有 `test_config_identity_bootstraps_without_plan_snapshots_or_side_effects` 及五项 `test_config_identity_uses_actual_t185_digest_and_tracks_configuration_changes` 使用实际 T185，覆盖原始配对与 routing/resources/partition/capabilities/identity 改变；不是 mock 出来的固定哈希。这六项属于协调方结果，T190 未重复运行。所有结果仅为离线证据。

| 增量证据 | SHA-256 |
| --- | --- |
| 2 项帮助 `help.json` | `81f17156d7128e6998df66c087aa80b4b996f73793444166b7bcb07b9a5f37fe` |
| 7 次 `commands.json` | `6d13494d64bd242cdecb355e4348f47ed2122a38bf61dc31159266bee37103ed` |
| T190 `report.json` | `f85c536f61da9e38b669f2b58dbfd21692c62eb072718fd7ffaa06a10397f9c0` |
| 协调方增量结果 | `ac7db03a09a97493049fd13ec06c9f084a371797294e3eb87d709074b22cd9e9` |
| 协调方 237 项日志 | `c5e30b0529af553c4c7102eb16752d3327b5c6543116b70b8f4d12beaa47866c` |

## 合成分支逐项走读

下表输入是人为构造的返回片段/证据条件，**不是真实集群输出，也不是可写回 state 的 schema**。逐项按短卡实际作出下一步选择；“拟执行”列正式入口及用途，参数见下节实际帮助核验。本表走读不 dispatch 远程动作；独立的本地 CLI 和 FakeTransport 回归证据见前两节。表中“保存”均指有有效 owner 时的正式 update；“暂停”指正式 pause；“收尾”指 finish。

| 场景与合成输入 | 所走短卡分支、拟执行入口与理由 |
| --- | --- |
| 无变化：running，状态/快照与上次相同 | §2/5：不空写简报，收尾；上节实际核对只读状态与 finish |
| 暂停观察：paused，已有 running Attempt | §1/2：观察租约后 status/snapshot；禁止 prepare/submit/cancel。组合实际验证暂停及计划过期后的观察租约 |
| 已结束：phase=ended | §1：直接退出；不 begin，不取得新预算；主线实际验证结束后 start 拒绝 |
| 已结束作业：finished；fetch 的 facts=written 或 unchanged | §2/4：拟 fetch 后读 facts 和原卡片；正常返回不代替科学审阅 |
| 成功取回但 facts=conflict | §2/5：保留输出/旧 facts，保存“需要你看”；不 refresh/reparse、不重交。上节实际保存同类合成分支 |
| facts=skipped，原因 no-facts/add-missing | §2：核对跳过原因；不当作解析完成。自动 facts 返回与发布保护已回归，独立 facts CLI 仍无 owner 参数 |
| facts=failed，解析器报告歧义 | §2：保存解析阻塞，交人处理；不以解析失败新建补救 Attempt |
| 快照缺失或 truncated，未见进展字段 | §2/3：证据不足，不当零进展；拟 snapshot 需正式 owner 保护，不取消 |
| 监控快照过期一次；下一 wake 再过期 | §5：首次阻断依赖动作；通过 update 保留两 wake 来源，下次 status 恢复，由模型计数后 pause；不声称内核自动聚合 |
| UNKNOWN，作业列表为空 | §2：暂停并保留预留/声明，拟 status 只读核对；不造替代、不重提 |
| 连续两 wake SSH 失败；同 wake 三个不同对象同失败 | §5：update 保存 wake/对象/错误来源，由模型分别按两 wake、三对象判断后 pause；同对象重复报错不加对象数，不以模型计数替代真实提交消费 |
| 同一对象第三次相同失败 | §4：分支“需要你看”，不通过改名或换猜测再补救；其他分支仅在无全局暂停时可继续 |
| 需要无进展取消：两个连续不同 wake 正式快照、各自理由、原归属一致 | §3：拟 cancel 的 no_progress 入口核验；单份快照或只有大小不变不够；每 wake 两次上限，组合正式函数已用合成传输回归 |
| 取消 accepted，当前仍 active | §3：拟 verify-stopped 只读核验，保留原占用；不再次 cancel、fetch 或替代提交 |
| 取消 unknown | §2/3：暂停，消费不退回、不重试；只核对已发动作后果 |
| 符合改投前提：从未运行、排队 ≥6 h、无 chk、同路由当前更高候选 | §3：拟 reroute 取消；接受后另核验同实例停止和历史，再拟带原来源的新 prepare/submit。完整前后证明成立、无运行/重排反证时，start=end 本身不拒绝；组合正向链及此时间边界已回归，不声称服务端原子排队保护 |
| 缺改投证据：版本不支持、实例缺失、历史不明、有 chk 或无更高候选 | §3：拒绝改投；不扩大成普通提交版本门槛。PBS 保留人工取消 |
| 取消后发现曾运行，或仅有 start=end 而缺前后完整证明 | §3：不能仅靠时间相等证明从未运行；缺完整证明或有运行反证就拒绝替代，保留旧占用/结果证据。区别于上一正例，不因相等本身拒绝 |
| 放宽输入：计划与规则 allow_relaxed=true，输入列跳过项 | §4/5：逐次提醒、方法口径未核验；仍核查字节/预算/归属，不因可提交接受结果；本演练不执行 prepare/submit |
| TS 极小点：正常完成、n_imag=0；TS 方向错：n_imag=1、来源绑定的模式报告不符 | §4：拟 scientific-review 分别记录 `ts_zero_imaginary` / `ts_wrong_mode`，均待人确认；再核验补救次数与最小改动，组合正式证据函数已回归。新写模式报告仍受下节缺口限制 |
| 超时或已取消：存在正式同实例结束证据及输出 | §2/4：拟 status → 合规 fetch/incomplete → 诊断；单凭 cancelled 标签不补救 |
| 实际提交 9/10，prepare 来源记录另有 3 | §4/5：90% 暂停；不能算成 12 次，也不能借新 wake 清零。组合实际提交消费/prepare 意图独立回归通过 |
| 失锁、60 分钟到点、90 分钟接管 | §1/5：旧 owner 停止发布；按上节实测边界处理。组合慢 IO/解析期间失权后的发布拒绝已回归 |
| 目标量齐；结构/代表集合/最终结果有签字缺项 | §4/5：保存全部待确认判断及签字缺项，暂停推进后收尾；不代签、不宣布 study 完成 |

## 接口核验与缺口

固定组合实际帮助已逐项读取。以下按入口列参数，基础参数沿用上节和各入口帮助；不能把某入口的参数拼到另一个入口。省略 owner 参数不构成自主执行方式。

| 组合入口 | 已核实的参数与区别 |
| --- | --- |
| autonomy 的 start | `--study`、`--plan`、`--owner`；观察专用加 `--observe-only`，接管另需 `--takeover-reason` |
| status / snapshot / fetch | 本次 `--run`、`--token`、`--plan-sha256`；fetch 接 Attempt ID，不带 `--study`；snapshot 可带 study/max-bytes |
| prepare / submit | `--autonomous-policy`、`--run`、`--token`、`--plan-sha256`、`--object-id`、`--job-class`；补救加 `--failure-class`，改投后继加 `--reroute-source`；prepare 仍须模板、输入、walltime、label、method-basis 等基础参数 |
| prepare 的放宽输入 | `--relaxed-input`，有附件才逐项 `--include-file`；不能据此绕过规则和方法边界 |
| route 的首次配置身份（上述 T186 增量） | `--config-identity`，可加 `--json`；不需要计划/规则/快照，不能混入其他路由参数；只返回 routing_sha256，不选节点或创建授权 |
| route 的自主分支 | `--study`、`--template`、`--job-class`、`--round-id`、`--run-id`、`--object-id`、`--walltime`、`--autonomous-policy`、`--token`、`--plan-sha256`；CREST/xTB 另带 tier，Gaussian 阶梯不带 tier |
| autonomy 的 scientific-review | `--study`、`--attempt`、`--run`、`--token`、`--plan-sha256`、`--object-id`、`--reason` 均须提供；`--outcome` 为 `ts_zero_imaginary` / `ts_wrong_mode`，方向错误另需 `--mode-review` 来源报告 |
| cancel 的自主路径 | Attempt ID 与 `--run`、`--token`、`--plan-sha256`、`--autonomous-policy`、`--reason`；`--kind no_progress` 加 `--reviews`，`--kind reroute` 不加 reviews |
| cancel 的停止核验 | Attempt ID、`--verify-stopped` 及 `--run`、`--token`、`--plan-sha256`；只核验已接受取消，不再次取消或自动准备后继 |

具体仍需处理的能力边界：

1. **study.md 写入**：组合 `study.py` 仅 init 新建 study.md，CLI 无受 owner 保护的更新入口。manual-writers/release-writer 管登记和释放，不是文档写入命令。自主期用 update 保存待写摘要；一次 check 后直接编辑仍有失权窗口，不采用。
2. **本地科学写工具**：fetch 自动 facts 有发布保护；独立 facts CLI 没有 run/token 接口，走手动 writer 保护。review 和模式报告命令也不能从帮助推导出 owner 支持。需新写模式报告等依赖步骤时交人处理，已有来源绑定报告可按 scientific-review 核验；不把 Python API 有 guard 误写成每个 CLI 都支持。
3. **首次路由身份已补齐**：T186 增量的正式 config-identity 入口已按上节实际验证；不再列为本组合缺口。未集成该入口/实际 T185 的检出仍不能首次绑定；不把配置身份导出等同资源核验或授权。
4. **熔断职责**：update/status 能保存恢复来源，模型计数后 pause；不要求新聚合命令。保存当前/前次不同 wake 的成功或失败结果及来源，本 wake 按对象 ID 去重。仅来源缺失、损坏或失权无法保存时列具体阻塞；不是内核自动聚合，也不替代实际提交消费。
5. **计划文本**：逐类耗时/试点标志仍在现有文本，没有结构化字段；计划的科学边界及所有中间判断仍待人审阅。

验证结果在 [T190 任务单](../../../docs/redesign-tasks/T190-autonomous-run-card.md)中同步。第 1/2 项的写保护后续任务 T206/T207 尚待范围批准，不假定已经实现。缺口只阻断依赖它们的操作；不把缺一个特定命名命令扩大为其他已实现路径不可用。核心合并前现场验证、自主启用与 T198 非研究试点仍须独立完成。
