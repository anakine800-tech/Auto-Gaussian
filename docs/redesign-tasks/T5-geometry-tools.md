# T5：`ag dedup`、`ag cluster`、`ag graph`

分支：`codex/redesign-t5-geometry`　位置：本地或云端　依赖：T0 已合并　预计：1～1.5 天

## 目标

提供构象去重、代表构象选择（含镜像简并识别）和 Attempt 关系展示三个确定性本地工具。规格见方案 4.4、4.9、5.5 和决策 D16。

## 允许改动的路径

- `ag/src/ag/geometry.py`、`ag/src/ag/dedup.py`、`ag/src/ag/cluster.py`、`ag/src/ag/graph.py`
- `ag/tests/test_geometry.py`、`ag/tests/test_dedup.py`、`ag/tests/test_cluster.py`、`ag/tests/test_graph.py`
- `ag/tests/data/`（测试用的人工构造 xyz，只用正丁烷、乙烷之类的小分子）

## 不允许

- 改 T1、T2 拥有的文件；子命令通过 `register(subparsers)` 挂载。
- import 旧代码。可参考 `auto_g16/conformer/_geometry.py` 和旧 `skills/auto-g16-conformer-search/scripts/` 中的算法，改写后注明来源。

## 步骤

1. **`geometry.py`**：读写多帧 xyz（注释行可带能量）；从 xyz 用 RDKit `rdDetermineBonds` 推断连接关系（需要传入总电荷）；比较两帧的连接图是否一致；计算考虑原子对称等价的重原子 RMSD（`rdMolAlign.GetBestRMS`）；可选计算镜像 RMSD（坐标取反后再比较）。
2. **`ag dedup <输入> --charge <q> [--energies <文件>] [--rmsd 0.125] [--de 0.05] [--window 3.0] [--out <study>/analyses/]`**：
   - 输入可以是 CREST 的 `crest_conformers.xyz`（能量取 `crest.energies` 或注释行），也可以是若干 Attempt 的 `final.xyz` 加 `facts.json` 能量。
   - 剔除连接图与第一帧不一致的结构（记为 `graph_changed`，不静默丢弃，写进输出）。
   - 能量窗口外的剔除；RMSD 小于阈值且能量差小于阈值的视为重复，保留能量更低的。
   - 输出 `dedup-<时间戳>.json`（每个保留结构的序号、能量、相对能量、来源帧）和对应的多帧 xyz；不覆盖已有文件。
3. **`ag cluster <dedup 输出> [--max 20] [--rmsd 0.5] [--mirror]`**：
   - 按能量从低到高贪心选择：与已选结构的 RMSD 都大于阈值才入选，直到达到上限。
   - `--mirror`：若某结构与已选结构的镜像 RMSD 小于阈值、能量差小于 0.05 kcal/mol，则不单独入选，而是把已选结构的 `degeneracy` 加 1（例如正丁烷的两个 gauche 构象）。
   - 输出 `cluster-<时间戳>.json`（代表构象列表：序号、能量、`degeneracy`、被合并的成员）和每个代表构象的单独 xyz 文件（供 `ag prepare` 使用）。
4. **`ag graph --study <dir> [--json]`**：读取所有 `manifest.json` 的 `parents`/`relation`，按树形打印（Attempt id、模板、标签、状态）；`--json` 输出节点和边。缺失的父节点标记出来，不报错退出。

## 验收标准

- `pytest ag/tests` 通过。
- 测试覆盖：正丁烷 anti/gauche/gauche′ 三帧，`dedup` 保留 3 个，`cluster --mirror` 得到 2 个代表构象且 gauche 的 `degeneracy = 2`；一帧故意改变连接关系的结构被标为 `graph_changed`；重复帧被去掉；`graph` 能正确显示三层父子关系。
- 对 200 帧、20 个重原子的输入，`dedup` 在普通笔记本上 1 分钟内完成（在 PR 中报告实测时间）。

## 停止条件

- `rdDetermineBonds` 对带电或含硼结构推断失败率高：在 PR 中列出情况，不要自行引入新的依赖。

## PR 要求

PR 描述第一行 `Task: T5`；报告性能实测结果。
