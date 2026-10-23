# T119：研究对象与采用结果登记（`ag catalog`，`ag-catalog/1`）

版本：v1（监督方，2026-10-23）。**开发机做。** 后端出一个 PR，PR 描述第一行写 `Task: T119`。

## 分支与目标

- 分支：`codex/t119-catalog`。
- **开工条件：** 以当前最新的 main（不早于 `47aef3f`）为基线；和 T114 并行（不改同一个文件，只有 `cli.py` 里注册子命令的那一处会有加法冲突）。前端 T121 以后照本单第 2 节的结构开发。
- **负责人 2026-10-23 决定（前端改版规格 v6 第 3、4 节，依赖 B1）：**
  - C1 新增 `ag catalog` 命令，在 study 里登记：**研究对象**（构象 × 电子态）、Attempt 归属于哪个对象、每个对象**当前采用**的 Opt / Freq / SP、对象的退役（转为历史），以及报告的类别。
  - C2 登记用**只追加**的日志文件；ag 另外生成一份派生的状态文件供前端读取。已有的 manifest、facts、review.md、study.md **一律不改**。
  - C3 "采用"必须带负责人原话（`--quote`，逐字引用）。会话不能自己编写原话；已签字的结论要登记，由负责人按 study 逐个授权。
  - C4 写入前做核对：Attempt 存在并且属于本 study；采用时 Attempt 已取回、facts 可读，计算类型与所采用的角色相符；Freq 不能是 `freq_step_review=fail`。
  - C5 提供只读的 `show`（查看当前状态）和 `suggest`（按父子关系给出建议的分组，只打印，不写入）。
- **资料：** `ag/src/ag/attempt.py`（parents、`local_records`）、`facts.py`、`graph.py`、`study.py`、`locks.py`、`approval.py`（T111 的原话与一次性记录写法，可以参考）、`cli.py`；T108 的 facts 字段。

## 允许改动的路径

- 新建 `ag/src/ag/catalog.py`。
- `ag/src/ag/cli.py`：只注册 `catalog` 子命令。
- 测试：新建 `ag/tests/test_catalog.py`，夹具只用合成 study（水、正丁烷等公开小分子）。
- 文档：新建 `docs/ag-catalog-1.md`（字段说明，供前端 T121 使用）；`README.md`；`skills-next/auto-g16-study/` 下与 study 记录相关的卡片（加一节"登记对象与采用结果"，写清 C3 的规矩）；`docs/LESSONS.md`；本单 `docs/redesign-tasks/T119-catalog.md`、`docs/redesign-tasks/open-tasks.txt`。

## 要做的

### 1. 命令

```
ag catalog object      <study> --id <对象ID> --name <显示名> [--state-label S0] [--multiplicity 1] [--conformer A] [--note …] [--dry-run]
ag catalog member      <study> --object <对象ID> --attempt <AttemptID> [--role auto|crest|opt|ts|freq|stable|sp|irc|scan|other] [--dry-run]
ag catalog adopt       <study> --object <对象ID> --role opt|freq|sp --attempt <AttemptID> --quote "<负责人原话>" [--report <analyses 下的相对路径>] [--dry-run]
ag catalog retire      <study> --object <对象ID> --reason "<原因>" [--dry-run]
ag catalog report-kind <study> --report <analyses 下的相对路径> --kind formal|energy|state-check|ensemble|irc|thermo|stage-review|figure|other [--dry-run]
ag catalog show        <study> [--json]
ag catalog suggest     <study>
```

- 对象 ID：沿用 `study.identifier()` 的规则，在 study 内唯一。`object` 对已存在的 ID 报错；要改显示名，再记一条 `object` 事件，并加 `--update`。
- `--role auto`：从 route 推断计算类型（Opt、TS、Freq、Stable、SP、IRC、Scan），从模板推断 CREST 和 xTB。推断不出来就报错，要求手动指定。
- `--dry-run` 只打印将要写入的事件和核对结果，不写文件。

### 2. 文件与结构（写死；前端照此开发）

- 日志：`<study>/catalog/journal.jsonl`。每行一个事件：
  ```
  {"schema":"ag-catalog/1","seq":<从 1 开始连续递增>,"at":"<UTC ISO>","op":"object|member|adopt|retire|report-kind",
   ...各 op 的字段..., "prev_sha256":"<上一行的 SHA-256；第一行为 null>"}
  ```
  - `object`：`id, name, state_label|null, multiplicity|null, conformer|null, note|null, update(bool)`
  - `member`：`object, attempt, role`
  - `adopt`：`object, role, attempt, quote, report|null, checks:{fetched, facts_readable, role_match, freq_review}`
  - `retire`：`object, reason`
  - `report-kind`：`report, kind`
- 状态：`<study>/catalog/state.json`，由 ag 每次写完日志后重新生成：
  ```
  {"schema":"ag-catalog-state/1","journal_sha256":"<整个日志文件的 SHA-256>","generated_at":"…",
   "objects":[{"id","name","state_label","multiplicity","conformer","status":"adopted|candidate|retired",
               "members":[{"attempt","role"}],
               "adopted":{"opt":{"attempt","at","quote","report"}|null,"freq":…,"sp":…},
               "values":{"scf_h":…,"zpe_h":…,"g_h":…,"source":{"scf_h":"<AttemptID>",…}}}],
   "report_kinds":{"<相对路径>":"<kind>"}}
  ```
  - `status`：有任何采用记录就是 `adopted`；被退役就是 `retired`；否则是 `candidate`。
  - `values` 从**被采用的** Attempt 的 facts 中**复制**（SP 的 scf、Freq 的 ZPE 和 G），不做任何计算；拿不到就写 null。
- 写入：
  - 用 `locks.py` 的 study 级锁；
  - 日志用 `O_APPEND` 追加，并 `fsync`；
  - 状态文件先写临时文件，再 `os.replace` 替换（这是本机派生文件，不是服务器文件，也不是研究证据）；
  - 写入前核对整条日志的 `seq` 和 `prev_sha256` 链是否完整，不完整就拒绝写入，并提示人工处理。**ag 不修复、不重写日志。**
- 前端以后读 `state.json`，并用 `journal_sha256` 核对是否与日志一致；不一致就显示警告。本单不改前端。

### 3. 核对（C4）

- 所有命令：study 存在；Attempt 存在、属于本 study，并且只按精确 ID 查找。
- `member`：`role` 与推断出的计算类型一致；手动指定的角色与推断结果不同时，要求加 `--force-role`，并在事件里记下。
- `adopt`：
  - Attempt 已取回（fetched），facts 可读；
  - `role` 与计算类型相符（opt 对 Opt 或 TS；freq 对 Freq，或 Opt+Freq 同一作业；sp 对 SP）；
  - Freq 的 `freq_step_review` 不是 `fail`（`manual_review` 允许，但输出里要醒目提示）；
  - `--quote` 不能为空，长度不超过 2000 字；
  - 该 Attempt 如果还不是这个对象的成员，自动补一条 `member` 事件。
- `report-kind`：路径规范化后必须落在 `analyses/` 内并且文件存在。

### 4. `show` 与 `suggest`（C5）

- `show`：用表格打印各对象的状态、成员和采用情况；`--json` 时输出 `state.json` 的内容。只读。
- `suggest`：按 parents 关系把尚未归属任何对象的 Attempt 连成链，每条链给出建议的对象 ID 和成员列表，并打印出对应的 `ag catalog` 命令草稿。**只打印，不写入。**

### 5. Skills 卡片

- 写明：会话可以运行 `object`、`member`、`report-kind`、`show`、`suggest`；**`adopt` 只能逐字引用负责人在当前对话中的原话**，不能转述，不能跨会话引用，也不能自己生成原话；已签字结论的登记，要负责人按 study 逐个授权。

## 不允许

- 不改 manifest、facts、review.md、study.md、签字记录，不改已有的 Attempt。
- 不修复或重写日志；不提供删除事件的命令（撤销只能靠 `retire`，或再记一条新事件）。
- 不连服务器；不计算能量差；不做科学判断。
- 夹具、文档和 PR 里只用合成 study 和公开小分子。

## 测试

| 场景 | 预期 |
|---|---|
| object → member → adopt opt/freq/sp | 日志 5 行（adopt 时自动补 member），`seq` 连续，哈希链正确；`state.json` 中 `status=adopted`，`values` 从 facts 复制 |
| `--dry-run` | 不写文件，打印事件和核对结果 |
| 采用未取回的 Attempt | 拒绝 |
| 采用 `freq_step_review=fail` 的 Freq | 拒绝；`manual_review` 允许并给出提示 |
| `--role sp` 指向 Opt 作业 | 拒绝 |
| `--quote` 为空 | 拒绝 |
| 其他 study 的 Attempt | 拒绝 |
| 重复的对象 ID | 拒绝；加 `--update` 时接受 |
| `retire` | `status=retired`，采用记录保留在日志中 |
| 日志被手工改坏（`seq` 断开或哈希不符） | 拒绝写入；`show` 也报告日志损坏 |
| 两个进程同时写 | 有锁，结果串行，链不断 |
| `report-kind` 指向 analyses 外的路径 | 拒绝 |
| `suggest` | 只打印，不写文件；链和父子关系一致 |
| `show --json` | 与 `state.json` 一致 |

推送前本地跑一次全量 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，之后以 CI 为准；同时做敏感信息扫描，并运行 `git diff --cached --check`。

## 真实环境验证（合并前，开发机；不提交作业）

- 把一个**非研究的验证 study**（只含公开小分子）复制到临时目录，在副本上跑：`suggest` → 用 `--dry-run` 跑一遍 → 真正写入一个对象和一次采用（原话用"验证用，非研究结论"）→ `show`。确认副本中原有的文件哈希不变。研究 study 一律不动。
- 出现异常就停下汇报，不要重试。

## 停止条件

- 需要改已有的 Attempt 文件或 study.md；需要改动范围外的文件。
- 同一问题修两次仍未解决。

## 合并前审阅与交付

- 需要监督方审阅：**是**（写 study 数据，涉及原话记录）。合并只由负责人操作。
- PR 描述包括：C1–C5 各自对应的改动、`ag-catalog/1` 与 `ag-catalog-state/1` 的字段表、全量测试结果、真实验证记录。
- **合并后：** 开发机同步。各研究 study 什么时候开始登记、已签字的结论要不要补登记，由负责人逐个决定。

## 版本记录

- v1（2026-10-23，监督方）：依据负责人 10-23 决定 C1–C5 与前端改版规格 v6 第 4 节 B1 起草。

## 实现与验证记录（2026-10-23）

- 基线 `47aef3f`，分支 `codex/t119-catalog`。C1–C5 实现在 `catalog.py`，CLI 只增加模块注册；字段表见 `docs/ag-catalog-1.md`。
- 使用 `locks.py` 现有锁函数，将锁目录绑定到 study 的 catalog；不修改锁工具。日志每行哈希包含末尾 LF，自动 member 与 adopt 在同一锁内追加；状态由同目录临时文件原子替换。
- 测试表“5 行”按事件规则澄清：对象、已有 Opt+Freq 成员、三个角色的采用、自动 SP 成员合计 6 行；三个不同 Attempt 全部自动加入时合计 7 行。未省略或合并事件。
- 本地相关验证：`ag/tests/test_catalog.py` 45 项通过；与 `skills-next` 合计 554 项通过。
- 推送前全量执行一次：4517 passed、19 skipped、10 failed（848.44 s）；10 项失败均为 `test_smoke.py` 的注册模块清单缺少新增 catalog。19 项跳过为 18 项 Linux 方言/procfs 检查和 1 项未启用的私有日志检查。
- 范围补充：负责人在当前会话明确回复“批准这两行测试同步”，授权 `ag/tests/test_smoke.py` 的参数清单及预期模块清单增加 catalog；除此以外不改该文件。不为迁就旧清单而改变产品注册方式；补测 `ag/tests/test_smoke.py ag/tests/test_catalog.py` 为 69 passed（26.90 s），后续以 CI 为准。
- 真实本地验证使用现有非研究水/正丁烷工程验证 study 的临时副本，不连接服务器。执行版本为上述基线加 T119 改动，catalog.py SHA-256：`9630f907317628b4c30fe95c4689eedbfb74d69531670f765516155508a57dc4`。
- 首次 suggest 因 macOS 临时目录路径含系统符号链接而被拒绝，未写 catalog；按停止条件报告。负责人在当前会话明确回复“允许，使用实际路径重新验证”，后以同一副本的实际路径执行，不改变产品路径保护。
- 授权后依次运行 suggest、object dry-run、object、adopt dry-run、adopt、show、show JSON，7 步退出码均为 0；采用原话为工单指定“验证用，非研究结论”。
- 源 study 与副本原有 94 个文件的 SHA-256 前后全部相同；两次 dry-run 无写入；新增仅 catalog 的 journal、state、锁文件；采用 SCF 与现有 facts 相同，show JSON 与 state 相同。完整输出及哈希清单保留本机临时目录，不进入仓库。
- 当前阻塞：工程验证无；合并前仍需监督方审阅，研究对象启用和旧签字补登记由负责人逐 study 决定。
