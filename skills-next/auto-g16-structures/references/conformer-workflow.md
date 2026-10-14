# Force-field conformer screening

Adapted from `skills/auto-g16-view-rt-win/references/conformer-workflow.md`.

After human structure confirmation, use one connected molecular graph, preserving
ChemDraw explicit-H wedge/dash stereochemistry. Unassigned tetrahedral centers
and conflicting or unsupported CFG values stop generation.

The migrated algorithm embeds with ETKDGv3 and `enforceChirality=True`, initially
prunes at 0.1 Å, and retries embedding with random coordinates if no conformers
were found. This is local geometry generation, not a remote job retry. It uses
MMFF94s when all atoms are parameterized, otherwise fully parameterized UFF.

Defaults are 50 requested conformers, seed 61453, 1000 minimization iterations,
6 kcal/mol energy window, 0.5 Å all-atom symmetry-aware best-RMSD threshold and at
most 10 retained conformers. Change `--num-conformers`, `--seed`, `--max-iters`,
`--energy-window`, `--rmsd-threshold`, or `--max-keep` deliberately. These are the
legacy screening defaults, not a claim that sampling is complete.

`conformers.xyz` contains retained explicit-H frames in increasing force-field
energy order. Each comment starts with energy in kcal/mol, then the force-field
name. `summary.json` records input identity, supplied multiplicity, parameters,
conformer IDs, absolute/relative energy, nearest kept RMSD, convergence and
warnings. A nonconverged conformer remains flagged for review. The UFF fallback
is disclosed even when minimization converges.

Inspect identity, CIP centers, source atom count, formula, explicit-H count,
force-field fallback, convergence and 3D geometry. Inspect axial configuration
separately. For the combined CREST/ETKDG route, optimize the reviewed ensemble
with CREST `--mdopt` at the same xTB level before merging and energy filtering;
review the resulting representative set with the researcher. Multiple representatives can proceed;
there is no single-conformer selection step.

For the T12b research workflow confirmed on 2026-10-14, retain enough force-field candidates
for same-method CREST `--mdopt` optimization, merged xTB filtering, and DFT
single-point reranking before applying the DFT optimization count limit.
The script's legacy `--max-keep 10` is not that research limit; deliberately
choose and record candidate coverage. The force-field window is not an xTB
window. See the [screening card](../../auto-g16-recipes/cards/rdkit-screen.md)
and [confirmed methods](../../auto-g16-study/references/acceptance-methods.md).
Refine relevant representatives with the same selected DFT protocol. Reject
failed optimizations and inappropriate imaginary frequencies when modeling
minima. Check whether different starting conformers converge to the same
structure. Use the reviewed thermochemistry workflow for final relative Gibbs
energies and populations; do not mix force-field and DFT energies.

## 双路线交叉核对

TS 族、关键中间体、复合物必须走双路线；可旋转键较多的分子也建议走。
普通、连通且可参数化的稳定分子用 CREST + RDKit ETKDG；TS 与断开的
复合物不能强塞进本地力场脚本，用 CREST + 按机理假设定向构造的约束
CREST (`directed`) 交叉核对。这两条路线仍共享 CREST 引擎，报告此局限。
采样引擎仍是 CREST/RDKit，不自写 MD 或退火引擎。

每条路线先独立审核身份、立体化学和收敛，保留足够候选。
ETKDG 的多帧 XYZ 必须先按 [CREST 卡片](../../auto-g16-recipes/cards/crest-screen.md)
用 `--param=--mdopt` 做逐帧优化；与 CREST 路线使用相同 GFN2-xTB、溶剂、
电荷及自旋。prepare 校验 1–1000 帧、原子数/元素序列一致、有限坐标。
经人确认提交，status → fetch → facts 后取得 Attempt 下的 `mdopt.xyz`，
每帧注释为优化后的 Hartree 能量。力场预筛窗口不是 xTB 的 6 kcal/mol 窗口，
不要用旧默认 `--max-keep 10` 提前截断研究候选；记录预筛造成的覆盖局限。
审阅结果后先合并两路线，再相对共同最低 xTB 能量开 6 kcal/mol 窗口并去重，
保留足够候选供 DFT 单点重排。
相同方法多种子可以反复使用同一个路线名，不把多个 ETKDG 种子伪装成多条路线。
把审阅过的多帧 XYZ 合并（以下路径均为 study 内占位符）：

```text
ag dedup --source crest=crest.xyz --source etkdg=attempts/ETKDG_MDOPT/mdopt.xyz --representative lowest --de 0.05 --hydrogens polar --window 6 --charge 0 --out analyses --json
ag coverage --merged analyses/dedup-TIMESTAMP.json --energies attempts/SP_A attempts/SP_B --window 3 --out analyses/coverage-01.md
```

`--hydrogens heavy|polar|all` 默认 polar，比较重原子及 N/O/S/P 上的氢，
保留 OH 等极性氢朝向；普通甲基转动仍可合并。涉及氢键或参与反应的氢必须
参与构象区分，若包括 C–H 等其他氢，选择 all。heavy 仅比较重原子。
原始原子顺序与坐标保持不变，仅临时比较副本筛选原子并做对称性比对。
JSON 的 hydrogens 记录实际模式；每次合并的 heavy_rmsd 是重原子 RMSD，
rmsd 是实际判定用的 RMSD（Å），两者分别拟合，不能互换作判据。

`--source` 按身份与所选原子的 RMSD 合并，重复构象的 `sources` 保留实际合并的全部路线，
`members` 保留原始文件、帧号、路线与原能量。显式 `--representative lowest`
表示人已确认各来源能量可比，要求所有帧为有限 Hartree 能量，按最低能选代表，
并接受 `--window 6`；合并还要求能差小于 `--de`（默认 0.05 kcal/mol，可显式调整）。CREST 来源取 `crest_conformers.xyz` 的绝对能量注释。
代码不能从 Hartree 单位验证相同方法，GFN-FF 与 GFN2-xTB 不能混排；
定向约束路线只有在确认约束及能量口径一致后才加入此窗口。

省略 lowest 时保留原来的几何合并行为：代表按输入次序，允许不同方法/单位，
不接受 `--window` 或 `--de`；合并来源始终不接受 `--energies`、`--energy-unit`
或位置输入。位置输入的能量规则不变，但氢模式默认改为 polar；不能靠转换单位比较力场与 xTB 能量。

对合并后的每个候选原样制作 DFT 单点输入，使用一致方法、基组、溶剂、
电荷与多重度。`ag coverage` 读取已有 facts，不运行 DFT、不重写 facts。
coverage 与 cluster 自动继承 dedup 的 hydrogens；旧 JSON 缺少字段时按 heavy
解释。旧 heavy 结果已丢失的氢朝向无法恢复，涉及相关氢时重新去重。
对应按候选与 Attempt **输入**的元素顺序及所选原子坐标距离 ≤ 1e-4 Å 建立；
不按名称、也不旋转/平移或交换原子。为保证可追溯，输入须符合 manifest 哈希。
重复能量映射、缺失或歧义均列为未匹配，不静默挑最低值。
若优化后几何变了，不能把原候选名称当成对应依据；重新整理候选和输入映射。

`--energies` 也接受 JSON 字符串列表（相对路径相对于列表文件），或原生
`ag thermo` 的 `ag-thermo/1` JSON 表；不接受 Markdown 表。Attempt ID 用
`--study STUDY` 解析；原生 analyses/ 热化学表可从所在目录找到 study。
单点用 SCF Hartree，热化学表用 qh_G Hartree（含表内 SPC 修正）；不要混用。
热化学模式仍按频率 Attempt 的输入匹配，使用者须审阅该输入与最终构象关系，
不能用这张报告宣称优化后的几何覆盖。覆盖报告不验证方法适用性或热化学科学判据。

先读未匹配 Attempt/候选，再看 DFT 窗口内构象数、各路线命中数、最低
`--top N` 个（默认 5）及单路线独有的低能构象。能量窗口相对唯一匹配集合
最低值、含边界；最低 N 个从全部已匹配候选列出。路线计数有交集，不能相加
当总数。没有匹配能量时窗口为空，零计数不能解释成不存在低能构象。
最低能构象（含并列）仅一条路线找到，或窗口内严格超过一半仅由某条路线找到，
报告“采样可能不足”。这是计数提示，**覆盖报告不能证明采样已经完备**；
没有警告也不是科学验收。`--out` 必填且已存在即拒绝；`--json` 写 JSON，
默认写 Markdown。报告只读输入，不自动决定、生成或提交下一步。

出现警告时，LLM 与人结合遗漏构象讨论扩大采样：CREST 去掉快速模式并给足
walltime（只加 walltime 不会自动增加已正常结束的采样）；增加 ETKDG 种子和
候选数；加入下述定向构造。延长轨迹的其他参数须先经过模板白名单审阅，
不得透传未审阅选项。新远程 Attempt 仍须人确认及 Mac 点击；完成后重做合并、
同层级 DFT 重排并用新文件名重出报告，记录限制，不能因警告自动重提。

## 定向构造

1. 明确一个可检验的结构假设：氢键、离子对接触、催化剂/底物相互作用，
   或亲核进攻方向/反应面。记录备选取向，避免仅围绕预期答案构造。
2. 在结构 Skill 中以已审阅结构为基础搭建特定取向的 Cartesian XYZ；
   保留各片段身份、原子顺序和立体化学，记录总电荷/多重度、质子位置。
   片段可先分别准备，按明确距离/角度放置后逐项审阅；现有 connected-only
   RDKit 脚本不负责拼接复合物，也不把人工构造当已优化结构。
3. 与人核对所约束原子编号、目标距离/角度/二面角，按照
   [CREST 卡片](../../auto-g16-recipes/cards/crest-screen.md) 用 `--constraints`
   准备约束 CREST；非共价复合物可配 `--nci`。假设和约束会引入偏向，需记录。
4. 把这条路线结果标为 `--source directed=...`；普通 CREST 仍标 `crest`。
   约束采样不能证明 TS；TS 候选仍逐个审阅一个虚频及方向，IRC 双向完成并识别端点。

## 聚类代表

`ag cluster --representative lowest|medoid` 默认 lowest，保持旧输入的最低能
代表行为。medoid 在原有簇内选到其他成员的所选原子 RMSD 之和最小的成员；
平局按能量、输入顺序，使用 `--mirror` 时同原有镜像能差条件取更小镜像 RMSD。
聚类分组仍由原算法生成；输出 `representative_method`、medoid RMSD 总和，
成员中的 reason/rmsd/heavy_rmsd 是相对原簇种子的归属证据，`cluster_seed_index` 标识该种子。
直接分组、镜像判断及 medoid 均使用继承的氢模式；镜像合并的两个 RMSD 都比较镜像坐标。
未经能量统一的来源合并集合只允许 medoid 且不启用镜像能差判断，平局按输入顺序。
ETKDG 经 `--mdopt` 且按上述 lowest 模式合并后，已建立同层级能量集合，
可继续用 `ag cluster --representative lowest`。medoid 是几何中心
代表，不保证低能，也不能在覆盖报告之前靠聚类数量上限截掉 DFT 候选。
