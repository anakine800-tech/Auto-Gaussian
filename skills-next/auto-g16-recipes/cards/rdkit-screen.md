# RDKit 本地构象初筛

## 要点

- 只用于所有原子可由 MMFF94s 或 UFF 参数化的主族闭壳层单个连通分子；不用于金属、离子对、TS 或双分子取向搜索。（[见第 1 节](#1-适用范围)）
- 结构须已由人签字，电荷、多重度和立体化学明确；使用新 structures Skill 的实际初筛用法。（[见第 2 节](#2-前置条件)）
- 氢键或反应相关氢须参与构象区分；相关氢连在 C 等非 polar 范围元素上时选择 all，旧 heavy 结果不能恢复丢失的氢朝向，需重新去重。（[见第 3 节](#3-输入模板)）
- 生成证据清单后请人签代表及简并度；成员出现次数不直接等于物理简并度，依据不清标待确认。（[见第 6 节](#6-结果判据清单)）
- 结果只是初筛；力场排序不能作为 DFT 自由能或最终 Boltzmann 布居。（[见第 6 节](#6-结果判据清单)）

## 1. 适用范围

主族、闭壳层、单个连通分子，所有原子能由 MMFF94s 或 UFF 参数化。不是金属、离子对、TS 或双分子相对取向搜索。

关键中间体须保留双路线；本卡适用的稳定单分子用 ETKDG 与 CREST 交叉核对。
普通稳定分子不因做过 CREST 就一律要求补 ETKDG；可旋转键较多时建议交叉核对，
已签方案要求的来源不能无依据删去。TS/复合物也须双路线，但用已审阅初猜的
约束 CREST + 定向构造约束 CREST（directed），不扩大本卡力场适用范围。
来源选择与比较分支详见[分支表](../../auto-g16-structures/references/conformer-workflow.md#分支选择)。

## 2. 前置条件

结构已由人签字，电荷、多重度和立体化学明确；新 `auto-g16-structures` Skill 及其初筛脚本可用。读该 Skill 的实际用法，不运行旧部署脚本。

## 3. 输入模板

把已审阅的 SMILES / ChemDraw 衍生结构交给 `auto-g16-structures` 初筛脚本，输出到 study 的 `structures/`。使用 ETKDGv3 并保持手性，完整记录随机种子、请求 / 成功构象数、能量窗口、RMSD 阈值和力场收敛情况。MMFF94s 全参数化时优先使用；否则仅在 UFF 也全参数化时回退。

研究命令显式填写 `--num-conformers N_REQUESTED --max-keep N_KEEP`，两者用
本研究已审阅整数替换，并写明保留数量的覆盖/预算依据。核对 summary 中实际
生成与保留数；默认 `--max-keep 10` 可能在 xTB/DFT 前截断，不是 DFT 优化上限。
以上是待填骨架，未填数量和依据不能视为已审阅研究方案；没有依据时保留数量
待决定，不统一替换成某个更大的固定值。

生成后按下述 A 或 B 分支调用 `ag dedup`，需要代表分组时再用 `ag cluster`。
力场窗口由 study 明确记录，不能把 CREST 的 xTB 6 kcal/mol 窗口当成跨力场相同精度。
去重使用 `--hydrogens heavy|polar|all`，默认 polar 保留 N/O/S/P 上的氢，避免丢失 OH 等转子；普通甲基转动仍可合并。
涉及氢键或参与反应的氢必须参与构象区分；若相关氢连在 C 等其他元素上，选择 all。
coverage 与 cluster 继承 dedup JSON 的 hydrogens（旧文件无字段时为 heavy）；旧 heavy 结果无法恢复丢失的氢朝向，需重新去重。
每次合并记录 heavy_rmsd 和实际判定 rmsd（Å），核对阈值是否保留了目标氢朝向。
候选先按 [SP](sp.md) 做 DFT 单点重排，再选 DFT 单点能 3 kcal/mol 内
代表，手动模式请人确认集合和简并度后进入 opt-freq；符合 [AGENTS 自主运行规则](../../../AGENTS.md#自主运行)时可按计划暂定选择并标“待人确认”，仍须负责人签字。优化后重新去重。
数值及优化层级筛选单点方法见[方法表](../../auto-g16-study/references/acceptance-methods.md)，负责人已于 2026-10-14 确认。

**A：统一 xTB 后合并。** 要在共同 xTB 标度筛选时，ETKDG 系综先按
[CREST 卡片](crest-screen.md#etkdg-系综统一到-xtb-能量)做同方法 mdopt，
保留 etkdg 来源标签。与 CREST 的方法、溶剂、电荷、自旋和约束口径一致且经审阅后，
才选择 `--representative lowest`、共同 `--window 6` 及 `--de`（默认 0.05 kcal/mol）；
几何和能差均通过才合并。Hartree 单位相同不能证明方法可比。

**B：仅几何合并后统一 DFT。** 各路线独立预筛后，
`ag dedup --source crest=crest.xyz --source etkdg=etkdg.xyz --hydrogens polar --charge 0 --out analyses`
按输入顺序做几何合并并保留来源，无需先 mdopt；不用 lowest、window 或 de，
不跨方法比较能量。几何相近不保证等能，首个代表不保证最低能；保留原始帧供复核。

两分支都记录每个来源实际保留数、上限及依据，保留 [SP](sp.md) 要求的窗外
独特验证对象；各自的预筛窗口也可能漏候选。不能在 DFT 重排前靠聚类数量上限截断。
对合并候选用同层级 DFT 单点，再执行 `ag coverage --merged analyses/dedup-TIMESTAMP.json --energies attempts/SP_A attempts/SP_B --window 3 --out analyses/coverage-01.md`。
先看所选原子的输入几何（1e-4 Å、保留原子顺序）未匹配项，再看窗口总数、路线命中数、
最低 5 个构象来源和单路线独有低能构象。最低构象单路线独有或某路线独占
超过窗口一半会警告“采样可能不足”；无警告不代表充分，覆盖报告不能证明采样已经完备。
可选 `--top N` / `--json`；`--out` 必填且不能覆盖。
聚类默认 lowest 保持原行为；`--representative medoid` 选簇内 RMSD 总和最小成员。
不同方法来源合并后只用 medoid，不按原始力场/xTB 能量选最低者。

## 4. 资源建议

本地运行，不占集群档位，也没有 PBS walltime。少于约 50 原子的普通分子可从 50 个 ETKDG 候选起步；柔性较大时按覆盖情况提出扩大样本，记录实际耗时。DFT 重排后进入优化的去重代表最多研究 20 个、验收 10 个，不在重排前套用此上限；达到上限要说明截断，不能声称搜索穷尽。

## 5. 提交前检查清单

- 本任务不提交；确认源结构、显式氢、楔形键、电荷和立体化学已经正确解释。
- 初筛脚本实际支持所需参数；参数化失败、未指定手性或断开结构先报告。
- 输出写在 study 中，源结构和每个构象的身份映射可以追溯。

## 6. 结果判据清单

- 成功生成非空候选集合，记录请求/成功/保留数量、保留上限及依据，以及每个候选的力场名称、能量单位、收敛状态和警告。
- 元素组成、连通性与立体化学保持；轴手性需人工检查，不能只看四面体中心列表。
- `ag dedup` 输出无重复代表；聚类保留代表与成员对应关系、氢模式、两种 RMSD、阈值、窗口和筛除原因，氢键或反应相关氢参与区分。
- 先运行 `ag review manifest --study <dir>` 生成证据清单，再展示代表及简并度给人签字，并记录清单路径及 SHA-256；成员出现次数不直接等于物理简并度，依据不清就标待确认。
- 所选比较分支与来源要求一致：A 的 ETKDG 经同层级 mdopt 后才作共同 xTB 能量筛选，B 仅几何合并后统一 DFT 重排；按方案所需的双路线来源及覆盖报告已审阅，未匹配项、低能独有项、警告与采样限制已记录。不适用双路线时写明依据，不把缺来源当作充分覆盖。
- 明确结果是初筛；力场排序不能作为 DFT 自由能或最终 Boltzmann 布居。

## 7. 常见失败与处理

参数化失败、嵌入失败或手性改变时保存报告，提出修正结构或调整本地生成方案，等人确认受影响的结构 / 集合。初筛能力不足可提出 CREST 路线；若需要远程计算，新 Attempt 按 [Study 流程](../../auto-g16-study/SKILL.md)取得对应模式授权。

出现覆盖警告时增加 ETKDG 随机种子/候选数（仍标 etkdg）、延长 CREST 有效采样（去掉快速模式、给足 walltime），或由结构 Skill 按特定相互作用/进攻方向假设搭建初猜再用约束 CREST，来源标 directed。新增远程计算按上述模式规则取得授权；重做合并、同层级 DFT 重排和覆盖报告。警告本身不授权扩样，不重提旧 Attempt。

## 8. 常见坑

本节历史来源链接固定到 `v3-frozen`，仅用于追溯经验出处；现行执行以本卡为准，不沿用冻结文档中的流程。

知识衔接：[GKB-0420：局部极小点与构象覆盖](../../auto-g16-gaussian-learning-library/references/core-job-types.md)。

- ChemDraw 显式氢和楔形键丢失会改变立体化学；ETKDG 的手性保持不能修复输入时已丢失的信息。来源：[conformer-workflow.md（v3-frozen）](https://github.com/anakine800-tech/Auto-Gaussian/blob/v3-frozen/skills/auto-g16-view-rt-win/references/conformer-workflow.md)。
- 无四面体手性中心不代表没有轴手性；自动几何仅是初猜。来源：[chemistry-boundaries.md（v3-frozen）](https://github.com/anakine800-tech/Auto-Gaussian/blob/v3-frozen/skills/auto-g16-view-rt-win/references/chemistry-boundaries.md)。
- 力场能量不能与 Gaussian 电子能或自由能混排。来源：[conformer-workflow.md（v3-frozen）](https://github.com/anakine800-tech/Auto-Gaussian/blob/v3-frozen/skills/auto-g16-view-rt-win/references/conformer-workflow.md)。
