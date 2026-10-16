# T68：RDKit 坐标推断风险验证

验证日期：2026-10-16。被测基线：`36e6c1f`（ag 4.2.0）。环境：macOS、
Python 3.11.15、RDKit 2026.03.3。只新增测试、合成 XYZ、报告和工单；未改源码，
未连接集群，未读取 HSS、BCB 或其他研究结构、日志或已签证据。

**结论：22 个常规合成几何的连接、总电荷及可指派立体身份通过本次检查；
这不能外推为所有含硼/离子体系均可靠。** 发现两类限制：

- **R1：局域共振表示未保留。** nitronate 的 C 负离子写法被改为 O 负离子写法。
  总电荷和化学身份仍相容，不能把它称为错误分子，但不能把推断的逐原子形式电荷当作电子密度证据。
- **R2：不确定接触的顶层状态发生提升。** 第 23 个边界几何中 B–O = 2.2 Å，
  `irc-compare` 返回“无法确定”，`topology` 却因确定边片段数从 1 到 2 返回 `changed`。
  详细警告和键级/立体 `unknown` 仍保留，所以不是完全静默的错误；只取顶层状态有误读风险。
  **请监督方优先审阅 R2；本报告不判断任何已签 study 是否受影响。**

## 模型、独立预期与可复现方式

测试：[test_inference_risk.py](../../ag/tests/test_inference_risk.py)。
全部坐标：[fixtures/inference](../../ag/tests/fixtures/inference)。
工单：[T68](../redesign-tasks/T68-rdkit-inference-validation.md)。

12 个基础模型在测试的 `SMILES` 中明示连接、氢数、电荷、立体标签。XYZ 生成过程为
`Chem.AddHs` → ETKDGv3（seed 6801）→ UFF（maxIters 2000，均返回收敛码 0）。
衍生几何使用固定小扰动、镜像、片段平移或保留原子映射的质子转移。
UFF 收敛只是生成条件，不是量化优化、稳定物种或可行反应的证据；尤其 BH3、混卤硼酸根
及边界接触只作为算法模型。

测试从独立声明的 SMILES 图取得逐原子键表、键级、形式电荷、总电荷、连通分量，
与 XYZ 的推断结果逐项比较；不以“自身比较 unchanged”证明推断正确。
预期图的解析和坐标嵌入仍使用 RDKit，因此这是针对 `DetermineBonds` 的独立图预期，
不是对 RDKit 全部功能的独立化学认证。文件行序是 SMILES 重原子顺序加 `AddHs` 顺序；
派生文件保持编号，质子转移对的 F 与转移 H 放在最后两行。

从仓库根目录、已有依赖的 Python 环境运行：

```sh
PYTHONPATH=ag/src python -m pytest ag/tests/test_inference_risk.py -q -rxX
PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs
```

重生成只写入一个新的空目录；不会覆盖现有 fixture。不同 RDKit 版本不保证生成坐标逐字节一致，
日常测试读取已冻结 XYZ，不重新嵌入。可用下列命令审阅生成过程：

```sh
PYTHONPATH=ag/src python ag/tests/test_inference_risk.py --generate-fixtures NEW_EMPTY_DIRECTORY
```

共 23 个 XYZ：12 个基础模型、N–Bpin 小扰动 1 个、硼配合物分离态 3 个、镜像 2 个、
守恒质子转移对 4 个、B–O 不确定接触 1 个。硝基甲烷 O→BH3 模型的配位氧原先是 O⁻，
成键后是中性 O；电荷为 N⁺/B⁻，并非每个含氧硼加合物都必须写成 O⁺/B⁻。

## 验证摘要表

“键正确”包括编号对应的键级；“电荷正确”包括逐原子形式电荷和总电荷。
“微扰”指每个坐标分量交替 ±0.0001 Å；常规模型均同时验证
`graph_key`、`stereo_key` 及比较结果不变。无手性模型的立体键不变不代表已验证手性分辨能力。
CLI 的 minimum 是工具模式，不是科学上的极小点确认。表中 `匹配/不匹配/无法确定` 是 IRC 工具状态。

| 模型（对应文件名 stem） | 推断成功 | 键是否正确 | 电荷是否正确 | topology minimum / IRC 判断 | 立体判断 | 失败方式或限制 |
| --- | --- | --- | --- | --- | --- | --- |
| `nbpin` / `nbpin_perturbed`：N–Bpin-1,4-二氢吡啶 | 是 | 是 | 是，q=0，全中性 | unchanged；端点/参考匹配，两个相同目标不能唯一分配方向 | 微扰不变；无指定手性中心 | 未见错误 |
| `acetone_bf3` / `acetone_bf3_separated` | 是 | 是，B–O 断开 | 是，配合物 O3⁺/B4⁻，分离态中性，总 q=0 | changed；片段 1→2；正确端点匹配，交叉不匹配 | 微扰不变；无指定手性中心 | 未见错误；不推断实际解离能 |
| `ester_bh3` / `ester_bh3_separated`：乙酸甲酯羰基配位 | 是 | 是，B–O 断开 | 是，O5⁺/B6⁻→中性，总 q=0 | changed；片段 1→2；IRC 匹配/交叉不匹配正确 | 微扰不变；无指定手性中心 | 未见错误 |
| `nitro_bh3` / `nitro_bh3_separated`：硝基氧配位 | 是 | 是 | 是，N2⁺/B5⁻→N2⁺/O4⁻，总 q=0 | changed；片段 1→2；IRC 匹配/交叉不匹配正确 | 微扰不变；无指定手性中心 | 未见错误；配位氧不是 O⁺ |
| `nitronate` / `nitromethane`：裸阴离子与质子化形式 | 是 | 共振等价；C 局域写法未保留 | 总 q=-1/0 正确；阴离子的 C⁻移为 O⁻ | 各自微扰 unchanged/匹配；直接跨物种比较因少/多一个 H：topology unknown，IRC 不匹配 | 微扰不变 | R1：无警告的表示变化，非已证实的化学身份错误；裸对不能沿用原子映射 |
| `nitronate_hf` / `nitronate_protonated_f`：阴离子+HF→硝基甲烷+F⁻ | 是 | 共振等价；H 的 F→C 归属正确 | 总 q=-1 正确，局域表示同 R1 | changed；片段 2→2；质子转移有明确编号；IRC 匹配/交叉不匹配正确 | 微扰不变 | R1；没有把质子转移漏报为 unchanged |
| `enolate` / `ketone`：O 局域负离子与丙酮 | 是 | 是 | 是，O3⁻/中性，总 q=-1/0 | 各自微扰 unchanged/匹配；裸对因 H 数不同：topology unknown，IRC 不匹配 | 微扰不变 | 显式映射拒绝；不是错误认同 |
| `enolate_hf` / `enolate_protonated_f` | 是 | 是，C–H 成键和 F–H 断键 | 是，O3⁻→F10⁻，总 q=-1 | changed；片段 2→2；IRC 匹配/交叉不匹配正确 | 微扰不变 | 未见错误 |
| `zw_open` / `zw_closed`：亚胺鎓/O⁻开链→氨基环丁酮 | 是 | 是，闭环 C2–C6 成键，键级按独立图正确 | 是，N1⁺/O5⁻→中性，总 q=0 | changed；片段 1→1；无质子迁移；IRC 正确匹配并报告 formed | 微扰不变；本模型无手性中心 | 距离差异使 topology 提前返回，键级/立体 assessment 仍 unknown；不得把空立体差异当作确认 |
| `boron_adjacent` / `boron_adjacent_mirror`：B 邻位手性碳 | 是 | 是，两者 graph_key 相同 | 是，q=0 | changed；IRC 自身匹配、镜像不匹配，理由为立体 | stereo_key 不同，C2 构型反转；微扰不变 | 未见错误 |
| `borate` / `borate_mirror`：四配位 B(F)(Cl)(Br)(I)⁻ | 是 | 是，两者 graph_key 相同 | 是，B1⁻，q=-1 | changed；IRC 自身匹配、镜像不匹配，理由为立体 | stereo_key 不同，B1 构型反转；微扰不变 | 未见错误；不代表实际构型稳定性 |
| `acetone_bf3` / `acetone_bf3_stretched`：B–O=2.2 Å 边界 | 是，但选择分离图 | 物理成键真值未指定；按 ag 规则应保留不确定性 | 推断选择中性分离片段，总 q=0；不能从 XYZ 确认局域电荷 | topology changed（片段 1→2）；IRC 无法确定 | 未评估，assessment unknown | R2：顶层状态失去不确定性；细节仍有警告，不是完全静默 |
| `enolate`、`borate` 人为错填 q=0（不新增 XYZ） | 否 | 未获得 | 输入电荷与可行价态不相容 | 两个 CLI 均返回 unknown/无法确定；退出码 0 表示报告生成成功 | 未评估 | infer_molecule 明确 ValueError；工具不假报匹配；硼酸根的表层理由是距离不确定，未直接展示底层电荷异常 |

每个常规模型还检查：显式给出的端点/参考总电荷相差 1 时，`compare_endpoint` 明确返回
`不匹配` 且理由为 `charge 不同`。这只验证已提供元数据的冲突处理，不能证明元数据本身真实。
CLI 测试逐个核对输入 manifest、facts 和 XYZ 的字节与 mtime 保持不变；所有文件均在临时合成 Attempt 内。

## 两项风险及建议方向（本轮不修复）

### R1：形式电荷/键级是被选中的表示，不是坐标给出的唯一事实

本模型声明 `[CH2-][N+](=O)[O-]`，推断得到 `C=[N+]([O-])[O-]`。
编号 1–4 为 C/N/O/O；形式电荷由 `(-1,+1,0,-1)` 变成 `(0,+1,-1,-1)`，
C–N 从单键变双键，原 N=O 从双键变单键，总电荷一直为 -1，氢没有移动。
测试允许这两种明示的共振图作为同一身份的预期，同时用两个 `strict=True`、
`raises=AssertionError` 的 xfail 单独暴露“保留指定局域表示”的失败。
**不把两个共振式的差异说成质子转移，也不把 q 正确当作逐原子电荷正确。**

影响：`geometry.infer_molecule`、`graph_key`，以及使用它们的 `ag topology` / `ag irc-compare`。
建议后续工单明确区分共振等价性、键级表示差异与化学身份差异，并在需要局域图时引入
已审阅的显式结构参照；不要只靠坐标猜测电子分布。是否调整比较口径由监督方审阅，
不能简单忽略全部电荷/键级差异。

### R2：片段数规则可能覆盖上游 unknown

在 B–O=2.2 Å 时，共价半径和为 1.50 Å，比值约 1.466667，位于当前 `[1.2,1.5]`
不确定区间。`compare_endpoint` 把 `[3,4]` 放入 `ambiguous_bonds`，不报告确定断键。
随后 `topology._check_fragments_and_mapping` 只统计确定相连边，得到 1→2，
把顶层状态提升成 `changed`。与此同时 `bond_differences=[]`，
`bond_order_and_stereo_assessment.status=unknown`，原因仍写着“XYZ 距离不能确定成键”。

一个严格 xfail 要求这个边界比较保留顶层 unknown；另一个通过测试固定警告、2.2 Å、
片段数、IRC unknown 和实际 RDKit 分离图，避免用 xfail 隐藏其他失败。
这里不主张 2.2 Å 必然成键或断键，暴露的是状态汇总与不确定证据之间的差异。

影响：直接影响 `ag topology` 的 minimum 状态汇总；`ag irc-compare` 在本例正确保留 unknown。
建议另开工单审阅：不确定边导致的片段数变化是否应保留 unknown，并区分“确定边分量数变化”
和“化学片段已解离”。相关实现见
[topology.py](../../ag/src/ag/topology.py) 与 [irc_compare.py](../../ag/src/ag/irc_compare.py)。

**已由 T73 修复。** 以下为修复后的口径，以上 T68 原始观察保留：
`topology` 对提交和最终结构分别按不确定接触“相连／不相连”计算片段数；
只有两种处理都出现同向变化才因片段数判为 `changed`，两者都不变则继续原有比较，
其他情况保留片段数不确定性，原因列明跨确定片段的不确定接触编号、元素、距离和半径比。
按 T73 v2 审阅修订：若 `compare_endpoint` 已因确定的 `bond_differences` 返回 `changed`，
顶层保持 `changed`，追加片段数不确定性的说明；没有这种确定键变化时才保留 `unknown`。
B–O=2.2 Å 样例由 `changed` 改为 `unknown`，与原有 `irc-compare` 一致；
原 R2 strict xfail 改为正常回归断言，R1 的两个 xfail 保持不变。
`fragments.submitted/final` 仍是确定边结果；存在不确定接触时才补充
`fragments_if_uncertain_bonded` 和 `fragment_change_depends_on_uncertain_contacts`，
无不确定接触的 JSON 保持原字节（版本来源字段除外）。阈值、默认 `ag fragments`
输出、`irc-compare` 和既有证据不变。本修复不判断任何已签 study 是否受影响；
合并后由 HSS 主会话按 [T73 工单](../redesign-tasks/T73-topology-uncertain.md)
在 study 外新建临时报告，逐项比较并交监督方判断。

### 可用范围与人工核对重点

在本次固定样例、正确电荷、正确原子映射和正常键长下，可以使用工具提供的连接变化、
质子归属、片段数以及可指派的含硼立体差异作为辅助证据。没有观察到常规样例
静默推断成错误化学身份，或把这两组对映体静默判为相同。

nitronate/其他可能有共振的离子、拉长配位键、弱接触、未知电荷、未指派立体以及
原子顺序变化仍须人工核对；有限合成样例不能覆盖其他溶剂、金属、开壳层、实际反应路径，
也不能验证未输入 XYZ 的电子态。不得仅凭 `unchanged`、graph_key 相同、空差异列表
或 CLI 退出码 0 给研究结果签字。推断失败的底层原因可在后续工单中改进诊断展示，
影响 `topology` / `irc-compare`，但本轮不更改错误处理。

## 验证记录

- 新增测试：**93 passed，3 xfailed**。3 项均 `strict=True`，仅接收 AssertionError；
  其中 2 项为 R1 的局域表示要求，1 项为 R2 的顶层 unknown 要求。
- 全量命令：`PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`：
  **2558 passed，3 skipped，3 xfailed**（197.87 秒）。跳过 2 项 Linux 专用远端方言测试
  和 1 项未启用的私有日志测试；未加载私有日志。另有 1 条 pytest 缓存写权限警告，
  不影响断言或测试结果。
- `python ag/tools/scan_sensitive.py --staged` 与 `git diff --cached --check`：通过。
  人工检查改动仅含获准的测试、合成 XYZ、报告和工单；提交身份已核对为 noreply。
- 真实环境验证：工单不要求；没有连接集群或提交作业。
- 当前阻塞类别：**科学审阅**。需要监督方确认报告解释和后续修复范围；本任务不实施修复。

## 给 HSS 主会话的只读核查说明

本节供唯一负责该 study 的主会话在计算机本地执行，不授权其他会话推进 study，
也不要求重新取回、解析、刷新、提交或取消任何作业。T68 没有读过 028 的文件或已签清单，
不据本报告推断其拓扑结论或签字是否有误。

1. 确认实际检出版本、RDKit 版本和被检查 Attempt。使用已保存的 `manifest.json`
   中提交种子与已有优化末帧，先验证元素序列、全部 H 和原子编号一致；核对原始输入、
   manifest 声明的总电荷与多重度。优先 `final_input.xyz`，缺失时才使用 `final.xyz`。
   不运行 `ag facts --refresh`，不改写已有证据。
2. 在该 study 的 `analyses/` 选择一个从未存在的新报告名，例如带时间后缀。
   通过当前检出的 ag 运行以下命令（变量由主会话设置）：

   ```sh
   ag topology "$ATTEMPT" --out "$STUDY/analyses/topology-028-T68-NEW.json" --json
   ```

   命令只读取已有输入并独占创建新的分析 JSON/Markdown。检查 `status`、`reasons`、
   `bond_differences`、`ambiguous_bonds`、`proton_differences`、`fragments` 和
   `bond_order_and_stereo_assessment` 的组合，不能只抄 changed/unchanged。
3. 像本测试一样，对种子和末帧分别调用 `infer_molecule`，打印全部编号键、键级、
   形式电荷、总电荷、graph_key 和 stereo_key。以下示例仅向终端输出，不写文件：

   ```sh
   PYTHONPATH=ag/src python - "$ATTEMPT" <<'PY'
   import json, sys
   from pathlib import Path
   from rdkit import Chem
   from rdkit.Chem import rdDetermineBonds
   from ag import geometry as geo, topology

   root = Path(sys.argv[1])
   science = json.loads((root / 'manifest.json').read_text())['science']
   charge = science['charge']
   assert type(charge) is int
   assert not science.get('structures'), '多结构输入须先人工选择对应种子'
   seed = topology._frame(science['geometry'])
   final_path = root / 'final_input.xyz'
   if not final_path.exists():
       final_path = root / 'final.xyz'
   frames = geo.read_xyz(final_path)
   assert len(frames) == 1 and seed.symbols == frames[0].symbols
   for label, value in [('seed', seed), ('final', frames[0])]:
       try:
           mol = geo.infer_molecule(value, charge, Chem, rdDetermineBonds)
           print(label, 'total_charge', Chem.GetFormalCharge(mol))
           print('atoms', [(a.GetIdx()+1, a.GetSymbol(), a.GetFormalCharge()) for a in mol.GetAtoms()])
           print('bonds', [(b.GetBeginAtomIdx()+1, b.GetEndAtomIdx()+1, b.GetBondTypeAsDouble()) for b in mol.GetBonds()])
           print('graph', geo.graph_key(mol, Chem))
           print('stereo', geo.stereo_key(mol, Chem))
       except (ValueError, RuntimeError) as exc:
           print(label, 'INFERENCE_FAILED', type(exc).__name__, str(exc))
   PY
   ```

   `_frame` 是当前源码的内部读取函数，版本变化时应对照实现；不要把推断输出重新用作预期图。
   逐项对照主会话已审阅的显式结构/SMILES、氢归属和原子映射，判断共振式、真实成键或推断失败。
   待查成键原子对使用该 study 自己的编号，不能沿用本报告合成闭环的 C2–C6。
4. 结果及新报告引用只记入该 study。若现有结论只依据顶层状态，或核查发现与已签结论冲突，
   立即在 study 的“当前阻塞”记明结构/科学审阅问题并通知监督方，保留旧文件及旧签字证据，
   不自行刷新或重签。是否需要后续计算由负责人另行决定。
