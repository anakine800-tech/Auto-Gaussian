# T141：允许仅配置 Gaussian 的集群入口（条件触发的后端兼容修复）

版本：v1（监督方，2026-10-26）。**开发机 Codex 做。** 本文件可以进入公开仓库，但**只在私有部署检查确认目标集群确实缺少 xTB/CREST，而 v4.6.0 无法直接验收时才启动本代码单**。它不代表部署完成；真实连接与机器配置由仓库外私用部署指令管理。

## 1. 分支与目标

- 任务编号：`T141`（开工前确认未被占用）。
- 分支：`codex/t141-gaussian-only-cluster`；PR 描述第一行：`Task: T141`。
- 开工条件：先读 `AGENTS.md`、`docs/DEVELOPING.md`、`docs/LESSONS.md`；`origin/main` 基线核对为 `f7a27af01a66a195a42b3c4752369a7d18254975`（v4.6.0），如 main 已前移，先停下报告新的完整提交号及冲突；工作区干净且无其他进行中的同区域修改。不得通过修改发布检出直接上线。
- 目标：当入口**明确** `allowed_templates = ["gaussian"]`（或仅包含已经确认不依赖 xTB 的 Gaussian 家族模板）时，可以不填写不存在的 `programs.xtb.root`；Gaussian 的配置、`doctor`、渲染、路由、静态入口列表正常工作。缺少相关程序的入口不能准备 xTB/CREST Attempt。
- 本单不接入任何具体服务器、不读取私有 SSH、不修改本机配置、不提交任务。

### 负责人决定

- R1：优先复用现有软件安装。只有真实环境查不到可用且合规的 xTB/CREST，才做本修复；不得用虚构路径或 `doctor` 跳过错误来冒充验收。
- R2：不声明新的默认程序能力；**省略 `allowed_templates` 时保持旧版“所有受审阅模板可用”的行为与必要程序检查**。
- R3：已配置完整 Gaussian+xTB+CREST 的旧入口在配置解析、输入字节、`doctor`、监控和提交上保持兼容。
- R4：新增能力必须有显式拒绝规则，防止意外在没有可执行文件的入口上准备计算；不放宽提交审批、作业唯一性、远程根目录、哈希或安全约束。
- R5：新功能合并后再由负责人决定补丁版发布及两机部署，不能将未发布的开发分支部署到研究机。

## 2. 已核实的代码依据（v4.6.0）

- `ag/src/ag/config.py` `validate_cluster()` 中固定要求 `programs.xtb.root`，并无条件调用 `crest_executable()`；省略 xTB 会触发缺项。
- `ag/src/ag/doctor.py` `doctor()` 无条件检查 `gaussian`、`xtb`、`crest` 三个可执行程序。
- `ag/src/ag/render.py` 在渲染任意模板前就组装 xTB 变量，Gaussian-only 也会解引用缺少的 xTB 配置。
- `ag/src/ag/route.py` 已有基于 `allowed_templates` 和程序存在性的筛选逻辑；保持原有只读建议语义。
- `ag/src/ag/clusters.py` 已以 `programs.get('xtb', {})` 表达程序启用状态，优先复用现有行为。
- `README.md` 当前规定：Gaussian 单节点执行；PBS 档位内存不超过 120 GB；不能把集群物理核总数直接当成单作业上限。

## 3. 允许改动的路径

- `ag/src/ag/config.py`
- `ag/src/ag/doctor.py`
- `ag/src/ag/render.py`
- 因上述修改确有必要、且能够指出防止的具体事故时，才允许修改 `ag/src/ag/route.py` 或 `ag/src/ag/clusters.py`（先在 PR 描述说明）。
- `ag/tests/test_clusters.py`、`ag/tests/test_mixed_clusters.py`、`ag/tests/test_route.py`、`ag/tests/test_cluster.py` 及新建 `ag/tests/test_gaussian_only.py`。
- `README.md` 中的程序配置说明、`ag/config.clusters.example.toml` 中的**通用占位符**范例。
- `docs/redesign-tasks/T141-gaussian-only-backend.md`、`docs/redesign-tasks/open-tasks.txt`（以仓库现有格式登记；不得引入任何私有实值）。

不得修改其他路径，包括前端、旧架构、研究数据、研究 Skills、`AGENTS.md`、任何真实本机文件或远程服务器。

## 4. 实现要求

1. 配置边界：只允许**显式白名单且其中没有 xTB/CREST 依赖模板**的入口省略整个 `[clusters.<ENTRY>.programs.xtb]`。未指定白名单时仍按原有完整依赖规则校验；白名单包含 xTB 或 CREST 而依赖缺失时明确报错。独立 CREST 路径的其他兼容组合不在本单范围内，不得暗中开启。
2. 只对实际存在的程序字段进行路径规范化；`programs.gaussian.g16root` 必须是真实的 `g16` 直接所在目录，保持严格绝对路径检查。不允许把缺失路径变成空串、`.`、占位目录或假可执行程序。
3. `doctor` 检查本入口**实际启用且已配置**的程序。仅有 Gaussian 时要求它可执行，并准确返回已核验程序集合；完整旧配置下不得减少原来的检查。`ag clusters --json` 必须准确标注可用与不可用程序。
4. `render` 只为所选模板引用确实需要的程序变量；Gaussian-only 渲染不得解引用 xTB。对于完整旧配置，渲染出的每一个字节必须与 v4.6.0 一致，避免影响已确认的输入和脚本哈希。
5. `ag prepare` 必须在创建任何 Attempt 前拒绝不在 `allowed_templates` 中的 xTB、CREST 或其他模板。`ag route` 对该入口只建议有权限且软件可用的程序族。
6. 对缺失依赖报清晰、脱敏的错误；不得包含机器私有信息。遵守现有 `AGENTS.md` 的提交、取消、哈希和不可覆盖规则。
7. 修改公共说明和范例时全部用占位符；若实现需改其他路径，先停下请求负责人扩大范围。

## 5. 测试表

| 场景 | 预期 |
|---|---|
| 显式仅 Gaussian，完整 g16 配置，无 xTB 表 | `load_config`、`ag clusters --json`、`doctor` 和 Gaussian 渲染正常 |
| 仅 Gaussian，远程 g16 不存在 | `doctor` 失败，不能伪装为软件可用 |
| 未写 `allowed_templates`，也没有 xTB | 保持旧版校验拒绝 |
| 白名单允许 CREST/xTB，但依赖缺失 | 配置/prepare 在副作用前拒绝 |
| 仅 Gaussian 白名单下准备 xTB 或 CREST | 在创建 Attempt 前拒绝 |
| 原有完整配置（PBS/Slurm、旧 default） | 配置、doctor 程序检查与渲染字节保持旧版行为 |
| 有独立 CREST 路径的旧配置 | 不产生回归 |
| `ag route`、`ag clusters --json` | 程序可用性标志与建议不虚报 |
| 配置或远程程序检查失败 | 不启动作业、不变更研究数据、错误脱敏 |

交付前执行仓库认可的全量测试（以本次检出的 README/DEVELOPING.md 命令为准，通常为 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q`）；另外执行带本机有效私有词表的 `scripts/scan_public.py`（0 命中）、`git diff --cached --check` 和新增测试。私有词表缺失不能当作扫描通过。

## 6. 真实环境验证与停止条件

- 此 PR 内仅在开发机通过 mock/fake transport 和合成配置验证，不运行真实计算、不访问真实研究 study。可在本机使用**完全脱敏**的合成例子运行静态命令。
- 不把真实环境探测信息、地址、账户、IP、SSH 别名、队列/分区名称、节点清单、总核数、目录、转发工具名称、研究对象和原始日志写入公开 PR/issue/测试夹具。
- 任何意外、权限拒绝、SSH 报错、测试回归或拟修改允许路径之外的代码：立即停止，保留报告，不重试也不绕过。
- 不合并、不直接推 main、不打 tag、不部署研究机；这些都由负责人依据独立私用部署单批准。

## 7. PR 与交付

- PR 描述第一行 `Task: T141`；列出基线完整提交号、改动文件、兼容保证、每项测试结果与风险（均脱敏）。
- 监督方逐行审阅配置校验、渲染与 doctor；逐段审阅说明和测试。Codex 按审阅意见修改并回报新完整提交号，合并由负责人操作。
- 合并后**尚不是部署完成**；如该功能实为必需，先另走补丁版发版/双机部署，再开始新服务器的私有入口接入。

## 8. 版本记录

- v1 / 2026-10-26：依据 v4.6.0 实码核查写成的条件性兼容修复工单。负责人已授权新集群配置及所需的正常开发工作；发布、提交作业和研究机维护窗口仍保留人工关口。
