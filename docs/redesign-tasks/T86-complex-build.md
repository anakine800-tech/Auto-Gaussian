# T86：定向复合物构建（F5 第一步）——按指定内坐标挂上一个底物

## 分支与目标

- 分支：`codex/t86-complex-build`；基于最新 main（含 T80），一张任务单一个 PR。**开发机做。**
- **开工条件：** T80 已合并（已满足）；占用一条空闲开发线（同时最多三条）。
- **目标：** 新增本地脚本 `build_complex.py`，三个子命令：
  1. `sites`：列出客体（底物）上可配位的杂原子及其孤对方向参照，供人勾选；
  2. `measure`：从一个已有复合物几何中量出六个相对位置参数（用于复用文献或已有结构的摆法，也用于往返测试）；
  3. `build`：按人给出的六个内坐标，把客体刚性地摆到主体（催化剂 / 路易斯酸）上；核对进攻面标签和 syn/anti 标签、检查原子重叠、记录每个原子来自哪个组分，并输出一份 CREST 约束草稿。
- **为什么：** 某研究课题需要定向初猜。complex 卡片要求“定向构造初猜的约束 CREST（directed）”，但现在只能手写坐标，无法复现，也无法核对进攻面。v2.7 没有成熟实现，新写。
- **负责人 10-16 决定：**
  - 用 Z-matrix 式内坐标指定位置，参照原子全部由人指定；进攻面标签只用来**校验**，不用来生成结构；
  - 产出默认作为**约束 CREST 采样的起点**（也可直接用于 DFT 优化，但卡片默认走约束采样）；
  - 发现原子重叠就**拒绝**并报告，不自动转动寻找无重叠的摆法（那是第二步“系统枚举”的事）；
  - 候选配位位点由工具列出、人勾选，不全自动枚举；
  - 只做主族元素的**单个配位键**（例如一个 B 接一个 O）；多配位点、金属中心不做。
- 资料：`skills-next/auto-g16-recipes/cards/complex.md`（“构建与约束采样”一节）、`crest-screen.md`（约束构象搜索）；`ag/src/ag/crest_input.py`（约束文件语法校验）；`ag/src/ag/topology.py`（半径比规则：< 1.2 倍共价半径和视为相连）；`skills-next/auto-g16-structures/scripts/check_species.py`（T80，读写和哈希记录方式）；`ag/src/ag/geometry.py`。

## 允许改动的路径

- 新增 `skills-next/auto-g16-structures/scripts/build_complex.py`。
- 新增 `skills-next/auto-g16-structures/tests/test_build_complex.py` 和合成夹具。
- `skills-next/auto-g16-structures/SKILL.md`：加“定向复合物构建”一节。
- `skills-next/auto-g16-recipes/cards/complex.md`：只在“构建与约束采样”一节补一段用法，不改其他规则。
- `docs/redesign-tasks/T86-complex-build.md`：本任务单。
- 约束草稿必须能通过 `ag/src/ag/crest_input.validate`（import 调用，不复制、不修改 `crest_input.py`）。不改 `ag/` 下其他文件。

## 要做的

### 1. 输入

- 主体、客体各一个**三维** XYZ（study 内的相对路径，例如 Attempt 的 `final_input.xyz` 或审阅过的构象文件）；每个文件只含一个连通分子（按半径比规则判断），否则拒绝。
- 主体、客体的电荷由人给出；复合物多重度由人给出；脚本不推断。
- 主族限制：主体受体原子和客体给体原子都必须是主族元素；含过渡金属、镧系、锕系的输入拒绝。

### 2. `sites`

```
python build_complex.py sites --guest <xyz> [--study <study>]
```

列出客体中 O、N、S、P、卤素等可能给出孤对的原子：原子序号（从 1 开始）、元素、相连原子、按几何估计的杂化（端位 sp2 氧、sp3 氧、sp2 氮等，仅作提示），以及可用作 syn/anti 参照的相邻原子。只列出，不选择。

### 3. 六参数定义（`build` 的输入，也是 `measure` 的输出）

主体取三个参照原子 `P2, P1, A`（A 为受体原子，例如 B），客体取三个参照原子 `D, X, Y`（D 为给体原子，例如 O；X 与 D 相连；Y 与 X 相连），原子序号分别是两个文件中从 1 开始的序号：

| 参数 | 含义 |
|---|---|
| `r` | A–D 距离（Å） |
| `theta1` | ∠(P1, A, D) |
| `theta2` | ∠(A, D, X) |
| `phi1` | 二面角 (P2, P1, A, D) |
| `phi2` | 二面角 (P1, A, D, X) |
| `phi3` | 二面角 (A, D, X, Y) |

六个参数全部必须给出（单位 Å 和度）。参照原子不能共线（角度接近 0° 或 180° 时，二面角无定义，报错并指出是哪一个）。

### 4. `build`

```
python build_complex.py build --study <study> --name <名称>
    --host <xyz> --host-charge <q> --host-atoms P2,P1,A
    --guest <xyz> --guest-charge <q> --guest-atoms D,X,Y
    --r ... --theta1 ... --theta2 ... --phi1 ... --phi2 ... --phi3 ...
    --multiplicity <m>
    [--face Re|Si --face-center <客体原子> --face-priority a,b,c]
    [--syn-anti-ref <客体原子>]
    [--vdw-factor <f>]
    --force-constant <值> [--constrain-angle]
```

- **构建：** 主体坐标不动；客体作为刚体变换（只做旋转加平移，不改变客体内部几何），使六个参数达到给定值。构建后重新测量六个参数，与给定值的偏差须 < 1×10⁻⁶（Å / 度），否则报错。客体内部所有原子间距与输入的偏差须 < 1×10⁻⁸ Å（证明是刚体变换）。
- **进攻面校验（可选，给了 `--face` 时必须同时给 `--face-center` 和 `--face-priority`）：** `face-center` 是客体上被进攻的三角形中心（例如羰基碳）；`face-priority` 是人按 CIP 优先级从高到低给出的三个相连原子（可取自 T80 核验报告）。脚本计算主体受体原子 A 位于该平面的哪一侧，按“从 A 一侧看，a→b→c 顺时针为 Re”判定，与 `--face` 不一致就报错。三个原子不在 face-center 周围，或 A 几乎在平面内（离平面 < 0.3 Å）时报错。**脚本不自己推断 CIP 优先级。**
- **syn/anti 标签（可选）：** 给了 `--syn-anti-ref`（必须与 X 相连）时，按二面角 (A, D, X, ref) 的绝对值是否 < 90° 标为 syn，否则为 anti。
- **位点标签：** 输出形如 `O7-syn(C9)-Re` 的标签（给体原子 + syn/anti 及参照原子 + 进攻面），并记录每一部分所依据的原子。
- **重叠检查：** 对所有主体–客体原子对（A–D 除外）：按 topology 的半径比规则，距离 < 1.2 × 共价半径和即视为“意外成键”，拒绝；给了 `--vdw-factor` 时，再加一条：距离 < f × 范德华半径和也拒绝。拒绝时列出全部违规原子对（序号、元素、距离、比值）；无论是否通过，报告都列出最近的 10 个主体–客体接触。
- **原子来源映射：** 复合物原子顺序为“主体全部原子在前，客体在后”；输出 `atoms.csv`：复合物序号、组分（host / guest）、来源文件、来源序号、元素。
- **约束草稿：** `constraints.inp` 只含 `$constrain`、`force constant=<人给的值>`、`distance: A, D, <r>`；给了 `--constrain-angle` 时再加 `angle: A, D, X, <theta2>`（使用复合物序号）。写出后用 `crest_input.validate` 校验通过才算成功。脚本不提供力常数默认值。
- **输出：** `analyses/complex-build/<名称>/` 下的 `complex.xyz`（第二行注释写名称、总电荷、多重度）、`constraints.inp`、`atoms.csv`、`build.json` 和 `build.md`（输入文件相对路径与 SHA-256、全部参数及构建后实测值、位点标签及依据、重叠检查结果、总电荷和多重度）。输出目录已存在就拒绝；拒绝符号链接；不出 study。

### 5. `measure`

```
python build_complex.py measure --complex <xyz> --host-range 1-40 --host-atoms P2,P1,A --guest-atoms D,X,Y
```

从已有复合物（主体原子须是连续序号段，客体为其余原子）量出六个参数；参照原子序号用**各自组分内**的序号（与 `build` 一致）。输出可直接作为 `build` 的参数。

### 6. 卡片与技能

- complex 卡片“构建与约束采样”一节补一段：定向初猜用 `build_complex.py` 构建；六个参数和参照原子由人指定并写进 study；进攻面标签只作校验；产出默认走约束 CREST；多配位点和金属不在范围内。
- structures 技能加“定向复合物构建”一节，写清三个子命令和输出位置。

## 不允许

- 不推断 CIP 优先级、电荷、多重度；不自动选择位点；不自动转动以消除重叠；不枚举。
- 不改变客体或主体的内部几何。
- 不处理金属和多配位点。
- 测试只用合成小分子。

## 测试

- **往返测试：** 用合成复合物（例如 BF₃·丙酮、水二聚体）：`measure` 得到六个参数 → 拆开、分别随机转动平移两个组分 → `build` 重建 → 与原复合物对齐后 RMSD < 1×10⁻⁶ Å。
- 进攻面：同一底物分别从两侧接近，标签正确；`face-priority` 顺序颠倒时结论随之翻转；A 几乎在平面内时报错。
- syn/anti 标签；共线参照原子报错；输入不是单个连通分子、含金属时拒绝。
- 重叠：故意给一个太短的距离或错误的二面角，按半径比规则拒绝并列出违规原子对；`--vdw-factor` 更严时额外拒绝。
- 约束草稿通过 `crest_input.validate`；序号是复合物序号。
- 输出已存在、符号链接、路径越界被拒。
- 开发中只跑相关测试；推送前本地跑一次全量 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，之后以 CI 为准。敏感扫描与 `git diff --cached --check`。

## 真实环境验证

- 纯本地工具，不需要集群，不作为合并前条件。
- 合并前在开发机上补做一次：取 L1–L3 或 T68 合成样例中的一个真实复合物几何，走 `measure` → 拆分 → `build` 的往返，结果写进 PR。
- 研究 B 试点时实际使用（届时由研究会话按 T80 流程确认结构后构建）。

## 停止条件

- 需要修改 `crest_input.py` 或 `ag/` 下其他文件。
- 六参数刚体摆放无法在给定精度内复现。
- 需要推断 CIP 优先级才能完成进攻面判定。

## 合并前审阅与交付

- 需要监督方审阅：是。
- PR 描述第一行：`Task: T86`；附往返测试结果。
- 合并只由负责人操作。

## 版本记录

- T116 脱敏：研究标识、编号与环境字面量改为泛称；原工单结构和结论不变。
