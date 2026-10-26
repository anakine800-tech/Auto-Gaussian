# T142：六档资源、显式 PBS 高内存与单作业时限

版本：v2，2026-10-27。负责人已授权扩展本单；继续同一分支，以本版目标、允许路径及验收替代原仅高内存范围。只做研发和离线合成测试，不部署或提交真实计算。

## 目标与依据

固定四档和 PBS 120 GB 上限无法表达部分入口的显式高资源授权；缺少入口级作业时限也可能让已准备的长作业在配置收紧后仍进入提交。本单统一配置、准备、提交、路由和只读展示的资源规则，保留旧入口默认行为。

- 基线：`e7e1af9b662ae53f125dc9c6a7560a1a15ae7dcc`，已包含 T141。
- 分支：`codex/t142-pbs-high-memory`；PR 首行：`Task: T142`。
- 固定档位顺序：`mini/simple/general/complex/max/ultra`；前四档必需，后两档各自可选，不补虚构档位。只识别这六名；既有未知元数据不透传，不新增未知键硬拒绝。
- 新字段：PBS 入口的 `resources.pbs_max_mem_gb`，严格整数 **120–200**；省略为 **120 GB**，不向旧配置写入默认字段。
- 所有 PBS 档位的 `mem_gb` 不得超过本入口上限。布尔值、小数、字符串和越界值拒绝；在 Slurm 入口显式填写该 PBS 专用字段也拒绝。
- 上限仅表示负责人写入本机配置的授权范围，**不证明节点物理容量、调度器许可或账号配额**，不影响其他入口。
- 可选 `resources.max_walltime`：PBS/Slurm 均可配置正值 `HH:MM:SS`，小时 2–4 位 ASCII 数字、分秒 00–59。省略不增加 AG 入口时限，不证明调度器无限制；布尔、数字、null、零值、非法格式拒绝。
- Gaussian 单节点、`%mem ≤ 档位内存 × 85%`、核数及提交批准检查不变；不替任何作业授权。
- 扩展 prepare、CLI、route、clusters 和 monitor 的已知档位，保留 ag-monitor/1 版本，不改模板或重写既有 Attempt。

## 贯通行为

1. prepare/CLI 接受实际配置的可选档位；缺档或 walltime 超限，在新文件、序号声明、日志或远程可执行检查之前拒绝。
2. submit 从不可变 manifest 重核实际 walltime。首次超限在构造/绑定 Transport、日志、锁、审批消费、claim 和远程写入之前拒绝；确认后、claim 前再次核对。人工对话框、批准记录和长期规则不能覆盖资源硬上限。
3. 使用本次提交调用加载的有效配置，不在确认期间重新加载整份磁盘配置；旧 prepared 在下一次提交时按新有效限额拒绝。旧 manifest/bundle 不改写，不自动改小资源或时限，旧配置脚本字节保持。
4. route 请求缺少的可选档位时返回“不允许”及“不支持该档位”，cores/mem_gb 为 null、personal_allowed 为 false，不推荐也不抛 KeyError；文本不输出 None。
5. `ag clusters --json` 的 `resources.tiers` 和 `ag-monitor/1` 的 `own.tiers` 按固定顺序只输出实际四至六档；每档继续只输出 cores/mem_gb。
6. `resources.max_walltime` / `own.max_walltime` 仅配置时输出同一字符串，省略时不补 null。失败快照使用当前配置；移除字段或档位后不能残留缓存旧值。

## 允许路径

- `ag/src/ag/config.py`、`attempt.py`、`cli.py`、`route.py`、`monitor.py`、`clusters.py`、`submit.py`；必要时 `render.py`；`approval.py` 仅为复用既有时间解析所必需的调整。
- `ag/tests/test_pbs_high_memory.py`、`test_resource_limits.py`，以及直接相关的配置、prepare、CLI、route、monitor、submit、approval、clusters 回归测试。
- `README.md`、`ag/config.example.toml`、`ag/config.clusters.example.toml`、`docs/redesign-tasks/T19-clusters-json.md`。
- 本任务单及 `docs/redesign-tasks/open-tasks.txt`（只追加本单；历史待办清理留发版任务）。

不改 remote/transport、模板、版本、依赖、Skills、真实配置或研究记录；不另建配置分支或独立 schema 治理文档。确需越界先报告。

## 离线验收

1. 旧 PBS 省略新字段时 120 GB 通过、121 GB 拒绝；显式 120 与旧行为一致。
2. 显式授权允许 121–200 GB 内的有效档位，200 GB 通过；档位超过授权上限或超过 200 GB 拒绝。
3. 非整数、布尔、越界上限拒绝；不同入口不继承此授权。Slurm 未使用该字段时保持既有内存行为。
4. 合成 Gaussian-only 配置的高内存档位可由 prepare 记录并正确渲染 PBS 指令；静态入口列表和 route 使用同一档位。
5. Gaussian 显式 85% 边界、自动内存规则、禁用模板、prepare 后配置变化及 bundle 字节保护保持。
6. 用既有合成多入口测试证明旧入口和路由不变，复用旧渲染 SHA-256 回归证明脚本字节兼容。
7. 四档旧配置、各可选档位、六档顺序、缺档拒绝和未知元数据不泄露；时限省略/正值/四位小时/零值/非法格式/边界。
8. submit 初次超限零副作用；dialog/approval/policy 均不能绕过；确认后及 claim 前收紧有效配置拒绝，不改旧 bundle、不产生远端写入。
9. 成功、失败和旧快照中的可选档位/时限更新与移除；schema 仍为 ag-monitor/1；排队机制原样复用。
10. 相关测试先跑；推送前全量 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`、有效本机词表扫描及 diff 检查通过。

## 真实环境与交付边界

本轮负责人明确限定研发/离线测试。全部使用临时合成配置、小分子及假 Transport；未进行真实提交验证。实际环境、容量和端到端作业验证在正式发布后另行审批，不能以离线/CI 成功代替。

公开工单、测试、PR 和日志只含通用行为及合成数据，不含实际机器、账号、SSH 别名、队列、资源组合或研究参数。PR 的最终标题、描述与测试均以本版完整范围为准，等待监督审阅与负责人合并；发版另单，禁止提前部署开发分支。
