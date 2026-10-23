# T62：小修合集（status 权限误报、L123 原因识别、facts 冲突异常、文献缓存日期、清单标记、SMD 引用）

## 分支与目标

- 分支：`codex/t62-small-fixes`；基于最新 main，一张任务单一个 PR。开发机做。
- **目标：** 一次清掉审阅中积压的六个小问题。每项独立，在 PR 里逐项说明。**涉及 `status.py`、`remote.py` 的第 1 项属于硬内核范围，必须审阅。**

## 允许改动的路径（按项列出）

1. `ag/src/ag/remote.py`（只改 `output_observation`、`incomplete_output_observation`、`receipt` 三个命令里“文件不存在”的判断）、`ag/src/ag/status.py`（只改对应的解析）、`ag/tests/test_core.py` 或 `ag/tests/test_fetch.py` 中相关用例，新增 `ag/tests/test_observation_permissions.py`。
2. `ag/src/ag/_parse_outputs.py`（只改 `error_hint` 的识别规则）、`ag/tests/test_facts.py` 或现有 error_hint 测试文件。
3. `ag/src/ag/facts.py`（新增异常类）、`ag/src/ag/fetch.py`（`auto_facts` 改用这个异常类型判断）、`ag/tests/test_fetch_facts.py`。
4. `skills-next/auto-g16-literature/scripts/literature_records.py`、`skills-next/tests/test_literature_records.py`。
5. `ag/src/ag/_review_manifest.py`、`ag/tests/test_review_manifest.py`。
6. `skills-next/auto-g16-recipes/cards/sp.md`：**只改文件末尾 S8 一节里的那一条 SMD 输出格式引用**，其他行不动。
- `docs/LESSONS.md`（如有新经验）；`docs/redesign-tasks/T62-small-fixes.md`：本任务单。

## 要做的

1. **status 把权限错误报成 absent：** 现在远程用 `test ! -e` 判断缺失，没有读权限、上级目录不可进入时也会报成 absent。改为区分三种情况：存在、确实不存在、无法判断（权限或其他错误）。无法判断时输出单独的标记（例如 `unreadable`），本地解析成“无法判断”：**不改变 Attempt 状态、不当作缺失**，在 status 输出和 journal 里提示人工核对。命令仍然只用固定文本和已有的 `quote`，不引入新的 shell 结构以外的东西；在 PR 里贴出改前改后的完整命令文本。
2. **IRC `L123` 原因识别：** 在 `error_hint` 中识别 `Maximum number of corrector steps exceeded`（IRC 校正失败），给出明确的提示（参见 `skills-next/auto-g16-study/references/gaussian-errors.md` 里 l123 那一行）；不只看 Link 号。补合成 log 片段的测试。
3. **facts 冲突的异常类型：** `facts.py` 新增 `FactsConflictError(ValueError)`，在“内容不同、拒绝写入”时抛出（报错文本不变）；`fetch.auto_facts` 改为按类型判断 conflict，不再匹配文本。现有调用 `except ValueError` 的地方行为不变。
4. **文献脚本离线缓存的核实日期：** 离线命中缓存时，核实日期记缓存里的查询日期，方法注明“缓存”；缓存没有日期就标 `unverified`，不写当天日期。
5. **清单的 `resolved_from` 标记：** Markdown 中以 `analyses/` 开头的引用，直接按 study 根目录解析，不再先按源目录找、也不加 `resolved_from` 标记；其他相对引用的回退规则（T49b）不变。用 L1、L2 复扫：文件数和哈希不变，`resolved_from` 只剩真正回退的那些。
6. **SMD 引用：** 把 sp.md S8 中引用的催化论文 SI（DOI 10.1039/C4CY01031K）换成 Gaussian 官方关于 SCRF/SMD 输出的说明页（链接需核实可访问）；如果找不到合适的官方页面，就删掉这条引用并在 PR 里说明，不另找二手来源。

## 不允许

- 第 1 项不改变“存在”“不存在”两种情况的现有判断结果；不自动重试、不改状态机。
- 第 6 项不动 sp.md 的其他行。
- 不改范围外的文件；开发时不连集群。

## 测试

- 第 1 项：用假的远程输出覆盖存在、不存在、无法判断三种情况，以及 status 在“无法判断”时不改状态；命令文本的快照测试。
- 第 2–5 项：各自的合成用例；第 3 项确认 T52 的冲突用例仍然通过。
- `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`；敏感扫描与 `git diff --cached --check`。

## 真实环境验证

- 第 1 项合并后，由研究 A 下一次 `ag status` 顺带验证：输出没有变化即可（正常情况下不会出现“无法判断”）。不单独构造权限错误。

## 停止条件

- 第 1 项需要改动 `path_checks`、提交或取消的命令。
- 第 3 项需要改变 facts 的写入逻辑。
- 任何一项需要改范围外的文件。

## 合并前审阅与交付

- 需要监督方审阅：是（第 1 项涉及 remote/status）。
- PR 描述第一行：`Task: T62`；六项逐条说明改动和测试。
- 合并只由负责人操作。


## 审阅补充 v2（2026-10-16，针对 c6ea5eb）

- 三处 ENOENT case 统一只匹配 `*'No such file or directory'` 后缀；补完整命令测试，覆盖文件名带引号/不带引号的缺失诊断，以及 `Permission denied` 不得判为 absent；同步命令快照。
- 合并后在两套集群各核验一次研究 A 运行中作业的 `ag status`：退出回执尚不存在时，状态应正常推进，不应报 unreadable。具体作业身份由运行会话核对；开发会话不连接集群，也不单独构造权限错误。

## 版本记录

- T116 脱敏：研究标识、编号与环境字面量改为泛称；原工单结构和结论不变。
