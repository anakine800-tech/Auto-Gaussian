---
name: auto-g16-structures
description: Read ChemDraw or SMILES structures, review identity and stereochemistry, run local RDKit force-field prescreening, and prepare Cartesian Gaussian inputs within a study.
---

# Structure preparation

Use when a new structure enters a study, local force-field prescreening is needed,
or a reviewed single-frame XYZ needs conversion to Gaussian input. Run the
scripts with `conda run -n chem python`; they use sibling modules and need no
runtime configuration or installed legacy Skill. RDKit with ChemDraw CDX support
is required for CDX/CDXML inputs.

Read `study.md` and `references/chemistry-boundaries.md`. Multiplicity must come
from the researcher or `study.md`, never be inferred from a structure. This first
version handles connected, closed-shell main-group organic molecules. Stop and
ask the researcher about radicals, metals, coordination systems, disconnected
complexes, or unclear protonation/tautomer/stereochemistry. Unassigned tetrahedral
centers and conflicting/unsupported ChemDraw CFG stop the scripts. Do not remove
stereo annotations or change the source drawing to make an error disappear.

## Workflow

1. Read the source directly with `scripts/prepare_preview.py SOURCE --study STUDY
   --name structure-review --multiplicity MULT`. ChemDraw, MOL, SDF and SMILES
   are accepted. `inspect_chemdraw.py` offers the same study/name/multiplicity
   options for ChemDraw-specific review artifacts.
2. Present `summary.json` and `preview.png`: canonical isomeric SMILES, formula,
   source atom count, explicit-H atom count, charge, supplied multiplicity, CIP
   centers, import diagnostics and warnings. Atom indices are zero-based. Source
   atom count may differ from the Cartesian count because implicit H are expanded.
   If MOL/SDF roundtrip loses stereo, retain the original source or `stereo.smi`.
3. **Ask the researcher to confirm the structure (milestone 1).** Record their
   confirmation in `study.md` before screening. A successful script is not a
   human signature. Do not invent a signature from a test run.
4. Follow `references/conformer-workflow.md`: TS families, key intermediates and
   complexes require two sampling routes; flexible molecules are also recommended.
   Use CREST + ETKDG for supported minima, CREST + hypothesis-directed constrained
   CREST for TS/complexes. Construct and review the proposed interaction/attack
   direction before constrained CREST and label that route `directed`; do not feed
   disconnected complexes/TS into the connected-only force-field script. The
   coverage report cannot prove completeness. For supported minima run
   `scripts/prepare_conformers.py generate SOURCE --study STUDY --name ff-screen
   --multiplicity MULT`. Inspect warnings and force-field convergence. Keep the
   original source for ChemDraw so explicit-H wedge information survives.
5. Hand `structures/ff-screen/conformers.xyz` and `summary.json` to `ag dedup`
   (consult `ag dedup --help` for its installed interface). XYZ comment lines
   begin with absolute force-field energy followed by the force field and
   `kcal/mol`; these are **not Hartree, DFT energies or Gibbs energies**. Keep
   this unit explicit when using dedup/cluster. Review the representative set
   with the study Skill before DFT work.
6. To draft a Gaussian input from one reviewed XYZ frame, use:

   ```sh
   conda run -n chem python scripts/make_gaussian_input.py FRAME.xyz \
     --study STUDY --name opt-input --route 'METHOD/BASIS opt freq' \
     --charge CHARGE --multiplicity MULT --nprocshared CORES \
     --mem MEMORY --chk structure.chk
   ```

   Supply the literature-based route or explicitly declared fallback, reviewed
   charge and multiplicity, and resource values appropriate for `ag prepare`.
   XYZ has no bonds: verify its atom order and identity against the confirmed
   structure; the converter cannot determine radicals or stereochemistry from
   XYZ. Multiple frames are rejected to prevent silently choosing one conformer.
   The helper also retains direct structure-to-3D conversion for reviewed source
   inputs. Audit the GJF with `scripts/audit_cartesian_input.py INPUT.gjf`, then
   pass the GJF to `ag prepare`. No script submits or starts Gaussian.

Every writer uses a fresh `STUDY/structures/NAME/` directory and refuses an
existing name, including a partially written run. Choose a new descriptive name
for a rerun. Read-only `audit_cartesian_input.py` needs no `--study` option.

Optional GaussView inspection can still use the frozen
`skills/auto-g16-view-rt-win/scripts/windows_gaussview.py` and
`gaussview_load_probe.ps1` manually when requested. They are not imported or
invoked by this Skill. `runtime_config.py` is omitted: no retained operation
needs its machine paths or remote settings.

## 开题物种核验

开题按 study Skill 的 [0a–0d](../auto-g16-study/SKILL.md#每次调用的固定流程)
推进。`check_species.py` 只核验起始物、产物、催化剂、试剂及需配平的副产物、
添加剂；中间体留给后续流程。图片仅供对照，不从图片直接生成坐标。

在私有 study 写 UTF-8 的 `analyses/intake/species.csv`，每个物种一行：

```csv
species_id,role,source_file,second_source,expected_formula,expected_charge,multiplicity,expected_cip,stereo_basis,note
butane,reactant,structures/butane.smi,smiles:CCCC,C4H10,0,1,none,无四面体中心,第二来源的出处另记
```

必填列为 `species_id,role,source_file,expected_formula,expected_charge,multiplicity`。
role 仅为 `reactant/product/catalyst/reagent/byproduct/additive`；物种 ID 与开题模板一致，
使用字母、数字、下划线、连字符，最长 80 字符。源文件接受 `.cdxml/.cdx/.mol/.sdf/.smi`，
所有文件路径相对于 study 根目录，拒绝符号链接、绝对路径和 `..`。
第二来源为 study 内文件或 `smiles:` 文本；记录真实出处，两个派生文件一致不证明来源独立。
预期分子式由人从原件读取，使用 Hill 顺序，电荷另列；多重度只接受研究者提供的值。
缺失预期值或多重度保留未知，不猜测；可选 `stereo_basis` 和 `note` 保留依据及人工备注。

`expected_cip` 使用 `2:R;4:S`；`none` 表示预期无四面体立体中心，空表示未给。
编号是源文件读入顺序**从 1 开始**的原子序号，不是规范 SMILES 顺序、ChemDraw 对象 ID
或旧 preview 的零基编号。新脚本保留 SMILES 中独立的 `[H]` 原子；`[C@H]` 的 H 计数
不单独占序号。MOL/SDF 原子块、ChemDraw 直接读入顺序均保留，在新预览图逐原子标号。
不按不同来源的原子序号或 CIP 标签排列顺序比较身份。

```sh
conda run -n chem python scripts/check_species.py --study STUDY
# 可显式指定输入；重复核验必须换输出目录，旧报告保留：
conda run -n chem python scripts/check_species.py --study STUDY \
  --species analyses/intake/species.csv --reaction analyses/intake/reaction.csv \
  --output-dir analyses/intake-v2
```

默认读取 `analyses/intake/species.csv`；存在默认 `reaction.csv` 时自动核对，
或用 `--reaction` 指定。反应表列为 `species_id,side,coefficient`，side 为 `left/right`，
系数为正整数、小数或分数，两侧均须列出。按实际结构（含隐式氢）
精确计算元素和电荷，差额定义为右减左；只报告缺失副产物等可能性，不自动补组分。

输出为 `analyses/intake/species-check.json`、`.md` 及 `<species_id>/preview.png`；
已有任何目标文件或物种目录即拒绝，部分失败输出也保留并要求换名。
报告列出源原子数、源中显式 H 原子数、补氢后总原子数、电荷、组分、CIP/未指定中心、
读入诊断、所有输入文件的 study 相对路径及 SHA-256。补氢只在内存中计数，不生成 3D。
第二来源比较仅在副本上统一普通显式/隐式氢表示并忽略原子映射标签，保留同位素与立体；
报告构造、电荷、立体差异，构造/质子化不同时立体对照记未知，不强造原子对应。

各项为 `match/mismatch/unknown`，物种为 `all_match/has_mismatch/incomplete/out_of_scope`。
未提供第二来源或预期 CIP 会得到 `unknown`，汇总为 `incomplete`；不可静默当作通过。
超出既有 `validate_scope` 或非单重态的物种记 `out_of_scope`，继续核验其余物种；
不可读结构记 `incomplete` 并输出占位预览。轴手性等局限仍须人工审阅。
命令退出 0 只表示报告成功写出，不能解释为各项匹配或结构签字。

展示报告和预览后，由人解决或明确接受未决项并写理由；`out_of_scope` 仍暂停依赖计算，
不能用接受备注扩展计算能力。沿用既有结构里程碑和证据清单，确认前不开始文献检索或采样。
脚本不签字、不修改结构源、不修改 `study.md`；原有预览/构象脚本保持原行为与输出位置。

## 定向复合物构建

[scripts/build_complex.py](scripts/build_complex.py) 是 T86 的纯本地例外入口：
两份已审阅三维 XYZ，各自须按 `<1.2 × 共价半径和` 规则为单个连通分子，
仅构造主族的一个 A–D 配位接触；拒绝过渡金属、镧系和锕系，不做多配位点或自动对接。
不调用普通单分子力场脚本，不推断电荷、多重度、位点选择或 CIP 优先级。
需要当前 ag、NumPy 和 RDKit；从仓库根运行时可用 `PYTHONPATH=ag/src`，
已安装 ag 的 chem 环境也可运行。XYZ 的三个笛卡尔分量须有限，平面分子允许；
XYZ 本身不能证明化学身份、质子化或电子态，须先按 T80 核验和人工确认。

三个子命令（路径相对于 `--study`，只读命令省略该选项时以当前目录为根）：

```sh
python skills-next/auto-g16-structures/scripts/build_complex.py sites \
  --study STUDY --guest structures/guest.xyz
python skills-next/auto-g16-structures/scripts/build_complex.py measure \
  --study STUDY --complex structures/reviewed-complex.xyz --host-range 4-7 \
  --host-atoms 3,2,1 --guest-atoms 3,2,1
python skills-next/auto-g16-structures/scripts/build_complex.py build \
  --study STUDY --name directed-01 \
  --host structures/host.xyz --host-charge Q_HOST --host-atoms P2,P1,A \
  --guest structures/guest.xyz --guest-charge Q_GUEST --guest-atoms D,X,Y \
  --r R --theta1 THETA1 --theta2 THETA2 --phi1 PHI1 --phi2 PHI2 --phi3 PHI3 \
  --multiplicity MULT --force-constant FORCE_CONSTANT
```

`sites` 只列出 O/N/S/P/卤素等候选、相连原子、几何杂化提示和 D–X–Y / syn–anti
可用参照，供人勾选；几何提示不是键级或真实孤对方向判定。参照候选为空时须换一组
符合条件的显式原子，工具不补原子或自动选择。`measure` 的 host-range 是整体 XYZ
中连续的主体段，客体为其余原子且保留原顺序；两组三原子编号始终是**各自组分内**
从 1 开始，输出 JSON 的 `build_parameters` 可直接粘入 build 命令。

六参数及参照原子全部由人指定并写进 study：r = A–D（Å），theta1 = P1–A–D，
theta2 = A–D–X，phi1 = P2–P1–A–D，phi2 = P1–A–D–X，phi3 = A–D–X–Y（角度为度）。
D–X、X–Y 须相连；参照平面共线或近共线（归一化垂直分量 < 1e-6）报出对应原子组。
主体坐标不动，客体仅旋转加平移；重测参数偏差 < 1e-6 Å/度（扭角按周期差），
客体全部内部原子间距偏差 < 1e-8 Å，并保留可复现的双精度输出。

可加 `--face Re|Si --face-center C --face-priority a,b,c`：三个相连原子按**人给的**
CIP 优先级排序，从 A 看 a→b→c 顺时针为 Re。只校验，不据标签摆放或自行推断 CIP；
需核对三角形环绕中心、中心距平面 ≤ 0.1 Å（防止给四面体/锥形中心误标进攻面），
A 距平面 < 0.3 Å 拒绝；期望与实测不一致也拒绝。`--syn-anti-ref REF` 须与 X 相连
且不同于 D/X，按二面角 A–D–X–REF 的绝对值 < 90° 标 syn，否则 anti。
报告生成如 `O7-syn(C9)-Re` 的组分内编号标签，并列出各部分依据。

除声明 A–D 外，全部主体–客体原子对按共价半径比 < 1.2 拒绝（含 topology
视为不确定的极短接触）；可加正数 `--vdw-factor F`，再拒绝 vdW 半径比 < F 的接触。
全部违规对及最近 10 个接触均列出；发现重叠不自动转动、修几何或枚举。
力常数必须显式给出且为正数，无默认值；单位/约束势说明沿用
[CREST 约束构象搜索](../auto-g16-recipes/cards/crest-screen.md#约束构象搜索)。
草稿含 A–D 距离；加 `--constrain-angle` 才含 A–D–X 角，编号转换成复合物编号。
写出后直接调用 `ag.crest_input.validate`，通过才成功。

输出到新的 `analyses/complex-build/NAME/`：`complex.xyz`、`constraints.inp`、
`atoms.csv`、`build.json`、`build.md`；主体原子在前，客体在后。报告含输入相对路径与
SHA-256、全部参数及实测、标签依据、接触检查、各组分与总电荷及多重度。
重叠/标签拒绝时退出 2，仅保留 `build.json` 和 `build.md`，不发布结构或约束文件；
输入/几何错误直接退出 2。已有目录（含拒绝或部分失败）、符号链接和越界路径均拒绝。
产出默认作为人工审阅后**约束 CREST** 的起点，也可按已签方案直接准备 DFT 优化；
它不证明稳定复合物或 TS，不修改 study、不签字，也不提交计算。

## Migration and validation

Source files are credited in each script header; applicable chemistry notes
were adapted in `references/`. The CDX loader and Cartesian auditor retain their
chemical behavior. Conformer embedding, minimization, energy ranking and RMSD
filtering retain the original algorithm; output is now a multi-frame XYZ and
summary instead of individual GJF drafts and selection artifacts.

Run `conda run -n chem python -m pytest skills-next/auto-g16-structures/tests` from
the repository root. CDX tests skip only when RDKit lacks CDX support; they must
pass locally. Fixtures are synthetic butane and explicit-H chiral 2-butanol;
the previously suggested reaction-scheme fixture contains no molecular graph.
