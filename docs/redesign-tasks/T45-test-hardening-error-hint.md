# T45：测试加固（错配证据案例）与 error_hint 按原因识别

## 分支与目标

- 分支：`codex/t45-test-hardening-error-hint`；基于最新 main，一张任务单一个 PR。
- 目标：
  1. **修复 `error_hint` 的粗映射。** 现在 `termination()` 只看出错的 link 编号：L9999 一律报“优化步数用完”。RCFC 验证中，A1′ 因“负曲率数为 0”在第 1 步就停止，同样从 l9999 退出，也被误报成“步数用完”。改为按日志里实际的错误原因判断。
  2. **补“故意拼错证据”的测试。** 参照 V3.1 的思路，用新版接口补几类反例，确认 ag 会拒绝或明确报告，而不是静默接受。
- 资料：
  - `ag/src/ag/_parse_outputs.py:24–36`：`termination()`，link 到提示的映射 `{'9999': 'L9999: 优化步数用完', '502': 'L502: SCF 不收敛'}`；
  - RCFC 验证报告（负责人提供）：A1′ facts 的 `termination=error` 正确，`error_hint` 误报；
  - 旧版知识来源（只读参考，不 import，提交说明注明来源）：`archive/tests/v3/` 下 result、conformer 相关测试中的错配用例思路；
  - 现有防护：`thermo._pairing_evidence`（SP 与 Freq 几何配对）、`dedup`/`cluster`、`profile` 的 `selectivity` 重复检查、`review check` 的 facts 新鲜度检查、T42 的作业段来源。
- 防的事故：
  - `error_hint` 误导诊断。“步数用完”会让 LLM 提出增加 MaxCycles，而真正的原因是 TS 曲率不对，应该换初猜或重算 Hessian。
  - 证据拼错时被静默接受。例如单点能配到了另一个构象的频率，系综里同一个构象被算了两次，或者 facts 更新之后旧的审阅仍被当作有效。

## 允许改动的路径

- `ag/src/ag/_parse_outputs.py`：只改 `termination()` 中的 `error_hint` 判定。
- `ag/tests/` 下新增 `test_evidence_mismatch.py`，以及 `test_facts.py`、`test_gaussian_sections.py` 中与 error_hint 相关的测试；合成或脱敏的小片段 fixture。
- `skills-next/auto-g16-recipes/cards/failure-diagnosis.md`：只在报错提示对照处补一句新的提示文字（如果卡片引用了这些提示）。
- `docs/redesign-tasks/T45-test-hardening-error-hint.md`：本任务单。

## 要做的

1. **error_hint 按原因识别：** 先找具体的错误信息，找不到再退回到 link 编号：
   - `Number of steps exceeded` 或 `Optimization stopped` 并伴有步数上限的说明 → “优化步数用完”；
   - `Wrong number of Negative eigenvalues`（附带 Desired/Actual）→ “TS 曲率不符：负本征值数与期望不符”；
   - `Convergence failure` / `SCF has not converged` → “SCF 不收敛”；
   - 其他 l9999 → “L9999：优化未完成（原因见日志）”，不再默认说成步数用完；
   - 其他 link → 保持现有的 “L<编号>”；walltime 的判断不变。

   提示里附上命中那一行的行号（在所属作业段内换算成全局行号）。
2. **错配证据测试（只加测试；如果发现现有代码会静默接受，停下报告，不在本任务里修）：**
   - **SP 与 Freq 配错构象：** `thermo` 的 SP 配对用了另一个构象的单点 → 拒绝；
   - **同一构象重复：** 同一个 Attempt 在 thermo 的系综里出现两次 → 拒绝或报告；`profile` 物种的 attempts 里重复 → 拒绝；
   - **跨作业借用事实：** 两段日志里，第二段的频率被截断时，不能借用第一段或别的作业的频率（T42 已覆盖的，引用现有测试即可，不重复）；
   - **证据更新后旧审阅失效：** facts 用 `--refresh` 更新后，`review check` 必须报“review 可能过期”；
   - **签字清单与文件不符：** `review manifest` 生成后，被引用的文件被改动，再次生成的清单哈希会不同（证明清单能反映改动）。
3. 每个测试写清楚它防的是哪一种错配（一行注释）。

## 不允许

- 不改 `termination` 字段的判定，只改 `error_hint`。
- 发现现有代码会静默接受错配时，不在本任务里顺手修，停下报告，另开任务单。
- 不使用研究数据或真实日志；不连接集群；不修改上述范围外文件。

## 测试

- error_hint：每类错误各一个合成片段（步数用完、负本征值数不符、SCF 不收敛、未知的 l9999、walltime），提示文字与行号都正确。
- 错配测试：全部按预期拒绝或报告。
- 后端：`PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`；记录通过数和跳过原因。
- 暂存精确文件后运行敏感扫描与 `git diff --cached --check`。

## 真实环境验证

- 合并后，在计算机上对 RCFC 验证中的 A1′ 只读运行 `ag facts`（不加 `--refresh`），确认差异摘要里只有 `error_hint` 变化，且新提示是“TS 曲率不符”。结果写在 PR 评论里。

## 停止条件

- 某个错配测试显示现有代码会静默接受：停下报告具体的用例和位置。
- 要改范围外文件；同一问题修两次仍未解决。

## 合并前审阅与交付

- 需要监督方审阅：是（解析行为变化，影响 facts）。
- 修改 AGENTS.md：无。
- PR 描述第一行：`Task: T45`；列出每个错配测试防的事故，以及 error_hint 的新映射表。
- 用 `gh pr view <编号> --comments` 读取评论，逐条处理并回复；冲突本地 rebase；合并只由人操作。
- 注意：`error_hint` 的值变化会让已有 Attempt 的 `ag facts` 出现“既有值变化”。合并前，要用和 T42b 相同的方式，对 29 个 Attempt 做一次只读复扫：除 `error_hint` 外不应有其他变化，`error_hint` 的变化要逐项列出。


## 执行记录（2026-10-15）

- 基线：最新 `origin/main`，`7f12708`（T42b，#261）；隔离分支与独立 `.venv`。
- 负责人批准最小范围扩展：除 `termination()` 内的 error_hint 判定外，允许在同一个 `_parse_outputs.py` 的 error_hint 调用处传递作业段行号偏移；不扩大到其他文件的生产逻辑。`termination` 与其他 facts 字段保持不变，单段按原始行序编号，多段换算全局行号；补多段测试，PR 描述记录本批准，合并前 29 个 Attempt 复扫仅允许 error_hint 变化。
- 新测试全部使用合成 HOOH 文本、坐标与数值；不读取研究数据、不访问集群。旧版仅参考错配测试思路：`archive/tests/v3/result/test_service.py::test_gaussian_parser_rejects_artifact_identity_mismatch` 与 `archive/tests/v31/conformer/test_thermochemistry_readonly.py::test_self_consistent_association_and_numeric_shape_splices_reject`，不复制框架或 import 旧模块。
- 跨作业借用频率引用 T42 既有 `test_frequency_truncated_never_uses_partial_results`、`test_extra_frequency_job_does_not_reuse_completed_frequency`，不重复新增。
- 提示采用所属段最后一个明确原因；仅 `Optimization stopped` 不说明步数耗尽。具体原因行与兜底 link 行附 `（line N）`；scheduler 的 `walltime` 关键词、判断及既有优先级保持原样，不冒充 Gaussian 日志行号。仅有 L502 而无 SCF 原因时按其他 link 兜底为 `L502`。
- 合并前仍需负责人按 T42b 方式另开验证会话，在内存中只读复扫 29 个 Attempt，逐项列出 error_hint 变化，确认其他字段不变；本开发任务不读取真实日志，不做 refresh。合并后 A1′ 的只读核查另行记录。
- 离线验证：`PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`（使用隔离 `.venv`）得到 **1877 passed, 2 skipped**；跳过 `test_completion.py:309` 的 Linux stat/ps 方言检查（交 Linux CI）及 `test_facts.py:132` 的显式 opt-in 私有日志。新错配用例 6 passed，无静默接受。
- 另用基线 `7f12708` 原解析器，对 50 个纯合成正常/错误/多段/截断/带 scheduler 文本的情形进行内存对比：48 个 error_hint 预期变化，其他 facts 字段与几何全部不变；这不代替真实 29 个 Attempt 复扫。
- 精确暂存六个允许范围内的文件后，敏感扫描与 `git diff --cached --check` 通过；作者/提交者均为 GitHub noreply。
