# T154：入口默认档位与新任务资源解析

版本：v1，2026-10-28。目标仓库：Auto-Gaussian。本单是开发工单；写单不等于启动开发、部署或计算。

## 分支与目标

- 分支：`codex/t154-entry-default-tier`；一张任务单、一个分支、一个 PR，PR 第一行 `Task: T154`。
- 核查基线：`e24a5bd1d9045e3b783d8ef25f02e430ad4dc3c5`；实际开发从包含前置任务的最新 main 建独立 worktree，不切换或改写在用检出。开工再次核对任务编号及上游提交。
- 前置与并行：可立即开发；与 T156/T159/T161 可在独立 worktree 并行。与 T156 的 cli.py 改动分别限 prepare 参数和新命令注册；建议 T154 先合并，后续 rebase。T158 等本单接口合并。
- 开工先读现行 AGENTS.md、本单、README、后端 docs/DEVELOPING.md 与 docs/LESSONS.md。旧任务单只用于实现追溯。
- 目标：已选择入口后，省略档位可使用该入口明确配置的默认值；避免复制任务继续沿用旧资源、或把一个入口的默认值扩散到其他入口。
- 依据：`ag/src/ag/cli.py` 当前 prepare 的 tier 必填；`attempt.prepare` 在资源校验前调用节点绑定；`clusters.describe` 目前不发布默认档位。
- 设计决定：采用可选入口配置 `resources.default_tier`，不把具体入口名称写死在代码中。跨入口 `ag route` 继续显式指定档位，由 T155 处理 walltime。

## 允许改动的路径

- `ag/src/ag/config.py`：可选默认档位校验与解析；`ag/src/ag/attempt.py`：新 prepare 在正确位置解析最终 tier。
- `ag/src/ag/cli.py`：prepare 参数及提示；`ag/src/ag/clusters.py`：白名单发布默认档位。
- `ag/tests/test_default_tier.py`（新建）：默认/显式/缺省/坏配置；`ag/tests/test_clusters.py`、`ag/tests/test_core.py`：受影响现有断言。
- `ag/config.clusters.example.toml`、`README.md`、`docs/DEVELOPING.md`：泛化配置与行为说明；`docs/LESSONS.md`：仅本单经验。
- `docs/redesign-tasks/T154-entry-default-tier.md`：本单随实现 PR 纳入；`docs/redesign-tasks/open-tasks.txt`：只处理本单条目，不覆盖其他任务。

## 要做的

1. `resources.default_tier` 可省略；提供时必须是当前入口已配置且合法的档位。空字符串、未知值、未配置档位或不合法资源拒绝，不能静默回退。
2. prepare 有显式 tier 时保持显式选择；省略时仅查已选入口的默认值。无默认值继续明确要求选择，不自行取 simple 或跨入口借值。必须在节点档位映射、资源检查、编号/目录分配之前完成解析。
3. 新 manifest 保存实际 tier/cores/mem，后续验证与提交按保存的绑定工作；默认配置后来改变不能改变旧 Attempt。无需为此回填旧 manifest 或增加新状态。
4. `ag clusters --json` 的每个入口 `resources` 可选增加 `default_tier`，与配置同名；未配置时不输出该键。T158 复用此字段，不在前端硬编码入口名。
5. 所有当前受支持且入口允许的程序使用同一解析规则，不扩展程序支持。Gaussian 缺失资源按现有规则补齐；显式完整输入不擅自覆盖。前端新草稿资源重写属于 T158。
6. 合成验收入口包含 mini 8/16、simple 12/24、general 24/48、complex 32/72、max 48/96（核/GB），默认 max；单作业/总承诺/排队限额使用合成合法配置。该表是验收参数，不得改真实配置。Gaussian 保留现有内部余量，不能把调度器96GB直接写成Gaussian占满96GB。
7. 旧配置、旧 manifest、显式 tier 的渲染和哈希路径保留；配置迁移在代码与前端复核后另行执行。

## 不允许

- 不改范围外文件、AGENTS.md、冻结目录、版本号或 CHANGELOG；需要扩大范围时说明具体阻塞。
- 不改已有 Attempt、源文件、manifest、bundle、输入哈希、提交绑定、研究台账或科学签字。
- 不改提交授权、一次性声明、UNKNOWN 只读、确切作业绑定和共享账号额度；不自动换节点、重提、取消或迁移。
- 不做磁盘目录/配额改造、RSS/峰值监测、监控性能专项、跨机锁、PBS_NODEFILE 原文归档或已移出范围的事项。
- 不提交实际连接信息、用户名、主机、绝对路径、私有交接或研究数据；公开夹具只用合成数据。

## 测试

- 有默认/无默认、显式不同合法档位、坏默认及默认超限；每种允许模板至少覆盖资源解析。
- 省略 tier 与显式同 tier 的实际资源/脚本相同；输入未改、旧 manifest 不补字段、改变默认不影响旧绑定。
- 节点定向入口的映射校验仍发生在最终 tier 上；错误在创建编号或目录之前发生。
- clusters 不泄漏配置私有字段；旧消费者忽略新增可选键。

开发时运行相关回归；推送前一次 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，记录跳过原因，之后以 CI 为准。
仅暂存本单文件，运行 `git diff --cached --check`；按本仓现行敏感扫描说明检查暂存内容、提交身份和 PR，词表缺失或检查未覆盖须如实报告。

## 真实环境验证

本单不需要 SSH 或测试计算。使用隔离合成配置与小分子输入走本地 prepare、摘要和哈希核验，不调用真实 Transport、不改生产配置。程序专有的既有只读探测在测试中用注入替身。PR 明确只证明本地准备行为；不宣称提交、调度或科学验收。

## 停止条件

- 范围越界；新约束说不清防哪个具体事故；同一问题修两次仍未解决。
- 真实环境出现 UNKNOWN、哈希不一致、SSH 错误、输出异常或作业异常结束，立即停止报告，不改写命令绕过拒绝。
- 本单要求的证据不足时记录待补事项，不用离线结果冒充现场验证，不自行扩大执行权限。

## 合并前审阅与交付

- 监督方审阅必须绑定当前完整 head；读取 `<!-- ag-review head=... -->` 评论并逐项回应。
- PR 写清行为前后差异、兼容处理、相关与全量测试、实际验证版本及范围、未观察项和实际阻塞类别。
- 处理共享文件冲突时只保留本单增量，不复制一份解析或判断规则；rebase 后复核受影响行为。
- 合并由负责人完成。发布、生产配置迁移及服务操作另行安排；本单不授权这些动作。
