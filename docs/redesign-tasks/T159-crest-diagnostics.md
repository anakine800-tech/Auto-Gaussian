# T159：CREST 错误输出取回与本地诊断

## 分支与目标

- 仓库：Auto-Gaussian；分支：`codex/t159-crest-diagnostics`；一个任务、一个 PR，PR 首行 `Task: T159`。
- 规划基线：`e24a5bd1d9045e3b783d8ef25f02e430ad4dc3c5`。开发从最新 main 开独立 worktree；先读 AGENTS.md、本单、DEVELOPING.md、LESSONS.md。
- 目标：CREST 异常时从本地已有、经正式取回的程序输出和调度器错误输出给出有来源的摘要，供 T160 展示；完整文本保留在本地输出文件。
- 并行：可与资源线、T161 分别开发。若修改 `attempt.py`，T154 先合并，本单再 rebase；不得覆盖 T154 默认资源变化。与 T156 共有 `remote.py` 时，本单仅改输出集合、T156仅改节点采样；建议 T156 先合并，本单随后 rebase 检查两块均保留。T160 可先做合成展示，最终按本单合并接口验收。
- 现状：PBS 模板把 CREST stdout 写入 `crest.out`，stderr 随调度器合并到 `job.pbs.out`；Slurm 固定为 `job.slurm.out` / `job.slurm.err`。CREST 输出声明目前缺 PBS 合并输出；Slurm 的 `.err` 已由 `remote.output_names` 加入，但 CREST 解析没有完整利用它。
- 真实风险：异常原因遗漏；直接扩展动态输出列表会使旧不完整取回回执的 `outputs ∪ missing` 与当前列表不相等；日志被替换后展示错误出处。

## 允许改动的路径

- `ag/src/ag/_parse_outputs.py`、`ag/src/ag/facts.py`：CREST 普通和 mdopt 的诊断提取、调用及可选事实字段。
- `ag/src/ag/crest_diagnostics.py`（可新建）：仅 CREST 本地诊断和有界摘要，不建设通用日志框架。
- `ag/templates/crest.toml`、`ag/src/ag/remote.py`：仅 CREST 输出集合选择及相应固定文件名，不修改其他远程命令。
- `ag/src/ag/attempt.py`：仅在确有必要时为新 CREST manifest 增加识别输出集合的可选标识；旧 manifest 不补写。
- `ag/src/ag/fetch.py`：仅 CREST 输出集合兼容及诊断调用所必需的适配；不得放松哈希、状态或独占写入条件。
- `ag/tests/test_crest_diagnostics.py`（新建）；`ag/tests/test_mdopt.py`（协调方依本批自主规划授权补充的直接配套回归路径，仅更新新增输出列表和失败保留诊断 facts 的相关断言）；`ag/tests/test_facts.py`、`ag/tests/test_fetch.py`、`ag/tests/test_incomplete_fetch.py`、`ag/tests/test_fetch_facts.py`、`ag/tests/test_facts_preservation.py`、`ag/tests/test_core.py`：本单相关回归。
- `ag/tests/fixtures/crest-diagnostics/`（新建）：合成或脱敏小分子夹具。
- `docs/ag-facts-1.md`、`README.md`、`docs/LESSONS.md`：新增字段、来源和兼容说明；`skills-next/auto-g16-recipes/cards/failure-diagnosis.md`、`skills-next/auto-g16-recipes/cards/crest-screen.md`：只补本功能使用说明。
- `docs/redesign-tasks/T159-crest-diagnostics.md`、`docs/redesign-tasks/open-tasks.txt`。 后者补充范围为“协调方按本批自主规划授权补充的已完成清单同步”：仅移除已合并的 T156（#354）、T166（#360），不改其他任务；本单不以等待合并或现场覆盖限制保留为未完成功能条目。

## 要做的

1. 先核对 `render.py`、`crest.pbs` 和实际模板声明，记录 PBS/Slurm 文件对应关系。程序模板脚本字节、本次计算参数与调度器行为保持原样，不为了收集 stderr 改写旧 bundle。
2. 给新 CREST Attempt 声明所需错误输出，覆盖普通 CREST 和 mdopt。新增完整输出取回仍经既有大小、SHA-256 和独占发布核验；零字节 stderr 合法。
3. **兼容性必须先于扩表。** `remote.output_names` 同时影响 status、普通 fetch、补取和旧不完整取回核验。不得无条件把新文件加入所有历史 Attempt。采用仅新 CREST manifest 的可选输出版本标识或等价最小实现；无标识时保持旧集合。不得改旧 manifest、历史回执、状态、哈希或输入字节来通过校验。
4. 已有本地错误输出可被诊断；旧 Attempt 没有该文件时显示“错误输出未取回／来源缺失”，不能据此改变已有 termination。不开设自动补取、自动 facts refresh 或新的历史迁移。普通 fetch、`--add-missing`、`--incomplete` 的既有入口限制和缺失确认语义保持。
5. 先识别明确的程序／调度器错误证据，再形成摘要。明确报错、警告、正常信息和无法判断分开；单个关键词、非空 stderr 或退出码本身不能证明根因。不要让旧 CREST 正常终止标记覆盖明确调度器强杀证据，也不要把一般 warning 改成 error。
6. 为 `ag-facts/1` 增加可选 `crest_diagnostics`（本单新字段）。T159/T160 共同使用的最小语义：`summary` 为简短中文摘要；`status` 为 `identified` / `unresolved` / `none` / `unavailable`；`sources` 为来源列表，每项包含 outputs 内白名单文件名、该文件 SHA-256、1 基行范围；明确命中的规则只说明“发现此错误证据”，不声称已经证明科学根因。`identified` 不代表程序成功。没有可定位文本时不伪造行号。
7. 完整 stderr 不复制进 facts、PR 或网页初始响应。需要展示的上下文通过来源定位有界读取；摘要与片段截断须可识别。公开测试固定小上限并覆盖长行/大日志；开发者可选与现有读取器相容的上限并写入字段文档，不新增全局日志制度。
8. 普通 CREST 与 mdopt 都要在构象文件缺失或失败时留下可供 T160 读取的诊断，不把摘要依赖于完整构象解析成功。可在本单允许的 CREST 错误路径产出明确标注“解析未完成”的诊断 facts，几何、能量和构象数仅保留已能独立核实的值，否则为空；termination 仍按真实日志证据，不从解析异常臆造程序终止原因。诊断中另列解析错误；不得静默转成正常成功。哈希、来源绑定等完整性失败仍硬拒绝，不能用诊断 facts 绕过。已有 facts 仍不覆盖。
9. 本地解析不创建 Transport，不启动任何计算，不触发远端读取。已有 facts 若新解析内容不同，沿用 FactsConflictError 和明确人工 refresh 流程。

## 不允许

- 不新增自动重试、重提、取消或计算方法修改；不修改 Gaussian/xTB 的事实语义。
- 不放宽不完整取回的结束证据、确切作业绑定、缺失确认或哈希检查；不得把 SSH/权限错误归为文件不存在。
- 不改 `status.py` 的状态机、不改变模板执行脚本，不扩展任意文件读取。
- 不修改生产配置、服务、旧 Attempt 或研究数据；本单不提交测试计算。
- 不改冻结目录、版本号、CHANGELOG 或范围外文件；公开材料不含真实连接信息、研究标识和原始私有日志。

## 测试

- 合成 PBS 合并 stderr、Slurm `.err`、空 stderr、无错误文件、明确异常、普通 warning、正常标记与调度器终止冲突、多个不一致证据、超长文本、行号和 SHA 绑定。
- 普通 CREST/mdopt 的缺构象、失败标志、能量/构象不一致路径仍失败且可见原因；不改已正常解析的几何/能量。
- 新旧 manifest 的输出集合分别核对；旧普通 fetched、旧 `fetch-incomplete-*`、新普通 fetch 和新不完整取回均覆盖；旧回执与文件哈希保持不变。源文件变动、符号链接、下载不一致仍拒绝。
- 已有 facts 不变或明确冲突，不自动 refresh；非 CREST 模板和旧 PBS bundle 字节回归。
- 开发只跑受影响测试；推送前一次 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，之后按 CI 和增量变动复测。
- 暂存本单精确路径后运行现行敏感扫描（包含有效本机私有词表）、`git diff --cached --check`，检查 PR 文本及 noreply Git 身份。

## 真实环境验证

- 本单触及输出取回，**合并前**需有非研究对象的正式取回兼容证据，不能只写“合并后观察”。本批不提交测试计算。
- 使用负责人已明确允许读取的、已经结束的非研究 CREST Attempt；核对执行提交、绑定身份、其现存 PBS/Slurm 输出及新旧输出集合。通过受审阅 ag 操作，只读远端、在隔离本地验证目录保存独占结果；正式研究目录和生产服务不变。
- 已有来源能覆盖 PBS 与 Slurm 时分别验证；缺其中一种就记录缺口，不把合成样本称为现场验证。禁止为补证据提交新计算或临时拼接远程命令。
- 尚无合适对象、正式入口或授权时，开发和合成测试可完成，PR 标“待补真实取回证据”，不得宣称全部验收通过。任何意外按停止条件处理。

## 停止条件

- 需要改范围外文件；新抽象说不清防的事故；同一问题修两次仍未解决。
- 无法在不改旧记录的前提下保持输出集合兼容；需要新增任意远程命令或改状态机。
- 真实环境出现 SSH 错误、UNKNOWN、哈希不一致或作业异常：停止并报告，不自动重试写操作。

## 合并前审阅与交付

- 监督方审阅必需；提交 T159 实际 HEAD、字段样例、新旧集合对照、测试与真实证据边界。不修改 AGENTS.md。
- T160 按本单最终接口开发；本单合并后向负责人提供字段和夹具摘要供转发，不自行发跨会话消息。
- 用 `gh pr view <编号> --comments` 处理绑定 HEAD 的审阅意见；冲突本地 rebase。合并、发布和部署由负责人决定。
