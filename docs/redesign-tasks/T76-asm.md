# T76：`ag asm` 畸变能与相互作用能汇总

工单修订 v2（负责人 2026-10-16 确认）：保持原改动范围，不修改 `_review_manifest.py`。
证据清单直接收录 asm 的 JSON、Markdown 和照常收录的 facts；Attempt 几何通过
`ag-asm/1` 报告中的相对路径和 SHA-256 间接绑定，具体测试口径见下文。

## 分支与目标

- 分支：`codex/t76-asm`；基于最新 main，一张任务单一个 PR。**开发机做。**
- **开工条件：** v4.2.1（T67）已合并；**T73 合并后开工**（同时最多三条开发线，T73 工作量最小、最先结束）。
- **目标：** 新增本地命令 `ag asm`，做畸变–相互作用分析（活化应变模型）：
  1. `ag asm split`：按人工给出的原子列表，从一个 Attempt 的几何中切出片段 XYZ（记录原始原子编号），供负责人照常准备片段单点；
  2. `ag asm summary`：读取复合物单点、各片段单点（以及可选的片段弛豫参照）的 facts，核对口径一致后，计算相互作用能、各片段畸变能，并对两个竞争过渡态做差。
- **为什么：** 解释选择性来源的常用分析——两个竞争 TS 的能量差，有多少来自片段被扭曲（畸变），多少来自片段之间的相互作用。`ag fragments` 只能按距离规则拆分，不能指定化学片段，也不汇总能量。
- **原则：** 只汇总已有计算，不判断哪一项“决定”了选择性；片段由人指定，不推断片段电荷。
- 资料：`ag/src/ag/fragments.py`（XYZ 导出与 `original_atoms` 注释、独占写出）、`ag/src/ag/_profile_sources.py`（`protocol()` 方法口径解析、程序版本一致性检查）、`ag/src/ag/channel_coverage.py`（定义文件 + 输出带 SHA-256 的写法）、`docs/ag-channel-coverage-1.md`。

## 允许改动的路径

- 新增 `ag/src/ag/asm.py`。
- `ag/src/ag/cli.py`：只在分析命令元组里登记 `'asm'`。
- `ag/tests/test_smoke.py`：**已预先批准**，只在固定的分析命令列表断言里追加 `ag.asm`。
- 新增 `ag/tests/test_asm.py` 和合成夹具。
- 新增 `docs/ag-asm-1.md`：定义文件和输出格式。
- `ag/README.md`：分析命令一节加用法。
- `skills-next/auto-g16-recipes/cards/profile.md`：末尾追加一小节“畸变–相互作用分析”。
- `docs/redesign-tasks/T76-asm.md`：本任务单。
- 从 `_profile_sources`、`fragments`、`study` 等 **import 复用**，不复制实现、不修改这些文件。必须修改时停下询问。

## 要做的

### 1. `ag asm split`

```
ag asm split <Attempt> --geometry {input,final} --atoms 1-40,52 --name <片段名>
             --out <analyses/ 下新的 .xyz> [--study <study>]
```

- `--geometry input` 取 Attempt 的输入几何（单点用），`final` 取 `final_input.xyz`（优化/TS 用）；必须显式给出。
- 原子编号从 1 开始，支持范围和逗号；越界、重复报错。按给出的原子编号**升序**写出。
- XYZ 第二行注释：来源 Attempt、几何类别、片段名、`original_atoms=…`。输出已存在就拒绝；写法与 `ag fragments` 一样防符号链接、独占创建。
- 不给片段电荷和多重度（由人在准备单点时指定）。

### 2. 定义文件（放在 `analyses/` 下，JSON）

```json
{
  "schema": "ag-asm-definition/1",
  "systems": [
    {"label": "TS-A", "complex_attempt": "<Attempt>", "complex_geometry": "input",
     "fragments": [
       {"name": "nucleophile", "atoms": "1-40,52", "charge": 0, "multiplicity": 1,
        "attempt": "<片段单点 Attempt>", "reference_attempt": "<可选：片段弛豫后的同级别能量>"},
       {"name": "electrophile", "atoms": "41-51,53-84", "charge": 1, "multiplicity": 1,
        "attempt": "<Attempt>"}]}],
  "comparisons": [{"a": "TS-A", "b": "TS-B"}]
}
```

### 3. `ag asm summary`

```
ag asm summary --definition <analyses/ 下的定义文件> --out <analyses/ 下新的 .json> [--study <study>]
```

同时输出同名 `.md`；两者已存在就拒绝。

**核对（任一不满足就报错，指明 system / fragment）：**
- 每个 system 的片段原子列表互不重叠、正好覆盖复合物全部原子；片段电荷之和等于复合物电荷；复合物和片段都是单重态（开壳层本单不支持，直接报错）。
- 片段单点 Attempt 的输入几何，与复合物几何（`complex_geometry` 指定 input 或 final）按 `original_atoms` 取出的子集逐原子一致：元素相同，坐标偏差 ≤ 1×10⁻⁴ Å。
- 所有用到的能量：Gaussian 正常结束、有电子能（与 `ag profile` 读取的电子能字段相同）；`complex_geometry` 为 final 时用该 Attempt 最终几何对应的电子能。
- 复合物、片段、参照的方法口径一致：用 `_profile_sources.protocol()` 解析，方法、基组、色散、溶剂模型全部相同；程序版本相同。
- `reference_attempt`（可选）：元素组成、电荷、多重度与片段相同（原子顺序可以不同）；方法口径同上。
- 每个 comparison 的两个 system：片段名集合相同，同名片段的元素组成、电荷、多重度相同。

**计算（Hartree 原值保留，另给 kcal/mol，换算系数写进输出）：**
- 每个 system：`E_int = E_complex − Σ E_frag@complex`；有参照的片段给 `E_dist = E_frag@complex − E_frag,ref`；全部片段都有参照时给 `E_dist_total` 和 `ΔE = E_dist_total + E_int`。
- 每个 comparison（b − a）：`ΔΔE_complex`、`ΔΔE_int`、每个片段的 `ΔΔE_dist`（直接用两个 system 中该片段在复合物几何下的能量相减，**不需要参照**）；核对 `ΔΔE_complex = ΔΔE_int + Σ ΔΔE_dist`（数值误差 < 1×10⁻⁸ Hartree）。

**输出（`schema: "ag-asm/1"`，写进 `docs/ag-asm-1.md`）：** 定义文件和所有用到的 Attempt facts、几何文件用键名 `path` 记录并附 SHA-256；证据清单收录 asm 的 JSON 和 Markdown，facts 照常直接收录，Attempt 几何由报告中的路径和 SHA-256 间接绑定。固定附注：“电子能，不含零点能和热校正；未做基组重叠误差校正；溶剂模型与复合物一致；只描述能量分解，不判断选择性来源。” Markdown 给每个 system 一张表、每个 comparison 一张表。

## 不允许

- 不推断片段划分、电荷或多重度；不自动准备或提交片段计算。
- 不用自由能或热校正值；不做基组重叠误差校正。
- 不读 study 外的文件；拒绝符号链接（复用 `study.local_path`）。

## 测试

- 合成 study：两个 system（同样两片段，不同几何）各有复合物和片段单点的 facts；`E_int`、`ΔΔE_int`、`ΔΔE_dist` 与手算一致；加和核对通过。
- 有 / 无参照、部分片段有参照时的输出。
- `split`：编号范围解析、越界、重复、注释里的 `original_atoms`、输出已存在、符号链接。
- 各类核对失败：原子覆盖不全或重叠、电荷之和不对、片段几何与复合物不一致（超过 1×10⁻⁴ Å）、方法口径不同（例如基组或溶剂不同）、程序版本不同、未正常结束、开壳层、comparison 两边片段不一致。
- 输出没有绝对路径；证据清单能收录 asm 输出的 JSON 和 Markdown；报告中每个文件哈希均与实际文件一致，改动其中任一几何文件后，复算可发现不一致。
- 开发中只跑 asm 相关测试；推送前本地跑一次全量 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，之后以 CI 为准。敏感扫描与 `git diff --cached --check`。

## 真实环境验证

- 纯本地分析，不作为合并前条件。
- **建议（合并前后均可，开发机）：** 在非研究 study 中用一个很小的双片段体系（例如水二聚体，低理论级别）准备复合物和两个片段单点，由负责人确认提交；取回后跑 `split` → `summary`，核对口径检查和数值合理。结果写进 PR 评论。
- 研究 A 在有两个竞争 TS 之后（K6 以后）再实际使用，届时由研究 A 主会话写定义文件。

## 停止条件

- 需要修改 `_profile_sources.py`、`fragments.py`、`study.py` 或 facts 格式。
- 现有 facts 里取不到可靠的电子能或方法口径。

## 合并前审阅与交付

- 需要监督方审阅：是。
- PR 描述第一行：`Task: T76`。
- 合并只由负责人操作。

未来若需证据清单直接收录 Attempt 内的几何文件，另开工单，并要求复扫全部已签 study。

## 版本记录

- T116 脱敏：研究标识、编号与环境字面量改为泛称；原工单结构和结论不变。
