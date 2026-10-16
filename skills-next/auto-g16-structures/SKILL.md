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
