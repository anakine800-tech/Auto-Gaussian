# T37：计算方案签字与方法依据显式填写

## 分支与目标

- 分支：`codex/t37-method-plan-signoff`；基于最新 main（T36a 合并后 rebase），一张任务单一个 PR。
- 目标：
  1. study.md 有一节“计算方案”，与机理假设一起签字（纯性质研究随结构里程碑签字），不新增里程碑。
  2. 方法依据分三类：文献先例、本课题既有方案、兜底方法；Skill、模板和确认摘要都按三类写。
  3. `ag prepare` 不再为 `--method-basis` 提供缺省值，三种模板（gaussian、xtb、crest）都必须显式填写；缺失或空白时拒绝。
  4. 卡片里所有完整的 `ag prepare` 命令示例都写 `--method-basis`，并由一致性测试守住。
- 资料：`ag/src/ag/cli.py:130`（当前缺省值“兜底方法”）、`ag/src/ag/attempt.py:104、164、297`、`ag/src/ag/submit.py:80`（同批须同一方法依据）；study-md-template 的“方法与依据”“参考态与动力学模型”“方法敏感性”；reaction-plan 第 20–34 行模板；卡片审阅 F2、U5。前端 `autog_frontend/actions.py` 已强制填写并传入，不受影响。
- 防的事故：
  - 示例省略参数时，有文献先例或沿用既有方案的作业被静默记成“兜底方法”，确认摘要和 manifest 中的依据失真（opt-freq:48、sp:71、crest-screen:20/41 的示例都会触发）。
  - 研究沿用课题组既有计算方案时，现有 Skill 只有“文献先例 / 兜底方法”两类，只能错误归类。
  - 方法、溶剂、温度、标准态在研究中途被改而没有人签字。

## 允许改动的路径

- `ag/src/ag/cli.py`：只改 prepare 的 `--method-basis` 参数定义。
- `ag/src/ag/attempt.py`：`prepare()` 去掉 `method_basis` 缺省值；保留现有非空校验与报错。
- `ag/tests/` 中覆盖 prepare 参数的测试文件（新增或修改，PR 中列明）。
- `skills-next/auto-g16-study/SKILL.md`：第 3、7 步，阶段决策表中“涉及机理”一行。
- `skills-next/auto-g16-study/references/study-md-template.md`：“方法与依据”扩展为“计算方案”，以及里程碑表的签字对象说明。
- `skills-next/auto-g16-study/references/confirmation-summary.md`：“方法与依据”一列的说明。
- `skills-next/auto-g16-study/references/acceptance-methods.md`：只改开头第一段，写明三类方法依据；方法、基组、窗口、热化学设置一字不改。
- `skills-next/auto-g16-recipes/cards/reaction-plan.md`：模板中“判别计算”改为引用计算方案，并加计算方案签字说明。
- `skills-next/auto-g16-recipes/cards/opt-freq.md`、`sp.md`、`crest-screen.md`、`ts.md`、`irc.md`：只改 prepare 示例行。
- `skills-next/tests/test_card_consistency.py`：新增检查。
- `README.md`：只改 prepare 相关说明行。
- `docs/redesign-tasks/T37-method-plan-signoff.md`：本任务单。

## 要做的

1. **计算方案一节**（study-md-template）：列出
   - 各阶段的方法与基组（引用 acceptance-methods 的组合名，或写明既有方案的完整 route），以及每项的方法依据类别；
   - 溶剂模型与溶剂、温度、标准态与浓度处理；
   - σ 约定与比较口径（只留位置，写“按 thermo/profile 卡片的规则填写”，具体规则由 T39 补）；
   - 方法敏感性方案；
   - 已知局限。

   签字说明：机理研究随机理假设一起签；纯性质研究随结构里程碑签；方案改变时重新签字，旧签字保留。里程碑表不新增行，只在“机理假设”“结构”两行的签字对象里写明包含计算方案。
2. **三类方法依据**（study SKILL 第 3 步、acceptance-methods 开头、confirmation-summary）：
   - 文献先例：DOI 加主文页码或 SI 位置；
   - 本课题既有方案：写明来源（哪项既有计算或 study），并声明“不是文献先例，精度未经验证”；
   - 兜底方法：使用方法表并声明。

   `--method-basis` 的文字按所属类别填写。
3. **study SKILL**：第 3 步写明计算方案签字前不准备依赖它的 Gaussian Attempt；第 7 步写明计算方案改变时重新签字。
4. **reaction-plan 模板**：“判别计算”一行只写判别量，方法一项改为“见计算方案”。
5. **prepare 示例**：所有完整的 `ag prepare --study ...` 命令（含 xtb、crest）都加 `--method-basis <...>`。占位文字按三类写，例如 `--method-basis <DOI 及位置 / 本课题既有方案及来源 / 兜底方法声明>`；xTB/CREST 示例写构象筛选的依据。
6. **ag**：`--method-basis` 改为必填（argparse `required=True`），无缺省值；空白字符串仍由现有校验拒绝；报错信息提示三类写法。已有 manifest 不迁移、不改写。
7. **一致性测试**：卡片和 study Skill 中所有以 `ag prepare --study` 开头的完整命令示例（围栏代码块和行内代码）必须包含 `--method-basis`；附一个缺参数的合成反例，证明检查能抓住。
8. 确认摘要的 manifest 字段名、`submit.py:80` 的同批一致性检查保持不变。

## 不允许

- 不修改上述范围外文件、冻结目录或已有 Attempt；不引入旧运行模块。
- 不改 acceptance-methods 的方法、基组、窗口、热化学设置和组合表。
- 不新增里程碑，不修改 AGENTS.md。
- 不修改 submit、remote、cancel、status、fetch。
- 不改 CHANGELOG；不兼容变化写进 PR 描述，留给 v4.1 发布任务汇总。
- 不自动重提、不绕过 Mac 确认、不连接集群；不提交真实主机、用户名、作业号、绝对路径、凭据或研究数据。

## 测试

- 新增：`ag prepare` 缺 `--method-basis`，或值为空白时，非零退出，且不创建 Attempt 目录；带参数时 manifest 的 `science.method_basis` 与输入一致；xtb、crest 模板同样适用。
- 新增：一致性检查能抓出缺参数的 prepare 示例（合成反例）。
- 后端：`PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`；记录通过数和跳过原因。
- 只用合成数据；暂存精确文件后运行敏感扫描与 `git diff --cached --check`，人工核对 PR 文本和 Git 身份。

## 真实环境验证

- 不需要。合并后计算机同步 main 时，研究 A 会话下一次 prepare 自然会用到新参数要求。

## 停止条件

- 发现前端以外的调用方（脚本、Skill 里的命令）依赖缺省值：列出并停下。
- 计算方案的签字安排必须改 AGENTS.md 才能成立：停下询问。
- 要改范围外文件；同一问题修两次仍未解决。

## 合并前审阅与交付

- 需要监督方审阅：是（Skills 与卡片修改，prepare 行为变化）。不涉及 remote、submit、cancel、status。
- acceptance-methods 开头一段的改动需负责人确认，在 PR 中写明确认记录；方法表本身不改。
- 修改 AGENTS.md：无。
- PR 描述第一行：`Task: T37`；写明不兼容变化（prepare 必须显式填写方法依据）和测试结果。
- 用 `gh pr view <编号> --comments` 读取评论，逐条处理并回复；冲突本地 rebase；合并只由人操作。
- 与 T38 共用 `cli.py`、`README.md`（不同行），后合并者 rebase。

## 版本记录

- T116 脱敏：研究标识、编号与环境字面量改为泛称；原工单结构和结论不变。
