# T42b：修复作业段解析的两个缺陷（route 误判、优化完成措辞）

## 分支与目标

- 分支：`codex/t42b-section-parser-fixes`；基于最新 main（含 #256），一张任务单一个 PR。**优先级最高。**
- 目标：修复 T42 合并后，在 L2、L3 真实日志只读诊断中发现的两个缺陷，并查明另外两类既有值变化的原因。修复后，对 L1–L3 全部 29 个 Gaussian Attempt 重新做只读扫描，结果应当是：除了任务单里逐项说明、并经负责人认可的变化之外，全部为“只有新增字段，既有值未变”。
- 资料：
  - `ag/src/ag/_parse_outputs.py`：`gaussian_job_sections` 的 route 判定（`route = bool(re.match(r'\s*#', line))`，以及 `boundary` 里的 `route and seen_route`）；`_parse_gaussian_section` 中的 `opt_converged`（只认精确的 `'Optimization completed.'`）；`parse_gaussian` 中 `energies.scf` 取自最后一个正常结束段的规则。
  - 诊断结果（负责人提供，已脱敏）：
    - L2 的两个 SCNet Opt Freq（006、007）：第 1 段的完成标记是 `Optimization completed on the basis of negligible forces.`，新解析给出 `opt_converged = null`，旧值为 `true`。
    - L3 的 017–024（IRC）：`# OF POINTS ALONG THE PATH = …`、`# OF STEPS = …` 被当作 route，分别切成 5–89 段，并出现 `Unexpected job section`。
    - L3 的 015、016（IRC）：没有分段警告，但 `energies.scf` 的值变了。
    - L3 的 027（端点 Opt）：`final_geometry_orientation` 的值变了。
- 防的事故：已经发生（离线复现，没有改写任何证据）：T42 把这两个缺陷带进了 `ag facts`。不修复的话，研究 A 的 Opt+Freq 会被误报为“优化未完成”，IRC 的 facts 会被错切，T43 也会因为分段警告拒绝处理这些日志。

## 允许改动的路径

- `ag/src/ag/_parse_outputs.py`。
- `ag/tests/test_gaussian_sections.py`、`ag/tests/fixtures/` 下的合成或脱敏样例（只做最小片段，不提交真实日志）。
- `docs/LESSONS.md`：补充 T42 那一条，写明这两个缺陷及以后的写法。
- `docs/redesign-tasks/T42b-section-parser-fixes.md`：本任务单。

## 要做的

1. **route 判定：** 只有真正的 route 回显才算 route。route 在 Gaussian 输出里的形态是：前一个非空行是一整行短横线（`-----`），接着是一行或多行以 `#` 开头（或续行），然后又是一整行短横线。不满足这个形态的 `#` 行（如 `# OF POINTS…`、`# OF STEPS…`）一律不算 route，也不作为分段边界。现有提取 route 文本的正则也按同一规则对齐。
2. **优化完成措辞：** `opt_converged` 改为识别 `Optimization completed` 开头的所有措辞（包括 `Optimization completed on the basis of negligible forces.`），只在行首匹配，避免误认引用文字；`Optimization stopped` 同理。只看所属优化段，不扩大搜索范围。
3. **查明 L3-015/016 的 `energies.scf` 变化：** 在 PR 里写清旧值来源、新值、原因。如果原因是“单段作业不是正常结束，因此取不到最后正常段的 SCF”，按下面的规则处理：**只有一个作业段时，`energies.scf` 沿用该段自己的最后一个 SCF 能量**（与 T42 之前一致），并且 `fact_sources` 记录这一段；`termination` 已经单独记录了异常，不用靠清空能量来表达。多段作业仍然保持“取最后一个正常结束段”的规则。
4. **查明 L3-027 的 `final_geometry_orientation` 变化：** 在 PR 里写清旧值、新值和原因。属于缺陷就修；属于有意的改进就写明理由，留给负责人决定。
5. **只读复扫（在 PR 里写结果）：** 开发机上无法访问真实日志。合并前，负责人另开计算机上的验证会话，用这个分支在内存中解析 29 个 Attempt（不写文件、不加 `--refresh`），在 PR 评论里报告：每个 Attempt 的分类、`parser_warning`，以及仍属于“既有值变化”的项目和原因。

## 不允许

- 不放宽 normal 的判定（全部段都正常结束，且每段最后一个非空行是终止行）。
- 不改 facts 的比较与拒绝写入规则，不对任何 Attempt 运行 `--refresh`。
- 不提交真实日志、主机、路径、作业号；样例只截取必要的几行，并脱敏。
- 不修改上述范围外文件。

## 测试

- route：在合成 IRC 片段里放入 `# OF POINTS ALONG THE PATH`、`# OF STEPS`，不得产生新段；真正的 route 块（短横线夹住的一行或多行）仍正确识别。
- 优化完成：`Optimization completed on the basis of negligible forces.` 判为 true；`Optimization completed.` 判为 true；只出现在引用文字或缩进内容中时不判定。
- 单段非正常结束的作业：`energies.scf` 取自该段，`termination` 不为 normal。
- T42 的全部既有测试和 baseline 通过。
- 后端：`PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`；记录通过数和跳过原因。
- 暂存精确文件后运行敏感扫描与 `git diff --cached --check`。

## 真实环境验证

- 需要，即“要做的”第 5 项：只读、在内存中解析、不写文件，由负责人在计算机上另开会话执行。**这一项完成并经监督方确认后才合并。**

## 停止条件

- 修复后仍有无法解释的既有值变化：停下报告，不靠调整测试使其通过。
- 要改范围外文件；同一问题修两次仍未解决。

## 合并前审阅与交付

- 需要监督方审阅：是（解析行为，影响 facts 与已签字证据的核对）。
- 修改 AGENTS.md：无。
- PR 描述第一行：`Task: T42b`；写两个缺陷的根因、修复方式、两类变化的原因，以及只读复扫结果。
- 用 `gh pr view <编号> --comments` 读取评论，逐条处理并回复；冲突本地 rebase；合并只由人操作。
- T43（mode-review）依赖分段结果，T42b 合并后 T43 再 rebase。

## 版本记录

- T116 脱敏：研究标识、编号与环境字面量改为泛称；原工单结构和结论不变。
