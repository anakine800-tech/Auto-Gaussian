# T2：`ag facts` 与 `ag thermo`

分支：`codex/redesign-t2-facts`　位置：本地或云端（测试样例的制作必须在本地）　依赖：T0 已合并　预计：1.5～2 天

## 目标

把计算输出变成 LLM 可以直接读的客观数字（`facts.json`），并提供 qRRHO 热化学和 Boltzmann 加权（`ag thermo`）。规格见方案 4.9、5.5 和决策 D8、D21。

## 允许改动的路径

- `ag/src/ag/facts.py`、`ag/src/ag/thermo.py`、`ag/src/ag/_parse_*.py`（如需拆分）
- `ag/tools/sanitize_log.py`
- `ag/tests/test_facts.py`、`ag/tests/test_thermo.py`、`ag/tests/test_sanitize.py`、`ag/tests/fixtures/`
- `ag/pyproject.toml`（只调整 `chem` 依赖组的版本锁定）

## 不允许

- 改 T1、T5 拥有的文件（`cli.py` 只通过 `register(subparsers)` 挂载，不改 `cli.py` 本身）。
- 把任何 HSS、BPh₃、BF₃、DA 等研究体系的日志放进仓库。
- import 旧代码（`auto_g16/`、旧 `skills/`、`scripts/`）。可以阅读并改写其中的逻辑，提交说明里注明来源文件。

## 步骤

1. **`facts.py`**，入口 `build_facts(attempt_dir) -> dict`，写 `facts.json` 和 `final.xyz`：
   - 根据 `manifest.json` 的 `template` 选择解析器：`gaussian`、`crest`、`xtb`。
   - Gaussian：用 cclib 读取；cclib 不提供的字段用正则补充（`Sum of electronic and thermal Energies`、`<S**2>`、route 行、`Error termination via Lnk1e in .../lXXX.exe`）。
   - `termination`：有 `Normal termination` 且无错误行为 `normal`；有错误行为 `error`，并给 `error_hint`（l9999 → 优化步数用完；l502 → SCF 不收敛；其他给出 link 号）；都没有时为 `incomplete`，若 `job.pbs.out` 中有 walltime 超限信息则 `error_hint = "walltime"`。
   - `imag_modes`：对每个虚频，计算所有距离小于 3.5 Å 的原子对沿该振动的距离变化率 `(u_i - u_j)·(r_i - r_j)/|r_i - r_j|`，取绝对值最大的 5 对，记录原子序号（1 起始）、元素、当前距离、变化率。这是 TS 卡片判断“振动方向是否对应成键原子”的依据。
   - CREST：读 `crest.energies` 和 `crest_conformers.xyz`，给 `n_conformers`、相对能量（kcal/mol）、最低能量。
   - xtb：`TOTAL ENERGY`、是否 `GEOMETRY OPTIMIZATION CONVERGED`、是否 `normal termination of xtb`。
   - 注册子命令 `ag facts <attempt_dir|attempt_id> [--study S] [--json]`。
2. **`thermo.py`**，子命令 `ag thermo <attempt>... [--temp 298.15] [--conc 1.0] [--qs grimme] [--s-cutoff 100] [--h-cutoff 100] [--degeneracy <attempt>=<n>]... [--spc <attempt>=<sp_attempt>]...`：
   - 用 GoodVibes 4.3.0 计算每个结构的 E、ZPE、H、qh-G。调用方式可参考旧文件 `auto_g16/thermochemistry/_goodvibes.py`（只读参考，不要 import）。
   - Boltzmann 加权：按 qh-G 计算相对自由能和布居，`--degeneracy` 作为简并度权重（例如正丁烷 gauche 的镜像对为 2）；输出加权平均 G。
   - `--spc` 时用单点 Attempt 的电子能替换 E（GoodVibes 的 SPC 方式或等价计算），并在输出里注明。
   - 输出到 study 的 `analyses/thermo-<时间戳>.json` 和同名 `.md` 表格；不覆盖已有文件。
   - 任一输入不是 `termination = normal`，或含虚频，就拒绝并说明是哪个。
3. **测试样例（必须在本地制作）**：
   - 从本地已有结果中只挑非研究小分子：水的 Opt+Freq（例如 `h2o_ofs_713.log`）、正丁烷 anti 和 gauche 的 Freq 日志；CREST 样例只有当它是正丁烷之类的非研究分子时才可用，否则在 L1 验收跑完后再补。
   - 写 `ag/tools/sanitize_log.py`：把日志中的主机名（包括存档块里的 `GINC-<主机>`）、用户名、绝对路径、PID 替换成固定占位符。测试：脱敏后 cclib 仍能解析出相同的能量和频率。
   - 只提交脱敏后的文件。另外构造几份很小的“错误终止”和“未完成”日志片段，用于测 `termination` 和 `error_hint`。
   - 研究体系日志通过环境变量 `AG_LOCAL_FIXTURES=<目录>` 运行额外测试（TS 的 `imag_modes`、IRC），未设置时跳过；这些测试的断言不能写出任何研究分子的具体数值，只断言字段存在、类型正确、虚频数为 1 等。

## 验收标准

- `pytest ag/tests` 全部通过（CI 的 `ag-tests`）。
- 对水和正丁烷样例，`facts.json` 的能量与日志中的数值一致（误差 < 1e-6 Hartree），`n_imag = 0`。
- 本地设置 `AG_LOCAL_FIXTURES` 后，3 个 TS 日志的 `n_imag = 1`，`imag_modes` 中位移最大的原子对与人工查看一致（在 PR 描述中用“符合 / 不符合”说明，不写分子信息）。
- 正丁烷 anti + gauche（简并度 2）的 `ag thermo` 能给出布居表。

## 停止条件

- GoodVibes 4.3.0 无法在 Python 3.11 的 `chem` 环境中安装或调用。
- 脱敏后 cclib 解析结果发生变化。
- 无法找到合适的非研究小分子日志。

## PR 要求

PR 描述第一行 `Task: T2`；列出新增的样例文件及其来源类型（不写本机路径）；列出本地额外测试的运行结果。
