# 研究对象与采用结果：ag-catalog/1

`ag catalog` 只在本机登记构象 × 电子态对象、Attempt 归属、当前采用结果与报告类别。
不改 manifest、facts、review、study.md 或签字记录，不连接服务器，不计算能量差。
登记、父子分组和 `adopted` 状态都不能替代科学审阅或里程碑签字。

## 命令

`<study>` 可以是存在的 study 目录，或本机配置中的 study ID。目录形式无需配置；
ID 形式只加载本地 studies_root。Attempt 参数必须是本 study 下的完整精确 ID，不接受前缀或路径。

```sh
ag catalog object <study> --id water-a --name 'Water A' --state-label S0 --multiplicity 1 --conformer A
ag catalog object <study> --id water-a --name 'Water conformer A' --update
ag catalog member <study> --object water-a --attempt <AttemptID> --role auto
ag catalog adopt <study> --object water-a --role opt --attempt <AttemptID> --quote '<负责人在本 study 当前对话中的逐字原话>'
ag catalog adopt <study> --object water-a --role freq --attempt <AttemptID> --quote '<逐字原话>' --report review.html
ag catalog adopt <study> --object water-a --role sp --attempt <AttemptID> --quote '<逐字原话>'
ag catalog retire <study> --object water-a --reason '转为历史'
ag catalog report-kind <study> --report review.html --kind formal
ag catalog show <study> --json
ag catalog suggest <study>
```

所有写命令支持 `--dry-run`：只打印完整待写事件、核对结果和警告，连锁文件也不创建。
正式写入也输出这三项。`show`、`suggest` 均只读。
对象 ID 复用 `study.identifier()`，小写字母、数字、连字符，最长 80 字符。
重复 ID 拒绝，已有 ID 加 `--update` 才更新；更新未指定的可选元数据沿用旧值。
`--name` 必填，多重度指定时须为正整数；`--note` 仅保存在日志中。

`member --role` 支持 `auto|crest|opt|ts|freq|stable|sp|irc|scan|other`。
从不可变 manifest 的模板、science.route 和已有 scan 标记识别类型：

- Gaussian：Opt、Opt=(TS/QST2/QST3)、Freq、Stable、IRC、Scan、SP；组合 Opt+Freq 支持 opt 和 freq。
  无任务关键词但有方法/基组的 route 按 Gaussian 默认 SP 识别；未知 route 不猜测。
- CREST 为 crest；xTB 有 scan 标记为 scan，有 `--opt` 为 opt，否则为 sp。
- 自动成员角色依次优先 crest、scan、ts、opt、freq、stable、irc、sp。
  未能识别时要求明确指定角色；已识别但手工角色不符时必须加 `--force-role`，日志保留该标记。
- 重复登记同一对象的同一 Attempt，当前成员角色取最后一次；所有历史事件保留。
  同一 Attempt 可显式登记到多个对象，catalog 不代替人判断归属。

`adopt` 仅允许 opt、freq、sp：必须 fetched、现有 ag-facts/1 可读且角色相符。
opt 接受 Opt 或 TS，freq 接受 Freq 或 Opt+Freq，sp 只接受单点；强制成员角色不绕过采用核对。
freq_step_review=fail 拒绝，manual_review 允许登记并在 stderr 醒目警告；缺失值记 null，不能解释为通过。
原话非空且至多 2000 个 Unicode 字符，保留首尾空白与换行。
CLI 无法证明说话者身份；会话必须逐字引用负责人在**本 study 当前对话**中的原话，
不得转述、跨会话借用或自行生成。已签结论的补登记，仍须负责人按 study 逐个授权。
成员不存在时在同一锁内先追加 member，再追加 adopt；已有成员不重复添加。
自动补 member 时，采用角色属于推断结果则优先使用它（例如 Opt+Freq 以 freq 采用时记 freq）；
否则保留首个推断角色（例如 TS 以 opt 采用时仍记 ts）。已有成员的角色不随 adopt 改写。
同角色再次采用覆盖派生视图的当前指针，旧指针和原话留在日志。
retire 保留成员与采用历史，后续元数据更新或采用不自动恢复对象状态。

报告路径以 `analyses/` 为基准，也接受带 `analyses/` 前缀的写法，统一保存为 analyses 相对路径。
规范化后必须是 analyses 内现存文件，拒绝绝对路径、越界和符号链接；adopt 的可选 report 同样核对。
类别为 `formal|energy|state-check|ensemble|irc|thermo|stage-review|figure|other`。

## 追加日志字段

位置：`<study>/catalog/journal.jsonl`，UTF-8，每行一个 JSON 对象并以 LF 结束。

| 字段 | 类型与含义 |
|---|---|
| schema | 固定 `ag-catalog/1` |
| seq | 从 1 开始连续递增的整数 |
| at | UTC ISO 8601 时间，含时区 |
| op | `object|member|adopt|retire|report-kind` |
| prev_sha256 | 前一行原始 UTF-8 字节的 SHA-256，**包含末尾 LF**；首行 null |

| op | 事件特有字段 |
|---|---|
| object | `id`、`name`、`state_label`（string/null）、`multiplicity`（integer/null）、`conformer`（string/null）、`note`（string/null）、`update`（boolean）；更新事件保存完整元数据 |
| member | `object`、`attempt`、`role`；`force_role`（boolean）记录是否显式强制，读取缺省为 false |
| adopt | `object`、`role`、`attempt`、`quote`、`report`（string/null）、`checks` |
| retire | `object`、`reason` |
| report-kind | `report`、`kind` |

`adopt.checks` 为 `fetched`、`facts_readable`、`role_match` 三个 boolean 和
`freq_review`（facts 的 freq_step_review；非 freq 或来源缺失为 null）。前三项均为 true 才写入。
每次写前核对完整日志的 schema、序号、前行哈希与事件回放；损坏或末行不完整直接拒绝，show/suggest 同样报告。
哈希链用于检测不一致，不是签名：无法证明原话身份，也不保证发现人为重算整条链或尾部删改。

## 派生状态字段（前端 T121）

位置：`<study>/catalog/state.json`，每次成功追加后完整派生并原子替换。

| 顶层字段 | 类型与含义 |
|---|---|
| schema | 固定 `ag-catalog-state/1` |
| journal_sha256 | 整个 journal.jsonl 原始字节的 SHA-256（包括全部 LF） |
| generated_at | 该派生视图生成时的 UTC ISO 时间 |
| objects | 对象数组，按首次登记顺序 |
| report_kinds | `{ "analyses 下的相对路径": "类别" }`，同路径取最新事件 |

| objects[] 字段 | 类型与含义 |
|---|---|
| id / name | 对象 ID / 显示名 |
| state_label / conformer | string/null |
| multiplicity | integer/null |
| status | 有采用记录为 adopted，无则 candidate；retired 优先且不自动恢复 |
| members | `[{"attempt":"精确ID","role":"角色"}]` |
| adopted | 固定键 opt、freq、sp；每项 null 或 `{attempt, at, quote, report}` |
| values | 固定键 scf_h、freq_scf_h、zpe_h、g_h、source |

`values` 单位都是 Hartree，逐项含义如下：

| 字段 | 复制来源 | 含义 |
|---|---|---|
| scf_h | 被采用 SP 的 `facts.energies.scf` | SP 作业在其自身方法层级上的 SCF 总能量 |
| freq_scf_h | 被采用 Freq 的 `facts.energies.scf` | Freq 作业在其自身方法层级上的 SCF 总能量，不能用 SP 的 scf_h 替代 |
| zpe_h | 被采用 Freq 的 `facts.energies.zpe` | 零点校正量，不是加了零点校正后的总能量 |
| g_h | 被采用 Freq 的 `facts.energies.g` | Freq 作业在其自身方法层级上的总 Gibbs 自由能，不是自由能校正量，也不是 SP 层级的总自由能 |

前端若展示以 Freq 热校正修正 SP 的近似值，所用校正为 `g_h − freq_scf_h`，
再加到 SP 的 `scf_h` 上；不能直接把 g_h 当作校正量与 SP 能量相加。
这要求所选作业的几何与热化学条件适用，catalog 不作这一科学判断，
也不计算上述校正或能量差、不从 Opt 或 SP 回填缺失的 Freq 能量。
`values.source` 同样固定 scf_h、freq_scf_h、zpe_h、g_h，值为被复制数值的 Attempt ID；
未采用、facts/字段不可读、单位不是 Hartree 或数值非有限数时，数值和对应 source 均为 null。
facts 的后续变化不会由 show 自动刷新；数值是最近一次 catalog 写入时的副本。
旧状态文件可能没有 freq_scf_h，消费者应视为缺失，不用 scf_h 替代；
后续正常 catalog 写入会生成新增字段，show 不改写旧状态或日志。

前端核对日志完整字节的 SHA-256 与 journal_sha256；不匹配时显示警告，不能把旧视图当作最新登记。
`show --json` 输出磁盘状态的 JSON 内容，不偷偷重算；缺少日志且无状态时返回空视图、不写文件。
有日志却缺少状态时报告，状态哈希落后时警告并返回磁盘原视图。
`show` 表格展示对象状态、成员角色和 opt/freq/sp 当前指针。

## 写入与中断

使用 locks.py 的文件锁，锁位于本 study 的 `catalog/submit.lock`，与全局作业提交锁互不干扰。
核对、自动成员、采用、状态派生均在同一写锁内；只读操作只锁已有锁文件。
日志通过 `O_APPEND` 追加并 fsync，状态使用同目录临时文件、fsync、os.replace，再同步目录。
读取现有证据前拒绝符号链接。catalog 不调用 facts 解析器，原有文件字节与时间戳保持不变。
状态发布失败时日志仍保留；停止人工核对，不能盲目重复采用。没有删除事件或修复日志的命令。
完整、有效的后续新事件会重新派生状态；损坏日志必须人工处理，ag 不修复、不截断、不重写。

## 分组建议与测试口径

suggest 在尚未登记到任何对象的 Attempt 子图上按 parents 无向连通分组。
分叉属于同组，环只遍历一次，缺失父节点单独提示；已归属（含 retired）的节点不作为连接桥梁。
建议 ID 避开已有对象，输出 object/member 命令草稿；无法推断角色时留 `<CHOOSE_ROLE>` 占位。
父子关系不证明构象或电子态相同，执行草稿前由会话与人核对；不生成 adopt 草稿，不写文件。

工单测试表“日志 5 行”与事件规则不一致：object、显式 Opt+Freq member、opt/freq/sp 三次采用，
加上 SP 的自动 member，共 **6 行**。若三个角色使用不同且未登记的 Attempt，则共 7 行。
测试按每个实际事件一行核对连续序号和哈希链，不合并或省略事件来满足行数笔误。
