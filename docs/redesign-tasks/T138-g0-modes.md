# T138：G0 模式投影——反应内坐标的 Wilson B 投影与排序细化

版本：v1（监督方，2026-10-26）。**开发机做。** 后端出一个 PR，PR 描述第一行写 `Task: T138`。

## 分支与目标

- 分支：`codex/t138-g0-modes`。
- **开工条件：** 以后端 main 为基线（T136 已合并）。**与 T137 并行开发、T137 先合并**：
  - 本单的核心计算放在新文件 `ag/src/ag/g0_modes.py`，接口见第 1 节，不依赖 T137；
  - 并入 `ag g0` 的报告和排序，要等 T137 合并后 rebase 再接（第 6 节）。在那之前不要改 `g0.py`，也不要另写一份 G0 报告或排序。
- **目标（规格 T-E“反应坐标投影的实现要求”）：** 读取已有的频率结果，判断每个负模式是否沿着声明的反应内坐标运动：**断裂键应伸长、形成键应缩短**。用内坐标投影 δc = B q 逐个内坐标计算，共享原子（如质子转移中的 H）的贡献不会抵消。结果只作为标记和排序信号，不拒绝任何候选，不设任何阈值。
- **监督方决定（负责人 10-26 授权“按推荐”）：**
  - M1 **模式来源**：只读**已取回的 Gaussian 频率结果**，复用 `mode_review.frequency_section` 和 `mode_review.read_modes`（它们会确认模式向量和几何处于同一取向，并逐原子核对编号与元素）。频率结果可以是低层方法在初猜几何上的 Freq，也可以是 DFT TS 优化后的 Freq。**本单不做 xTB Hessian**：那需要新程序模板、白名单和真实验证，属于另外的范围，记入后续工作。
  - M2 **约定**：笛卡尔、不做质量加权。每个模式的 Gaussian 打印位移向量 q 先重新归一化为单位长度（‖q‖ = 1，单位 Å），再参与计算。全程只用这一种约定，并在文档里写明。
  - M3 **逐坐标投影与符号**：
    - 对每个声明的反应内坐标 k，算 δc_k = B_k · q（B_k 是该内坐标对笛卡尔坐标的导数行，即 Wilson B 矩阵的一行）；
    - 距离坐标的期望符号 s_k：断裂键（breaking）为 +1，形成键（forming）为 −1；角度坐标可以声明 increasing（+1）、decreasing（−1）或 report（只报告，不参与符号判断）；
    - 模式向量的整体符号是任意的，因此对 σ ∈ {+1, −1} 分别计算吻合数 Σ_k [σ s_k δc_k > 0]，取吻合数多的那个 σ；吻合数相同时取 σ·Σ s_k δc_k 为正的那个；
    - |δc_k| < 1e-3 Å 的记为“≈0，符号不定”，既不算吻合也不算不吻合。**1e-3 Å 只是数值上判断“是否为零”的容差，不是科学判据。**
  - M4 **重叠度（排序用）**：d = Σ_k s_k ∇c_k（只用有期望符号的坐标；∇c_k 就是 B_k 这一行），重叠度 O = |q · d| / ‖d‖（q 已是单位向量）。只用于排序和报告，**不设阈值**。
  - M5 **哪些模式**：频率结果中**全部虚频模式**都要分析；另附最低的 3 个实频模式作参考（不参与标记）。最匹配的模式 = 吻合数最多、其次重叠度最高的那个虚频模式。
  - M6 **标记**（只标记，不拒绝）：
    - `no_imaginary_mode`：没有虚频；
    - `multiple_imaginary_modes`：虚频多于一个；
    - `most_negative_not_best`：最负的虚频模式不是最匹配的那个（可能是无关扭转）；
    - `sign_inconsistent`：最匹配的模式也没能让全部有期望符号的坐标吻合；
    - `non_stationary_frequencies`：频率结果来自非驻点几何（例如初猜几何上的 Freq），仅作诊断参考。
  - M7 **排序**：保留 T137 的三组（拒绝 / 有标记 / 无标记）；组内依次按：存在符号完全吻合的虚频模式在前 → 最匹配模式的重叠度从高到低 → T137 的标记数从少到多 → 登记顺序。没有模式数据的候选排在同组有模式数据的候选之后。顺序只是建议。
  - M8 **反应坐标的声明**：写在 T137 的同一个窗口 JSON 文件里，新增顶层键 `reaction_coordinates`，按通道分组：
    ```
    "reaction_coordinates": {
      "<通道ID>": [
        {"kind": "distance", "atoms": [i, j], "role": "breaking" | "forming", "label": "..."},
        {"kind": "angle", "atoms": [i, j, k], "role": "increasing" | "decreasing" | "report", "label": "..."}
      ]
    }
    ```
    T137 只读 `channels` 和 `all`，其他顶层键忽略（已与 T137 协调）。
- **资料：** 规格 T-E；审计拆单建议中 T-E 的说明（`mode_review.displace` 已有逐距离的有符号导数，可作对照）；`ag/src/ag/mode_review.py`（`frequency_section` 104、`read_modes` 125、`displace` 32）；`ag/src/ag/geometry.py`（`kabsch`）；T137 工单（报告结构、窗口文件、排序）。
- **新增检查防的事故：** 只看最负虚频，而它其实是无关扭转；把共享原子上的位移按原子相加，导致质子转移这类反应的贡献互相抵消，判断失真（复审指出的原方案错误）；没有虚频或虚频方向不对的候选，没有被排到后面。

## 允许改动的路径

- **新建** `ag/src/ag/g0_modes.py`：B 矩阵行（距离、角度）、逐坐标投影、σ 选择、重叠度、模式汇总、标记。
- `ag/src/ag/g0.py`（T137 新建）：**T137 合并后**才改：加 `--modes-attempt`、并入报告和排序（第 6 节）。
- `ag/src/ag/mode_review.py`：只在需要把 `frequency_section` / `read_modes` 暴露为可复用函数时做不改行为的最小调整；现有测试保证行为不变。
- 测试：新建 `ag/tests/test_g0_modes.py`；T137 合并后补 `ag/tests/test_g0.py` 中的集成用例。合成的 Gaussian 频率 log 夹具放 `ag/tests/fixtures/`，格式参照现有的 `fluoride_freq_synthetic.log`。
- 文档：`docs/g0.md`（T137 新建）加“模式投影”一节；`README.md` 的 G0 一节；本单 `docs/redesign-tasks/T138-g0-modes.md`、`docs/redesign-tasks/open-tasks.txt`。
- **不改** prepare、submit、模板、`_parse_outputs.py` 的解析逻辑、facts、catalog 契约、前端、卡片（口径在 T139）、`CHANGELOG.md`、版本号。

## 要做的

### 1. 核心接口（`g0_modes.py`，与 T137 无关，可先做）

```
analyze_modes(elements, coordinates, frequencies, displacements, coordinates_spec) -> dict
```

- `coordinates_spec` 为第 M8 节的条目列表（单个通道）；原子编号从 1 开始，必须在范围内、互不相同，不合法时报错。
- 距离坐标的 B 行：∂r/∂x_i = (x_i − x_j)/r，∂r/∂x_j = −(x_i − x_j)/r，其余原子为 0。
- 角度坐标的 B 行：采用标准 Wilson 公式（i–j–k，j 为顶点）；角度接近 0° 或 180° 时（|sin θ| < 1e-6）报错“角度坐标退化”，不给数值。角度变化量以弧度为单位，报告时另换算成度。
- 返回：
  - `convention`（固定说明：笛卡尔、未质量加权、q 归一为单位长度、单位 Å 或弧度、δc = B q）；
  - `modes[]`：每个虚频模式和最低 3 个实频模式各一项，含 `index`、`frequency_cm1`、`imaginary`、`delta[]`（每个坐标的 δc、期望符号、σ 校正后的符号、是否吻合、是否 ≈0）、`sigma`、`consistent_count`、`signed_count`、`overlap`；
  - `best_mode`（虚频中最匹配者的 index，没有虚频时为 null）；
  - `flags[]`（M6）；
  - `notes[]`（固定说明：结果是诊断，不是 TS 验收；方向判断仍需人审）。

### 2. 读取频率结果

- `read_frequency_attempt(study, attempt_id)`：Attempt 必须是本 study 的精确 ID、已取回、facts 可读；用 `frequency_section` 和 `read_modes` 取出 elements、coords、frequencies、displacements、orientation。全部几何和模式都用 `read_modes` 返回的那一套（同一取向），**不做任何旋转或对齐**。
- 判断是否驻点：facts 中该频率段之前有收敛的优化（Opt 收敛）就视为驻点结果；否则标记 `non_stationary_frequencies`。判断不出来的记“未知”，不当作驻点。

### 3. 与候选的对应

- 候选的元素序列必须与频率结果的元素序列一致，否则报错（原子编号无法对应）。
- 报告候选存档几何与频率几何的对齐 RMSD（用 `geometry.kabsch`，只做正规旋转），**仅作参考**：频率结果可以来自优化后的几何，RMSD 大不算错误。

### 4. 反应坐标

- 从窗口 JSON 的 `reaction_coordinates` 中取候选目标通道的条目；候选没有目标通道、或该通道没有条目时，记“未声明反应坐标”，不做投影（不是错误）。
- 也接受 `--reaction-coordinate kind:atoms:role`（例如 `distance:3-7:forming`）临时补充，可重复。

### 5. 报告与标记

- 文本输出：模式表（频率、各坐标 δc、吻合情况、重叠度），最匹配模式加粗或标星；标记列表；固定说明。
- `--json` 输出 `analyze_modes` 的完整结构，以及频率 Attempt、几何哈希、对齐 RMSD、使用的坐标声明和来源（文件哈希或命令行）。

### 6. 并入 `ag g0`（T137 合并后 rebase 再做）

- `ag g0 ... --modes-attempt <ID>`（单个候选）；批量时，对每个候选取它最新的 candidate-result 中关联的 Attempt：若该 Attempt 已取回且含 Freq 段，就用它，否则记“无模式数据”。
- 候选报告新增 `modes` 一节；M6 的标记并入 T137 的 `flags`（类别前缀 `mode:`）；T137 的结论规则不变：模式标记只会让候选进入“有标记”组，**不会导致 rejected**。
- 排序按 M7 扩展 T137 的排序键；`--record` 写入的 diagnosis 包含 `modes` 一节（仍受 64 KiB 限制，超出时先截掉实频参考模式，再截断坐标细节，保留每个虚频模式的吻合数和重叠度）。

## 不允许

- 不计算任何 Hessian（xTB、Gaussian 都不跑），不新增模板或远程操作。
- 不设任何阈值或自动拒绝；规划时提到的 0.5 模式重叠阈值**不进入本单**。
- 除了归一化为单位长度，不对模式向量做任何变换：不做质量加权，不旋转、不对齐。
- 不按原子把各坐标的位移相加来判断方向（那正是复审指出的错误做法）。
- 夹具和 PR 里不出现真实研究对象、结构、study 名、Attempt 编号。

## 测试

| 场景 | 预期 |
|---|---|
| **共享原子质子转移夹具**（合成 O1–H···O2，模式主要是 H 从 O1 移向 O2；声明 O1–H breaking、H–O2 forming） | 两个坐标都吻合（δc 分别为正、负），重叠度明显大于 0；并附一个对照断言：若把两根键的原子位移按原方案相加，H 上的贡献会抵消——证明本实现没有抵消 |
| 同一模式向量取反（−q） | 选出的 σ 相反，吻合数、重叠度完全相同 |
| 两个虚频：最负的是甲基扭转，第二个是反应模式 | best_mode 为第二个；标记 most_negative_not_best 和 multiple_imaginary_modes |
| 没有虚频 | 标记 no_imaginary_mode；最低 3 个实频照常列出 |
| 某个坐标 |δc| < 1e-3 | 记为“≈0，符号不定”，不计入吻合或不吻合 |
| 角度坐标 increasing / decreasing / report | 前两种参与符号判断，report 只报告 |
| 角度接近 180° | 报错“角度坐标退化” |
| 坐标原子编号越界、重复、kind 与原子数不符 | 报错 |
| 频率结果来自非驻点几何 | 标记 non_stationary_frequencies |
| 频率 Attempt 未取回、没有 Freq 段、取向无法确认 | 报错（沿用 `read_modes` 的错误） |
| 候选与频率结果元素序列不同 | 报错 |
| 候选几何与频率几何不同（优化后的） | 正常分析，报告对齐 RMSD |
| 没有声明反应坐标 | 记“未声明反应坐标”，不做投影 |
| （T137 合并后）`ag g0 --modes-attempt`、批量、排序、`--record` | 模式标记只进“有标记”组、不导致 rejected；排序按 M7；diagnosis 含 modes 且不超过 64 KiB |
| `mode_review` 现有全部测试 | 不变 |

推送前本地跑一次全量 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，之后以 CI 为准；运行 `python scripts/scan_public.py`（带本机词表）和 `git diff --cached --check`。

## 真实环境验证

- 不需要远程验证。合并前在开发机上，对一个**非研究**、已取回、含 Freq 的 Gaussian Attempt（例如仓库夹具同款的小分子 TS 示例；没有就用合成夹具）跑一次，确认读取、分析和报告正常。不碰研究 study。

## 停止条件

- `read_modes` 无法复用、需要另写频率解析。
- 需要计算 Hessian 或新增模板。
- T137 的报告或排序接口不够用：停下，由监督方协调，不要在本单另写一份。
- 同一问题修两次仍未解决。

## 合并前审阅与交付

- 需要监督方审阅：**是，逐行审**（B 矩阵公式、σ 选择、重叠度、标记规则、与 T137 的并入）。合并只由负责人操作，**排在 T137 之后**。
- PR 描述包括：M1–M8 对应的改动、约定说明全文、测试表逐项结果（特别是共享原子质子转移夹具的数值）、真实验证记录。

## 版本记录

- v1（2026-10-26，监督方）：负责人授权“按推荐”，监督方依据规格 T-E 与审计拟定 M1–M8；对应审计拆单建议中 T-E 的“模式诊断”部分。xTB Hessian 记入后续工作。

## 执行记录（核心阶段，尚未完成整单）

- 基线 main `26391ed`（T136 #337 已合并），分支 `codex/t138-g0-modes`。
- 负责人于 2026-10-26 在本任务对话确认：“角度采用 1e-3 rad（建议）”。距离仍为 1e-3 Å；两者只作各自单位下的数值零容差。
- 本阶段只新增 `g0_modes.py`、合成测试与本工单记录；`frequency_section` / `read_modes` 原样复用。
- 约定全文：笛卡尔、未质量加权；Gaussian 打印位移 q 重新归一为单位长度（‖q‖ = 1 Å）；δc = B q；距离变化用 Å，角度变化用弧度并另报度。不旋转、不对齐模式向量。
- `index` 是输入频率列表中的原始 1-based 编号；列表按频率排序展示全部虚频及最低三个非负频率模式。吻合数和有符号总和均相等时保留 σ=+1；最匹配模式的吻合数、重叠度均相等时保留频率更低者，再按原始顺序。
- `delta.value` 为原始 Bq，`corrected_value` / `corrected_sign` 为 σ 校正值/符号。≈0 的 `matches` 和 `corrected_sign` 均为 null，既不算吻合也不算不吻合；`signed_count` 保留全部声明了期望符号的坐标数。`report` 坐标不参与 σ 或重叠度。
- 重叠度严格按有符号 B 行之和计算；d 为零时报告 0 并说明无合成方向，不引入阈值。混合距离/角度时直接使用 Å/rad 的原生数值，不额外缩放坐标或加权。
- 驻点只由 facts 中来源可对应的收敛 Opt 建立；后来的 Opt、旧 facts 缺来源、来源与所读频率段不符均为未知。单段 Opt Freq 另确认收敛标记在谐振块之前。未知也加 `non_stationary_frequencies`，报告明确写未知。
- 频率几何哈希针对同一取向的元素及坐标紧凑 JSON（键顺序 elements、coordinates；UTF-8、无空格）；日志与频率段另保留原始字节 SHA-256。候选比较只对几何做正规旋转 RMSD，不动位移向量，不重排原子。
- 合成共享氢夹具：δ(O1–H)=+1 Å、δ(H–O2)=−1 Å，吻合 2/2，O=2/√6=0.8164965809；反号模式选择 σ=−1，校正后数值不变。对照的无符号逐原子相加在 H 上为零。
- 当前阻塞（环境/集成依赖）：T137 尚未合并。按本单开工条件，不提前改 `g0.py`，不另写 G0 报告或排序。第 6 节的 CLI、批量、排序、64 KiB diagnosis，以及 `docs/g0.md` / README 接入说明和完整 CLI 验证，留待 T137 合并后 rebase 完成；本阶段 PR 保持 draft。
- 2026-10-26 验证：相关测试 `test_g0_modes.py` + `test_mode_review.py` 共 124 passed；最终全量 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs` 为 5297 passed、19 skipped（271.45 s，Python 3.11.15）。跳过 18 项 Linux 方言检查和 1 项未启用的私有日志测试；Linux 检查交由 CI。
- 本地合成验证：临时非研究 study 中使用新增夹具建立合成 fetched Attempt，经过真实 cclib 读取、候选分析与 JSON 序列化，best_mode=2，数值与上表一致，原 Attempt 全部文件字节保持不变。没有远程验证；完整 G0 CLI 验证仍待接入。
- 含本机词表的暂存区扫描（5 文件）、全仓库扫描（1819 文件）、PR 正文扫描均为 0 errors；`git diff --cached --check` 通过。T137 依赖 PR 为 #338，当前未合并。
