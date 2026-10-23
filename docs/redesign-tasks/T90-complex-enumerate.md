# T90：定向复合物系统枚举（F5 第二步）；`prepare_preview` 字段名更正

## 分支与目标

- 分支：`codex/t90-complex-enumerate`；基于最新 main（含 T86），一张任务单一个 PR。**开发机做。**
- **目标：**
  1. 在 T86 的 `build_complex.py` 中新增 `enumerate` 子命令：在人勾选的位点上，按二面角网格系统摆放客体，过滤重叠，去重，输出候选集合（多帧 XYZ）和逐个候选的参数表，作为约束 CREST 的多个起点；
  2. 更正 `prepare_preview.py` / `inspect_chemdraw.py` 中名不副实的 `explicit_h_atom_count`（T80 发现：存的是补氢后的总原子数）。
- **负责人 10-17 决定（枚举）：** r、θ₁、θ₂ 由人给定；三个二面角各自按 30° 一格枚举，可以只放开其中一部分、其余固定；枚举范围 = 人勾选的位点 × 指定的进攻面；先过滤重叠，再按重原子对齐 RMSD < 0.3 Å 去重；总数上限默认 200，超过就报错要求缩小范围，**不随机抽样**。仍只做主族单个配位键。
- 资料：`skills-next/auto-g16-structures/scripts/build_complex.py`（T86：`build_geometry`、`contact_report`、`site_labels`、`face_label`、输出写法）、`skills-next/auto-g16-structures/scripts/prepare_preview.py`、`inspect_chemdraw.py`、`check_species.py`（T80 的正确字段名）、`ag/src/ag/crest_input.py`（约束与 xyz 多帧校验）、`skills-next/auto-g16-recipes/cards/complex.md`、`crest-screen.md`。

## 允许改动的路径

- `skills-next/auto-g16-structures/scripts/build_complex.py`：新增 `enumerate` 子命令及其内部函数；`sites`、`measure`、`build` 的行为和输出不变。
- `skills-next/auto-g16-structures/scripts/prepare_preview.py`、`inspect_chemdraw.py`：只改字段（见第 2 节）。
- `skills-next/auto-g16-structures/tests/test_build_complex.py`、`test_structures.py`：新增和调整用例。
- `skills-next/auto-g16-structures/SKILL.md`、`skills-next/auto-g16-recipes/cards/complex.md`（“构建与约束采样”一节）：补用法。
- `docs/redesign-tasks/T90-complex-enumerate.md`：本任务单。
- 不改 `ag/` 下任何文件（只 import `crest_input`）。

## 要做的

### 1. `enumerate`

```
python build_complex.py enumerate --study <study> --name <名称>
    --host <xyz> --host-charge <q> --host-atoms P2,P1,A
    --guest <xyz> --guest-charge <q>
    --site D,X,Y[:face=Re|Si:center=<原子>:priority=a,b,c][:ref=<syn/anti 参照>]   （可重复，每个是人勾选的一个位点）
    --r ... --theta1 ... --theta2 ...
    --phi1 <固定值 或 grid[:步长]> --phi2 <...> --phi3 <...>
    --multiplicity <m> --force-constant <值> [--constrain-angle]
    [--vdw-factor <f>] [--dedup-rmsd 0.3] [--max-candidates 200]
```

- 每个 `--site` 给出该位点的客体参照原子 D、X、Y，以及可选的进攻面和 syn/anti 校验参数（含义与 T86 `build` 相同）。
- 每个二面角或者给固定值，或者写 `grid`（默认步长 30°，范围 [−180°, 180°)）；至少一个是 `grid`。
- 先计算组合总数：位点数 × 网格组合数；超过 `--max-candidates` 直接报错，并给出总数，提示缩小范围。
- 每个组合调用 T86 的同一套构建和核对函数（复用，不复制）：六参数复现、刚体检查、进攻面 / syn-anti 校验、重叠检查。进攻面与声明不符、重叠的组合**被剔除并记录原因**，不报错中止。
- **去重：** 对通过的候选，按重原子（全部组分）固定行序 Kabsch 对齐 RMSD < `--dedup-rmsd` 视为重复，保留先出现的一个（按位点顺序、再按网格顺序，顺序确定、可复现）；记录被合并的候选及其代表。
- **输出：** `analyses/complex-build/<名称>/` 下：`candidates.xyz`（多帧，注释行写候选编号、位点标签、六参数）、`candidates.csv`（编号、位点标签、六参数、最近接触、是否保留、去重代表）、`atoms.csv`（同 T86）、`constraints.inp`（与 T86 相同的约束，按复合物序号；所有候选共用同一套原子编号，所以只需一份）、`enumerate.json` / `.md`（输入哈希、网格定义、统计：总组合数、剔除数及原因分布、去重前后数量）。目录已存在就拒绝。
- `candidates.xyz` 须能通过 `crest_input.xyz_ensemble`（多帧原子一致），以便作为 CREST `--mdopt` 或多起点输入；在 PR 中说明后续如何交给 `ag prepare`（只写用法，不改 ag）。
- 全部被剔除时：不写 `candidates.xyz`，报告写明原因分布，退出码非零。

### 2. `prepare_preview` 字段更正

- 现状：`summary.json` 的 `explicit_h_atom_count` 实际是 `Chem.AddHs(mol).GetNumAtoms()`（补氢后的总原子数），`inspect_chemdraw.py` 同样。
- 修改：新增 `atom_count_with_h`（补氢后总原子数）和 `source_explicit_h_atom_count`（源文件中画出的显式氢数，与 T80 `check_species` 口径一致）；保留旧字段 `explicit_h_atom_count` 不变（兼容已有记录），并新增 `deprecated_fields: {"explicit_h_atom_count": "历史字段名，实为补氢后总原子数；请改用 atom_count_with_h"}`。
- 更新 structures 技能中引用该字段的说明。

## 不允许

- 不改 `sites`、`measure`、`build` 的输出；不随机抽样；不自动选择位点；不推断 CIP。
- 不删除或改变旧字段 `explicit_h_atom_count` 的值。
- 测试只用合成小分子。

## 测试

- 合成主体 + 客体（例如 BF₃ + 丙酮）：一个位点、φ2 网格 30°（12 个组合）→ 统计正确；含重叠的组合被剔除并有原因；对称导致的重复被去重。
- 两个位点、两个二面角网格 → 组合数正确；超过上限报错且不写输出。
- 进攻面声明与几何不符的组合被剔除。
- 去重顺序可复现（同输入两次输出字节一致）。
- `candidates.xyz` 通过 `crest_input.xyz_ensemble`；约束草稿通过 `crest_input.validate`。
- `prepare_preview` / `inspect_chemdraw`：新字段正确，旧字段值不变；现有测试数据其余输出不变。
- 开发中只跑相关测试；推送前本地跑一次全量 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，之后以 CI 为准。敏感扫描与 `git diff --cached --check`。

## 真实环境验证

- 纯本地，不需要集群。合并前在开发机上用一个合成或 T68 样例体系完整跑一遍 `sites` → `enumerate`，结果（统计和抽查的几个候选）写进 PR。
- 合并前由研究 A 主会话用已有结构只读跑一次（输出写到 study 以外），结果只汇报监督方，不写进 PR。

## 停止条件

- 需要改 T86 已有子命令的输出，或改 `ag/` 下文件。
- 去重或剔除规则需要随机性才能工作。

## 合并前审阅与交付

- 需要监督方审阅：是。
- PR 描述第一行：`Task: T90`。
- 合并只由负责人操作。

## 范围补充（10-17，监督方批准）

按“约束原子组合”分组：距离约束的 A–D 完全相同，且启用角度约束时 A–D–X
也完全相同的位点归为一组。每组输出 `candidates-group-N.xyz` 与
`constraints-group-N.inp`，因为一次 CREST 只能用一份约束文件。
只有一组时保留 `candidates.xyz` 和 `constraints.inp`。去重只在组内进行。
`candidates.csv` 和 `enumerate.json` 记录每个候选组号；JSON 同时记录每组的
位点、约束原子与配套文件。每组非空集合须通过 `crest_input.xyz_ensemble`，
每份约束须通过 `crest_input.validate`。空组不写 XYZ 并明确记录；全部为空时非零退出。
本补充取代上文“所有候选共用一份约束”和跨全部位点去重的原始要求。

## 版本记录

- T116 脱敏：研究标识、编号与环境字面量改为泛称；原工单结构和结论不变。
