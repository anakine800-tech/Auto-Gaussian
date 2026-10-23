# T117：提交路由建议——先交集群，集群没地方再交超算

版本：v1（监督方，2026-10-24）。**开发机做。** 后端出一个 PR，PR 描述第一行写 `Task: T117`。

## 分支与目标

- 分支：`codex/t117-route-suggestion`。
- **开工条件：** 以后端 main（不早于 `8d2afb0`，已含 T114、T119）为基线。和 T123 并行（两单不改同一个源文件；`README.md`、`docs/LESSONS.md` 只会有加法冲突）。
- **负责人 2026-10-23 决定：**
  - G1 默认顺序：Gaussian 及其他计算 default → newhpc → scnet；CREST scnet-test → default → newhpc。
  - G2 "没地方" = 交上去**不能马上运行**：本人上限不够（单作业、总上限、排队上限、调度器运行限额），或者集群空闲核数或内存不够；硬件数据未知也算没地方。
  - G3 ag **只给建议，不自动改入口**。入口仍在建 Attempt 时绑定，批准时照旧显示。
  - G4 某个研究 study 还没签字允许用某个入口时，按 study 单独指定顺序（例如签字前跳过 newhpc）。
  - G5 已有 Attempt 不迁移。
- **监督方细化（写单时补充，负责人可以否决）：**
  - G6 建议**只读本机监控快照**（`<studies_root>/.ag-monitor/<入口>/latest.json`），不发起任何 SSH。快照失败或过期（超过 3 倍采样间隔）时，该入口按"未知 → 没地方"处理。
  - G7 核数未知 → 没地方；核数已知、只有内存未知 → 只按核数判断，结果里标注"内存未知"。
  - G8 集群里已经有他人排队的作业时，新作业多半要排队，所以按"没地方"处理，并写明原因。
  - G9 所有入口都没地方时，建议"按顺序第一个本人上限允许的入口"，标为"需要排队"。
- **资料：** T114 快照字段（`docs/ag-monitor-1.md`，前端仓库）；`ag/src/ag/config.py`（`committed_cap`、`shared_clusters`、`optional_resource_caps`、`allowed_templates`）；`ag/src/ag/clusters.py`；`skills-next/auto-g16-study/SKILL.md` 第 12 行附近的选集群说明；`skills-next/auto-g16-recipes/cards/crest-screen.md`。

## 允许改动的路径

- 新建 `ag/src/ag/route.py`。
- `ag/src/ag/cli.py`：只注册 `route` 子命令。
- `ag/src/ag/config.py`：只新增可选的 `[routing]` 配置段及其校验。
- `ag/src/ag/attempt.py`：只在 prepare 的输出末尾加一行建议提示（见第 4 节），不改其他逻辑。
- 测试：新建 `ag/tests/test_route.py`，用合成快照和合成配置。
- 文档：`README.md`、`ag/config.clusters.example.toml`（加 `[routing]` 示例）、`skills-next/auto-g16-study/SKILL.md`（改写选集群那一段）、`skills-next/auto-g16-recipes/cards/crest-screen.md`、`docs/LESSONS.md`；本单 `docs/redesign-tasks/T117-route-suggestion.md`、`docs/redesign-tasks/open-tasks.txt`。

## 要做的

### 1. 配置（G1、G4）

```toml
[routing]
gaussian = ["default", "newhpc", "scnet"]     # 也用于 gaussian-cp、multiwfn
crest    = ["scnet-test", "default", "newhpc"] # 也用于 xtb

[routing.studies."<study 名>"]               # 可选，按 study 覆盖
gaussian = ["default", "scnet"]
```

- 列表里的名字必须是已配置的入口，不能重复；未知名字让配置校验失败。
- 没有 `[routing]` 段时：`ag route` 照样列出所有入口的状态，但不给出建议，并写"未配置路由顺序"。
- 本单**不改**开发机的配置文件（合并后的事）。

### 2. 判断（G2、G6–G9）

对顺序中的每个入口 E，给定模板和档位（得到核数 c、内存 m）：

1. E 的 `allowed_templates` 允许这个模板，程序已配置；否则写"不允许该模板"。
2. c ≤ 单作业上限。
3. 本人已占用（运行 + 排队）+ c ≤ 总上限。共享组（`shared_with`）的本人占用**只取一次**：取组内任一份新鲜快照的值，不相加；总上限取组内最小值。
4. 有排队上限或调度器运行限额时，同样核对。
5. 硬件：
   - PBS：存在状态为 free 的节点，满足空闲核数 ≥ c 且空闲内存 ≥ m；节点内存未知时按 G7 处理。并且 `job_summary.others_queued_jobs == 0`（G8）。
   - Slurm：分区 `cores_idle` ≥ c，内存按 G7 处理，并且 `others_queued_jobs == 0`（G8）。
6. 快照失败、过期或缺少 T114 字段 → 未知 → 没地方（G6）。

- 每个入口给出结论"可以马上运行 / 没地方 / 不允许"，并逐条写原因。
- 建议取顺序中第一个"可以马上运行"的入口；都不行时按 G9。

### 3. 命令

```
ag route --template <模板> --tier <档位> [--study <study>] [--json]
```

- 打印表格：入口（显示名）、结论、原因、快照时间。最后一行写"建议：<入口>"或"都需要排队：建议排在 <入口>"。
- `--json` 输出同样的内容，供 Skills 和前端以后使用。
- 只读：不写任何文件，不连服务器。

### 4. prepare 提示（G3）

- `ag prepare` 结束时，如果 `--cluster` 不是建议的入口，就多打印一行："路由建议为 <入口>（<原因摘要>）；本次按 --cluster <入口> 准备。"只是提示，不拦截，不写进 manifest。
- 读不到快照或没配置路由时，不打印这一行。

### 5. Skills

- `auto-g16-study/SKILL.md` 选集群一段改写为：准备新 Attempt 之前先运行 `ag route`，按建议选 `--cluster`；要偏离建议时，在 study.md 写明原因。已有 Attempt 不迁移（G5）。
- `crest-screen.md`：CREST 先查赠送分区入口（同样以 `ag route` 为准）。
- 卡片里只写入口名，不写分区名、队列名或账号名。

## 不允许

- 不发起 SSH，不调用调度器，不写快照或任何文件。
- 不自动改变 `--cluster`；不拦截 prepare 或 submit；不改提交和批准规则。
- 不迁移已有 Attempt。
- 夹具和文档只用合成快照，不出现真实用户名、主机名、分区名或队列名。

## 测试

| 场景 | 预期 |
|---|---|
| default 有一个 free 节点，空闲核数和内存都够，没人排队 | 建议 default |
| default 满了，newhpc 够 | 建议 newhpc，并写明 default 没地方的原因 |
| default 有他人排队作业 | default 没地方（G8） |
| 本人总上限不够 | 没地方，原因是"本人上限" |
| 快照过期 / 失败 / 缺少 T114 字段 | 没地方，原因是"快照非最新或缺字段" |
| Slurm 内存未知、核数够 | 可以马上运行，标注"内存未知" |
| 核数未知 | 没地方 |
| CREST 时赠送分区入口可用 | 建议该入口 |
| Gaussian 时，`allowed_templates` 不允许 Gaussian 的入口 | "不允许该模板"，不参与建议 |
| 共享组 | 本人占用只算一次，总上限取组内最小值 |
| 全部没地方 | 建议第一个本人上限允许的入口，标"需要排队" |
| `--study` 有覆盖顺序 | 按覆盖顺序判断 |
| 没有 `[routing]` | 只列状态，写"未配置路由顺序" |
| 配置里出现未知入口名或重复名 | 配置校验失败 |
| prepare 的 `--cluster` 与建议不同 | 多打印一行提示，manifest 不变 |
| 运行过程中有没有 SSH | 没有（用 transport 替身断言零调用） |

推送前本地跑一次全量 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，之后以 CI 为准；同时做公开仓库扫描（`scripts/scan_public.py`），并运行 `git diff --cached --check`。

## 真实环境验证（合并前，开发机；不提交作业）

- 复制一份配置到临时文件，在副本里加上 `[routing]`，指向常驻监控的真实快照目录（只读），对 Gaussian 的 general、complex 档和 CREST 的 mini 档各运行一次 `ag route`。PR 里只写各入口的结论和原因类别，不贴快照内容。
- 出现异常就停下汇报。

## 停止条件

- 需要 SSH 或改快照格式；需要改动范围外的文件；同一问题修两次仍未解决。

## 合并前审阅与交付

- 需要监督方审阅：**是**（改动提交流程中的提示和 Skills 规则）。合并只由负责人操作。
- PR 描述包括：G1–G9 各自对应的改动、判断规则表、全量测试结果、真实验证记录。
- **合并后：** 负责人确认后，Codex 在开发机配置里加上 `[routing]`（改之前先备份）。某个研究 study 在对应入口签字之前，用 `[routing.studies]` 覆盖顺序。研究用计算机在发版同步时再加。

## 版本记录

- v1（2026-10-24，监督方）：依据负责人 10-23 决定 G1–G5 起草，G6–G9 为监督方细化。

## 实施与验证记录（2026-10-24）

- 基线为 `8d2afb0`；实现位于 `codex/t117-route-suggestion`，只修改本单允许路径。
- 共享组复用配置中的 `shared_clusters`，与监控 `shared_with` 的产生规则一致；取组内最新成功、未过期且本人核数完整的一份占用，硬件仍按每个入口自己的快照判断。
- 缺采样间隔的单次快照无法按 G6 判断三倍间隔，按未知处理；显式未知内存和缺内存字段分别处理，前者适用 G7。
- Multiwfn 沿用当前 renderer 的 default PBS 限制，路由不会扩大模板支持。prepare 只在已有文本摘要末尾追加提示，JSON、manifest 和提交逻辑不变。
- 合成测试覆盖本单全部场景，并补充未知/无效内存、时间边界、共享入口失败、单节点限制、程序族、无缓存零写入、JSON 无私有快照内容及 prepare 的 manifest 不变检查。
- 真实验证：开发机临时配置副本加入 G1 顺序，三个命令均返回成功，读取常驻监控真实快照；原配置哈希不变，传输构造与子进程调用由替身禁止且均为零。未提交作业，未更新快照。
- 执行代码：`route.py` SHA-256 为 `cd9135cc5693ce1898dec86ddbfc83c7bf0442ff746870a85e159745e1ca2b5c`。以下只记录入口结论和原因类别，不保存现场快照或身份信息。

| 检查 | default | newhpc | scnet | scnet-test | 建议 |
|---|---|---|---|---|---|
| Gaussian general | 没地方：无符合要求的 free 节点 | 没地方：无符合要求的 free 节点 | 可以马上运行，内存未知 | 不允许该模板 | scnet |
| Gaussian complex | 没地方：无符合要求的 free 节点 | 没地方：无符合要求的 free 节点 | 可以马上运行，内存未知 | 不允许该模板 | scnet |
| CREST mini | 没地方：无符合要求的 free 节点 | 没地方：无符合要求的 free 节点 | 可以马上运行，内存未知 | 可以马上运行，内存未知 | scnet-test |

“可以马上运行”是 G2/G7 的快照判断，不是调度器启动保证。完整测试与扫描结果记录在本 PR；监督方审阅及负责人合并后，才按本单的合并后步骤另行处理本机配置。
