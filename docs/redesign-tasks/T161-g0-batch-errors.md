# T161：G0 批量诊断保留成功项与频率歧义错误

## 分支与目标

- 仓库：Auto-Gaussian；分支：`codex/t161-g0-batch-errors`；PR 首行 `Task: T161`。
- 规划基线：`e24a5bd1d9045e3b783d8ef25f02e430ad4dc3c5`；从最新 main 开独立 worktree，先读 AGENTS.md、本单、DEVELOPING.md、LESSONS.md。
- 目标：`ag g0 --all` / `--channel` 中一个候选的 Gaussian 频率段无法唯一确定时，仍输出其他候选已完成的诊断，单列失败对象与原因；不猜频率段，不把错误记成 clean。
- 防的事故：当前 `diagnose` 的列表推导中任一 `frequency_section` 歧义异常会丢掉整批报告；宽泛捕获 ValueError 又可能掩盖候选哈希损坏或 catalog 错误。
- 并行：可与资源线和 CREST 线独立开发；T162 必须在本单合并后接入 `g0.py` / `g0_modes.py`，本单不提前实现原子映射。

## 允许改动的路径

- `ag/src/ag/g0.py`、`ag/src/ag/g0_modes.py`：批次迭代、局部错误分类/来源、文本和 JSON 输出、退出码及 record 保护。
- `ag/src/ag/mode_review.py`：仅为明确区分频率段歧义所需的最小异常类型/上下文，不改变频率段选择规则。
- `ag/tests/test_g0.py`、`ag/tests/test_g0_modes.py`；`ag/tests/fixtures/g0-batch-errors/`（新建）：合成歧义及混合批次。
- `docs/g0.md`、`README.md`、`docs/LESSONS.md`：局部失败、退出码和写入边界。
- `docs/redesign-tasks/T161-g0-batch-errors.md`、`docs/redesign-tasks/open-tasks.txt`。

## 要做的

1. 仅把“候选所属频率来源无法唯一分段/选定”的已分类错误作为本单可恢复局部失败。分类应来自解析入口，不在最外层靠任意异常文本判断；不得 `except Exception` 后继续所有候选。
2. 保留 `ag-g0/1` 中已成功候选的完整原结构与原排序规则；新增可选顶层 `errors` 列表和失败计数。错误项包含 candidate、object、关联 Attempt（可取得时）、阶段、稳定类别和可读原因；有安全读取的日志字节时保留相对文件名与 SHA-256，无有效段时不伪造 section/行范围。
3. `order` 只含成功生成诊断的候选；错误项单独展示，不参与 clean/flagged/rejected 科学诊断排序。总选中数必须能与成功数、失败数对账，不丢项也不重复。
4. 文本和 JSON 都保留成功结果与失败列表，并明确“批次未完整完成”。任何局部失败退出码为 **2**；无局部失败但有 rejected 保持 **1**；没有 rejected/局部失败保持 **0**。候选 flagged 本身不变成错误。
5. 为避免把不完整批次默认为已完整登记，**批次出现局部错误时 `--record` 不写任何候选结果事件**，仍输出本次成功诊断及错误，并明确“未登记；可单独对成功候选执行诊断/记录”。不新增“强制部分记录”开关、不改 catalog 事件格式。全成功批次沿用原子批量登记、journal 哈希前置核对、`--dry-run` 和升级授权语义。
6. 单候选命令维持原来的失败行为和明确原因。无 Freq 且 auto 模式允许缺失仍是“无模式数据”，不能与歧义合并。原有异常结束/坏向量的拒绝保持，除非本次查到它属于同一个被明确分类的分段歧义；不得顺手扩大错误容忍范围。
7. 候选存档哈希不符、catalog/journal 不一致、非法路径/符号链接、参考身份损坏、配置/窗口文件错误仍停止整个操作且不登记。错误记录不代替原完整性保护。
8. 只读诊断不新建报告文件、不刷新 facts，不创建 Transport；用户显式 `--record` 才可进入既有登记流程。来源缺失不能补造科学结论。

## 不允许

- 不改 `catalog.py` / `catalog_v2.py` 事件语义，不改 prepare/submit/fetch/状态机。
- 不修改频率段选择算法，不自动选第一段/最后一段来消除歧义，不改波函数、方法、原子映射或模式算法。
- 不把已有研究 study 当测试对象，不自动升级 catalog、重算 facts 或改旧证据；不新增远程操作。
- 不改冻结目录、版本号、CHANGELOG、AGENTS.md 或范围外文件。

## 测试

- 三个候选中间一个歧义：其余完整诊断仍输出；成功顺序保持、errors 有唯一候选和来源、退出码2。
- 全失败、首项/末项失败、空集合、单候选失败；失败计数与选择集合一致。
- `--all` / `--channel`、文本/JSON、带/不带反应坐标；无模式数据仍与歧义不同。
- `--record` + 局部错误无任何新事件/文件；`--dry-run` 同样不写；全成功批次的登记及 journal 变更保护不退化。
- 候选哈希、catalog 损坏、坏路径、坏窗口、异常终止和坏向量仍按原要求失败；不可被宽泛捕获变成可忽略条目。
- 原 clean/flagged/rejected、模式排序和单候选结果兼容。
- 开发仅跑相关用例；推送前一次 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，记录跳过原因，随后依 CI 和新变动复测。
- 暂存精确文件后按现行流程做有效私有词表扫描、`git diff --cached --check`、Git 身份和 PR 文本核查。

## 真实环境验证

- 不需要远程查询或真实计算；本单为纯本地诊断与已有可选登记入口的受限处理。用临时合成 study 验证完整 CLI 和文件不变性。
- 不在真实 study 上重跑诊断、登记或 facts；离线报告不等于 TS 验收。

## 停止条件

- 需要修改 catalog 格式/写入机制、范围外文件，或不能把可恢复歧义与证据损坏分开。
- 新抽象无法说明具体事故；同一问题两次仍未解决；任何意外真实环境动作立即停止。

## 合并前审阅与交付

- 监督方审阅必需，重点审查捕获范围、错误来源、退出码和不完整批次零写入。不修改 AGENTS.md。
- 交付实际 HEAD、合成完整/部分/全失败输出、记录前后字节核对和测试结果；T162 基于本单最终接口继续。
- 用 `gh pr view <编号> --comments` 逐条处理绑定 HEAD 审阅；本地 rebase；由负责人合并，不发布或部署。

## 实现记录

- 解析入口新增 `FrequencySectionAmbiguity`；G0 只恢复携带安全日志来源的 `FrequencySourceAmbiguity`，不按错误文本恢复。
- 局部失败报告新增 `errors`、`incomplete_notice`、`counts.errors` 和 `counts.selected`；成功批次报告及候选排序保持兼容。
- 局部失败退出码 2，优先于 rejected；`--record`、`--dry-run`、升级选项都不进入候选结果写入流程。
- 合成 CLI 证据：完整批次为 3 个成功项、退出码 0；中间歧义为 2 个成功项和 1 个错误、退出码 2；全部歧义为 0 个成功项和 3 个错误、退出码 2。
- 上述诊断及部分失败的 record/dry-run 前后，文件字节、mtime、目录和文件模式均不变；配置读取及 Transport 创建被测试夹具禁止。
- 相关回归：`test_g0.py`、`test_g0_modes.py`、`test_mode_review.py` 共 274 passed。
- 推送前全量：`PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，5999 passed、19 skipped；18 项依赖 Linux 的 GNU stat/procfs 或远程命令格式，1 项私有本地日志为显式 opt-in。
- 无需真实环境验证；未访问真实 study 或远程计算环境。
