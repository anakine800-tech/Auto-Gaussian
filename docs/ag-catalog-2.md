# 研究对象、反应通道与候选台账：ag-catalog/2

T131 后端格式；T132 前端按本文字段读取。catalog 是人工登记视图，不判断化学含义，
不提交计算、不解析或改写 facts、不回写 manifest、review 或签字。
候选数和尝试次数不是简并度；“已验证”只来自负责人原话声明，登记核对不等于科学验收。
TS/IRC 的科学要求仍按 AGENTS.md：一个正确虚频，双向 IRC 完成并识别端点。
本命令只检查下文列出的本地证据，不自动证明振动方向或 IRC 已通过。

## 1. 升级与兼容

日志仍是 `<study>/catalog/journal.jsonl`，状态仍是 `catalog/state.json`，共用 `catalog.lock`。
只有首次写新事件（channel、channel-status、coverage、candidate、candidate-result）或带
expected_formula / expected_charge 的 object 事件才升级。即使值是 unset / unknown，也属于新字段。
纯旧命令不会因使用新版 ag 或带 `--upgrade-catalog` 而升级。

- 触发首次升级的写命令必须带 `--upgrade-catalog`；否则拒绝，连目录和锁也不创建。
- 所有写命令支持 `--dry-run`，无需升级标志即可看到将写的 /2 事件及影响；不创建任何文件或目录。
- 第一条新事件起，每行 schema 都为 `ag-catalog/2`，包括后续旧类型事件；不另写升级事件。
- 原 /1 行字节不变，seq 和 prev_sha256 跨版本连续；不迁移、不截断、不重算旧行。
- 没有 /2 行时仍生成 state/1；冻结相同时间与来源时，与基线 main 输出逐字节一致。
- 新读者接受 /1 前缀和 /2 后缀，拒绝 /2 后出现 /1、/1 中的新事件或新字段、未知 op/字段、
  错序号、错误哈希及不完整末行。损坏须人工处理，没有修复日志命令。
- **旧 ag 拒绝升级后的日志；v4.5.x 前端拒绝 state/2 并回退为未登记。**
  升级前等旧 catalog 进程退出；不能混用读写版本或靠删行降级。
- **T131 合并、T132 合并并在两台机器部署之前，真实研究 study 不写 v2 事件。**

状态发布失败时保留已追加日志，停止人工核对；不得盲目重做声明。候选存档先于日志追加，
中断可能留下未被事件引用的存档；不会覆盖它，后续只有字节相同且只读时才复用。

## 2. 命令

`<study>` 接受已存在 study 的目录或本地配置的 study ID。Attempt 必须是本 study 的精确 ID。
对象、通道、候选 ID 都用 `study.identifier()`：小写字母、数字、连字符，最长 80 字符。
通道和候选分别在对象内唯一；相同 ID 可以出现在不同对象下。
旧 object/member/adopt/retire/report-kind/show/suggest 命令及其含义保留，见 [ag-catalog/1](ag-catalog-1.md)。

```sh
ag catalog object <study> --id water-ts --name 'Synthetic water TS' --multiplicity 1 --formula OH2 --charge 0 --upgrade-catalog
ag catalog object <study> --id water-ts --name 'Synthetic water TS' --update --formula unknown
ag catalog object <study> --id water-ts --name 'Synthetic water TS' --update --charge unset
ag catalog object-suggest <study> --attempt <AttemptID>
ag catalog channel <study> --object water-ts --id a --name 'A' --definition '人工给出的化学定义' --product-branch '产物标签'
ag catalog channel <study> --object water-ts --id b --name 'B' --definition '待确认的定义' --discovered
ag catalog channel <study> --object water-ts --id b --update --confirm
ag catalog candidate <study> --object water-ts --id guess-a --xyz water.xyz --origin manual --target-channel a
ag catalog candidate-result <study> --object water-ts --candidate guess-a --outcome diagnosed --diagnosis-json diagnosis.json
ag catalog candidate-result <study> --object water-ts --candidate guess-a --outcome other_channel --assign undetermined --channel a --channel b
ag catalog candidate-result <study> --object water-ts --candidate guess-a --outcome accepted --attempt <AttemptID> --assign verified --channel a --quote '<负责人原话>'
ag catalog channel-status <study> --object water-ts --channel a --status verified --quote '<负责人原话>'
ag catalog channel-status <study> --object water-ts --channel b --status excluded-low-confidence --reason '有限采样的排除理由' --quote '<负责人原话>'
ag catalog channel-status <study> --object water-ts --channel b --status cleared --quote '<负责人撤销原话>'
ag catalog coverage <study> --object water-ts --statement stable --scope '声明的通道范围' --budget '声明的采样预算' --quote '<负责人原话>'
ag catalog coverage <study> --object water-ts --statement withdrawn --scope '撤销的范围' --budget '原采样预算' --quote '<负责人撤销原话>'
ag catalog show <study> --json
ag catalog ledger <study> --object water-ts --channel a --json
ag catalog suggest <study>
```

### 对象期望值与建议

`--formula` 接受元素符号与正整数计数组成的化学式，元素顺序不限，重复元素计数相加。
保存 Hill 顺序：有 C 时先 C、再 H、其余按字母；无 C 时全部按字母。例如 OH2 → H2O，H10C4 → C4H10。
不接受括号、同位素、点合物、电荷后缀或分数计量；电荷独立用 `--charge`。

两个期望字段均为三态：未提供 unset、明确未知 unknown、有效值 set。电荷 0 是 set。
新对象未指定字段为 unset；`--update` 未指定字段保留旧值，显式 unset 才清除期望。
只有被指定的期望字段写入 object 事件；旧更新事件不含这些字段时不清空已有值。
多重度继续使用原来的 nullable 正整数 `multiplicity`，没有第二个字段。

object-suggest 只读不可变 manifest；单结构数 science.geometry 的元素，并读取显式 charge/multiplicity；
QST 逐组读取 science.structures，三项分别要求各组一致，不用第一组掩盖矛盾。
xTB/CREST 从 manifest 声明且大小/SHA-256 相符的输入 XYZ 数元素（多帧要求组成相同），
电荷/多重度优先使用显式 template_params 的 --chrg / --uhf+1；与 science 冲突时报告无法建议。
参数缺省时可读取 prepare 已存储的 science 值；两处都缺失时不补 0/1。
建议逐项输出，缺失或不一致项写“无法建议”；不创建对象、不调用 prepare 或解析器。

每次写入 state/2 时保存 member_mismatches；show 和 suggest 另做当次只读核对，打印不一致及缺失说明。
期望 unset/unknown 的项跳过并注明；成员实际值缺失时说明“未核对”，不伪造实际值或 mismatch。
show 的 JSON 保留磁盘视图，实时核对信息输出到 stderr；不刷新 values、state 或日志。
suggest 的 expectation_reports 包含每对象的 member_mismatches 和 notes。

### 通道、声明与整体覆盖

channel 新增必须有 name/definition；update 可仅指定要改的字段，未指定沿用。
`--discovered` 保留发现来源；新发现通道 confirmed=false，其他新通道 confirmed=true。
发现来源不能改写；`--update --confirm` 只用于 discovered 通道，确认不需原话且不自动撤回。
retired 对象拒绝新增通道，已有历史不删除。

channel-status 的 verified 要求至少一条指向本通道的 verified 候选结果，在写锁内核对并保存候选 ID/结果序号。
excluded-low-confidence 必须有 reason。cleared 清除当前声明，历史事件保留。
coverage 最新一条生效；withdrawn 明确保留撤销记录，不代表“稳定”。
“在声明的通道范围与采样预算内稳定”只按人的 scope/budget/quote 记录，不推断全局完备性。

原话规则沿用 adopt：非空、最多 2000 个 Unicode 字符，首尾空白和换行原样保留。
channel-status 三种声明、verified 候选归属、coverage stable/withdrawn 都必须有原话。
其余登记、诊断、期望值修改和确认通道无需原话。CLI 无法验证发言人身份，
会话必须逐字引用负责人在本 study 当前对话中的话，不能生成科学结论原话。

### 候选来源、存档和结果

candidate 支持 `--origin scan|qst|template-transform|path-search|manual|literature`，可选
`--parent-attempt`、`--parent-file`、`--transform-json`、`--target-channel`、`--doi`、`--si-location`、`--note`。
原路径只作 source 说明，查询不再依赖原文件。parent-file 只记录用户给出的路径说明和 SHA-256，不复制。
parent-attempt 必须在本 study 存在；目标通道必须属于本对象。literature 必须有 DOI，
只检查 `10.` + 4–9 位数字 + `/` + 非空无空白后缀，不联网核实；si-location 必须与 DOI 一起提供。

XYZ 必须是单帧标准格式（原子数、注释、坐标），合法元素符号、有限坐标，最多 1 MiB。
保存 n_atoms、Hill formula、原始字节 SHA-256 和 study 相对路径。
读取源和存档拒绝符号链接；`catalog/candidates` 按 0700 创建，
`<sha256>.xyz` 用 O_EXCL 独占创建并 fsync，权限 0400，不覆盖。
同哈希已有文件只有字节一致且只读才复用；不悄悄修改权限或修复坏存档。
候选组成不符合对象期望时只警告，仍可登记；电荷无法由 XYZ 核对，明确写“未核对”。

candidate-result 的 outcome：diagnosed、accepted、other_channel、minimum、opt_failed、multiple_imag、other；
other 必须有 note。结果不改候选几何，同一候选每次追加完整结果记录。
transform-json 和 diagnosis-json 都必须是 ≤64 KiB 的 JSON 对象；对象字段、嵌套值原样保存，
不解释、不打分；允许 JSON 重排空白/键序，不保留源文件的排版。非有限 JSON 数字拒绝。

归属用 `--assign`（缺省 none）与可重复 `--channel`：none 不带通道，tentative/verified 恰好一个，
undetermined 无通道或至少两个不重复通道。所有通道必须属于本对象。
verified 必须有 quote 和 attempt，Attempt 已 fetched、ag-facts/1 可读、n_imag 为整数 1、已是本对象成员；
checks 保存当时的核对结果。其他归属关联非成员时只提醒，不自动 member。
accepted outcome 本身不等于 verified 归属，更不等于通道已验证。

## 3. 日志字段（逐个 op 的完整字段）

每行 UTF-8 JSON，以 LF 结束。所有事件共同字段：

| 字段 | 类型与约束 |
|---|---|
| schema | string，ag-catalog/1 或 ag-catalog/2，单调升级 |
| seq | integer，从 1 连续增加 |
| at | string，UTC ISO 8601，含零偏移时区 |
| op | 下表中的 string |
| prev_sha256 | string/null，前一行包含 LF 的 SHA-256，首行 null |

`Expectation<T>` 固定为 `{state: "unset"|"unknown"|"set", value: T|null}`。
unset/unknown 的 value 必须 null；set 的 value 为规范 Hill 字符串或整数。
ID 均为 string。下表列出共同字段以外的全部字段；未注明可缺省的字段在日志中必须存在。

| op | 字段与类型 |
|---|---|
| object | id:string，name:string，state_label:string/null，multiplicity:positive integer/null，conformer:string/null，note:string/null，update:boolean；/2 可缺省 expected_formula:Expectation<string>、expected_charge:Expectation<integer> |
| member | object:string，attempt:string，role:string；force_role:boolean（兼容缺省 false） |
| adopt | object:string，role:string，attempt:string，quote:string，report:string/null，checks:AdoptionChecks |
| retire | object:string，reason:string |
| report-kind | report:string，kind:string |
| channel | object:string，id:string，name:string，definition:string，product_branch:string/null，discovered:boolean，confirmed:boolean，update:boolean |
| channel-status | object:string，channel:string，status:"verified"/"excluded-low-confidence"/"cleared"，quote:string，reason:string/null，checks:ChannelChecks |
| coverage | object:string，statement:"stable"/"withdrawn"，scope:string，budget:string，quote:string |
| candidate | object:string，id:string，source:string，file:string，sha256:string，n_atoms:positive integer，formula:string，origin:string，parent:Parent，transform:object/null，target_channel:string/null，literature:Literature/null，note:string/null |
| candidate-result | object:string，candidate:string，outcome:string，attempt:string/null，diagnosis:object/null，assignment:Assignment，quote:string/null，note:string/null，checks:ResultChecks |

嵌套类型和枚举：

- AdoptionChecks：`{fetched:boolean, facts_readable:boolean, role_match:boolean, freq_review:string|null}`；旧语义保留。
- ChannelChecks：verified 为 `{verified_candidate_results:[{candidate:string, seq:integer}, ...]}`，
  按候选登记顺序、候选结果顺序记录当时所有匹配条目；其他声明为 `{}`。
- Parent：`{attempt:string|null, file:null|{source:string, sha256:string}}`。
- Literature：`{doi:string, si_location:string|null}`。
- Assignment：`{status:"none"|"tentative"|"verified"|"undetermined", channels:string[]}`。
- ResultChecks：verified 为 `{fetched:true, facts_readable:true, n_imag:1, member:true}`；其他为 `{}`。
- origin：scan、qst、template-transform、path-search、manual、literature。
- outcome：diagnosed、accepted、other_channel、minimum、opt_failed、multiple_imag、other。
- member.role：crest、scan、ts、opt、freq、stable、irc、sp、other；adopt.role：opt、freq、sp。
- report-kind.kind：formal、energy、state-check、ensemble、irc、thermo、stage-review、figure、coverage、ts、nci、other。

旧 op 在 /1、/2 语义相同。replay 只有一套；只读回放检查声明保存的证据和事件间关系，
不拿今天的 facts 撤销历史 checks。哈希链不证明发言身份，也不保证发现人为重算整条链或删尾。

## 4. state/2 字段（T132 消费）

顶层仍为 schema、journal_sha256、generated_at、objects、report_kinds；schema 改为 `ag-catalog-state/2`。
journal_sha256 是整个日志原始字节的 SHA-256，generated_at 为生成时 UTC ISO 字符串。
objects 为按首次登记顺序的数组；report_kinds 为 analyses 相对路径到类别的映射。
/1 的所有对象字段原样保留：id、name、state_label、multiplicity、conformer、status、members、adopted、values。
对象 status 仍是 candidate/adopted/retired；note 仍只在 object 日志中。
values 的四项 Hartree 数值及 source、adopted 的三种角色指针均按 /1 解释，不计算能量差。

每个对象增加以下字段，即使该对象只来自升级前的 /1 事件也补齐默认值：

| 字段 | 类型与默认值 |
|---|---|
| expected | `{formula:Expectation<string>, charge:Expectation<integer>}`；默认均 unset/null |
| channels | Channel[]，默认 [] |
| candidates | Candidate[]，默认 [] |
| coverage | null 或 `{statement:"stable"|"withdrawn", scope:string, budget:string, at:string, quote:string}` |
| member_mismatches | `[{attempt:string, field:"formula"|"charge"|"multiplicity", expected:string|integer, actual:string|integer}]`，默认 [] |

Channel 的全部字段：

| 字段 | 类型 |
|---|---|
| id / name / definition | string |
| product_branch | string/null |
| discovered / confirmed | boolean |
| status | untried / attempted_not_found / tentative_found / verified / pending_confirmation / excluded_low_confidence |
| declaration | null 或 `{status:"verified"|"excluded-low-confidence", at:string, quote:string, reason:string|null}`；cleared 后 null |
| candidate_ids | string[]，关联候选的登记顺序 |
| outcome_counts | `{outcome:string → integer}`，只列实际出现的结果，零结果为 {} |

Candidate 的全部字段：id、file、sha256、n_atoms、formula、origin、parent、transform、target_channel、literature、note
与 candidate 事件同名同型；另外有 registered_at:string（登记事件 at）、results:完整 candidate-result 事件数组
（含 schema/seq/at/op/prev_sha256 及全部特有字段）、latest_assignment:Assignment/null。
没有结果时 latest_assignment=null；否则取最后一条结果的 assignment，包含 none/undetermined，不能回退到更早的 verified。
原始 source 仅留在日志，file 始终是 study 相对存档路径。

## 5. 通道派生与查询

关联候选：target_channel 指向本通道，或任一次结果的 assignment.channels 包含本通道。
candidate_ids 去重；outcome_counts 统计这些候选的**每次结果**，同一候选可属于多个通道。
因此各通道计数不能相加当作全局不重复尝试数。诊断事件也计入 diagnosed；undetermined 不等于 tentative。

status 优先顺序：

1. 当前有效 declaration 为 verified 或 excluded-low-confidence → verified 或 excluded_low_confidence。
2. discovered 且未 confirmed → pending_confirmation。
3. 任一次结果明确 tentative 归属本通道 → tentative_found。
4. 有关联候选 → attempted_not_found。
5. 其余 → untried。

这是保留全部尝试的登记视图：历史 tentative 结果仍参与第 3 项，不因后一次失败或 none 被删掉；
latest_assignment 单独展示最新归属。verified 候选结果不会自动变成 verified 通道。
cleared 撤销声明后重新按第 2–5 项派生，不删除候选结果。coverage 不改变任何通道状态。

show 文本显示原对象表、新通道表（状态、候选数、各 outcome 数、最近结果的 Attempt）及候选表。
最近结果按 seq 确定；最近结果未关联 Attempt 时显示 `-`，不冒充更早的 Attempt 是本次结果。
show --json 返回磁盘 state；哈希或 schema 落后时警告、不改文件。
ledger 从日志只读回放，按通道列出每个候选的全部结果，包括时间、Attempt、outcome、归属和诊断是否存在。
ledger --json 为 `{object:string, channels:[{channel:string,status:string,candidates:Candidate[]}], unassigned:Candidate[]}`；
不传 --channel 时额外保留从未关联任何通道的候选；过滤通道时 unassigned=[]。
suggest 原来的 parents 分组建议保留，新增只读期望核对报告，不自动登记或采用。
