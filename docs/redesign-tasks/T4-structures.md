# T4：`auto-g16-structures` Skill（ChemDraw/SMILES → 结构 → 力场初筛）

分支：`codex/redesign-t4-structures`　位置：**本地**（需要带 CDX 支持的 RDKit，`chem` 环境）　依赖：T0 已合并　预计：1～1.5 天

## 目标

把现有已验证可用的 ChemDraw/RDKit 通路迁移成一个新 Skill，输出直接写到 study 的 `structures/`，作为 `ag prepare` 和 `ag dedup` 的输入。规格见方案 5.4、决策 D13。迁移以“原样复制、最小改动”为原则，这部分旧代码质量不错。

## 允许改动的路径

- `skills-next/auto-g16-structures/`（含 `SKILL.md`、`agents/openai.yaml`、`scripts/`、`references/`、`tests/`）

## 不允许

- 改旧 `skills/` 下的原文件（只复制）。
- 改变旧脚本中已经验证过的化学处理逻辑：CDX 读入保留显式氢、恢复楔形键 CFG、冲突楔形键不静默修复、手性中心未指定时停止、原子数与分子式漂移视为错误、含硼时 MMFF 缺参数回退 UFF 并提示。
- 引入旧治理字段（`candidate_only`、`calculation_ready`、receipt、选择回执等）。

## 步骤

1. 复制以下脚本到 `skills-next/auto-g16-structures/scripts/`，在每个文件头注明来源路径：
   - `skills/auto-g16-chemdraw-pipeline/scripts/`：`cdx_stereo.py`、`inspect_chemdraw.py`、`audit_cartesian_input.py`、`make_gaussian_input.py`
   - `skills/auto-g16-view-rt-win/scripts/`：`prepare_preview.py`、`prepare_conformers.py`、`runtime_config.py`
   - GaussView 预览（`windows_gaussview.py`、`gaussview_load_probe.ps1`）先**不**迁移；在 `SKILL.md` 中说明需要时仍可用旧 Skill 的脚本手动预览。
2. 最小改动：
   - 运行环境：直接在 `chem` 环境中运行；去掉对 `~/.codex/skills/...` 路径和旧 runtime 配置的依赖（`runtime_config.py` 只保留确实需要的项，或删除）。
   - 输出位置：增加 `--study <dir>`，输出到 `<study>/structures/<名称>/`，文件不覆盖。
   - `prepare_conformers.py`：去掉“一次只能选择一个构象”的选择回执流程；`generate` 输出一个多帧 xyz（注释行写 MMFF/UFF 能量，kcal/mol）和一个摘要 JSON，交给 `ag dedup`。保留 ETKDGv3 + 手性强制、MMFF94s/UFF、能量窗口和 RMSD 参数。
   - `make_gaussian_input.py`：作为从 xyz 生成 `.gjf` 的辅助工具保留；参数为 route、电荷、多重度、`%nprocshared`、`%mem`、`%chk` 文件名；去掉 Gaussian 09 相关措辞和 Windows VM 相关逻辑。
3. `SKILL.md`（简短）：
   - 何时使用：新结构进入研究、需要力场初筛、需要从 xyz 生成 Gaussian 输入。
   - 固定流程：读入 → 给出结构摘要（规范 SMILES、分子式、原子数、电荷、立体中心与 CIP、警告）→ **请人确认结构（里程碑 1）** → 可选力场初筛 → 交给 `ag dedup`。
   - 多重度必须由人或 `study.md` 给出，不从结构推断；自由基、金属、配位体系直接停止并告诉人。
   - `references/`：从旧 `skills/auto-g16-view-rt-win/references/chemistry-boundaries.md` 和 `conformer-workflow.md` 中搬入仍然适用的内容（注明来源），删去 RTwin/VM 部分。
4. 测试 `skills-next/auto-g16-structures/tests/`：
   - SMILES 路径：正丁烷、带一个手性中心的小分子（如 (R)-2-丁醇）——立体信息保留、手性未指定时报错。
   - CDX 路径：使用仓库已有的非研究样例 `tests/fixtures/reaction_workflow/source_scheme.cdxml`（复制一份到本 Skill 的测试目录）；若它不适合单分子测试，另画一个简单分子的 CDXML 作为样例。
   - 力场初筛：正丁烷生成多帧 xyz，能量注释可解析，帧数大于 1。
   - 参考旧测试 `tests/test_make_gaussian_input_safety.py` 中仍适用的用例并改写。
   - CI 环境如果没有 CDX 支持，CDX 测试自动跳过；本地必须运行通过。

## 验收标准

- 本地 `pytest skills-next/auto-g16-structures/tests` 全部通过（含 CDX 测试）。
- 用一个你手头的 ChemDraw 文件（非研究体系即可）演示：读入 → 结构摘要 → 力场初筛 → 生成多帧 xyz，过程记录写进 PR（不含本机路径）。

## 停止条件

- 复制后的脚本在新位置运行结果与旧脚本不一致（同一输入的 SMILES、立体信息、原子数不同）。
- 需要改变上面“不允许”中列出的化学处理逻辑才能跑通。

## PR 要求

PR 描述第一行 `Task: T4`；列出复制的文件、每个文件做了哪些改动；附演示记录。
