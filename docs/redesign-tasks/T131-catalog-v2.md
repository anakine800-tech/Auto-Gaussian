# T131：catalog v2 后端——对象期望值、反应通道与候选台账

版本：v1（监督方，2026-10-26）。**开发机做。** 后端出一个 PR，PR 描述第一行写 `Task: T131`。

## 分支与目标

- 分支：`codex/t131-catalog-v2`。
- **开工条件：** 以后端 main（不早于 `1e1d66b`，含 T130）为基线；T131 编号未被占用。可以与 T135 并行（两单不改同一文件）。前端 T132 在本单合并后照第 6 节字段开发。
- **目标：** 让每个 TS 初猜候选都能回答“从哪来、试过什么、结果如何、归到哪个通道”，让“某通道已尝试未找到”有记录可查，而不是空白；让对象记录期望的元素组成和电荷，供后续 T137 判断输入完整性。
- **负责人决定（10-24 A2/A3/Q1；10-26 K1–K7）：**
  - **K1 升级时机**：catalog 写入第一条 v2 事件时才升级。v2 事件包括：新增的通道、候选、覆盖结论事件，以及带期望组成或期望电荷的 object 事件。
    - 从这一行起，日志新增行一律写 `schema: "ag-catalog/2"`（含旧类型事件），state 改为 `ag-catalog-state/2`。
    - 已有 /1 行字节不变，不迁移、不重算哈希链（链照常跨越 /1 与 /2 行）。
    - 没有 v2 事件的 catalog 保持 /1：生成的 state/1 与 main 的输出逐字节相同。
    - 触发升级的写命令必须带 `--upgrade-catalog`；不带时拒绝，并说明升级后果（旧版 ag 和 v4.5.x 前端将不能再读写这个 catalog）。`--dry-run` 显示升级预览。
    - 新读者同时接受 /1 和 /2；/1 行只能出现在第一条 /2 行之前，/1 行里出现新事件类型视为损坏。
  - **K2 通道六种状态**（state 里的派生值，英文键见第 6 节）：未尝试 / 已尝试未找到 / 暂定找到（待 DFT 验收）/ 已验证 / 待确认通道 / 低置信度排除。另有对象级整体结论“在声明的通道范围与采样预算内稳定”。
  - **K3 候选分两类事件**：`candidate` 登记几何与来源，不要求已有 Attempt；`candidate-result` 追加诊断、关联 Attempt、结果和归属，同一候选可以追加多次，只追加不改写。
  - **K4 对象期望值**：object 事件新增期望元素组成、期望电荷，由人显式写入；三态区分“未提供 / 未知 / 有效值”，电荷 0 是有效值。ag 可以根据某个成员的 manifest 生成建议，但只打印、不写入。修改期望值后，已有成员只报告不一致，不回写 manifest、不撤销历史事件。现有 `multiplicity` 字段沿用，不新增第二个多重度字段。
  - **K5 通道挂在对象下**：通道属于一个 catalog 对象（通常是某个成键步的 TS 对象）。化学定义由人用文字写（立体标签、进攻面等），可选“对应的产物分支”；ag 不推断化学含义。采样中新发现的通道登记为“待确认”，人确认后才进入正常状态推导。
  - **K6 候选几何存档**：登记时把 XYZ 独占复制到 `<study>/catalog/candidates/<sha256>.xyz`，权限只读，不覆盖；相同哈希已存在就复用。事件记录哈希和 study 内的相对路径；原路径只作为来源说明。
  - **K7 原话要求**：只有结论性事件要逐字引用负责人原话：通道“已验证”“低置信度排除”及撤销声明；候选归属“已验证”；对象整体“稳定”结论及撤销。规则沿用 adopt（非空、至多 2000 字符、保留原样）。登记通道、登记候选、追加诊断或结果、写期望值、确认待确认通道都不需要原话。
- **资料：** `docs/ag-catalog-1.md`、`ag/src/ag/catalog.py`（`read_journal`、`replay`、`plan`、`change`、`show`、`suggest`、`register`）、`docs/research/ts-guess-audit.md` 第 6、8、9、11 节、`docs/research/ts-guess-plan-v1.md` 的 T-B 一节。
- **新增约束防的事故：** 候选和失败尝试没有记录，导致“已尝试未找到”和“没试过”无法区分；旧读者把新日志误读为旧格式（审计第 8 节）；期望组成按 study 统一判断，误杀不同计量的子任务（规格 T-E 第一条）。

## 允许改动的路径

- `ag/src/ag/catalog.py`：读写 v2、事件回放、派生 state/2、新子命令。可以把新代码拆到新文件 `ag/src/ag/catalog_v2.py`（只能有一份 replay 实现，/1 与 /2 共用）。
- 测试：`ag/tests/test_catalog*.py` 中受影响的用例（PR 中逐个列出）；新建 `ag/tests/test_catalog_v2.py`。夹具全部合成（水、正丁烷、虚构的小分子 TS 几何）。
- 文档：**新建** `docs/ag-catalog-2.md`（第 6 节契约，前端 T132 照此开发）；`docs/ag-catalog-1.md` 顶部只加一行指向 /2；`README.md` 的 catalog 一节；本单 `docs/redesign-tasks/T131-catalog-v2.md`、`docs/redesign-tasks/open-tasks.txt`。
- **不改** manifest、facts、review、`attempt.py`、`profile.py`、`AGENTS.md`、`skills-next/` 卡片（口径修订在 T139）、前端仓库、`CHANGELOG.md` 和版本号。

## 要做的

### 1. 读写兼容（K1）
- `read_journal` 接受 /1 与 /2，并校验 schema 单调（/2 之后不得再出现 /1）、seq 连续、哈希链；/1 行中出现新事件类型或新字段一律视为损坏。
- `replay` 只有一份实现：旧事件在 /1、/2 行中语义相同；旧 object 更新事件缺少期望字段时**保留**已有期望值，不清空。
- state：没有 /2 行时按现行代码生成 state/1（逐字节不变）；有 /2 行时生成 state/2（第 6 节）。
- 升级流程：写命令判断本次是否会写第一条 /2 行；需要 `--upgrade-catalog`，`--dry-run` 显示“将升级”及影响说明。升级本身不额外写一条“升级事件”。
- 损坏、未知事件、末行不完整：照旧拒绝并要求人工处理，不修复、不截断。

### 2. 对象期望值（K4）
- `ag catalog object` 新增 `--formula <化学式|unknown>`、`--charge <整数|unknown>`。化学式按 Hill 规范化后保存（输入时元素顺序不限）。不指定就是“未提供”。
- `--update` 未指定的期望字段沿用旧值；要改回“未提供”须显式 `--formula unset` / `--charge unset`。
- 新增只读命令 `ag catalog object-suggest <study> --attempt <ID>`：从该 Attempt 的不可变 manifest（`science.geometry` 计数元素、`science.charge`、`science.multiplicity`；QST 取 `science.structures[]` 并要求各组一致；xTB/CREST 取输入 XYZ 与 chrg/uhf）生成建议命令，只打印，不写入。缺字段时写“无法建议”，不用默认 0/1 代替。
- `show`、`suggest` 报告：对象已有成员中，manifest 的组成、电荷、多重度与当前期望值不一致的（只读报告，不改任何文件）。期望值为“未提供”或“未知”的项跳过，并在报告里注明。

### 3. 通道（K2、K5、K7）
- `ag catalog channel <study> --object <对象> --id <通道ID> --name <显示名> --definition <化学定义文字> [--product-branch <产物分支标签>] [--discovered] [--update] [--confirm]`
  - 通道 ID 用 `study.identifier()` 规则，在同一对象内唯一。
  - `--discovered` 登记为待确认；之后用 `--update --confirm` 确认（不需要原话）。
  - 已 retired 的对象拒绝新增通道。
- `ag catalog channel-status <study> --object <对象> --channel <通道> --status verified|excluded-low-confidence|cleared --quote <原话> [--reason <文字>]`
  - `verified` 的前提：该通道至少有一个候选结果的归属是“已验证”且指向本通道（写入时核对并存 `checks`），否则拒绝。
  - `excluded-low-confidence` 必须带 `--reason`。
  - `cleared` 撤销先前的声明，也要原话。
- `ag catalog coverage <study> --object <对象> --statement stable|withdrawn --scope <通道范围说明> --budget <采样预算说明> --quote <原话>`：整体结论，最新一条有效；`withdrawn` 撤销。
- **派生状态**（第 6 节 `channels[].status`），按以下优先级：
  1. 最新有效声明是 `verified` 或 `excluded-low-confidence`；
  2. 未确认的 discovered 通道 → 待确认；
  3. 有候选结果把归属指向本通道且状态为暂定 → 暂定找到；
  4. 有以本通道为目标的候选，或有结果指向本通道 → 已尝试未找到；
  5. 其余 → 未尝试。

  “已验证”只能来自声明，不能由候选结果自动推出。

### 4. 候选（K3、K6、K7）
- `ag catalog candidate <study> --object <对象> --id <候选ID> --xyz <文件> --origin scan|qst|template-transform|path-search|manual|literature [--parent-attempt <ID>] [--parent-file <文件>] [--transform-json <文件>] [--target-channel <通道>] [--doi <DOI> --si-location <文字>] [--note <文字>]`
  - XYZ：标准格式（原子数行、注释行、坐标行），元素合法，坐标是有限数，文件 ≤1 MiB；原子数和元素组成写入事件。不合法就拒绝。
  - 存档按 K6；拒绝符号链接；`catalog/candidates/` 不存在时创建（0700）。
  - `--parent-attempt` 必须是本 study 的精确 ID；`--parent-file` 只记录该文件的 SHA-256 和用户给出的说明，不复制。
  - `--transform-json` 是一个 JSON 对象（≤64 KiB），原样保存，ag 不解释。
  - `literature` 来源必须带 `--doi`；DOI 只做格式检查，不联网核实。
  - 目标通道必须是本对象下已登记的通道；可以为空。
  - 对象有期望组成或电荷时，只**报告**候选几何与期望值是否一致（电荷无法从 XYZ 得到，就写“未核对”），**不拒绝**（输入完整性的硬拒绝属于 T137）。
- `ag catalog candidate-result <study> --object <对象> --candidate <候选> --outcome <结果> [--attempt <ID>] [--diagnosis-json <文件>] [--assign none|tentative|verified|undetermined] [--channel <通道> ...] [--quote <原话>] [--note <文字>]`
  - `outcome`：`diagnosed`（只有诊断，尚无 DFT 结果）、`accepted`（通过验收）、`other_channel`（落入其他通道）、`minimum`（收敛到极小点）、`opt_failed`（优化失败）、`multiple_imag`（多个虚频）、`other`（须带 `--note`）。
  - 归属：
    - `tentative`、`verified` 恰好一个通道；
    - `undetermined` 列出两个及以上候选通道（例如 TS 后分岔），或不列（表示无法判断）；
    - `none` 不带通道。
  - `verified` 必须带原话和 `--attempt`。写入前核对：该 Attempt 已 fetched、facts 可读、`n_imag == 1`、是本对象成员；结果存进 `checks`，任一不满足就拒绝。
  - `--diagnosis-json` 是 JSON 对象（≤64 KiB），原样保存，ag 不解释、不打分。
  - `--attempt` 若还不是本对象成员，只报告提示，不自动加 member（成员登记仍由 `member` 命令完成）。

### 5. 台账查询
- `ag catalog show <study> [--json]` 显示通道表（状态、候选数、各结果计数、最近一次结果的 Attempt）和候选表（来源、目标通道、最新结果与归属）。
- 新增 `ag catalog ledger <study> --object <对象> [--channel <通道>] [--json]`：按通道列出全部候选及其每一次结果（时间、Attempt、outcome、归属、诊断是否存在），作为“已尝试未找到”的依据。只读。

### 6. 契约 `docs/ag-catalog-2.md`（T132 照此开发；字段名定稿后不得改）
- 日志：`schema` 为 `ag-catalog/1` 或 `ag-catalog/2`；新 op 为 `channel`、`channel-status`、`coverage`、`candidate`、`candidate-result`；`object` 在 /2 行可带 `expected_formula`、`expected_charge`，取值为 `{"state": "unset"|"unknown"|"set", "value": <Hill 字符串|整数|null>}`。逐个 op 列出全部字段及类型。
- state/2 顶层：`schema = "ag-catalog-state/2"`、`journal_sha256`、`generated_at`、`objects`、`report_kinds`。/1 的全部字段原样保留、含义不变。
- `objects[]` 新增：
  - `expected`：`{formula, charge}`，结构同上；
  - `channels[]`：`id`、`name`、`definition`、`product_branch`、`discovered`、`confirmed`、`status`（`untried|attempted_not_found|tentative_found|verified|pending_confirmation|excluded_low_confidence`）、`declaration`（null 或 `{status, at, quote, reason}`）、`candidate_ids`、`outcome_counts`；
  - `candidates[]`：`id`、`file`、`sha256`、`n_atoms`、`formula`、`origin`、`parent`、`transform`、`target_channel`、`literature`、`note`、`registered_at`、`results[]`（每次结果的全部字段）、`latest_assignment`；
  - `coverage`：null 或 `{statement, scope, budget, at, quote}`；
  - `member_mismatches[]`：`{attempt, field, expected, actual}`。
- 写明：catalog 不判断化学含义；“已验证”只来自负责人声明；状态是登记视图，不是科学验收。

## 不允许

- 不新增任何提交路径；不连接服务器；不调用解析器改写 facts；不设任何自动拒绝阈值。
- 不改旧事件含义，不重写或迁移已有日志行；不新增修复日志的命令。
- 候选结果不得自动产生“已验证”；不把尝试次数当作简并度；不推断通道化学含义。
- **合并后、前端 T132 合并并在两台部署之前，任何真实研究 study 都不写 v2 事件。**
- 夹具和 PR 里不出现真实研究对象、结构、study 名、Attempt 编号。

## 测试

| 场景 | 预期 |
|---|---|
| 只有 /1 事件的 catalog（用 main 代码生成的合成日志） | 读取、写旧事件后，state/1 与 main 输出逐字节相同 |
| 第一次写 v2 事件，不带 `--upgrade-catalog` | 拒绝，文件不变；`--dry-run` 显示升级预览 |
| 带 `--upgrade-catalog` | 新行为 /2，旧行字节不变，哈希链跨越连续；state 变为 /2 |
| /2 之后再写旧类型事件 | 写为 /2 行 |
| /2 行之后出现 /1 行；/1 行含新 op | 判定损坏 |
| 旧 object 更新事件（缺期望字段）回放 | 已有期望值保留 |
| `--charge 0` / `unknown` / 不指定 / `unset` | 分别为 set 0、unknown、沿用、unset |
| `object-suggest`（单结构、QST 一致与不一致、xTB） | 输出建议或“无法建议”，不写文件 |
| 修改期望值后已有成员不一致 | show 列出 mismatch；manifest 和历史事件不变 |
| 通道登记、重复 ID、对象已 retired | 成功 / 拒绝 / 拒绝 |
| discovered 通道未确认 → 确认 | pending_confirmation → 按候选推导 |
| 状态推导五级优先 | 逐级覆盖 |
| `verified` 声明而没有已验证归属的候选结果 | 拒绝 |
| `excluded-low-confidence` 缺 `--reason` 或缺原话 | 拒绝 |
| `cleared` 撤销声明 | 回到推导状态 |
| 候选 XYZ 不合法、超大、是符号链接 | 拒绝 |
| 同一几何登记两次（不同候选 ID） | 存档复用同一文件，不覆盖 |
| literature 来源缺 DOI | 拒绝 |
| 候选组成与对象期望值不一致 | 只报告，不拒绝 |
| `candidate-result` 归属规则（tentative 多通道、verified 缺原话、verified 的 Attempt 未 fetched 或 `n_imag ≠ 1` 或不是成员） | 拒绝 |
| `undetermined` 两个通道 | 接受，两个通道都不因此进入“暂定找到” |
| 同一候选追加多次结果 | 全部保留，`latest_assignment` 取最新 |
| `ledger` | 按通道列出全部候选与结果 |
| 并发写（两个进程） | 共用 catalog.lock，序号连续 |
| 所有写命令 `--dry-run` | 不创建任何文件（含存档目录和锁文件） |

推送前本地跑一次全量 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，之后以 CI 为准；运行 `python scripts/scan_public.py`（带本机词表）和 `git diff --cached --check`。

## 真实环境验证（合并前，开发机；只在临时非研究 study）

- 在临时目录新建一个非研究 study（合成 Attempt 目录和 manifest 即可，不提交计算），先用 v4.5.1 的 ag 写几条 /1 事件，再用本分支：
  - 升级；
  - 登记对象期望值、两个通道（其中一个 discovered）、三个候选（scan、manual、literature 来源各一）；
  - 追加诊断和结果（含 undetermined）；
  - 声明一次 excluded 后撤销；
  - 查询 show / ledger。
- 确认 v4.5.1 的 ag 读取升级后的日志时报“损坏/不支持”而不是误读，并记录原文类别；确认 v4.5.1 前端（本机 8773）打开这个临时 study 时提示 state 不受支持、回退为未登记。**只读打开，不在 8773 上做任何操作。**
- 不碰任何真实 study。PR 里只写结果。

## 停止条件

- 需要改 manifest、facts、attempt 或卡片；需要新增远程操作。
- 发现 /1 的派生 state 无法保持逐字节不变。
- 同一问题修两次仍未解决。

## 合并前审阅与交付

- 需要监督方审阅：**是，逐行审**（日志格式、回放、原话核对、存档写入）。合并只由负责人操作。
- PR 描述包括：K1–K7 各自对应的改动、`docs/ag-catalog-2.md` 全文对照、测试表逐项结果、真实验证记录。
- 用 `gh pr view <编号> --comments` 读取审阅评论，逐条处理并回复。

## 版本记录

- v1（2026-10-26，监督方）：依据 10-24 的 A2/A3/Q1 和 10-26 的 K1–K7 起草；对应审计拆单建议中的 T-B 后端部分。

## 开发与验证记录（Codex，2026-10-26）

- 基线：后端 main `1e1d66b`（含 T130），分支 `codex/t131-catalog-v2`；开工检索未发现已占用 T131 的 PR。
- K1：同一回放支持 /1 前缀及 /2 后缀；显式升级、不改旧行；main 生成的合成日志与固定时钟 state/1 字节对照通过。
- K2：六种通道状态、原话声明/撤销、有限范围与预算的整体结论；不自动科学验收。
- K3：candidate 与 candidate-result 分开，全部结果留存，最新归属独立展示。
- K4：Hill 组成与 charge 三态；沿用 multiplicity；从不可变 manifest/已核验 XYZ 只读建议与不一致报告。
- K5：对象内通道、发现后确认、retired 对象拒绝新增；不推断化学含义。
- K6：候选按 SHA-256 独占存档、0400 文件/0700 目录、同字节复用、拒绝符号链接与损坏存档。
- K7：结论原话的非空/长度/原样保存；已验证归属核对 fetched/facts/n_imag/member 并留 checks。
- `docs/ag-catalog-2.md` 覆盖第 6 节全部事件和 state 字段；另明确嵌套 Parent/Assignment/checks、历史结果计数、只读输出与升级限制。
- 既有测试仅调整 `test_catalog.py::test_lifecycle_chain_values_and_existing_files_unchanged`：为合成 manifest 显式提供已声明的 multiplicity=1，避免新只读核对把缺字段误当已核对。
- catalog 专项测试：110 项通过（原 56 项、新 54 项）；XYZ 超限用例使用简短测试 ID，防止测试日志被 1 MiB 输入撑大。

### 工单测试表逐项结果

| 工单场景 | 结果 / 对应测试 |
|---|---|
| /1 读取与追加旧事件字节兼容 | 通过；test_main_v1_bytes_and_old_event_after_upgrade，基线生成日志与派生状态 SHA-256 对照 |
| 无 upgrade 标志拒绝、dry-run 升级预览 | 通过；test_upgrade_refusal_and_preview_leave_every_file_unchanged（空目录和已有 /1 两种） |
| upgrade 后旧字节保留、连续哈希链与 state/2 | 通过；同上及 main_v1 字节用例 |
| 升级后旧事件也写 /2 | 通过；main_v1 字节用例 |
| schema 倒退、/1 新 op/字段损坏 | 通过；test_schema_and_v2_damage_refused_without_repair |
| 旧 object 更新保留期望 | 通过；test_expected_tristate_preservation_and_formula |
| charge 0/unknown/省略/unset | 通过；同上 |
| object-suggest 单结构/QST/xTB/CREST 与缺值 | 通过；test_object_suggest_provenance_and_missing_values（8 种） |
| 期望变化报告成员不一致且证据不变 | 通过；test_member_mismatches_and_unknown_are_reports_only |
| 通道新增/重复/retired | 通过；test_channel_priority_confirmation_declarations_and_coverage |
| discovered 确认 | 通过；同上 |
| 派生优先级 | 通过；同上及 all_result_history 用例 |
| 缺已验证候选的 verified 声明 | 通过；channel_priority 用例拒绝 |
| 排除缺 reason/quote | 通过；channel_priority 用例拒绝 |
| cleared 撤销 | 通过；channel_priority 用例回到派生状态 |
| XYZ 非法/超限/符号链接 | 通过；bad_xyz、archive_reuse、candidate_directory 用例 |
| 相同几何不同 ID 复用 | 通过；test_archive_reuse_symlinks_and_provenance，字节/mtime/权限保持 |
| literature 缺 DOI | 通过；archive_reuse 用例拒绝 |
| 候选与期望不一致只报告 | 通过；archive_reuse 用例 |
| 归属约束及 verified 证据缺失 | 通过；invalid_result_assignment 与 verified_checks 用例 |
| undetermined 两通道 | 通过；test_all_result_history_undetermined_ledger_and_cli |
| 追加多次、latest_assignment 最新 | 通过；同上 |
| ledger 全历史 | 通过；同上，含过滤和无通道候选 |
| 两进程共锁、序号连续 | 通过；test_two_processes_share_lock_during_upgrade_and_archive 及原并发测试 |
| 全部写命令 dry-run 不建文件 | 通过；原 dry-run、新 every_v2_write、first_candidate_dry_run 用例 |

额外覆盖：存档目录符号链接、已有存档损坏、读取后源文件变化、JSON 非对象/超限/非有限数、结论原话长度。

### 本机临时非研究 study 验证

执行版本：旧后端 v4.5.1 (`39aae35`)，新后端为本分支；前端 v4.5.1，本机 8773 原服务。
只创建新的临时合成水 study，未提交计算、未连接服务器、未修改任何已有研究 study 或前端配置。
旧版先写 object/member 两条 /1 事件；新版的 state/1 与旧版固定 generated_at 后逐字节相同。
随后新版登记期望值并升级、两个通道（一个 discovered）、三个来源候选（scan/manual/literature）、
诊断及结果（含 undetermined），声明 excluded 后 cleared，show/ledger 均正常。
原 /1 前缀字节不变；state/2 正确；三候选复用同一份只读 XYZ。

旧后端读取升级日志返回退出码 1，stdout JSON 的 error 类别及原文为：
`Catalog journal damaged: seq or prev_sha256 mismatch; requires manual handling; ag never repairs or rewrites the journal`。
这是旧版本对 schema 不匹配的预期拒绝，没有把新日志误读为旧格式。
验证脚本最初假设退出码 2/stderr，断言不符；只读检查确认实际为 1/stdout 后修正记录，未重复写验证事件。

8773 只读打开临时 study 的计算链页面，显示：
`登记记录格式或日志哈希不一致，按没有登记处理`，并显示 `未登记 · object-1`。
旧前端采用通用格式警告而非单独的“不支持 state/2”文案；实际已拒绝 state/2 并回退。
仅打开、读取和留存截图，没有点击任何操作按钮。临时 study、验证输出和截图留在本机仓库外。

当前阻塞（科学审阅）：待监督方按本 PR head 逐行审阅日志格式、回放、原话核对和存档写入；合并由负责人操作。


### 推送前最终检查

- `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`：**4958 passed, 19 skipped**，289.82 秒；本地全量只跑一次。
- 跳过：18 项依赖 GNU/Linux stat、procfs 或进程方言，交 Linux CI；1 项私有日志 opt-in 未启用。
- 新版 CLI 的 6 类写入 dry-run 及 show/ledger 实际命令均通过；临时 study 的全部文件字节与 mtime 不变。
- 全仓 1805 文件及暂存九文件的本机词表扫描均为 0 错误；`git diff --cached --check` 通过。
- author/committer 使用 noreply 邮箱；无真实研究夹具、主机信息、配置或计算输出进入提交。
