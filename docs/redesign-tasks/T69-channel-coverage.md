# T69：`ag channel-coverage` 按通道汇总采样覆盖

## 分支与目标

- 分支：`codex/t69-channel-coverage`；基于最新 main，一张任务单一个 PR。**开发机做。**
- **目标：** 新增本地命令 `ag channel-coverage`，按立体通道汇总采样和精修的覆盖情况，标出通道之间不均衡的地方。
- **为什么：** 选择性来自两组 TS 的能量差。如果通向某个产物的通道采样得更充分，最低能 TS 更容易被找到，ΔΔG‡ 就会系统性地偏向那一侧。研究 A 的相应阶段 和研究 B 都需要在审阅时看到每个通道的覆盖是否相当。
- **原则：** 只汇总已保存的清单，不推断通道归属，不判定“合格”；“不均衡”只是可调阈值的提示。
- 资料：`ag/src/ag/ensemble.py`、`docs/ag-ensemble-1.md`（`ag-ensemble/1` 格式）。

## 输入：通道表 CSV（负责人 10-16 决定）

放在 study 的 `analyses/` 下，UTF-8，带表头：

| 列 | 必填 | 含义 |
|---|---|---|
| `channel_id` | 是 | 通道编号（与 study.md 通道表一致） |
| `product_branch` | 是 | 产物分支标签（例如产物的 CIP 构型） |
| `ensemble_manifests` | 是 | 属于该通道的 `ag-ensemble/1` 清单，相对 study 根目录，多个用分号分隔 |
| `note` | 否 | 备注 |

## 允许改动的路径

- 新增 `ag/src/ag/channel_coverage.py`。
- `ag/src/ag/cli.py`：只在分析命令元组里登记 `'channel_coverage'`（命令名 `channel-coverage`，与现有命令的登记方式一致）。
- `ag/tests/test_smoke.py`：**已预先批准**，只在固定的分析命令列表断言里追加 `ag.channel_coverage`。
- 新增 `ag/tests/test_channel_coverage.py` 和合成夹具。
- 新增 `docs/ag-channel-coverage-1.md`：输出格式说明。
- `ag/README.md`：分析命令一节加用法。
- `docs/redesign-tasks/T69-channel-coverage.md`：本任务单。
- **不改 `ensemble.py`**（T70 在改它）。

## 要做的

1. **命令：**
   ```
   ag channel-coverage --channels <analyses/ 下的通道表 CSV> --out <analyses/ 下新的 .json>
                       [--study <study>] [--imbalance-ratio 0.5]
   ```
   同时输出同名 `.md`。两者已存在就拒绝。
2. **对每个通道汇总**（来自它引用的全部清单）：清单数；候选总数；按路线的候选数；有 SP 的候选数；有 Opt 的候选数；有热化学的候选数；`ambiguous` 数；`unmatched_attempts` 数；该通道最低能候选（按可用的最高层级：thermo > opt > sp > xtb）来自哪条路线、哪个清单、哪个候选编号；警告（例如清单的 `energy_basis` 是 `per_source_not_comparable`）。
3. **按产物分支汇总**同样的数字。
4. **不均衡提示：** 对 Opt 数、SP 数、候选数这三项，任一通道少于所有通道最大值 × `--imbalance-ratio` 时标出；产物分支之间同样比较。只提示，不判定。
5. **校验：** 清单必须在 study 内、`schema` 为 `ag-ensemble/1`；同一清单出现在两个通道里时报错；清单里的 `study_id` 与当前 study 不一致时报错；CSV 缺列、空值时报错并指明行号。
6. **输出格式**写进 `docs/ag-channel-coverage-1.md`（`schema: "ag-channel-coverage/1"`），引用的文件用键名 `path` 记录并附 SHA-256（这样 `ag review manifest` 能收录）。

## 不允许

- 不推断通道归属，不重算能量或布居，不判定覆盖是否足够。
- 不读 study 外的文件；拒绝符号链接（复用 `study.local_path`）。

## 测试

- 合成 study：两个产物分支、四个通道，各自有不同数量的候选、SP、Opt；其中一个通道明显偏少 → 被标出；调整 `--imbalance-ratio` 后提示随之变化。
- 最低能候选的层级选择正确（有 thermo 用 thermo，否则依次退回）。
- 各种校验错误（清单重复、study 不一致、CSV 缺列、清单不存在、符号链接）。
- 输出没有绝对路径；`ag review manifest` 能收录引用的清单。
- `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`；敏感扫描与 `git diff --cached --check`。

## 真实环境验证

- 纯本地分析，不需要集群。合并后在研究 A 的相应阶段 实际使用（届时由研究 A 主会话把通道表另存为 CSV）。

## 停止条件

- 需要修改 `ensemble.py` 或 `ag-ensemble/1` 格式。
- 需要推断通道归属才能工作。

## 合并前审阅与交付

- 需要监督方审阅：是。
- PR 描述第一行：`Task: T69`。
- 合并只由负责人操作。

## 版本记录

- T116 脱敏：研究标识、编号与环境字面量改为泛称；原工单结构和结论不变。
