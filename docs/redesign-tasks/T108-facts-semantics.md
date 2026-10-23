# T108：facts 语义修正——Gaussian 驻点结论、两套收敛阈值、稳定性识别、⟨S²⟩

版本：v1（监督方，2026-10-23）。**开发机做。** 后端出一个 PR，PR 描述第一行写 `Task: T108`。

## 分支与目标

- 分支：`codex/t108-facts-semantics`。
- **开工条件：** 后端 main 为 `6419a04`（v4.4.0）或其后；T108 编号未被占用。
- **问题来源：** DHP 三线态 study 的问题汇总（2026-10-22）#1、#2、#3、#9；HSS 的 061 也遇到同类问题（单独提交的 Freq 用的是默认阈值，父作业是 Opt=Tight）。
- **负责人 2026-10-23 决定：**
  - F1 **thermo 准入规则不变**，仍看 `freq_step_converged`，即频率步收敛表四项全部为 YES，且没有 Non-Optimized Parameters。
  - F2 另外新增一个字段，记录 Gaussian 自己给出的驻点结论。四项没有全部通过、但 Gaussian 判了驻点的结果，标为 **"需人工判定"**，不自动放行。已经签过字的判定（例如 HSS 的 016/017/027）不受影响。
  - F3 facts 同时记录两套阈值下的判定：作业日志实际打印的阈值，以及 Opt=Tight 的阈值。
  - F4 修正稳定性识别和 ⟨S²⟩ 的读取。
- **资料：** `AGENTS.md`、`docs/DEVELOPING.md`、`docs/LESSONS.md`、`docs/ag-facts-1.md`；T99（route 拼接、来源行号、reparse）任务单；`ag/src/ag/_parse_outputs.py`（`frequency_convergence()`、`wavefunction_stability()`、`parse_gaussian()` 中 `s2` 的读取）、`thermo.py`、`review.py`、`_profile_sources.py`。

## 背景（main `6419a04` 的代码现状）

1. `frequency_convergence()` 只读取 Freq 步收敛表中的四项 YES/NO 和 Non-Optimized Parameters。Gaussian 在力已可忽略时，即使位移项为 NO，也会打印 `Stationary point found`（"negligible forces"）。这一结论目前没有记录。
2. 收敛表里的阈值是作业自己打印的。同一作业里 `Opt=Tight Freq` 的 Freq 步打印的是 Tight 阈值；单独提交的 Freq 打印的是默认阈值。现在 facts 不区分这两种情况。
3. `wavefunction_stability()` 只认三种写法：`stable under the perturbations considered`、`internal instability`、`RHF -> UHF instability`。`The wavefunction is already stable.` 会被记成 `unknown`。
4. `s2 = last_number(r'<S\*\*2>\s*=|S\*\*2 before annihilation', text)` 取的是全文最后一个匹配，会读到稳定性分析或激发态行里的 `<S**2>=`（例如本征向量标签 2.000），而不是 SCF 收敛后的 ⟨S²⟩。

## 允许改动的路径

- `ag/src/ag/_parse_outputs.py`：上述三个函数，以及 `s2` 的读取。
- `ag/src/ag/thermo.py`：只改拒绝信息和警告的输出，**不改**准入判定。
- `ag/src/ag/review.py`：在审阅清单里显示新字段。
- `ag/src/ag/_profile_sources.py`：只有当频率相关 facts 的键列表必须同步时才改。
- `docs/ag-facts-1.md`（新增字段说明，并把规则版本号加一）、`docs/LESSONS.md`（加一条）。
- `skills-next/auto-g16-recipes/cards/opt-freq.md`、`cards/thermo.md`：只写新字段怎么判读、人工判定的规则。
- 测试：相关的现有测试文件（PR 中列出）；新建 `ag/tests/test_facts_semantics.py`。
- `docs/redesign-tasks/T108-facts-semantics.md`（本单）、`docs/redesign-tasks/open-tasks.txt`。

## 要做的

### 1. Gaussian 驻点结论（F2）

- 新增字段 `freq_step_gaussian_stationary`，内容为 `{found, basis, lines}`：
  - `found`：只在**当前这个 Freq 步内**判断，作用范围与 `frequency_convergence()` 相同，不能把前面 Opt 步或其他 Link1 步的结论借过来。值为 `true` / `false` / `null`（没有 Freq 步）。
  - `basis`：`all_criteria`（四项全过）、`negligible_forces`（力可忽略）或 `null`。判断依据是 Gaussian 实际打印的文字，以真实日志为准，不凭记忆。
  - `lines`：相关原文行的行号。
- `freq_step_converged` 的含义**不变**。
- 新增派生字段 `freq_step_review`，取值规则：
  - `freq_step_converged == true` → `"pass"`；
  - `freq_step_converged == false` 且 `found == true` → `"manual_review"`；
  - 其他情况 → `"fail"` 或 `null`。
- **thermo 准入不变**，仍然要求 `freq_step_converged is True`。遇到 `manual_review` 时，拒绝信息改为："四项未全部通过，但 Gaussian 判定驻点（力可忽略）：需人工判定；thermo 不自动接受"，后面附上收敛表原值和行号。不增加任何放行参数。

### 2. 两套阈值（F3）

- 在 `freq_step_convergence` 的每一项中，保留原来的 `threshold` 和 `converged`，即日志打印的阈值和 YES/NO；另外增加 `converged_tight`，用 Opt=Tight 的阈值重新判定：最大力 0.000015、RMS 力 0.000010、最大位移 0.000060、RMS 位移 0.000040。
- 新增 `freq_step_converged_tight`，规则与 `freq_step_converged` 相同，只是改用 Tight 阈值。另外新增 `freq_step_threshold_set`：日志打印的阈值和 Tight 阈值完全一致时记为 `"tight"`，和 Gaussian 默认阈值一致时记为 `"default"`，都不是时记为 `"other"`。默认阈值的数值以真实日志为准。
- **thermo 准入不变。** 当 `freq_step_threshold_set == "default"`、`freq_step_converged == true`、`freq_step_converged_tight == false` 时，thermo 照常通过，但要在输出的 `warnings` 中写明："Freq 步按默认阈值通过、按 Tight 阈值未通过；若父优化为 Opt=Tight，需人工判定是否接受"。审阅清单同样显示这条。

### 3. 稳定性（F4）

- 增加识别 `The wavefunction is already stable.`，记为 `stable`。作用范围和"新 route 或 Link1 即重置"的规则与现有逻辑相同。
- 新增 `wavefunction_stability_lowest_eigenvalue`：读取稳定性分析中最低的本征值，并记录行号。具体从哪一行读，以真实日志为准；格式不认识就记 `null`，不要猜。

### 4. ⟨S²⟩（F4）

- `s2` 改为：**最终那一次 SCF 收敛后**的 `S**2 before annihilation` 值。另外新增 `s2_after_annihilation` 和 `s2_line`（行号）。
- 稳定性分析、激发态或本征向量里的 `<S**2>=` 一律不采用。
- 闭壳层 RHF 作业日志里没有这一行时，`s2` 记为 `null`，不要填 0。
- 这是缺陷修复，会改变已有 `s2` 字段的含义。`ag-facts-1.md` 里写明，并把规则版本号加一。

### 5. 已有证据怎么处理

- 新规则只对新生成的 facts 和明确授权的 `--reparse` 生效。已有的 facts，尤其是 HSS 已签字的，**一律不自动重写**。是否 reparse、什么时候 reparse，由负责人按 study 逐个决定（沿用 T99 的流程：先 dry-run，预览差异）。
- LESSONS 记一条：Gaussian 的驻点判定和四项判据要分开记录；单独提交的 Freq 使用默认阈值；⟨S²⟩ 要从 SCF 段读取。

## 不允许

- 不改 `freq_step_converged` 的含义，不改 thermo / profile 的准入，不增加放行参数。
- 不改其他已有字段的含义（`s2` 的缺陷修复除外）。
- **测试夹具不得使用研究日志的内容**（DHP 的 c05、037、062，以及 HSS 的日志），这是 AGENTS 第 3.10 条的要求。夹具可以照抄 Gaussian 的输出格式，但数值和体系信息只能来自小分子真实验证，或者人工构造。
- 不自动对任何已有 study 执行 reparse。

## 测试

| 场景 | 预期 |
|---|---|
| Opt=Tight Freq，Freq 步四项全 YES | `freq_step_converged=true`，`threshold_set=tight`，`review=pass` |
| Freq 步位移为 NO，但打印了 negligible forces / Stationary point found | `converged=false`，`gaussian_stationary.found=true`，`basis=negligible_forces`，`review=manual_review`；thermo 拒绝，信息写"需人工判定" |
| 单独提交的 Freq（默认阈值），按默认阈值全过、按 Tight 不过 | `converged=true`，`converged_tight=false`，`threshold_set=default`；thermo 通过，但输出 warnings |
| Opt 步打印了 Stationary point found，但 Freq 步没有 | Freq 步的 `found` 不能借用 Opt 步的结论 |
| 多个 Link1 步 / 截断的日志 | 不跨作业步继承结论 |
| `already stable` | `wavefunction_stability=stable`，行号正确 |
| 稳定性分析中有本征值 | `lowest_eigenvalue` 和行号正确；格式不认识时为 null |
| UHF 三线态，稳定性分析中有 `<S**2>=2.000` 标签 | `s2` 取 SCF 段的湮灭前值，不取 2.000 |
| 闭壳层 RHF | `s2=null` |
| 已有 facts（旧规则生成） | 不被自动改写；reparse dry-run 能显示新字段和 `s2` 的差异 |

开发中只跑相关测试；推送前本地跑一次全量 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，之后以 CI 为准；另外做敏感信息扫描，并运行 `git diff --cached --check`。

## 真实环境验证（合并前，开发机，非研究体系）

用未合并的代码做真实提交前，要先由负责人批准方案；每次提交都由负责人亲手点击 Mac 确认框。建议在 newhpc 或 default 上用最小的资源档位：

1. **水 `Opt=Tight Freq`**（一个作业）：核对 `threshold_set=tight`，以及驻点字段。
2. **用第 1 步的结构单独提交一个 Freq**（默认阈值）：核对两套阈值的判定和 thermo 的 warnings。
3. **闭壳层水 `Stable=Opt`**：核对 `already stable`（或 `stable under...`）的识别和最低本征值。
4. **三线态小分子（例如三线态 CH₂ 或 O₂）UHF 的 `Stable=Opt` 加单点**：核对 `s2` 取自 SCF 段，并且没有误读稳定性分析里的标签。
5. 能用这几个真实日志的格式行做夹具的，就加进测试（只用小分子）。"力可忽略、四项未全过"这种情况，小分子很难稳定复现，可以按日志格式人工构造夹具，并在 PR 中说明。
6. **可选（需负责人另行批准）：** 对 DHP study 的 c05、037、062 在开发机本地做只读的 `--reparse --dry-run --out <study 之外的位置>`，只汇报"新字段是否符合预期"，不把任何数值或内容写进 PR。

出现异常就停下汇报，不重试。

## 停止条件

- 真实日志中驻点或稳定性的输出格式和预期不一致，又无法唯一确定该怎么读。
- 需要改动准入规则，或者需要改动范围以外的文件。
- 同一个问题修两次仍未解决。

## 合并前审阅与交付

- 需要监督方审阅：**是**（facts 字段语义、thermo 提示）。合并只由负责人操作。
- PR 描述要写清：F1–F4 每一项对应的改动；新字段说明；`s2` 含义变化及其影响；全量测试结果；真实验证的作业和结论。
- **合并后：** 开发机同步。各 study 要不要 reparse，由负责人逐个决定。HSS 只在负责人授权后才做 dry-run 预览。

## 版本记录

- v1（2026-10-23，监督方）：依据 DHP 问题汇总 #1、#2、#3、#9 和负责人 10-23 的决定起草。

## 开发交付记录（2026-10-23）

基于 `6419a04` 开发，规则版本从 `route-join-v1` 加至 `route-join-v2`。
新增字段及兼容行为见 `docs/ag-facts-1.md`；原 thermo/profile 准入保持。
`wavefunction_stability_line` 仍是原文，新增 `_line_number`；最低本征值使用
`{value, line}`。不认识的格式保留 null。默认阈值和驻点格式使用已有的脱敏
水/正丁烷日志核对；稳定性矩阵格式参考 UCSB 的公开 H₂ 示例，测试数值人工构造。
“力可忽略、四项未全过”也为人工构造，不能声明已真实复现。

### 已批准的真实验证方案

2026-10-23 负责人批准：“批准方案，CI 通过后逐次确认提交”。
首轮 HEAD 的 CI 为 ag/tests 3843 passed、1 skipped，skills-next 509 passed，
CodeQL 通过；以下前四个作业均逐次经 Mac 系统确认。

使用专门的非研究验证 study；工单第 4 个场景拆成 Stable=Opt 与后续 SP，
共 5 个新 Attempt，串行执行。目标 `default`，当前最小档位 `mini`：
4 核、调度内存 10 GB、Gaussian `%mem=8GB`。以下时限合计最多 4 核时。
水与 CH₂ 均无手性中心；CH₂ 明确采用中性三线态，仅检验解析，
不扩展开壳层研究支持或作科学验收。

| Attempt 用途 | 电荷/多重度 | 完整 route | walltime |
|---|---|---|---|
| 水 Tight Opt+Freq | 0 / 1 | `#p B3LYP/6-31G(d) EmpiricalDispersion=GD3BJ Opt=Tight Freq SCF=Tight Integral=UltraFine` | 00:20:00 |
| 上一项最终结构的独立 Freq | 0 / 1 | `#p B3LYP/6-31G(d) EmpiricalDispersion=GD3BJ Freq SCF=Tight Integral=UltraFine` | 00:10:00 |
| 闭壳层水稳定性 | 0 / 1 | `#p RHF/6-31G(d) Stable=Opt SCF=Tight` | 00:10:00 |
| 三线态 CH₂ 稳定性 | 0 / 3 | `#p UHF/6-31G(d) Stable=Opt SCF=Tight` | 00:10:00 |
| 上一项 chk 的同几何单点 | 0 / 3 | `#p UHF/6-31G(d) SP Guess=Read SCF=Tight` | 00:10:00 |

水 Opt+Freq 使用方法表已有的流程验收方案；HF 两项为 T108 解析验证的
兜底方法提案，无精度主张。独立 Freq 可能同时通过 Tight，此时应没有该
警告；默认通过而 Tight 失败的警告分支由合成/已有小分子回归单独覆盖，
不人为改变真实输出来制造警告。

首批三个输入已在仓库外完成本地校验、prepare 和逐次确认提交。
SHA-256：water-tight `794b424a7936336f79c2b67a35672f2de4e33d806da76fd93ace0288db2916b8`；
water-stable `e083034c86f6669210a5aba18215dd81481a4f30fee0fa29c7de713b473675bb`；
ch2-stable `27d107bb282633ccf8fed28730206161af3a695592aa8ea99fe50afd5ad13f38`。
后两份依赖实际结构/chk，均在父作业正常结束后生成：water-freq
`d93995bb0318b8ddafee5b213a604c8ceed3d37c54fe4d0c9ea691f92c3d6188`，
ch2-sp `5ace36b863036483451bba18acf2a0c549d2f15206cae8891a6796c852be39e9`。
逐项通过 ag prepare 生成确切目录和摘要，展示结构、route、资源及全部
输入哈希，再由负责人点击 Mac 确认框。chk 仅走 ag 专用父 chk 复制；运行、取回和诊断
只用正式 ag 命令。保留全部原始记录；任何异常立即停下报告，不重试或清理。

### 真实验证进展

专用非研究 study 为 `t108-facts-validation-20261023`，以下均为 Gaussian 16 A.03。
每个作业结束、输出哈希核验并取回后才提交下一个。PBS 的延迟退出记录仍
按占用计入 ag 提交检查，不将其误报成 Gaussian 正在计算。

| Attempt 后缀 | 退出/解析证据 |
|---|---|
| 001-water-tight | 退出 0、normal；Freq 阈值 tight，四项及 Tight 全过，stationary/all_criteria，review=pass；表行 2227–2230，驻点行 2233 |
| 004-water-freq | 退出 0、normal；父最终坐标，阈值 default，两套判据均过、0 虚频；thermo 成功且 warnings=[]，符合本例不应触发差异警告的预期 |
| 002-water-stable | 退出 0、normal；already stable 行 530，最低本征值 0.3087461（行 525）；SCF 自旋无记录，s2=null |
| 003-ch2-stable | 退出 0、normal；s2=2.0160、湮灭后 2.0001（行 401）；发现 archive route 回显误清空稳定性，暂停后续提交并修复；只读重算验证 stable（行 617）、最低本征值 0.3098649（行 610），保留原 facts 字节 |
| 005-ch2-sp | 本地 prepare 完成，尚未提交；等待修复后 CI 及父作业调度记录离队 |

新增回归采用本次水/CH₂ 的脱敏格式片段；archive 元数据及外层 job wrapper
人工构造。修复与上述格式回归共 250 passed；本次不再次运行本地全量，
以 CI 为准。“力可忽略”和默认通过/Tight 未过分支仍由人工/已有小分子
回归覆盖，不宣称本次真实复现。没有对已有 study 执行 reparse。

当前阻塞：**提交/环境**——CH₂ 父作业正常结束后仍有 PBS 残留，专用 chk
复制要求父作业离队；第五项未提交，取消清理需负责人另行授权及 Mac 点击。
**科学审阅**——facts 语义与 thermo 提示尚待监督方审阅。
