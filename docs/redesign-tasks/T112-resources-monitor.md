# T112：资源与后端小修——`%mem` 自动填写、资源参考、监控重读配置、档位进快照、doctor 误报、Dependabot

版本：v3（2026-10-23；监督方 v1 加负责人 R3、显示名和路径范围补充）。**开发机做。** 后端出一个 PR，PR 描述第一行写 `Task: T112`。

## 分支与目标

- 分支：`codex/t112-resources-monitor`。
- **开工条件：** T111 合并之后再开工（两单都会改到 `submit.py` 和 `attempt.py` 附近）；以当时最新的 main 为基线；T112 编号未被占用。
- **负责人 2026-10-23 决定：**
  - R1 Gaussian 输入（包括 `gaussian-cp`）**没有写 `%mem` 时**，prepare 自动填入 `%mem = min(核数 × 2, floor(档位内存 × 0.85))` GB。已经写了的保留，仍按"不超过档位内存的 85%"检查。
  - R2 确认摘要中给出**资源参考**：找本机已完成、模板相同、方法和基组相同、原子数在 ±20% 以内的 Attempt，列出它们的实际耗时和档位。只作提示，不替人选档。
  - R3 监控**每轮重新读取配置**。新增的集群自动开始采样，移除的集群停止采样。SSH 超时记为该集群本轮采样失败，写入快照，进程继续运行；存储用量每小时查询一次，单独设置超时。
  - R4 监控快照中加入**各档位的核数与内存**和**单作业上限**，供前端（T110）显示集群容量。
  - R5 修复 doctor 的"疑似同集群入口未合并"误报：两台不同的 PBS 集群不应触发这条提示。
  - R6 让 Dependabot 不再对冻结目录 `archive/` 发更新 PR（#315 已关闭）。
- **资料：** `ag/src/ag/attempt.py`、`gaussian_input.py`、`monitor.py`、`config.py`、`doctor.py`、`clusters.py`；T101（`unmerged_clusters`）、T103/T106（监控字段）任务单；前端 `docs/ag-monitor-1.md`。

## 允许改动的路径

- `ag/src/ag/gaussian_input.py`、`ag/src/ag/attempt.py`：R1、R2。
- `ag/src/ag/monitor.py`：R3、R4。
- `ag/src/ag/config.py`、`ag/src/ag/doctor.py`：R5、配置重读来源及显示名校验。
- `ag/src/ag/clusters.py`、`ag/src/ag/submit.py`：负责人在 T112 会话明确批准“允许这两处最小改动”，仅增加 clusters JSON 的 display_name 字段，以及提交确认摘要中的显示名、自动 %mem 说明和本地资源参考；不改提交或授权流程。
- `.github/dependabot.yml`（新建或修改）：R6。
- 测试：相关的现有测试文件（PR 中逐个列出），新建 `ag/tests/test_resources_monitor.py`。
- 文档：`README.md`、`docs/LESSONS.md`；`skills-next/auto-g16-recipes/cards/counterpoise.md` 与其他写了手动 `%mem` 示例的卡片（只改成"可省略，由 ag 自动填写"）。
- `docs/redesign-tasks/T112-resources-monitor.md`（本单）、`docs/redesign-tasks/open-tasks.txt`。

## 要做的

### 1. `%mem` 自动填写（R1）

- 只在 Link0 段没有 `%mem` 时插入 `%mem=<n>GB`，插入位置紧跟在 `%nprocshared` 之后。`n` 为整数 GB，`n ≥ 1`。
- 生成的输入纳入 bundle 哈希，确认摘要中写明"`%mem` 由 ag 自动填写：n GB（规则 R1）"。
- 已有 `%mem` 的输入，一个字节都不改。已经 prepare 的 Attempt 不受影响，`verified_files()` 对旧 bundle 的核验照常通过。
- 各档位的预期值：default 与 scnet 的 mini / simple / general / complex 分别为 8 / 10 / 42 / 88 GB；newhpc 的 8/16、16/32、24/48、36/72 档分别为 13 / 27 / 40 / 61 GB。以实际配置为准，在测试中用合成配置覆盖。

### 2. 资源参考（R2）

- prepare 时在本机 `studies_root` 下查找已完成（finished 或 fetched）且有 facts 的 Attempt，条件是：模板相同；方法和基组相同（用 T82 / `protocol()` 的规范化结果比较）；原子数在 ±20% 以内。
- 按原子数接近程度排序，最多列 5 条，每条写：study 与 Attempt 编号、集群、档位与核数、原子数、实际耗时（来自开始和结束回执；缺任何一项就写"未知"）、termination。
- 没有找到就写"无参考"。这部分**只写进确认摘要**，不影响档位选择，也不写进 manifest。
- 只读取本机文件，不连接集群。参考记录中只出现 Attempt 编号，不写路径。

### 3. 监控每轮重读配置、超时容错与存储采样（R3）

- `run_clusters()` 在每一轮开始时重新加载配置。
  - 新增的集群：从这一轮开始采样。
  - 移除的集群：停止采样，它最后一份快照里写上"配置已移除"（只加字段，不删文件）。
- 配置加载失败（例如写到一半）：沿用上一轮的配置，并在本轮各集群的快照里写明警告，进程不退出。
- 单集群模式（`run()`）同样每轮重读配置。
- 负责人 2026-10-23 补充：监控采样遇到 SSH 超时，按该集群本轮采样失败处理并写入快照，进程不退出；其他集群继续采样，下一轮照常执行。
- 负责人 2026-10-23 补充：存储用量查询降到每小时一次，并单独设超时。间隔内沿用最近值并保留其查询时间；失败保留旧值及错误说明，没有旧值时保持未知。用合成时钟和传输验证频率与超时，不制造真实 SSH 故障。

### 4. 档位进快照（R4）

- 在 `own` 中新增两项：`tiers`（各档位的 `{cores, mem_gb}`）和 `max_cores`（单作业上限）。只新增字段，`ag-monitor/1` 中原有字段的含义不变。失败快照同样写这两项，取值来自当前配置。
- 同步更新前端仓库中的 `docs/ag-monitor-1.md`：PR 中提供文档补丁，由 T110 一并合入前端仓库；本单不改前端代码。

### 5. doctor 误报（R5）

- `unmerged_clusters()` 改为：调度器相同，**并且**本机 `ssh -G` 解析出的 hostname、port、user 三者都相同，但别名或配置文件不同，才提示"疑似未合并"。
- `ssh -G` 只读取本机配置、不连接远端。解析失败时不提示，也不判 doctor 失败。
- 输出中不出现主机名或用户名，只列入口名。

### 5a. 可选入口显示名（负责人 2026-10-23 补充）

- 来源：负责人在“按 T110 工单开发”会话中的原始 userMessage，已由 T112 只读核对。`scnet-test` 的显示名改为“scnet-初筛”，入口内部名称不变。
- 配置允许可选 `display_name`：1–32 个可打印字符；成功、失败及沿用旧数据的监控快照均在 `cluster.display_name` 提供当前配置值，缺省时省略该字段。
- `ag clusters --json` 同时提供 `name` 与可选 `display_name`；prepare 和 submit 确认摘要显示“显示名（入口名）”。manifest、台账文件名、作业号前缀继续只使用入口内部名称。
- 合并后才备份本机配置并为 `scnet-test` 加 `display_name = "scnet-初筛"`；合并前不修改实际配置。

### 6. Dependabot（R6）

- 先查明 #315 是由哪种 Dependabot 机制产生的（version updates 还是 security updates）。
- 用最小改动让 Dependabot 不再处理 `archive/`：
  - 如果能通过 `.github/dependabot.yml` 排除，就在 PR 中提交该配置；
  - 如果只能在仓库设置里调整，就在 PR 描述中写清楚需要负责人在网页上做哪些操作，不在 PR 中提交多余的文件。

## 不允许

- 不改档位配置，不改"`%mem` 不超过档位内存 85%"的检查，不改已有 Attempt 的输入。
- 资源参考不能自动替人选档位或 walltime。
- 监控只增加字段，不改变已有字段的含义；配置加载失败时进程不能崩溃。
- 不修改 `archive/` 目录。

## 测试

| 场景 | 预期 |
|---|---|
| 没有写 `%mem`，default general 档（22 核 / 50 GB） | 插入 `%mem=42GB`，摘要中注明 |
| 没有写 `%mem`，newhpc mini 档（8 核 / 16 GB） | 插入 `%mem=13GB` |
| 已写 `%mem=30GB` | 原样保留 |
| 已写的 `%mem` 超过档位内存的 85% | 照旧拒绝 |
| `gaussian-cp` 没有写 `%mem` | 同样自动填写 |
| 旧 bundle 核验 | 通过 |
| 存在符合条件的历史 Attempt | 摘要列出最多 5 条，按原子数接近程度排序 |
| 没有符合条件的历史 Attempt | 写"无参考" |
| 历史 Attempt 缺回执 | 耗时写"未知" |
| 监控运行中新增一个集群 | 下一轮开始采样 |
| 监控运行中移除一个集群 | 停止采样，最后一份快照标注"配置已移除" |
| 配置文件损坏 | 沿用上一轮配置，快照中写警告，进程不退出 |
| 单集群或多集群采样遇到 SSH 超时 | 该集群写失败快照，进程不退出，其他集群及下一轮继续 |
| 一小时内多轮采样及满一小时 | 存储查询一小时内仅一次，满一小时后再查，使用独立超时 |
| 存储查询超时 | 本轮写失败快照并保留最近值和时间，无旧值则未知；进程继续 |
| 快照（成功和失败两种情况） | 都有 `tiers` 和 `max_cores` |
| 可选显示名 / 缺省 / 非法值 | 成功、失败、旧快照沿用和移除显示名均使用当前配置；缺省兼容；拒绝超长、非字符串与不可打印值；身份绑定不变 |
| 两个 PBS 入口，`ssh -G` 解析结果不同 | 不提示 |
| 两个 PBS 入口，`ssh -G` 解析结果相同、别名不同 | 提示 |
| `ssh -G` 解析失败 | 不提示，doctor 不失败 |

推送前本地跑一次全量 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，之后以 CI 为准；同时做敏感信息扫描，并运行 `git diff --cached --check`。

## 真实环境验证（合并前，开发机；不提交作业）

1. 在 default、scnet、newhpc 上各 prepare 一个**不写 `%mem`** 的水分子 SP，只做 prepare，不提交。核对插入的 `%mem` 值和确认摘要中的资源参考（开发机上已有 T106、T108 等验证作业，可以作为参考对象）。
2. 用新代码临时启动一个监控（不替换已有的 LaunchAgent），确认快照中有 `tiers` 和 `max_cores`；在本机配置中加入一个临时测试入口，确认下一轮就开始采样，然后移除该入口并恢复配置。整个过程只用本机配置的副本，不影响正在运行的常驻监控。
3. 对 default 和 newhpc 跑 doctor，确认不再出现"疑似未合并"的提示。
4. 出现异常就停下汇报，不要重试。

## 停止条件

- 需要改档位配置或已有 Attempt；需要改动范围外的文件。
- 同一问题修两次仍未解决。

## 合并前审阅与交付

- 需要监督方审阅：**是**。合并只由负责人操作。
- PR 描述包括：R1–R6 各自对应的改动、`ag-monitor/1` 新增字段、全量测试结果、真实验证记录；R6 如果需要负责人在网页上操作，写明具体步骤。
- **合并后：** 开发机同步，**重启常驻监控**（R3 生效之后，再加集群就不需要重启了）。

## 2026-10-23 开发机验证记录

- 执行代码：T111 合并提交 `e682914` 加本 PR；七个变更源码的 SHA-256 在验证前单独保存，提交前复核字节一致。原始记录留在仓库外。
- default / scnet / newhpc 各 prepare 一个不写 `%mem` 的水分子 SP（mini），生成值依次为 8 / 8 / 13 GB；输入与 bundle 核验通过，源输入不变，摘要列出本机已完成的同方法/基组水分子参考。均停留在 prepared，没有提交声明或 submission 记录。
- 使用真实配置的本机副本和独立缓存运行三轮临时监控：第一轮 4 个入口，第二轮增加临时 PBS 入口共 5 个，第三轮移除后恢复 4 个；共 13 次采样全部成功，移除入口的最后快照保留并标注“配置已移除”。各快照均包含当前 tiers/max_cores，副本中的 scnet-test 显示名正常。
- 两个 Slurm 入口的存储查询时间在三轮间保持不变，未随每轮调度查询重复执行；满一小时和故障分支由合成时钟/传输测试覆盖，没有制造真实 SSH 故障。
- default / newhpc 的 doctor 均通过，没有“疑似同集群入口未合并”提示。实际配置字节未变，临时配置已恢复，常驻监控没有替换或重启。
- 定向回归 1162 通过；显示名、提交摘要与批准兼容补充回归 148 通过。
- 本地全量首次结果：4475 通过、19 跳过、1 失败；唯一失败是未修改的 `test_dedup.py::test_performance_200_frames_20_heavy_atoms`（102.172 秒超过原有 60 秒阈值，保留/排除结果断言通过）。跳过项为 macOS 不支持的 Linux 远程方言与未启用的私有日志。去重代码和测试均与基线一致，未修改阈值；最终 CI 结果见 PR。
- 同一性能测试单独复跑通过：计时区域 11.534 秒，总计 25.72 秒；没有代码或阈值调整。不把单项复跑表述为首次全量通过。

## 版本记录

- v1（2026-10-23，监督方）：依据负责人 10-23 决定 R1–R6 起草，`%mem` 采用方案 A。

- v2（2026-10-23，负责人补充）：R3 增加 SSH 超时按集群记本轮失败但监控不退出；存储用量每小时一次并单独设置超时，补对应测试。

- v3（2026-10-23，负责人补充）：支持可选 display_name，仅改变展示；负责人明确批准 clusters.py / submit.py 的上述最小范围。实际配置待合并后备份再改。

## R6 调查与负责人网页操作

2026-10-23 只读核对：#315 更新 `archive/requirements/chemistry.lock.txt` 中的 Pillow 12.3.0 → 13.0.0；仓库从未配置 `.github/dependabot.yml` / `.yaml`，安全更新已开启且未暂停。同一路径的安全告警 #7–#34 在 PR 创建前约一分钟生成，修复版本均为 13.0.0。因此该 PR 来自 security updates，而不是 version updates。

`exclude-paths` 当前不覆盖安全更新（[上游跟踪 #14408](https://github.com/dependabot/dependabot-core/issues/14408)）；本 PR 不新增无效的 dependabot.yml，也不修改 archive 或仓库设置。

负责人在网页操作：
1. 仓库 Settings → Advanced Security → Dependabot → Dependabot rules → New rule。
2. 名称例如“冻结 archive 清单”；State 选 Enabled；Target alerts 以 Manifest path 精确选择 `archive/requirements/chemistry.lock.txt`，并选择依赖图中其他属于 `archive/` 的清单。这里按实际清单列表选取，不假定该输入支持 glob。
3. Rules 选择 Dismiss alerts → indefinitely，保存 Create rule。该规则也会忽略这些冻结清单的安全告警；不是修复漏洞。依赖图中现存 archive 告警只有上述 chemistry 清单；若以后新增冻结清单，应补入规则。
4. 核对规则命中范围仅限 archive；保留其他路径的 Dependabot 安全更新。核对现有告警转为自动忽略，未来 archive 告警不会触发安全更新 PR。

依据：[GitHub 自定义自动分流规则](https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/manage-your-dependency-security/auto-triage-dependabot-alerts)。本次只提供操作说明，尚未执行网页设置。

## 前端字段文档补丁（交 T110 合入）

仅提供文档补丁，不改前端代码；在前端 `docs/ag-monitor-1.md` 的末尾追加以下段落。若 T110 已说明 tiers/max_cores/display_name，可保留一份定义并合入下面的生产端失败与新鲜度说明。

```diff
--- a/docs/ag-monitor-1.md
+++ b/docs/ag-monitor-1.md
@@ -70,3 +70,17 @@
 失败、过期和来源歧义沿用非最新标记。`shared_with` 非空时显示
 “与 <入口名> 共享总上限”，多个名称以顿号分隔；页面没有跨入口核数合计或占用比例。
 `budget` / `expires` 为 null 时不显示对应行。此规则替代 T97 文档中的旧容量退回显示。
+
+T112 生产端补充（ag-monitor/1，仅新增字段）：
+- own.tiers：mini/simple/general/complex 各为 {cores: 正整数, mem_gb: 正整数}；own.max_cores 为单作业正整数上限。
+- 成功与失败快照中的 tiers/max_cores 都取当前有效配置；core_cap 等已有字段含义不变。
+- cluster.display_name：可选、1–32 个可打印字符；显示为“显示名（入口名）”，缺省只显示入口名。
+- 显示名来自当前配置，即使本轮失败、沿用旧占用数据也更新；移除配置中的显示名时移除该字段。
+- config_warning：配置重读失败时的说明，否则 null；warnings 同时新增 kind=config-reload-failed。
+- config_removed：配置已移除的入口为 true；config_note 为“配置已移除”。
+- 移除入口时保留最后快照原有字段与 sampled_at，仅加标注；不再采样，不把旧数据当新数据。
+- SSH 超时只使该入口本轮 ok=false；其余入口和下一轮继续，监控传输不立即重试。
+- Slurm cluster.storage_kib 每小时查询一次，独立 30 秒超时；失败尝试也按一小时节流。
+- cluster.storage_checked_at 为最近查询尝试的 UTC 时间；storage_sampled_at 为最近成功时间或 null。
+- cluster.storage_error 为最近存储查询的脱敏错误或 null；storage_kib 未取得成功值时为 null。
+- 两次存储查询之间沿用旧值和成功时间。存储查询超时当轮失败，后续调度采样可成功但仍保留存储错误；显示时结合存储时间/错误，不能仅凭顶层 ok 当作存储新鲜。
```
