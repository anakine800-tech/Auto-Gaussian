# T52：`ag fetch` 成功后自动运行 `ag facts`，失败只记录

## 分支与目标

- 分支：`codex/t52-fetch-auto-facts`；基于最新 main（含 T51、T53），一张任务单一个 PR。
- **目标：** 负责人 10-15 决定：取回成功后自动解析，前端马上就能看到能量、构象和收敛过程，不用再手动运行 `ag facts`。facts 失败**只记录**，不影响取回结果，不回滚，也不改状态。
- **为什么：** 研究 A 接下来会有一批单点、相应阶段 试点和 TS 作业。现在每个 Attempt 取回后都要再手动跑一次 `ag facts`，容易漏；漏了，前端、`ag ensemble`、`ag review` 读到的就是缺失或过期的 facts。
- **要防的事故：** 自动运行**绝不能覆盖已有的 facts.json**，否则可能悄悄改掉已签证据。`build_facts(refresh=False)` 在新旧内容不同时会拒绝写入，必须保持这个行为。
- 资料：`ag/src/ag/fetch.py`（`fetch`、`_incomplete`、`_add_missing`）、`ag/src/ag/facts.py`（`build_facts`，第 208 行）、`ag/src/ag/cli.py`（第 77–79 行 fetch 分支和参数注册）。

## 允许改动的路径

- `ag/src/ag/fetch.py`：新增 `auto_facts(path)`，供 CLI 调用。
- `ag/src/ag/cli.py`：只改 fetch 分支和 fetch 子命令的参数（新增 `--no-facts`）。
- `ag/tests/test_fetch.py`、`ag/tests/test_incomplete_fetch.py`：只为新增的返回字段调整断言。
- 新增 `ag/tests/test_fetch_facts.py`。
- `ag/README.md`：fetch 一节加一段说明。
- `docs/redesign-tasks/T52-fetch-auto-facts.md`：本任务单。

**不改 `facts.py`、`_parse_outputs.py`、`status.py`、`remote.py`、`transport.py`。不改任何卡片**（研究 A 正在使用）。

## 要做的

1. **触发时机：**
   - 普通 `ag fetch` 成功（状态变为 fetched）后：运行。
   - `ag fetch --incomplete` 成功后：运行（facts 会记为 incomplete，接续流程本来就要用它导出 `final_input.xyz`）。
   - `ag fetch --add-missing`：**不运行**（补取不改写既有记录）。
   - `ag fetch` 本身失败或被拒绝：不运行。
   - 加 `--no-facts`：不运行。
2. **调用方式：** 在本地调用 `build_facts(path, refresh=False)`；不连 SSH，不传任何会覆盖的选项。
3. **结果写进 fetch 的 JSON 输出**，新增字段 `facts`：
   - `{"status": "written"}`：原来没有 facts.json，新写入；
   - `{"status": "unchanged"}`：已有 facts.json，解析结果相同（`build_facts` 判定一致）；
   - `{"status": "conflict", "reason": "<build_facts 的差异摘要，首行，≤ 300 字>"}`：已有 facts.json 但内容不同，**未覆盖**；提示人工核对后用 `ag facts --refresh`；
   - `{"status": "failed", "reason": "<异常类别和首行信息，≤ 300 字>"}`：解析出错；
   - `{"status": "skipped", "reason": "no-facts" | "dependency-unavailable" | "add-missing"}`。
   - reason 里不能出现本机绝对路径；出现时用相对 study 的路径替换（复用现有的脱敏方式，没有就截掉路径部分）。
4. **记录：** 在 study 的 journal 里追加一条 `facts`（`auto`）记录，内容与上面的 `facts` 字段相同。不改 `status.json`。
5. **退出码：** 取回成功时，不管 facts 结果如何，退出码都保持 0；facts 是 `conflict` 或 `failed` 时，在 stderr 打印一行中文提示。
6. **保持不变：** 取回本身的全部校验、哈希、状态写入、不完整取回的证据检查、`add-missing` 的语义；facts 的 `--refresh` 只能由人手动运行。
7. **前端兼容：** 前端操作模式会调用 `ag fetch` 并读取它的输出。请只读检查前端仓库 `autog_frontend/actions.py` 等处，确认多出一个字段不会导致报错；如果会报错，在 PR 里说明，**不改前端**。

## 不允许

- 不覆盖已有的 facts.json；不传 `refresh=True`；不新增“自动刷新”的选项。
- 不让 facts 的失败影响取回结果、状态或退出码。
- 不改范围外的文件；开发时不连集群。

## 测试

- 普通取回：无 facts.json → `written`；已有相同 facts → `unchanged`；已有不同 facts → `conflict`，并断言原文件字节不变。
- 解析抛出 ValueError、OSError → `failed`，取回结果与状态不变，退出码 0。
- 缺少化学依赖（模拟 ImportError）→ `skipped` / `dependency-unavailable`。
- `--incomplete` 成功后运行；`--add-missing` 不运行；`--no-facts` 不运行；取回失败时不运行。
- journal 里有对应的记录；reason 里没有绝对路径。
- 三种模板（gaussian、crest、xtb）各一个合成用例。
- `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`；敏感扫描与 `git diff --cached --check`。

## 真实环境验证

- 合并后由研究 A 下一次真实取回顺带验证：负责人在计算机上同步 main，研究 A 会话取回时在回报里写明 `facts.status`，并确认 facts.json 已生成。不另起验证 study。

## 停止条件

- 需要修改 `facts.py` 才能区分 written、unchanged、conflict（先在 PR 里说明，可以考虑先读已有字节再调用的方式）。
- 前端在多出 `facts` 字段时会报错。
- 发现有已签的 facts.json 因自动运行被改写的任何可能。

## 合并前审阅与交付

- 需要监督方审阅：是（fetch 流程、证据保护）。
- 修改 AGENTS.md：无。
- PR 描述第一行：`Task: T52`；写明前端兼容检查的结果。
- 合并只由负责人操作。

## 版本记录

- T116 脱敏：研究标识、编号与环境字面量改为泛称；原工单结构和结论不变。
