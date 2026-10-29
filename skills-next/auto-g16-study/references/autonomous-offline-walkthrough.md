# 自主短卡：离线唤醒演练

2026-10-29 的合成走读与真实本地记录。未连接集群，未提交、取消、改投、安装、部署或建立定时任务；本页不证明现场兼容、科学正确或自主启用。短入口见[自主运行卡](autonomous-run.md)。

## 来源和验收状态

| 来源 | 固定提交 / 状态 |
| --- | --- |
| 当前主线及 T184 | `8ff90e3bcf5f8b99542b2425c65fa09af6bcafb5`，本地生命周期已演练 |
| T185 | `47ac89867132d5271c996f6d56183f1935011af8`，仅作为待组合来源 |
| T186 | `e5b2daa60570d139f222210de5da93c968e0ee51`，字段与动作接线只读核对，不能代替组合运行 |
| T187 | 最终固定提交尚未提供；未提交工作树只用于定位，不作验收来源 |
| T188 | `9bbebcc527d6864c79b7fd02a37599a332c3bdac`，仅作为待组合来源 |
| 组合副本 | 尚未提供；最终帮助、计划解析、owner 参数和动作演练均未验收 |

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

## 合成分支逐项走读

下表输入是人为构造的返回片段/证据条件，**不是真实集群输出，也不是可写回 state 的 schema**。逐项按短卡实际作出下一步选择；“拟执行”只列正式入口及用途，组合未验收的完整参数不编造。所有远程动作均未 dispatch，也未调用模拟 SSH；实际执行仅为上节的本地生命周期。表中“保存”均指有有效 owner 时的正式 update；“暂停”指正式 pause；“收尾”指 finish。

| 场景与合成输入 | 所走短卡分支、拟执行入口与理由 |
| --- | --- |
| 无变化：running，状态/快照与上次相同 | §2/5：不空写简报，收尾；上节实际核对只读状态与 finish |
| 暂停观察：paused，已有 running Attempt | §1/2：观察租约后 status/snapshot；禁止 prepare/submit/cancel。主线只验证暂停检查，组合观察租约未验收 |
| 已结束：phase=ended | §1：直接退出；不 begin，不取得新预算；主线实际验证结束后 start 拒绝 |
| 已结束作业：finished；fetch 的 facts=written 或 unchanged | §2/4：拟 fetch 后读 facts 和原卡片；正常返回不代替科学审阅 |
| 成功取回但 facts=conflict | §2/5：保留输出/旧 facts，保存“需要你看”；不 refresh/reparse、不重交。上节实际保存同类合成分支 |
| facts=skipped，原因 no-facts/add-missing | §2：核对跳过原因；不当作解析完成。组合受保护解析入口未验收 |
| facts=failed，解析器报告歧义 | §2：保存解析阻塞，交人处理；不以解析失败新建补救 Attempt |
| 快照缺失或 truncated，未见进展字段 | §2/3：证据不足，不当零进展；拟 snapshot 需正式 owner 保护，不取消 |
| 监控快照过期一次；下一 wake 再过期 | §5：首次阻断依赖动作；通过 update 保留两 wake 来源，下次 status 恢复，由模型计数后 pause；不声称内核自动聚合 |
| UNKNOWN，作业列表为空 | §2：暂停并保留预留/声明，拟 status 只读核对；不造替代、不重提 |
| 连续两 wake SSH 失败；同 wake 三个不同对象同失败 | §5：update 保存 wake/对象/错误来源，由模型分别按两 wake、三对象判断后 pause；同对象重复报错不加对象数，不以模型计数替代真实提交消费 |
| 同一对象第三次相同失败 | §4：分支“需要你看”，不通过改名或换猜测再补救；其他分支仅在无全局暂停时可继续 |
| 需要无进展取消：两个连续不同 wake 正式快照、各自理由、原归属一致 | §3：拟 cancel 的 no_progress 入口核验；单份快照或只有大小不变不够；每 wake 两次上限，组合未执行 |
| 取消 accepted，当前仍 active | §3：拟 verify-stopped 只读核验，保留原占用；不再次 cancel、fetch 或替代提交 |
| 取消 unknown | §2/3：暂停，消费不退回、不重试；只核对已发动作后果 |
| 符合改投前提：从未运行、排队 ≥6 h、无 chk、同路由当前更高候选 | §3：拟 reroute 取消；接受后另核验同实例停止和历史，再拟带原来源的新 prepare/submit。无服务端原子排队保证，组合正向仍未执行 |
| 缺改投证据：版本不支持、实例缺失、历史不明、有 chk 或无更高候选 | §3：拒绝改投；不扩大成普通提交版本门槛。PBS 保留人工取消 |
| 取消后发现曾运行，或只见 start=end | §3：不能仅靠时间相等证明从未运行；缺完整证明就拒绝替代，保留旧占用/结果证据 |
| 放宽输入：计划与规则 allow_relaxed=true，输入列跳过项 | §4/5：逐次提醒、方法口径未核验；仍核查字节/预算/归属，不因可提交接受结果；本演练不执行 prepare/submit |
| TS 极小点：正常完成、n_imag=0；TS 方向错：n_imag=1、来源绑定的模式报告不符 | §4：拟 scientific-review 分别记录 `ts_zero_imaginary` / `ts_wrong_mode`，均待人确认；再由正式补救入口核验次数和最小改动，未执行组合接口 |
| 超时或已取消：存在正式同实例结束证据及输出 | §2/4：拟 status → 合规 fetch/incomplete → 诊断；单凭 cancelled 标签不补救 |
| 实际提交 9/10，prepare 来源记录另有 3 | §4/5：90% 暂停；不能算成 12 次，也不能借新 wake 清零。主线意图接口不能验证此例，组合未验收 |
| 失锁、60 分钟到点、90 分钟接管 | §1/5：旧 owner 停止发布；按上节实测边界处理。远程 IO 后发布保护仍需组合验证 |
| 目标量齐；结构/代表集合/最终结果有签字缺项 | §4/5：保存全部待确认判断及签字缺项，暂停推进后收尾；不代签、不宣布 study 完成 |

## 接口核验与缺口

本节是具体集成待办，不授予接口缺失时的替代执行权限。

1. **固定组合**：最终 T187 SHA 与协调方组合目录仍缺；须从该组合重跑全部帮助并核对 owner 选项。T186 单支、源码签名或假输出不算命令验收。
2. **观察与发布**：T186 候选有 start 的 `--observe-only`，status/snapshot/fetch 的 `--run`、`--token`、`--plan-sha256`。需组合验证暂停/计划过期观察、慢 IO 失权后不发布，以及自动 facts 的五种返回。
3. **实际动作**：候选 prepare/submit 有 `--autonomous-policy`、run/token/plan-sha256、object-id/job-class；补救带 failure-class，改投后继带 reroute-source。route 使用 `--run-id` 而非动作入口的 `--run`，另需 round-id 等上下文；不照抄 T185 单支的占位拒绝路径。科学失败入口与 cancel 的 no_progress/reroute/verify-stopped 都需最终帮助和真实本地证据组合验证。
4. **熔断职责**：已有 update/status 可受租约保护地保存、恢复失败来源，模型计数后调用 pause，故不要求另增聚合命令。保存当前/前次不同 wake 的 ID、成功或失败结果、来源文件与哈希；本 wake 按对象 ID 去重同类失败。来源损坏/缺失、失权无法保存时才列具体阻塞，不猜计数或直接编辑日志。这不是内核已自动强制，也不替代实际提交消费。
5. **study.md 与本地科学工具**：尚未发现可在写入时重验 owner 的 study.md CLI；一次 check 后直接编辑有失权窗口。自主期仅以 update 保存待写摘要，不能自行编辑。独立 facts、review、模式报告等写工具的 owner 支持也须逐项核实；没有则停止依赖步骤，不通过脚本包一层自建执行框架。
6. **计划数据与路由身份**：逐类耗时/试点标志目前只可放现有文本，不新增 JSON 键。路由配置身份的首次正式提取入口须核对，不能用任意内部 Python 求哈希后当作获准路由。计划字段解析与真实提交消费由最终组合验收。

主线现有 Skills 测试、链接/锚点及敏感扫描结果在 [T190 任务单](../../../docs/redesign-tasks/T190-autonomous-run-card.md)中更新。以上缺口解决和独立审阅前，本页保持未完成组合验收；核心合并前现场验证与 T198 非研究试点另行授权。
