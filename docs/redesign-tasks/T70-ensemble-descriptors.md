# T70：`ag ensemble` 可选输出局部构象描述（T63 的二面角分组、关键距离）

## 分支与目标

- 分支：`codex/t70-ensemble-descriptors`；基于最新 main，一张任务单一个 PR。**开发机做。**
- **目标：** 让 T63 的局部构象判别结果进入构象集合清单，供 K4、N2 审阅和前端集合页（T71）显示。`ag ensemble` 新增可选参数，写法与 `ag dedup` 完全相同：`--dihedral-bins`、`--report-distance`。给了参数，每个候选多输出分组、是否靠近边界、关键距离；不给，**输出与现在逐字节一致**。
- **为什么：** T63 已经能在去重时按二面角分组，但集合清单和集合页看不到这些分组，审阅时还得另外查。
- 资料：`ag/src/ag/ensemble.py`（`build`、`register`）、`ag/src/ag/dedup.py`（`descriptor_definitions`、`frame_descriptors`）、`ag/src/ag/geometry.py`、`docs/ag-ensemble-1.md`。

## 允许改动的路径

- `ag/src/ag/ensemble.py`：新增参数和字段；从 `dedup` import `descriptor_definitions`、`frame_descriptors`，**不复制实现**。
- `ag/tests/test_ensemble.py`：新增用例。
- `docs/ag-ensemble-1.md`：补充新增字段（标明是可选字段，仍为 `ag-ensemble/1`）。
- `ag/README.md`：ensemble 一节加用法。
- `docs/redesign-tasks/T70-ensemble-descriptors.md`：本任务单。
- **不改 `dedup.py`、`geometry.py`**（只 import）。如果必须改，停下询问。

## 要做的

1. **新参数**（可重复，语法、校验和错误信息与 `ag dedup` 一致）：`--dihedral-bins A,B,C,D:b1,b2[@名1,名2]`、`--report-distance I,J`。不支持 `--contact-atoms`（集合页用不上，避免清单过大）。
2. **新增字段（只在给了参数时出现）：**
   - 顶层 `descriptors`：与 `ag dedup` 输出里的定义格式相同（二面角的原子、分界、组名；距离原子对）。
   - 每个候选 `local`：`dihedrals`（度）、`bins`（组名）、`near_boundary`（布尔）、`distances`（Å）。根据该候选在 XYZ 中的那一帧计算。
   - 顶层 `bin_summary`：每种分组组合有多少候选，以及其中最低能候选的编号（按 thermo > opt > sp > xtb 的可用层级）。
   - Markdown 表多出“分组”“近边界”“距离”三列和一张分组汇总表。
3. **不给参数时，JSON 和 Markdown 输出与 main 逐字节一致**（用现有夹具对比哈希）。
4. 原子编号越界、共线二面角等错误，按 `ag dedup` 的方式报错，并指明是哪一帧、哪个定义。

## 前端 T71 依赖的格式（写进 `docs/ag-ensemble-1.md`）

```json
"descriptors": {"dihedral_bins": [{"atoms": [1,2,3,4], "boundaries": [-90, 90], "names": ["cis", "trans"]}],
                "distance_pairs": [[5, 14]]},
"bin_summary": [{"bins": ["cis"], "count": 3, "lowest_candidate": 1, "lowest_layer": "sp"}],
"candidates": [{ "...": "原有字段", "local": {"dihedrals": [12.3], "bins": ["cis"], "near_boundary": false, "distances": [1.587]} }]
```

## 不允许

- 不改变不给参数时的任何输出；不改 `ag-ensemble/1` 的 schema 名。
- 不根据分组合并或删除候选（`ag ensemble` 只汇总，去重是 `ag dedup` 的事）。

## 测试

- 合成正丁烷集合：按 C–C–C–C 三组分，分组、近边界、距离与独立计算一致；`bin_summary` 计数和最低能候选正确。
- 不给参数时输出哈希与 main 一致。
- 参数错误、编号越界、共线二面角的报错。
- `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`；敏感扫描与 `git diff --cached --check`。

## 真实环境验证

- 纯本地分析，不需要集群。合并后在 HSS 的 K4 使用（HSS 主会话用已签的 s-cis/s-trans 定义生成）。

## 停止条件

- 需要修改 `dedup.py` 或 `geometry.py`。
- 新字段需要改变 `ag-ensemble/1` 的已有字段。

## 合并前审阅与交付

- 需要监督方审阅：是。
- PR 描述第一行：`Task: T70`；附“不给参数时输出不变”的哈希对比。
- 合并只由负责人操作。
