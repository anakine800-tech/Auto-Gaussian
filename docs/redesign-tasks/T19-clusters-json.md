# T19 — 前端集群只读查询与监控字段

范围依据：负责人在 T19 中给出的查询字段、快照字段及测试要求。
改动范围：`ag/` 的集群查询、预算摘要、CLI、monitor 和相关测试，以及本文档。
接口需求来源：[前端 T7e 草稿 PR #9](https://github.com/anakine800-tech/Auto-Gaussian-Frontend/pull/9)。

防止的具体事故：把整个配置表序列化后泄露连接身份、路径、账户或模块；
把读取失败的预算显示为零；把上次成功的监控数据误当作本次实时数据。
不新增远程操作，不改变提交、取消、预算结算或配置校验规则。

## `ag clusters --json`

仅读取本地配置、预算台账及预算一致性检查所需的本地 manifest/提交声明。
不建立 Transport、不执行 SSH（包括 `ssh -G`）、不运行子进程、不写文件。
沿用 `ag` 的配置加载与校验；例如 SSH 配置文件必须在本地存在，但不读取连接状态。
默认输出一个 JSON 对象，唯一顶层成功字段为 `clusters`，其值为按名称排序的数组。

每个元素严格按白名单构造，不透传配置表：

| 字段 | 类型与含义 |
|---|---|
| `name` | 配置中的集群别名；旧单集群配置固定为 `default` |
| `scheduler` | `pbs` 或 `slurm`；旧单集群为 `pbs` |
| `is_default` | 布尔值，名称为 `default` 时为 true，与 `prepare --cluster` 的缺省选择一致 |
| `resources.max_cores` | 配置核数上限，整数 |
| `resources.max_committed_cores` | 规范化后的配置值；未配置时等于 `max_cores`，不代表实时可提交额度 |
| `resources.tiers` | 固定四档 `mini`、`simple`、`general`、`complex`；每档只含整数 `cores` 和 `mem_gb` |
| `budget` | 仅 Slurm 且配置 `resources.budget_core_hours` 时出现，见下文 |
| `expires` | 配置到期日期 `YYYY-MM-DD`，未配置为 null |
| `programs_enabled` | 仅 `gaussian`、`xtb`、`crest` 三个布尔值，表示相应程序根目录是否配置 |

当前配置校验要求 Gaussian 与 xTB 根目录均存在于配置中，因此有效配置通常返回三个 true。
CREST 与 xTB 共用 `programs.xtb.root`，两个布尔值一致；这些值不是远程安装或可执行性探测结果。
旧配置添加命名集群时，由原有配置加载逻辑补出隐式 `default`；纯命名配置没有 `default` 时，
所有 `is_default` 均为 false，不擅自选取第一个集群。

不输出主机、路径、用户名、账户、分区、队列、模块名、模块路径或台账内的作业标识。
配置中的集群别名本身应是可展示的名称。
前端 PR #9 曾请求 `local.studies_root`；T19 的路径禁出要求优先，**本命令不返回该字段**。
前端可使用 `ag clusters --json --verify-studies-root <路径>` 核对自身配置的 study 根目录。
仅在提供该参数时，成功 JSON 顶层增加布尔值 `studies_root_matches`：
输入路径与 ag 配置中的 studies_root 各自按 `Path.resolve()` 解析后比较，
因此经符号链接指向同一目录也返回 true；不一致返回 false，命令仍成功退出。
不回显输入路径、配置路径或解析后路径；解析失败沿用不含路径的错误 JSON。
省略参数时不执行此比较，不添加字段，保持原有输出和行为。

### 预算单位、缺失和错误

`budget` 只包含以下三个数值，单位全部为核时（core-hours）：

```json
{"core_hours": 100, "used": 1.5, "reserved": 0.25}
```

- `core_hours`：本地配置的预算上限。
- `used`：本地台账累计已结算核秒除以 3600。
- `reserved`：本地台账仍预留的核秒除以 3600，包括尚未核对的 UNKNOWN；查询不会释放或结算预算。

台账来源为本地配置文件所在目录中的 `budget-<name>.json`，前端不应自行读取或解析它。
数值不代表平台余额，也不包含网页等外部消费或存储费。
未配置预算时 `clusters` 元素省略 `budget`，不能按零预算或无限预算解释。
新集群没有台账且没有对应提交声明时，复用现有预算逻辑得到 used/reserved 为零，查询不创建台账。
损坏、不可读、集群不匹配的台账，或已声明 Attempt 缺少台账记录时，查询失败；不返回部分集群列表。

成功退出码 0。配置/预算校验错误通常为 1，本地环境 I/O 错误为 2。
失败 JSON 只有 `error`（固定通用消息）与 `exit_code`，不包含原始异常中的路径或值。

## `ag monitor` 快照位置

令 `<studies_root>` 为前端已配置并核对的本地 study 根目录，`<name>` 为上述集群别名：

| 配置形式 | 每个集群的完整快照 |
|---|---|
| 旧单集群配置，没有 `clusters` 表 | `<studies_root>/.ag-monitor/latest.json` |
| 纯命名多集群配置 | `<studies_root>/.ag-monitor/<name>/latest.json` |
| 旧配置加命名集群的混合配置 | 所有集群均为 `<studies_root>/.ag-monitor/<name>/latest.json`，包括 `default` |

命名 `default` 的路径是 `.ag-monitor/default/latest.json`。
前端若不知道配置形式，可检查两种 default 路径，但不能把历史遗留文件自动认作正在刷新的快照；
必须结合 `sampled_at`、`ok`、`last_ok_at` 判断新鲜度。
本命令不额外返回路径或自动运行 monitor。

`latest.json` 由 monitor 在本地原子替换；同目录 `history.jsonl` 是摘要而非完整快照，
达到现有 5 MiB 限制后轮转为 `history.1.jsonl`。前端应读取 `latest.json`，不从 history 推断新增字段。
一次性 `ag monitor --json` 对旧配置输出快照本体，多集群输出 `{"clusters": {"<name>": <snapshot>}}`；
磁盘上的各 `latest.json` 均直接存快照本体。

## 快照字段

沿用 `schema: "ag-monitor/1"`，本次为 Slurm `cluster` 对象添加可选数据字段。
前端需要兼容旧快照中没有这些字段的情况。

| 字段 | 含义 |
|---|---|
| `schema` | `ag-monitor/1` |
| `sampled_at` | 本次采样时间，UTC ISO 8601 |
| `interval_seconds` | watch 间隔；一次采样为 null |
| `ok`、`error` | 本次是否成功、失败说明；失败时 error 非 null |
| `last_ok_at` | 最后成功时间，首次失败为 null |
| `own.cores_in_use`、`own.core_cap` | 本用户运行加排队核数及配置核数上限 |
| `own.cores_running`、`own.cores_queued`、`own.committed_cap` | 成功采样后的核数分解与额度；首个失败快照可能缺失 |
| `own.jobs` | 本用户作业数组；包含 job_id、name、state、cores、queue、walltime_used、study、attempt；PBS 另含 mem、walltime_limit、start_time。找不到本地关联时 study/attempt 为 null |
| `cluster.nodes`、`cluster.queues` | PBS 节点与队列统计；Slurm 为 [] |
| `cluster.cores_total`、`cluster.cores_used` | PBS 硬件统计；Slurm 保留旧占位 0，不表示实际容量为零 |
| `cluster.name`、`cluster.scheduler` | Slurm 成功快照的集群名和 `slurm` |
| `cluster.hardware_capacity_known` | Slurm 为 false，不能用占位硬件数字推断可用核数 |
| `cluster.budget` | **新增**；与 clusters 命令相同的 core_hours/used/reserved 和核时单位；未配置或首次采样失败为 null |
| `cluster.expires` | **新增**；当前本地配置到期日期，未配置为 null |
| `cluster.storage_kib` | Slurm 既有字段，本次保证首次失败也有键；ag 远程根目录的 KiB 占用，未知为 null。沿用现有只读存储查询，不新增远程调用 |
| `cluster.expiry_warning` | 既有到期提醒，未到提醒窗口或未配置日期为 null；采样失败时仍从当前配置更新 |
| `warnings` | 本地/调度器状态不一致或超额提醒数组；每项含 kind、job_id、study、attempt、detail |

命名集群的作业 ID 带 `<name>:` 前缀。PBS 节点元素含 name/state/cores_total/cores_used；
队列元素含 name/running/queued。快照沿用现有 monitor 数据，并非 clusters 命令的脱敏配置摘要。

Slurm 首次采样失败时，budget/storage_kib 为 null；有历史成功快照时保留旧 budget/storage_kib，
同时 `ok=false`、`error` 非空、`last_ok_at` 保持旧时间。读取旧版快照缺失的新字段时补 null。
expires 与 expiry_warning 仍反映当前本地配置。前端不能把旧预算、存储值标为实时，也不能将 null/缺失当零。
PBS 不增加 budget/expires/storage_kib，保持原快照行为。

## 验证范围

使用临时合成配置和假 Transport：输出各层白名单及敏感键/值排除、无子进程及无文件变更、
旧配置/双集群/混合配置、缺省选择、预算单位及坏台账、快照新字段、失败保留值和旧快照兼容。
路径核对覆盖一致、不一致、输入或配置端经符号链接指向同一目录，以及符号链接循环不泄露路径。
运行全部 `ag/tests` 并在提交前扫描敏感信息。
真实环境验证不在本任务范围；不读取真实配置、不连接集群、不提交或取消作业。
本任务提供集群查询及根目录一致性布尔核对；前端接入和实际页面验收仍由 T7e 完成。
