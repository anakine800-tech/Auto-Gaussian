# RDKit 本地构象初筛

## 1. 适用范围

主族、闭壳层、单个连通分子，所有原子能由 MMFF94s 或 UFF 参数化。不是金属、离子对、TS 或双分子相对取向搜索。

TS 族、关键中间体、复合物必须双路线；可旋转键较多的分子建议也走。
本卡适用的稳定单分子以 ETKDG 与 CREST 交叉核对；TS/复合物用 CREST +
定向构造约束 CREST（directed），不扩大本卡力场适用范围。详见
[conformer-workflow](../../auto-g16-structures/references/conformer-workflow.md)。

## 2. 前置条件

结构已由人签字，电荷、多重度和立体化学明确；新 `auto-g16-structures` Skill 及其初筛脚本可用。读该 Skill 的实际用法，不运行旧部署脚本。

## 3. 输入模板

把已审阅的 SMILES / ChemDraw 衍生结构交给 `auto-g16-structures` 初筛脚本，输出到 study 的 `structures/`。使用 ETKDGv3 并保持手性，完整记录随机种子、请求 / 成功构象数、能量窗口、RMSD 阈值和力场收敛情况。MMFF94s 全参数化时优先使用；否则仅在 UFF 也全参数化时回退。

生成后调用 `ag dedup`，需要代表分组时再用 `ag cluster`。参数名与输入形式读取各工具帮助；不在这里发明脚本文件名或 CLI 选项。力场窗口由 study 明确记录，不能把 CREST 的xTB 6 kcal/mol 窗口当成跨力场相同精度。
候选先按 [SP](sp.md) 做 DFT 单点重排，再选 DFT 单点能 3 kcal/mol 内
代表并请人确认集合和简并度，之后进入 opt-freq；优化后重新去重。
数值及优化层级筛选单点方法见[方法表](../../auto-g16-study/references/acceptance-methods.md)，负责人已于 2026-10-14 确认。

各路线独立预筛后，`ag dedup --source crest=crest.xyz --source etkdg=etkdg.xyz --charge 0 --out analyses`
按几何合并并保留所有来源，不跨方法比较能量。对合并候选用同层级 DFT 单点，
再执行 `ag coverage --merged analyses/dedup-TIMESTAMP.json --energies attempts/SP_A attempts/SP_B --window 3 --out analyses/coverage-01.md`。
先看输入几何（1e-4 Å、保留原子顺序）未匹配项，再看窗口总数、路线命中数、
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

- 成功生成非空候选集合，记录每个候选的力场名称、能量单位、收敛状态和警告。
- 元素组成、连通性与立体化学保持；轴手性需人工检查，不能只看四面体中心列表。
- `ag dedup` 输出无重复代表；聚类保留代表与成员对应关系、阈值、窗口和筛除原因。
- 展示代表及简并度给人签字；成员出现次数不直接等于物理简并度，依据不清就标待确认。
- 双路线来源及覆盖报告已审阅，未匹配项、低能独有项、警告与采样限制已记录。
- 明确结果是初筛；力场排序不能作为 DFT 自由能或最终 Boltzmann 布居。

## 7. 常见失败与处理

参数化失败、嵌入失败或手性改变时保存报告，提出修正结构或调整本地生成方案，等人确认受影响的结构 / 集合。初筛能力不足可提出 CREST 路线；若需要远程计算，提出新 Attempt，等人确认。

出现覆盖警告时增加 ETKDG 随机种子/候选数（仍标 etkdg）、延长 CREST 有效采样（去掉快速模式、给足 walltime），或由结构 Skill 按特定相互作用/进攻方向假设搭建初猜再用约束 CREST，来源标 directed。新增远程计算经人确认；重做合并、同层级 DFT 重排和覆盖报告，不自动扩样或重提。

## 8. 常见坑

知识衔接：[GKB-0420：局部极小点与构象覆盖](../../auto-g16-gaussian-learning-library/references/core-job-types.md)。

- ChemDraw 显式氢和楔形键丢失会改变立体化学；ETKDG 的手性保持不能修复输入时已丢失的信息。来源：`skills/auto-g16-view-rt-win/references/conformer-workflow.md`。
- 无四面体手性中心不代表没有轴手性；自动几何仅是初猜。来源：`skills/auto-g16-view-rt-win/references/chemistry-boundaries.md`。
- 力场能量不能与 Gaussian 电子能或自由能混排。来源：`skills/auto-g16-view-rt-win/references/conformer-workflow.md`。
