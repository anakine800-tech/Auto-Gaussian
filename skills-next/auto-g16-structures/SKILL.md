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
   source atom count, `source_explicit_h_atom_count` (drawn/source H atoms),
   `atom_count_with_h` (total after adding H), charge, supplied multiplicity, CIP
   centers, import diagnostics and warnings. Atom indices are zero-based. Source
   atom count may differ from the Cartesian count because implicit H are expanded.
   The legacy `explicit_h_atom_count` remains the total after adding H for
   compatibility; `deprecated_fields` directs new consumers to `atom_count_with_h`.
   Source H counting matches T80: standalone `[H]` counts, `[C@H]` H counts do not
   create separate source atoms. Other identity fields/artifacts retain their behavior.
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

单次构建的三个子命令（路径相对于 `--study`，只读命令省略该选项时以当前目录为根）：

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

### 人选位点的系统枚举

T90 的 `enumerate` 接收人勾选的一个或多个 `--site`，复用上述几何构建、
刚体、六参数重测、进攻面和 syn/anti 核对。r、theta1、theta2 固定；每个 phi
是固定度数或 `grid[:步长]`（默认 30°，从 −180° 起，严格小于 180°），至少一个
phi 为网格。不自动选位点，不随机抽样。位点顺序优先，然后 phi1、phi2、phi3
升序笛卡尔积（phi3 最快）。默认总组合上限 200，按位点数 × 网格组合数在
任何输出前检查，超限报告总数并要求缩小范围；可显式用 `--max-candidates` 调整。

```sh
python skills-next/auto-g16-structures/scripts/build_complex.py enumerate \
  --study STUDY --name directed-grid \
  --host structures/host.xyz --host-charge Q_HOST --host-atoms P2,P1,A \
  --guest structures/guest.xyz --guest-charge Q_GUEST --site D,X,Y \
  --r R --theta1 THETA1 --theta2 THETA2 --phi1 PHI1 --phi2 grid --phi3 PHI3 \
  --multiplicity MULT --force-constant FORCE_CONSTANT
```

位点可写 `--site 'D,X,Y:face=Re:center=C:priority=a,b,c:ref=REF'`，face/center/priority
须一起提供，ref 可独立提供，含义与 `build` 相同。重复 `--site` 枚举其他位点/面。
`--vdw-factor`、`--constrain-angle` 与单次构建相同。重叠、进攻面不符或标签核对
失败只剔除该组合并记录原因；不旋转修复、不静默删记录。

先按实际约束原子组合分组：A–D 相同，启用角度约束时 A–D–X 也相同的位点
归一组。只在组内对通过检查的候选作全部组分重原子、固定行序 Kabsch 对齐，
RMSD < `--dedup-rmsd`（默认 0.3 Å）保留先出现者。不交换对称原子、不作镜像，
也不含氢；氢朝向或局部差异仍须人工检查，此去重不作科学覆盖验收。

新目录 `analyses/complex-build/NAME/` 内保留所有组合的 `candidates.csv`，
含编号、组号、位点、六参数、最近接触、状态/是否保留、去重代表及剔除原因；
`atoms.csv` 保留源原子映射；`enumerate.json` / `.md` 记录输入哈希、网格、
约束分组及各组位点/约束原子、总组合/剔除原因/去重前后统计，以及逐候选核对细节。
每个非空组输出 `candidates-group-N.xyz` 与 `constraints-group-N.inp`；只有一组
时用 `candidates.xyz` 与 `constraints.inp`。XYZ 注释含编号、位点标签、六参数，
不伪造能量。逐组通过 `crest_input.xyz_ensemble` 和 `crest_input.validate`。
空组保留约束草稿和原因报告，不写 XYZ，JSON 的 candidates_file 为 null；
全部剔除时退出 2。已有目录仍拒绝，包括先前失败目录。

审阅每组候选及约束后，可将**同组** XYZ / INP 交给现有入口：

```text
ag prepare --study <study_id> --template crest --input <candidates-group-N.xyz> --constraints <constraints-group-N.inp> --param=--mdopt --param=--gfn2 --param=--chrg=<总电荷> --param=--uhf=0 --tier <档位> --walltime <时限> --label <组与来源> --card crest-screen --method-basis <已审阅依据>
```

一组时替换为无 group 后缀的文件。`--mdopt` 仅作该组候选的同方法优化，不等于
完整 CREST 搜索；按已签方案，可将审阅后的单帧逐一用于不带 `--mdopt` 的约束
CREST 多起点采样，每帧新 Attempt。方法/溶剂沿用 [crest-screen](../auto-g16-recipes/cards/crest-screen.md)，
不同组不混用约束，不因生成文件而提交或签字。

## TS 立体标签

在参照产物已按 T80 核验并由人签字后，用 `scripts/ts_stereo_label.py` 比较
TS 的局部手性，按**产物**的 CIP 标注构型。参照支持 `.cdxml/.mol/.sdf`，
每个四面体中心必须指定；催化剂参照及映射可选，须成对提供。结构身份、签字和
映射由研究者核对，脚本不从几何推断键级，也不把成功输出当作签字或 TS 验证。

```sh
python skills-next/auto-g16-structures/scripts/ts_stereo_label.py \
  --study STUDY --name stereo-01 --ts ts-a,ts-b \
  --product structures/product.mol --product-map analyses/product-atoms.csv \
  --catalyst structures/catalyst.mol --catalyst-map analyses/catalyst-atoms.csv \
  --channels analyses/channels.csv
```

除 `--study` 外，文件路径均相对于 study 根目录；Attempt 使用 `attempts/` 下的
目录名。默认 `--geometry final` 只读各 Attempt 的 `final_input.xyz`，缺失就报错，
不回退到其他几何。检查初猜时显式加 `--geometry input`：读取不可变 manifest 的
`science.geometry`；QST3 取 `science.structures[2].geometry`（第三组 TS 初猜），
QST2 没有 TS 初猜组，拒绝此选项。两种模式都不证明结构已优化或反应方向正确。

映射 CSV 列为 `reference_atom,ts_atom`，两者均从 **1** 开始，以读入源文件的原子
行序及 TS Cartesian 行序为准。保留源中显式 H；隐含 H（含没有独立原子行的 H
计数）用 `H@<参照中心序号>`。例如中心 2 的未画出氢映射到 TS 第 19 个原子：

```csv
reference_atom,ts_atom
2,7
1,3
3,8
4,9
H@2,19
```

只需覆盖每个中心及全部四个邻居，可以保留其他原子映射。映射须一一对应，
越界、缺邻居或元素不一致报错；同元素交换不能靠元素检查识别，必须人工核对。
XYZ 不含同位素信息，同位素身份同样依赖人工映射核验。参照限制沿用本 Skill 的
闭壳层主族单分子范围；TS 可含其他片段，只比较已映射邻居。

按参照 RDKit 的邻居顺序（隐含 H 最后），将中心至四个 TS 邻居的向量归一化为
`u1…u4`，计算 `v = det(u1−u4,u2−u4,u3−u4)/(16/(3√3))`，范围约 −1 到 1。
参照符号由同序手性标记确定：CCW 为正、CW 为负，因此二维 ChemDraw/MOL 图
不需要生成三维参照。依据：[RDKit 原子手性及邻居顺序](https://www.rdkit.org/docs/cppapi/classRDKit_1_1Atom.html)。
符号相同沿用参照 CIP，相反交换 R/S；阈值 `--min-chirality` 默认 0.05，须在
`(0,1]`；`|v|` 小于阈值记 `unknown`，重合坐标报错，不能猜构型。

参照 CIP 使用 [RDKit accurate CIP labeler](https://www.rdkit.org/docs/source/rdkit.Chem.rdCIPLabeler.html)。
假手性 r/s、相对/混合立体组记 `needs_review`；另在参照副本上移除其他立体信息，
若不能保留该中心的 CIP，也记 `needs_review`，避免其他中心翻转后优先级变化使
简单 R/S 交换失效。几何符号关系仍保留供审阅，不从 TS 重新计算 CIP。
催化剂的局部符号相反会醒目警告；未知或需审阅的中心不能算自检通过。

产物标签固定为 `元素+参照原子序号:构型`，按参照原子序号递增、以分号连接，
例如 `C12:R;C15:S`。通道表至少含唯一非空 `channel_id` 和非空 `product_branch`；
后者须与完整标签**逐字一致**（顺序相同、不加内部空格）。已有 `R`/`S` 等其他
写法会报告无匹配，不自行解释；同一标签对应多个通道会报告多重匹配。

输出独占写入 `analyses/ts-labels/NAME/labels.json` 和 `labels.md`：每个中心的
参照/TS 序号、邻居顺序、体积、关系、标签及原因，催化剂自检，以及所有输入的
相对路径和 SHA-256。提供通道表时另写 `channel-suggestions.csv`，字段为
`attempt,product_configuration,suggested_channel_id,status,note`；状态恒为
`pending_confirmation`。只有完整构型唯一匹配且催化剂无异常时才填建议通道，
无匹配、多重匹配或有 unknown/needs_review 时留空并说明。
人审核后另行维护通道归属；草稿不是 `ag channel-coverage` 的输入，不含 ensemble
清单，不修改通道表或 study.md，`ag channel-coverage` 仍不推断归属。

已有目录（包括部分失败输出）、符号链接、越界路径和输入在读取期间变化均拒绝。
研究 A 合并前对照由其主会话负责：将最小输入按原字节复制到 study 外的私有临时
study 布局（不用符号链接），用该临时目录作为 `--study`，使报告留在原 study 外；
与人工通道判断对照后只向监督方汇报，不把研究结构、结果或报告放进 PR。

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
