# T165：CP 报告补齐两片段的溶剂相单点能量

版本：v1，2026-10-28。目标仓库：Auto-Gaussian。类型：纯本地实现单。覆盖 H6。

## 分支与目标

- 分支：codex/t165-cp-solvent-fragments；一个任务单、一个分支、一个 PR；PR 第一行：Task: T165。
- 基于开工时最新 main；已核查基线 e24a5bd1d9045e3b783d8ef25f02e430ad4dc3c5。先读 AGENTS.md → 本单，再读 T105、docs/ag-cp-1.md、docs/DEVELOPING.md、docs/LESSONS.md 的 CP/SCRF 记录。
- 目标：在现有气相 CP 诊断和同几何复合物溶剂单点基础上，显式接入两个片段在复合物几何下、各自自身基组的 SMD 单点，给出可追踪的溶剂相相互作用能和加气相 BSSE 的近似值。
- 已核实现状：cp_report._solvent 只取得复合物能量，两个片段缺项令 interaction_raw / interaction_corrected 为 null；这不是当前已有的错误数值。本单补功能，不改写历史报告。
- 新检查防的事故：混入优化后的孤立片段、另一构象/电子态/溶剂/方法，或将 ghost/复合物基组片段能量当作自身基组能量，得到无效的相互作用能。
- 并行：可与资源、CREST、G0、父 chk 任务独立开发。本单只在 cp_report.py 自注册参数，不抢 cli.py 或共享 facts 解析器；T166 只整合 TS 文档，不与本单争改 counterpoise 卡。

## 允许改动的路径

- ag/src/ag/cp_report.py：新输入、复合物/片段对应、有限能量组合、JSON 与 Markdown。
- ag/tests/test_counterpoise.py：增补本功能的合成样例与回归。
- docs/ag-cp-1.md：新增参数、来源和诊断含义。
- skills-next/auto-g16-recipes/cards/counterpoise.md：只补片段单点的本地报告用法、来源要求和限制。
- README.md：只更新 cp-report 命令入口。
- docs/redesign-tasks/T165-cp-solvent-fragments.md、docs/redesign-tasks/open-tasks.txt；必要经验仅追加 docs/LESSONS.md。
- _profile_sources.py、_parse_outputs.py、geometry.py、fragments.py、facts.py 等只复用/查阅，不改其行为。确需扩展共享解析能力时停下说明具体证据，不从本单顺带改热化学或方法支持。

## 要做的

1. 沿用现有 --solvent-sp 指定复合物单点；新增可重复参数：
       --solvent-fragment-sp <fragment_index>:<attempt_id>
   index 明确为现有 CP 片段序号 1 或 2，不用模糊名称匹配。重复同一 index、未知 index、没有 --solvent-sp 却给片段参数均报错；不自动搜索 study 猜配。
2. 三个溶剂来源均用本 study 已存在的 ordinary Gaussian 单点；新片段模式先限于已支持方法的 SMD，整体/片段仍沿用 T105 闭壳层两片段范围。普通单点必须真实正常结束，符合现有 _load 的输入、bundle、日志、可选 facts 一致性检查；只看 route 回显不够。
3. 片段身份来自已绑定 CP CSV 的两片段原子列表。按原复合物编号顺序抽取对应坐标和元素，用它与片段单点的输入及输出几何配对；保留全体系号到片段局部号的明确列表。不得自动交换同元素原子或优化片段几何。
4. 配对复用现有 proper Kabsch、固定行顺序、RMSD ≤0.001 Å 的约定，不反射、不自动置换、不另造科学阈值。片段 SP 电子态须与 CP 的该片段声明相符，不拿整体电荷/多重度代替。
5. 验证片段仅含该片段真实原子、无 ghost/Counterpoise/额外片段、自定义基组或外部基组读取；每个片段使用自身原子上的同一受支持基组。方法、基组、基函数类型、色散须与复合物及气相 CP 相容；溶剂模型、溶剂及实际打印的关键溶剂参数须与复合物一致。沿用现有网格差异提示，不新设科学强制阈值。
6. 沿用 cp-report 受支持 SCF 单点的能量口径，对三个 SMD 来源分别记录日志行和哈希；核对现有 Gaussian SMD 总能量含义，不重复加 CDS 等修正。不得仅因看到“溶剂能量”标签就换用不同定义。若发现现有 _solvent 的能量口径需改，报告实证并停下扩大范围，不悄悄改变旧报告含义。
7. 两片段都有效时计算：
       interaction_raw = E_AB(SMD) - E_A(SMD) - E_B(SMD)
       interaction_corrected = interaction_raw + BSSE(gas)
   统一先以 Hartree 运算，再用现有常数换算 kcal/mol；所有派生量保留全部操作数来源、公式、片段绑定及几何匹配证据。
8. 只提供零个/一个片段时保留当前部分报告能力：已核验的片段能量可以显示，缺项逐一列明，两个 interaction 字段仍为 null；不以气相 MCBS/DCBS 代替。显式提供但证据损坏/不匹配的来源不能被悄悄当缺失跳过。
9. 不给新参数时，现有命令、气相报告和缺片段结果语义保持；已有 ag-cp/1 核心字段不改名。新输入下补齐既有 null 能量字段及必要来源信息，先核对消费者对 null/quantity 的处理，不能以新增报告悄悄破坏旧消费者。
10. Markdown 与 JSON 一致，清楚区分复合物能量、相互作用能、加气相 BSSE 的近似值。保留“假设 BSSE 基本不受溶剂影响”“诊断量；不进入 thermo/profile”“不是计算出的结合自由能”的边界。现有 complex_energy_plus_gas_bsse 继续明确不是相互作用能。
11. report 仍纯本地、只读来源、独占创建新的 JSON/Markdown；不修改 facts、manifest、原输入或科学签字，不生成/提交片段计算。

## 不允许

- 不在同一 Gaussian 作业启用 Counterpoise+SCRF；不绕过已记录的 G16 A.03 限制。
- 不支持三片段、开壳层、Gen/ECP、ghost 基组片段能量，不新增方法。
- 不把气相 BSSE 当作已证明溶剂修正，不添加热化学、标准态或变形能到本公式。
- 不改 thermo/profile/ASM、prepare/submit/模板，不把新结果灌入主线剖面。
- 不重写旧报告、研究数据、既有 facts 或哈希；不启动计算来补缺数据。

## 测试

| 场景 | 预期 |
| --- | --- |
| 合成水二聚体 CP + 复合物与两个片段 SMD SP | 两个差值和近似修正按独立手算值一致，Hartree/kcal单位正确 |
| 仅复合物或一个片段 | 保留已知值，缺项准确，interaction 仍为 null |
| 同名片段/重复 index/错误电子态/不同溶剂或方法 | 明确拒绝，不能猜配 |
| 片段已优化、可判定的原子换序、镜像或误选另一几何 | 固定原子配对不符时拒绝，不自动寻找另一对应；不宣称几何比较可证明所有同元素的化学身份 |
| ghost、CP 片段输出、额外原子、自定义基组 | 不接受为自身基组 ordinary SP |
| 只有 route、缺实际溶剂执行证据，频率/优化混合段 | 拒绝作为本功能能量源 |
| 任一输入/日志/已存 facts 失配，来源读后变化 | 不发布报告，不刷新旧 facts |
| 原命令无新参数 | 旧字段、限制、气相结果与缺项行为保留 |
| 现有结果文件、链接、越界 | 不覆盖；来源校验与独占写规则不变 |

仅使用合成小分子和现有脱敏夹具。开发阶段跑相关测试；推送前一次运行：
    PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs

记录通过数与跳过原因，之后以 CI 为准。按现行开发手册扫描精确暂存内容及有效私有词表，运行 git diff --cached --check，人工核对 PR 和提交身份。

## 真实环境验证

本单不需要提交测试计算：它只消费已有本地证据，不变更远程、状态、取回或模板。已有公开/脱敏非研究小分子输出可用于读取兼容核查，记录来源及覆盖范围；缺少三份真实配套 SMD 输出时明确只完成合成数值验证，不冒充现场验证或科学验收。不得使用真实研究补算来完成工程验收。

## 停止条件

现有能量/溶剂解析证据不足；需要改共享解析器或方法表；需要额外科学假设才可配对；范围越界；同一问题修两次未解决。真实环境意外按 AGENTS.md 停止报告。

## 合并前审阅与交付

- 必须监督方审阅，重点核对自身基组、复合物几何子集、溶剂实际执行证据、全来源操作数和旧行为。
- PR 第一行 Task: T165；附一套小分子合成报告及独立手算、失败矩阵、消费者兼容核查。
- 不修改 AGENTS.md；逐条处理绑定实际 head 的 ag-review 评论。人工合并，不发版、不部署。
