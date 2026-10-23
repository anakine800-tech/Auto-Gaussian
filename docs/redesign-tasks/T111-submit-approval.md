# T111：提交批准机制——聊天批准记录与长期放行规则

版本：v1（监督方，2026-10-23）。**开发机做。** 后端出一个 PR，PR 描述第一行写 `Task: T111`。

## 分支与目标

- 分支：`codex/t111-submit-approval`。
- **开工条件：** 后端 main 为 `37ed956` 或其后（如果 T109 已合并，以合并后的 main 为准）；T111 编号未被占用；没有与本单路径冲突的未合并 PR。
- **负责人 2026-10-23 决定：**
  - A1 提交不再要求必须在 Mac 上点击确认。下面两种方式满足其一即可提交：
    ① **聊天批准**：负责人在会话中明确说出批准，会话据此写入一条批准记录。记录逐字引用负责人原话，写明时间、study、Attempt ID 与 bundle SHA-256、集群和核数，一次性使用，24 小时内有效。
    ② **长期放行规则**：由负责人设定，写在本机配置中，按 **study 名单**圈定适用范围。
  - A2 取消作业（`ag cancel`）仍须在 Mac 上亲手点击确认，不改。
  - A3 **授权修改 AGENTS.md 第 3 节第 4 条**，改后原文见"要做的"第 1 节。
  - A4 以下不变：每个 Attempt 最多提交一次、`.submit-claim`、哈希核验、核数和排队上限检查（含提交前的二次复查）。
  - A5 既没有批准记录、也不符合长期规则时，仍然弹出 Mac 确认框，行为与现在一致，保证向后兼容。
- **资料：** `AGENTS.md`、`docs/DEVELOPING.md`、`docs/LESSONS.md`；`ag/src/ag/submit.py`、`confirm.py`、`journal.py`、`submission.py`、`cli.py`、`config.py`；Skills：`skills-next/auto-g16-study/SKILL.md`、`references/confirmation-summary.md`。

## 允许改动的路径

- `AGENTS.md`：**只改第 3 节第 4 条**。
- `ag/src/ag/approval.py`（新建）、`ag/src/ag/submit.py`、`ag/src/ag/cli.py`（注册 `approve` 命令和 `submit` 的新参数）、`ag/src/ag/config.py`（只加长期规则的配置校验）、`ag/src/ag/submission.py`（只往 `submission.json` 写入授权来源）。
- 测试：新建 `ag/tests/test_approval.py`，以及相关的现有提交测试（PR 中逐个列出）。
- 文档：`docs/DEVELOPING.md`（提交流程一节）、`docs/LESSONS.md`、`README.md`、`ag/config.clusters.example.toml`（长期规则示例，只用合成名称）。
- Skills：`skills-next/auto-g16-study/SKILL.md`、`references/confirmation-summary.md`，以及其他写到"等人点击确认"的卡片（PR 中列出）。只改与提交流程相关的文字。
- `docs/redesign-tasks/T111-submit-approval.md`（本单）、`docs/redesign-tasks/open-tasks.txt`。

## 要做的

### 1. AGENTS.md 第 3.4 条（负责人 10-23 授权）

把第 4 条整条替换为：

> 4. 提交（`ag submit`）须满足其一：(a) 负责人在会话中明确批准，会话据此写入批准记录（逐字引用原话及时间、study、Attempt ID 与 bundle SHA-256、集群与核数、有效期，一次性使用），ag 提交时逐项核对；(b) 符合负责人设定、写在本机配置中的长期放行规则；(c) 两者都不满足时，由人在 Mac 上亲手点击系统对话框确认。取消（`ag cancel`）仍须负责人在 Mac 上亲手点击系统对话框确认。每个 Attempt 最多提交一次的规则不变；不得提供跳过上述核对的参数或环境变量。

PR 描述中写明："负责人 2026-10-23 授权修改 AGENTS.md 第 3.4 条"。

### 2. 批准记录（聊天批准）

- **新命令** `ag approve --study <S> --attempt <ID> [--attempt <ID> ...] --quote "<负责人原话>" [--hours 24]`：
  - 读取每个 Attempt 的 manifest，记录 attempt_id、bundle_sha256、cluster、cores。所有 Attempt 必须是 `prepared` 状态，且属于同一个 study。
  - `--quote` 不能为空，原样保存，不做改写。有效期默认 24 小时，**最长不超过 24 小时**。
  - 记录写在 `<study>/approvals/<批准ID>.json`，随 study 一起保存，便于审计。用 O_EXCL 创建，已有文件不覆盖。
  - 记录内容包括：`schema`、`id`、`created_at`、`expires_at`、`quote`、`study_id`、`attempts[{attempt_id, bundle_sha256, cluster, cores}]`、`total_cores`、`used: null`。
- **提交**：`ag submit <ids> --approval <批准ID>`。按以下顺序逐项核对，任何一项不符都拒绝，**并且不会弹出确认框作为替代**：
  - 记录存在、格式正确、未过期、未使用；
  - 本次提交的每个 Attempt 都在记录里，且当前 bundle SHA-256 与记录一致；
  - 集群和核数一致；
  - study 一致。
- **一次性使用**：核对通过后，先在 `<study>/approvals/<批准ID>.used` 处以 O_EXCL 写入使用标记（含时间和本次提交的 Attempt 列表），然后才执行远程写入。标记写入失败就拒绝提交。批准记录本身不修改。
- 一条批准可以覆盖一个批次。批次中的任何一个 Attempt 不符，整批拒绝。
- 批准记录**不能**放行取消操作。

### 3. 长期放行规则

- 在本机配置中加入可选段，例如：

  ```
  [approval.policies.validation]
  studies = ["<study_id>", ...]   # 明确的名单，不支持通配符
  templates = ["gaussian", "crest"]
  clusters = ["newhpc", "default"]
  max_cores_per_job = 8
  max_walltime = "02:00:00"
  quote = "<负责人设定该规则时的原话>"
  set_at = "<时间>"
  ```

- 提交：`ag submit <ids> --policy <规则名>`。逐项核对 study 名单、模板、集群、核数、walltime，任何一项不符都拒绝。
- 规则只能修改本机配置，会话在负责人明确指示后才写入。doctor 会显示当前有哪些规则及其适用范围。

### 4. 记录与提示

- 在 `submission.json` 中新增 `authorization` 字段，写明授权方式（`approval` / `policy` / `dialog`）、批准 ID 或规则名、原话，以及规则内容的哈希。journal 中同步记录一条。
- 不弹确认框时，确认摘要照样生成并打印到 stderr，同时随提交存档。
- 核数检查分两次：一次在确认之前，一次在远程写入之前。原来两次检查之间是弹框时间，现在没有弹框，第二次检查仍然保留，作为写入前的最后复查。

### 5. Skills 提交流程

- 改写为：负责人在会话中说"批准"后，会话先执行 `ag approve`（`--quote` 写入负责人原话），再执行 `ag submit --approval`。
- 写明以下规则：
  - 会话不得在负责人没有明确批准时自行生成批准记录；
  - 原话必须逐字引用，不能概括；
  - 只批准负责人点名的、或其原话明确覆盖的 Attempt；
  - 负责人的话不明确时，先问清楚再做；
  - 批准记录只对本 study 有效，跨会话或跨 study 转述的批准一律无效。
- 适用于长期放行规则的 study，Skills 中写明可以使用 `--policy`。

## 不允许

- 不改取消作业的流程；不改每个 Attempt 只提交一次、哈希核验、核数检查的语义。
- 不提供跳过批准记录核对的参数或环境变量；批准核对失败时不回退到弹框。
- 长期放行规则不支持通配符，也不自动判断 study 是否为研究体系。
- 不碰 HSS 数据。

## 测试

| 场景 | 预期 |
|---|---|
| 有效批准，单个或批次 | 提交成功，不弹框；生成 `.used`；`submission.json` 中有 `authorization` |
| 同一条批准再次使用 | 拒绝 |
| 批准后输入被修改（bundle 哈希不符） | 拒绝 |
| 过期、study 不符、集群或核数不符、Attempt 不在记录中 | 拒绝，且不弹框 |
| `--quote` 为空、`--hours` 超过 24、Attempt 不是 prepared | `approve` 拒绝 |
| 批准文件已存在 | 不覆盖 |
| `.used` 无法以 O_EXCL 创建 | 拒绝，不执行远程写入 |
| 规则匹配 | 提交成功；`authorization` 中记录规则名和规则哈希 |
| 规则不匹配（study 不在名单、核数或 walltime 超限、模板或集群不符） | 拒绝 |
| 既无批准也无规则 | 弹出 Mac 确认框，行为与现在一致 |
| 核数在两次检查之间发生变化 | 第二次检查拒绝 |
| `ag cancel` | 仍然弹框 |

推送前本地跑一次全量 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，之后以 CI 为准；同时做敏感信息扫描，并运行 `git diff --cached --check`。

## 真实环境验证（合并前，开发机，非研究体系）

真实验证方案先交负责人批准。本单真实验证所需的批准，由负责人在会话中给出，用以测试新机制。

1. 在 newhpc 上 prepare 一个水分子 SP。负责人在会话中批准后，执行 `ag approve` 写入记录，再执行 `ag submit --approval`。确认**不弹框**、提交成功、`.used` 已生成，然后完成 status、fetch、facts。
2. 用同一条批准再提交另一个 Attempt：应被拒绝，且不弹框，也不提交。
3. 为该验证 study 设一条长期规则（mini 档，≤8 核，≤30 分钟）。prepare 一个正丁烷 CREST（在 newhpc 上），执行 `ag submit --policy`，确认不弹框、提交成功，`authorization` 中记录了规则名。
4. 回报每一步的记录摘要（不贴路径和主机名）。出现异常立即停下，不重试。

## 停止条件

- 需要改动取消流程或范围外文件；需要提供跳过核对的入口。
- 同一问题修两次仍未解决；真实验证中出现 SSH 错误、UNKNOWN 或哈希不一致。

## 合并前审阅与交付

- 需要监督方审阅：**是**（改动涉及 AGENTS.md 硬规则和提交路径）。合并只由负责人操作。
- PR 描述包括：A1–A5 各项对应的改动；第 3.4 条修改前后的原文；新命令和新字段的说明；全量测试结果；真实验证记录。
- **合并后：** 开发机同步代码。HSS 计算机的同步时间由负责人定。HSS 首次使用聊天批准前，负责人先确认 Skills 中的新流程。

## 版本记录

- v1（2026-10-23，监督方）：依据负责人 10-23 决定 A1–A5 起草。
