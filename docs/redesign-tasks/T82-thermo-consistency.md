# T82：thermo / profile 输入一致性加固（频率证据、单点配对、集合可比性、方法范围）

## 分支与目标

- 分支：`codex/t82-thermo-consistency`；基于最新 main，一张任务单一个 PR。**开发机做。**
- **优先级：高。** 外部审阅（10-16，基于 v4.2.2 `5ab0eb4`）用合成小分子复现了以下问题，监督方已对照代码确认。它们会让错误的热化学结果“正常”生成；研究 A 很快要用 `ag thermo` 和 `ag profile` 做系综热化学，**必须在研究 A 用这两个命令签字之前修好**。
- **目标：** 让 `ag thermo`、`ag profile` 拒绝下面几类在卡片中已明确不允许、但代码没有拦截的输入：

| # | 问题（已确认） | 位置 |
|---|---|---|
| 1 | `profile` 直接引用 Attempt（`attempts` 方式）时，单点精化只核对元素组成、电荷、多重度，**不核对几何配对**；anti 的频率可以配上 gauche 的单点（RMSD 1.28 Å）。`thermo` 已有配对检查（RMSD ≤ 1×10⁻³ Å），`profile` 没有复用。 | `_profile_sources.py` `load_species` |
| 2 | `thermo` 和 `profile` 只看 `termination == normal` 和 `n_imag`，**不看 `freq_step_converged`、`vibrational_modes_complete`**；频率阶段明确未收敛的结果也能生成热化学。 | `thermo.py` `calculate_thermo`；`_profile_sources.py` |
| 3 | `thermo` **不核对输入集合的可比性**：不同物种（例如水和正丁烷）能一起算“构象布居”；部分行有单点修正、部分行没有也能混算；方法、溶剂、程序版本不一致也不拦。 | `thermo.py` |
| 4 | 电子能固定取 `energies.scf`。MP2、双杂化泛函等方法的最终能量不在 SCF 行，程序却照常接受，单点修正会算错。 | `_profile_sources.py` `protocol`；`_parse_outputs.py` |
| 5 | “同一计算方案”的比较漏了显式 `5D/6D`、`7F/10F`（改变基函数形式）；积分网格差异也没有展示。 | `_profile_sources.py` `protocol` |

- 资料：`ag/src/ag/thermo.py`（`calculate_thermo`、`_pairing_evidence`）、`ag/src/ag/_profile_sources.py`（`protocol`、`attempt_facts`、`load_species`）、`ag/src/ag/_parse_outputs.py`（`_FREQUENCY_FACTS`、`expected_vibrational_modes`）、`skills-next/auto-g16-recipes/cards/thermo.md`、`profile.md`、`opt-freq.md`。

## 允许改动的路径

- `ag/src/ag/thermo.py`、`ag/src/ag/_profile_sources.py`、`ag/src/ag/profile.py`（只在接入上述检查所必需时）。
- `ag/tests/test_thermo*.py`、`ag/tests/test_profile*.py`、`ag/tests/test_asm.py`（`protocol()` 变严后需要同步的用例）及合成夹具。
- `skills-next/auto-g16-recipes/cards/thermo.md`、`profile.md`：只在“工具会拒绝什么”的说明处补句；不改其他规则。（T81 正在给这两张卡加开头要点，注意 rebase。）
- `ag/README.md`：thermo / profile 一节。
- `docs/redesign-tasks/T82-thermo-consistency.md`：本任务单。
- **不改 `facts.py`、`_parse_outputs.py` 的解析和 facts 输出**（只读取已有字段）。需要改就停下。

## 要做的

1. **频率证据（thermo 与 profile 共用一个检查函数）：**
   - 要求 `freq_step_converged is True` 且 `vibrational_modes_complete is True`；明确为 `False` 时拒绝，并给出 facts 中的收敛表或模式数。
   - facts 缺这些字段（旧版 facts）时拒绝，提示先运行 `ag facts --refresh`；不按缺失放行。
   - 单原子物种（没有振动模式）：不要求模式完整，但报告中注明；独立 Freq 作业（不是 Opt+Freq）同样要求上面两个字段。
   - `n_imag` 的要求不变（thermo 为 0；profile 中 TS 为 1 且须有审阅记录）。
2. **profile 的单点配对：** `attempts` 方式下有 `spc_attempt_id` 时，复用 thermo 的 `_pairing_evidence`（固定行序、Kabsch 对齐、RMSD ≤ 1×10⁻³ Å、记录输入几何哈希），**TS 的单点精化同样适用**；配对证据写进 profile 输出。`thermo` 缓存方式不变（thermo 输出里已有配对证据）。
3. **thermo 的集合可比性：** 所有行的元素组成、电荷、多重度相同；频率层方法口径（`protocol()`）和程序版本相同；单点修正要么全有、要么全无，全有时单点层方法口径和程序版本也相同。任一不满足就拒绝并列出不同之处。报告中写明：“分子式相同不等于同一物种，是否属于同一物种的构象集合仍由人审阅。”
4. **方法范围（`protocol()`）：** 只接受最终电子能就是 `SCF Done` 那一行的方法（HF 和普通 DFT，含常用色散修正）。遇到 MP2/MP3/MP4、CCSD、CCSD(T)、QCISD、CBS-*/G3/G4 等复合方法、双杂化泛函（B2PLYP、mPW2PLYP、DSD-*、PBE0DH 等）、半经验方法、ONIOM 时**明确拒绝**，提示“当前只支持 SCF 能量的方法”。名单写成常量并在 README 列出。
5. **方案比较补字段：** `protocol()` 返回值增加 `basis_function_type`（显式 `5D`/`6D`、`7F`/`10F`，未写时为 `basis_default`），纳入“同一方案”的比较；另外记录积分网格（`int=`/`integral=` 的写法，未写时为 `program_default`），**只展示和警告**（例如一层写了 `UltraFine`、另一层用默认），不作为拒绝条件。程序默认网格的含义随版本不同，不要自行推断等价。
6. 下游影响：`ag asm` 和正在开发的 `ag irc-review`（T79）都 import `protocol()`，变严后随之生效。本单同步 `test_asm.py` 中受影响的用例；在 PR 里说明对 T79 的影响（T79 如晚于本单合并，需 rebase）。

## 不允许

- 不放宽现有检查；不改 GoodVibes 设置、热化学公式和输出中已有字段的含义。
- 不改 facts 解析和输出；不回写任何已有 thermo / profile 报告。
- 不自动判断“是否同一物种”。

## 测试

- 外部审阅的几个反例全部改为被拒绝：anti 频率配 gauche 单点（profile `attempts` 方式，含 TS 单点精化）；`freq_step_converged=false` 且零虚频；`vibrational_modes_complete=false`；水和正丁烷混算；部分行有单点修正；频率层方法不同；程序版本不同；MP2 和 B2PLYP 路线；显式 `5D` 与 `6D`。
- 网格不同只产生警告；单原子物种的说明；旧版 facts 缺字段时的提示。
- 现有正常夹具的 thermo / profile 数值结果不变（新增字段除外）。
- 开发中只跑相关测试；推送前本地跑一次全量 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，之后以 CI 为准。敏感扫描与 `git diff --cached --check`。

## 真实环境验证（合并前，开发机，只读）

- 对 L1–L3 中已有的 thermo / profile 输入，用新版本重跑，输出写到 study **以外**的临时目录：数值结果与原报告一致（新增字段除外）；如有新的拒绝，逐个列出原因，判断是原结果确有问题还是新检查过严。
- 不改已签 study，不连集群。
- **合并后（研究 A 主会话，计算机，只读；负责人安排时间）：** 对研究 A 已有和将要签字的 thermo 输入，检查所用 Attempt 的 `freq_step_converged`、`vibrational_modes_complete`、单点配对和集合可比性，列出不满足的 Attempt 交监督方判断。** 研究 A 用 thermo / profile 结果签字之前必须完成这一步。**

## 停止条件

- 需要改 facts 解析或 facts 输出。
- L1–L3 重跑中出现数值变化（不只是新增字段）。
- 已签的 L1–L3 结果被新检查拒绝：停下汇报，不要放宽检查。

## 合并前审阅与交付

- 需要监督方审阅：是（影响热化学结果的可信度）。
- PR 描述第一行：`Task: T82`；附反例前后对照和 L1–L3 重跑结果。
- 合并只由负责人操作。

## 实现与验证记录（2026-10-16）

- 基线：`5ab0eb4`（v4.2.2）；原始任务要求保留在上文。
- 频率证据共用 `_frequency_evidence`，只读取已有 facts 字段；单原子仅豁免模式完整性，仍要求频率段明确收敛。新增带虚构收敛表的原子热化学夹具，原解析夹具保持不变；`test_evidence_mismatch.py` 仅补其内嵌合成 HOOH 夹具的收敛表，未改测试断言、解析器或研究数据。
- profile 直接 Attempt 的单点（含 TS）复用 `_pairing_evidence`，JSON/Markdown 保留配对证据；缓存 thermo 沿用已有证据。
- thermo 比较组成、电荷、多重度、各层 protocol 与程序版本，拒绝部分 SPC；报告保留“同分子式不保证同一物种”的人工审阅说明。
- `protocol()` 采用明确的 SCF 方法常量，拒绝不支持和未知方法；新增 `basis_function_type`。网格由 `integration_grid()` 单独记录，避免共享 protocol 的字典比较把网格警告变成拒绝。
- 同步 `test_asm.py` 的方法拒绝和基函数差异测试。T79 继承更严格的方法范围和新增方案字段；若晚于 T82 合并，需 rebase 并核对其测试。没有修改 T79 文件。
- 只读重跑：L1 thermo、L2 两份 thermo、L3 复合物/端点/分离物种三份 profile 的既有数值均完全一致；新增字段除外，无新拒绝。输出只写到 study 外临时目录，444 份选定证据的 SHA-256 与 mtime 不变；未连接集群。
- 合并后研究 A 检查仍由负责人安排给研究 A 主会话；本次结果不代替该检查或研究 A 签字。
- 本地全量运行一次：3073 passed、3 failed、3 skipped、2 xfailed；失败均为上述合成夹具兼容问题。修复后只复测受影响的 184 项，全部通过；最终全量结果以 CI 为准。3 项跳过为两项 Linux 专属命令方言检查和一项未启用的私有日志测试，未开启私有日志测试。

## 版本记录

- T116 脱敏：研究标识、编号与环境字面量改为泛称；原工单结构和结论不变。
