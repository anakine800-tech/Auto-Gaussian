# T36a：卡片错字与流程验收示例标注

## 分支与目标

- 分支：`codex/t36a-card-cleanup`；基于最新 main，一张任务单一个 PR。
- 目标：修正 ts 卡片的错字；把正丁烷流程验收专用的参数和档位改为显式标注的示例，避免 LLM 把个例当成通则。读者打开 thermo、crest-screen 卡片时，能一眼区分“通用规则”和“L1 正丁烷验收示例”。
- 资料：2026-10-14 卡片审阅意见 U3；`skills-next/auto-g16-recipes/cards/ts.md:184`、`thermo.md:61`、`crest-screen.md:17`、`crest-screen.md:136`。
- 若新增检查或抽象：不新增。

## 允许改动的路径

- `skills-next/auto-g16-recipes/cards/ts.md`：只改第 184 行错字。
- `skills-next/auto-g16-recipes/cards/thermo.md`：只改第 61 行。
- `skills-next/auto-g16-recipes/cards/crest-screen.md`：只改第 17、136 行。
- `docs/redesign-tasks/T36a-card-cleanup.md`：本任务单。

## 要做的

1. `ts.md:184`：“確認”改为“确认”。
2. `thermo.md:61`：把正丁烷的报告要求改写为通用规则（报告构象与分组定义，再给 ΔG 和布居；只计算有限集合时写明是集合内归一化结果），正丁烷 anti/gauche 的写法改为括号中标注的“示例（L1 正丁烷流程验收）”。
3. `crest-screen.md:17`：窗口与首选方法的通用说明保留；`--gfn2 --chrg 0 --uhf 0 --ewin 6 --quick` 这组参数改为标注“示例（L1 正丁烷气相流程验收）”，并说明正式研究的电荷、uhf、溶剂和是否用 quick 按体系填写。
4. `crest-screen.md:136`：档位与 walltime 建议改为标注的示例，保留“按既有耗时调整档位”的通用要求。
5. `thermo.md:17` 与 `crest-screen.md:33` 的 `--mirror` 通用规则**不改**（正丁烷只是举例）。
6. 卡片行数与“常见坑”条数不增加。

## 不允许

- 不修改上述范围外文件、冻结目录或已有 Attempt；不改方法表、不改判据含义。
- 不自动重提、不绕过 Mac 确认、不连接集群。
- 不提交真实主机、用户名、作业号、绝对路径、凭据、研究数据、日志或 chk。
- 不顺带做卡片拆分或去重（属后续第二批）。

## 测试

- `grep -n '確' skills-next/auto-g16-recipes/cards/ts.md` 无结果。
- 后端：`PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`；记录通过数和跳过原因，卡片一致性与格式测试必须通过。
- 暂存精确文件后运行 `python ag/tools/scan_sensitive.py --staged` 与 `git diff --cached --check`，人工核对 PR 文本和 Git 身份。

## 真实环境验证

- 不需要。

## 停止条件

- 要改范围外文件。
- 发现所列行号与 main 不符：按内容定位，PR 中说明实际行号；内容找不到时停下询问。

## 合并前审阅与交付

- 需要监督方审阅：是（卡片修改）。
- 修改 AGENTS.md：无。
- PR 描述第一行：`Task: T36a`；写改动、测试结果；实际阻塞写“无”。
- 用 `gh pr view <编号> --comments` 读取 `<!-- ag-review head=... -->` 评论，逐条处理并回复；冲突本地 rebase；合并只由人操作。
- 本任务应在 T37、T39 之前合并（它们也改 crest-screen、thermo），合并后它们各自 rebase。
