# T99：Gaussian route 换行导致子任务误判的修复 + facts 重新解析（保留旧版本）

## 分支与目标

- 分支：`codex/t99-route-wrap`；基于最新 main，一张任务单一个 PR。**开发机做。**
- **优先级：高。** 当前所有 route 恰好在关键词中间换行的 Opt+Freq 都会被判为顶层 `incomplete`，会挡住所有热化学签字。
- **起因（10-17 只读核对，细节不进仓库）：** Gaussian 在日志中打印 route 时按固定宽度换行，并且会把词从中间截断（实际见到 `… Fre` / `q`、`… Fr` / `eq`）。解析器只看 route 的第一行，所以第二段 Freq 没被识别，产生 `Unexpected or unrecognized job section 2` 警告；同时顶层 `termination` 被记为 `incomplete`，而日志中两段各有一次 `Normal termination`，`job_sections` 内两段也都是 `normal`。
- **目标：**
  1. 修正 route 的拼接和子任务识别；
  2. 修正顶层终止的判定规则；
  3. 新增“重新解析”命令：用已取回的本地日志重新生成 facts，**旧 facts 保留并归档，不直接覆盖**，并列出 study 中引用旧哈希的文件，供人重新确认。
- **负责人 10-17 决定：** 修复后不覆盖旧 facts；重新解析写新版本，旧版本归档，在 study.md 中记录原因；涉及已签内容的由负责人重新确认。
- 资料：`ag/src/ag/` 中生成 facts 的 Gaussian 解析模块（route 读取、`job_sections`、顶层 `termination`、`parser_warning`）；`ag facts` 现有命令；`docs/` 中 ag-facts/1 格式说明；`skills-next/auto-g16-study/references/study-md-template.md`（进度日志）；T82 的 thermo 前置检查。

## 允许改动的路径

- Gaussian 日志解析模块（route 拼接、子任务识别、顶层终止判定）。
- `ag/src/ag/cli.py` 及 `ag facts` 所在模块：新增 `--reparse` 相关选项（见下）。
- ag-facts/1 格式文档：补充顶层 `termination` 的判定规则和新增的 `parser` 字段说明（只新增可选字段，不改已有字段含义）。
- 新增测试 `ag/tests/test_route_wrap.py`、`ag/tests/test_facts_reparse.py` 及合成日志夹具；已有解析测试中**只在期望值因本修复而正确改变时**调整，并在 PR 中逐条列出。
- `skills-next/auto-g16-study/SKILL.md`：在审阅或结果相关步骤补一句“facts 重新解析的流程与记录方式”；`study-md-template.md` 进度日志处补一行示例格式。
- `docs/redesign-tasks/T99-route-wrap-reparse.md`：本任务单。
- **不改** `remote.py`、`submit.py`、`status.py`、`transport.py`、`fetch.py` 的远程部分，不改任何模板，不改前端仓库。

## 要做的

### 1. route 拼接

- 识别日志中每一段子任务的 route 块（Gaussian 用两条虚线包住的 `#` 开头的多行文本），把各行去掉行首单个空格后**直接首尾相连、不加空格**，再做关键词识别。这样被截断的词能还原；原本在词与词之间换行的情况，Gaussian 会在行尾或下一行开头保留空格，不受影响（用测试覆盖两种情况）。
- 第一段和 Link1 之后的各段（`Proceeding to internal job step number N`）都用同样方法。
- 拼接后的 route 写入 `job_sections[*].route`（如已有该字段则修正其内容），便于审阅。

### 2. 顶层终止判定

- 顶层 `termination = normal` 的条件：识别出的子任务数 ≥ 1；每个子任务都有对应的 `Normal termination`；`Normal termination` 总次数等于子任务数；全日志没有 `Error termination`。
- 任何子任务无法识别类型时，仍写 `parser_warning`，但**只要上述终止证据完整**，顶层就判 `normal`；子任务类型未知只影响依赖该类型的字段（例如频率字段），不影响终止判定。
- 次数不一致、缺少结束标记、出现 `Error termination` 时，顶层仍为 `incomplete` 或 `error`（沿用现有取值），不得放宽。
- 新增可选字段 `parser`: `{ "ag_version": "...", "rules": "route-join-v1" }`，标明这份 facts 由哪版规则生成。

### 3. 检查使用方

- 列出所有直接读取顶层 `termination` 的代码（thermo、profile、topology、irc-review、irc-compare、asm、snapshot 等），确认修复后行为符合预期；如有使用方需要改动，停下列出，不在本单内顺手改。

### 4. 重新解析命令

```
ag facts <Attempt> --reparse [--dry-run --out <study 外的 .json>]
```

- 只读本地已取回的 `outputs/` 日志，不连接集群。
- `--dry-run`：把新 facts 写到 `--out`（必须在 study 外、文件不存在），同时输出与当前 facts 的**逐字段差异**（JSON），不改 study 内任何文件。
- 正式执行（无 `--dry-run`）：
  1. 新 facts 先写到临时文件并完整校验；
  2. 当前 `facts.json` 以独占创建方式复制到 `facts-history/<UTC 时间戳>-<旧 SHA-256 前 12 位>.json`（目标已存在就报错，不覆盖），复制后核对哈希一致；
  3. 再用原子替换写入新的 `facts.json`；
  4. 输出旧、新 SHA-256、逐字段差异，以及 **study 内引用旧 SHA-256 的文件清单**（只在 study 的文本文件 .md / .json / .csv 中搜索完整的 64 位哈希，只读，不修改这些文件）。
- 符号链接、越界、日志缺失、facts 读取失败 → 报错，不写任何文件。
- 前置条件：Attempt 状态为 fetched；其他状态拒绝。

### 5. 流程说明（技能）

- SKILL.md 补充：发现 facts 解析错误时，先 `--dry-run` 给人看差异；人同意后正式执行；在 study.md 进度日志记录“哪些 Attempt、为什么重新解析、旧 / 新哈希前 12 位”；命令列出的引用旧哈希的已签内容，由负责人重新确认，不自动继承旧签字。

## 不允许

- 不覆盖、不删除旧 facts；不修改日志；不修改引用旧哈希的文件。
- 不放宽“真正未完成”的判定：截断日志、缺结束标记、Error termination 必须继续被拒。
- 不改 `freq_step_converged` 等收敛字段的判定；不自动重算任何东西。
- 测试只用合成日志（可按真实格式改写，不得包含 HSS 的分子、坐标或 route 以外的研究内容）。

## 测试

- route 在关键词中间换行（`Fre`/`q`、`Fr`/`eq`、`Op`/`t`）、在词间换行、三行以上 route、Link1 后的第二段和第三段 → 子任务类型正确，无警告，顶层 `normal`。
- 截断日志（只有第一段 Normal termination）、无任何结束标记、含 Error termination、结束次数多于或少于子任务数 → 顶层不是 `normal`。
- 子任务类型无法识别但终止证据完整 → 顶层 `normal`，保留警告。
- `--reparse --dry-run`：study 内所有文件字节和 mtime 不变；差异只含预期字段。
- 正式 `--reparse`：旧 facts 归档且哈希一致；归档文件已存在时拒绝且不写任何文件；引用旧哈希的文件被正确列出；中途失败不留下半成品（facts.json 仍为旧版本）。
- thermo 前置检查：同一合成 Opt+Freq，修复前拒绝、修复后通过（仅终止条件部分）。
- 开发中只跑相关测试；推送前本地跑一次全量 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，之后以 CI 为准。敏感扫描与 `git diff --cached --check`。

## 真实环境验证

- 纯本地。合并前由 HSS 主会话对 10-17 核对过的 5 个 Attempt 只读运行 `ag facts <Attempt> --reparse --dry-run --out <study 外>`，汇报每份的差异；预期只有顶层 `termination`、`parser_warning`、子任务类型和新增的 `parser` 字段变化，**能量、频率、收敛字段不变**。结果只发监督方，不进 PR 和公开仓库。
- 正式重新解析在合并后由负责人决定是否执行，不作为合并条件。

## 停止条件

- route 块在某些日志中无法确定起止（给出合成复现后停下）。
- 使用顶层 `termination` 的代码需要在本单外改动。
- dry-run 显示能量、频率或收敛字段也发生变化（说明影响超出预期，停下汇报）。

## 合并前审阅与交付

- 需要监督方审阅：是（改动解析规则和 facts 写入）。
- PR 描述第一行：`Task: T99`；列出被调整期望值的旧测试及理由。
- 合并只由负责人操作。

## v2：监督方 10-17 批准的范围扩展

保留上面的原始任务记录。此修订额外允许修改 `ag/src/ag/thermo.py`、
`ag/src/ag/_profile_sources.py` 及对应测试，解决修复终止判定后暴露的段来源混用。

- 热校正、频率及对应方法、基组、溶剂、色散绑定实际 Freq 来源段；电子能另记来源段。
- 同一 Attempt 的 Opt/Freq 方法、基组、溶剂、色散或基函数类型不同，逐项列出并拒绝。
  T82 的 SCF 方法范围、程序版本、配对几何、完整模式和频率收敛等规则全部保留。
  不推断 `SCRF=Check` 的溶剂，不自动等同 R/U 前缀；证据不明即拒绝。
- GoodVibes 只读取 Freq 段的科学数据；不改 qRRHO 公式、截断、温度、浓度处理。
- 合成回归覆盖相同口径绑定 Freq、不同口径拒绝、单段 Freq 数值不变，以及尾随 SP 隔离。
- 原定五份本地 dry-run 后，由研究主会话在 study 外的临时副本放入预览 facts，
  运行同一套 thermo 前置检查，逐份核对终止、频率收敛和 Freq 来源口径。
  私有验收名单及预期结果沿用监督方通知；结果只交监督方，不进公开 PR。
  无法确认 Freq 段口径时记录实际拒绝原因，不以预期替代测试结果。
- PR 描述明确写明“这是监督方 10-17 批准的范围扩展”。
