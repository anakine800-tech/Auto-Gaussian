# T42：Gaussian 日志按作业段解析

## 分支与目标

- 分支：`codex/t42-gaussian-job-segments`；基于最新 main，一张任务单一个 PR。
- 目标：Gaussian 日志按作业段解析，每项事实只取自它所属的段，并保留来源位置。只有全部段都正常结束，`termination` 才是 normal；最后一段没有结束时，判为 incomplete。
- 资料：
  - `ag/src/ag/_parse_outputs.py:24–35`：`termination()` 只要全文任何位置出现完成标记，就判为 normal；
  - `_parse_outputs.py` 中 opt、freq 相关事实的提取（含 `freq_step_converged`，约第 143 行）；
  - 旧版知识来源（只读参考，不 import，提交说明注明来源）：`archive/tests/v3/result/test_gaussian_job.py` 第 219、234、370、828 行附近的用例（复合作业的内部步骤、Link1 与结束边界、尾部空行），以及同目录对应的 v3 解析实现。
- 防的事故：一条 route 写 `Opt Freq` 时，Gaussian 会在同一份日志里先后运行优化段和频率段。频率段被 walltime 杀掉或中途出错时，日志中仍留有优化段的 `Normal termination`，现在的解析会判为 normal，并可能沿用前一段的收敛与频率证据。开发方已用脱敏水日志末尾追加一段未完成作业，离线复现：`termination`、`opt_converged`、`freq_step_converged`、`vibrational_modes_complete` 全部为真。

## 允许改动的路径

- `ag/src/ag/_parse_outputs.py`：分段与按段取值。
- `ag/src/ag/facts.py`：只在需要写出新增字段时修改。
- `ag/tests/` 中解析相关测试，以及由仓库内已脱敏的小分子日志（水、正丁烷）改写的合成样例。
- `docs/LESSONS.md`：新增一条经验。
- `docs/redesign-tasks/T42-gaussian-job-segments.md`：本任务单。

## 要做的

1. **分段：** 以 Gaussian 每个作业的开始标记（如 `Entering Gaussian System`、`Initial command:`，按实际输出核实）切分作业段。每段记录起止行号，以及它以哪种方式结束：normal、error 或未结束。
2. **termination：**
   - 任一段 error，整体为 error；
   - 所有段都以 normal 结束，整体才是 normal；
   - 最后一段没有结束，整体为 incomplete。
   - error_hint 取自出错的那一段。
3. **按段取值：**
   - 优化相关事实（`opt_converged`、最终几何）只取自含优化的段；
   - 频率相关事实（频率、虚频、`freq_step_converged`、`vibrational_modes_complete`、热化学量）只取自频率段，而且只有频率段本身正常结束时才给值，否则写 null 并说明原因；
   - 单点能取自最后一个正常结束的段，并注明来源段。
4. **新增字段：**
   - `job_sections`：每段的序号、起止行号、route、结束方式；
   - 主要事实旁的来源段序号。
   - 现有字段名不变。
5. **意外的段：** 段数多于 route 应有的段数，或出现无法识别的尾段时，写入 `parser_warning`，`termination` 判为 incomplete，不默默忽略。
6. **兼容：** 对单段、完整正常结束的日志，所有既有字段的值保持不变。用仓库现有脱敏样例做回归。

## 不允许

- 不改 xTB、CREST 的解析；不改 thermo、profile 的计算。
- 不放宽 `gaussian_input.py` 对 Link1 的禁止。
- 不提交真实日志、chk、研究数据；合成样例只由仓库已有的脱敏小分子日志拼接或截断得到。
- 不修改上述范围外文件；不连接集群。

## 测试

- 完整的 `Opt Freq` 两段日志：normal，各项事实与现状一致。
- 频率段在中途截断：incomplete；频率相关事实为 null，`opt_converged` 仍来自优化段。
- 频率段 error：error，error_hint 来自频率段。
- 完整日志末尾追加一段未完成的新作业（复现开发方的样例）：incomplete，并有 parser_warning。
- 内部步骤与尾部空行（参照旧版第 219、234、370、828 行附近的用例思路重新编写）：边界判断正确。
- 单段单点、单段 Opt 的回归：既有字段不变。
- 后端：`PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`；记录通过数和跳过原因。
- 暂存精确文件后运行敏感扫描与 `git diff --cached --check`，人工核对 PR 文本和 Git 身份。

## 真实环境验证

- 合并后，由负责人在计算机上对 L1、L2、L3 和 V-T22 已取回的 Gaussian Attempt 逐个运行 `ag facts <id>`。现有机制下，解析内容相同就不写文件；内容不同会拒绝写入并列出差异。这样可以只读地确认已签字的证据是否受影响。不用 `--refresh`，不提交作业。
- PR 评论里只记录：受影响的 Attempt 数，以及差异的字段名。如有受影响的已签字证据，停下来，交给负责人决定。

## 停止条件

- 修复会改变单段、正常结束日志的任何既有字段：停下说明。
- 真实日志中的段开始标记与预期不同，无法可靠切分：停下，报告实际形态（脱敏后）。
- 要改范围外文件；同一问题修两次仍未解决。

## 合并前审阅与交付

- 需要监督方审阅：是（解析行为变化，影响 facts）。
- 修改 AGENTS.md：无。
- PR 描述第一行：`Task: T42`；写分段规则、新增字段、测试结果，以及参考的旧版文件。
- 用 `gh pr view <编号> --comments` 读取评论，逐条处理并回复；冲突本地 rebase；合并只由人操作。
- 必须在 HSS 第一批 Opt+Freq 的 facts 之前合并；它与 T36a 没有文件重叠，可以同时进行。


## 实现说明

- `job_sections` 使用从 1 开始、两端均包含的 `start_line` / `end_line`；段末尾空行不纳入来源。`index` 也是从 1 开始。
- 同次启动的 `Entering Gaussian System` 和 `Initial command:` 合为一段；正常 Opt+Freq 的第二段识别 `(Enter …/l1.exe)` 后的 `Link1: Proceeding…2`，也支持不带 `Link1:` 前缀的同一标记。普通计算过程中 Enter/Leave Link 不分段。
- 目前认可的多段组合是 Opt+Freq 的内部第二步 Freq；额外启动、显式 Link1、异常步骤序号或未知非空尾段产生警告，不能判 normal。任一段 error 优先于 incomplete。
- `fact_sources` 将事实键（热化学量使用 `energies.g` 等点分名称）映射到来源段序号；null 表示无法归属。频率收敛表的行号仍为整份原日志的绝对行号。
- `frequency_unavailable_reason` 解释频率段未正常结束或未知尾段导致的 null。几何导出与来源段一致；未知尾段不能回借旧几何。仍在等待 route 的内部第二步可保留已识别的优化几何。
- 单段正常日志及现有完整水 Opt+Freq 的全部既有字段和几何与开发前基线逐项比较。新增来源字段会使旧 facts 比较出现差异，即使数值未变；仍须按现有机制人工核对，不自动 refresh。
- 旧版只参考 `archive/tests/v3/result/test_gaussian_job.py` 和 `archive/auto_g16/result/gaussian_job.py` 的边界案例与识别思路；没有 import 或改动旧代码。

## 本次离线验证

- `PYTHONPATH=ag/src .venv/bin/python -m pytest ag/tests skills-next -q -rs`：1683 passed、2 skipped；跳过项为 Linux 远端 stat/ps 方言测试（交 Linux CI）及未启用的私有日志测试。
- 单段 SP/Opt 样例进一步限定为相应阶段后，重跑 `ag/tests/test_gaussian_sections.py`：35 passed；解析器实现没有再改动。
- 暂存文件敏感扫描与 `git diff --cached --check` 通过；author/committer 均已核对为 noreply。
- 当前阻塞：等待监督方审阅与负责人合并。未连接集群，未运行真实研究 facts；合并后的旧证据核对由负责人按上节另行执行。
