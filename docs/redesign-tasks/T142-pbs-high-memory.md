# T142：显式授权 PBS 高内存档位

版本：v1，2026-10-27。负责人已授权本单开发；仅做通用后端配置兼容与离线验证，不部署、连接集群或提交计算。

## 目标与依据

现行 PBS 档位固定不超过 120 GB，阻断已由负责人明确授权的高内存入口；直接全局提高上限又会同时放宽未授权入口。本单只增加入口级显式配置，保留旧配置默认上限。

- 基线：`e7e1af9b662ae53f125dc9c6a7560a1a15ae7dcc`，已包含 T141。
- 分支：`codex/t142-pbs-high-memory`；PR 首行：`Task: T142`。
- 新字段：PBS 入口的 `resources.pbs_max_mem_gb`，严格整数 **120–200**；省略为 **120 GB**，不向旧配置写入默认字段。
- 所有 PBS 档位的 `mem_gb` 不得超过本入口上限。布尔值、小数、字符串和越界值拒绝；在 Slurm 入口显式填写该 PBS 专用字段也拒绝。
- 上限仅表示负责人写入本机配置的授权范围，**不证明节点物理容量、调度器许可或账号配额**，不影响其他入口。
- Gaussian 单节点、`%mem ≤ 档位内存 × 85%`、核数及提交批准检查不变；不替任何作业授权。
- 复用 prepare、render、route 的现有档位处理；不改监控协议或模板，不重写既有 Attempt。

## 允许路径

- `ag/src/ag/config.py`。
- 仅确有必要时：`ag/src/ag/clusters.py`（白名单元数据）、`ag/src/ag/attempt.py`、`ag/src/ag/render.py`、`ag/src/ag/route.py`。
- `ag/tests/test_pbs_high_memory.py`；必要时既有 `test_core.py`、`test_gaussian_only.py`、`test_route.py`、`test_clusters.py`、`test_slurm.py` 中与本单直接相关的测试。
- `README.md`、`ag/config.example.toml`、`ag/config.clusters.example.toml`。
- 本任务单及 `docs/redesign-tasks/open-tasks.txt`（只追加本单；历史待办清理留发版任务）。

不改其他代码、模板、版本、依赖、Skills、服务配置或研究记录。需要越界时先报告。

## 验收

1. 旧 PBS 省略新字段时 120 GB 通过、121 GB 拒绝；显式 120 与旧行为一致。
2. 显式授权允许 121–200 GB 内的有效档位，200 GB 通过；档位超过授权上限或超过 200 GB 拒绝。
3. 非整数、布尔、越界上限拒绝；不同入口不继承此授权。Slurm 未使用该字段时保持既有内存行为。
4. 合成 Gaussian-only 配置的高内存档位可由 prepare 记录并正确渲染 PBS 指令；静态入口列表和 route 使用同一档位。
5. Gaussian 显式 85% 边界、自动内存规则、禁用模板、prepare 后配置变化及 bundle 字节保护保持。
6. 用既有合成多入口测试证明旧入口和路由不变，复用旧渲染 SHA-256 回归证明脚本字节兼容。
7. 相关测试先跑；推送前全量 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`、有效本机词表扫描及 diff 检查通过。

## 真实环境与交付边界

本单只修改本机配置校验，不修改远程命令、提交/状态/取回或证据路径；使用临时合成配置、小分子及假 Transport，不运行真实作业。实际高内存硬件、共享目录、调度限制与 Gaussian 执行验收在发布后按独立私有部署授权完成；离线/CI 成功不等于真实计算或部署通过。

公开工单、测试、PR 和日志只含通用行为及合成数据，不含实际机器、账号、SSH 别名、队列、资源池或研究参数。PR 等监督方审阅与负责人合并；同号发版另单办理。
