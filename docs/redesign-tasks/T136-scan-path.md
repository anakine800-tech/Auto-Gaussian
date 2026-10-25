# T136：沿扫描路径的成键与构象连续性诊断

版本：v1（监督方，2026-10-26）。**开发机做。** 后端出一个 PR，PR 描述第一行写 `Task: T136`。

## 分支与目标

- 分支：`codex/t136-scan-path`。
- **开工条件：** 以后端 main 为基线，且 **T133（#335）已合并**；T136 编号未被占用。T134 可能同时在开发：本单不改 `gaussian_input.py`、`qst_endpoints.py`。
- **问题来源（规格 T-C 第 4 条，审计第 7 节）：** 柔性体系做弛豫扫描时容易“拖构象”：扫描途中某个侧链翻转或氢键换位，能量曲线上的“峰”其实是构象跳变造成的，而不是反应坐标上的势垒。现在只有 `scan-peak` 的两个粗略提示（相邻能差超过 20 kcal/mol、RMSD 超过 0.5 Å），没有逐点的成键和构象比较。
- **负责人决定（10-26）：**
  - P1 新增只读命令 `ag scan-path <扫描 Attempt>`，输出逐点诊断表。`scan-peak` 调用**同一个函数**，把摘要和警告并入它的报告；`--register-candidate` 时把摘要写进候选的 `transform.path_diagnostics`。只能有一份实现。
  - P2 预期内的成键变化：按键长扫描（`kind = B`）时，被扫描的那对原子成键或断键自动算预期内；其他预期变化（如协同质子转移）用 `--expect-bond i-j` 声明（可重复，两个命令都支持）。未声明的成键变化一律报出。成键状态不确定的原子对单独列为“不确定”，既不算变化，也不算一致。
  - P3 构象描述：相邻两点之间，
    - 可旋转单键的重原子二面角变化超过报告阈值（默认 60°，`--dihedral-threshold` 可调）就列出；扫描坐标本身（`kind = D` 时的那个二面角，以及它的中心键）不计；
    - 非成键接触出现或消失也列出：重原子对距离跨越接触截断（默认 3.5 Å，`--contact-cutoff` 可调）；氢键型接触（与 N、O、F 成键的 H 到另一个 N、O、F 的距离跨越 2.5 Å，`--hbond-cutoff` 可调）；
    - 保留现有的能差、RMSD 提示，口径不变。
    - **所有阈值只决定“是否列出”，不是科学判据**，在输出和 README 里写明。
  - P4 只警告、只记录，不拦：`scan-peak` 照常导出；若问题发生在所选峰前后各两点的范围内，在输出最前面醒目警告“峰可能被构象跳变或成键变化污染”，写明发生在哪两点之间；登记候选时一并写入。
- **默认做法（10-26 已告知负责人）：**
  - 只支持一维扫描。二维扫描时 `scan-path` 说明“本单不支持二维”并以非零退出；`scan-peak` 的二维行为完全不变（不附带路径诊断）。
  - 未收敛或缺几何的点：它与两侧的比较记为“未知”，不跳过去和更远的点比。
  - 成键状态复用 `irc_compare._pairs` 的三态判定（bonded / separated / uncertain），不另写成键判断；二面角复用 `geometry.dihedral`，接触复用 `geometry.contact_fingerprint`（不够用时在同一模块里扩展，不复制一份）。
  - 报告固定注明：“沿程点多为受约束的非驻点；成键差异只说明几何变化，不说明极小点身份。”
- **资料：** `ag/src/ag/scan_peak.py`（`select_peak` 25–84 中的跳变提示、`run`）、`ag/src/ag/_scan.py`（`coordinate`：`kind`、`atoms`）、`ag/src/ag/irc_compare.py`（`_pairs` 63）、`ag/src/ag/topology.py`、`ag/src/ag/geometry.py`（`dihedral` 361、`contact_fingerprint` 408、`infer_molecule`）、审计第 7 节、规格 T-C。
- **新增检查防的事故：** 扫描途中构象跳变或意外成键变化，峰被污染却被当作正常的 TS 初猜送去 DFT。

## 允许改动的路径

- **新建** `ag/src/ag/scan_path.py`：诊断函数与 `ag scan-path` 命令（按现有可选子命令的方式注册）。
- `ag/src/ag/scan_peak.py`：调用诊断、合并报告、新增 `--expect-bond` 等参数、写入 `transform.path_diagnostics`。
- `ag/src/ag/geometry.py`：只在 `contact_fingerprint` 或二面角工具不够用时**扩展**（不改现有行为）。
- 测试：新建 `ag/tests/test_scan_path.py`；`ag/tests/test_scan_peak*.py` 中受影响的用例（PR 中逐个列出）。夹具全部合成（见测试表）。
- 文档：`README.md` 的 scan 一节；`skills-next/auto-g16-recipes/cards/ts.md` 第 2 节加一句“生成草稿前先看 scan-path 的诊断”（只改操作步骤，口径留给 T139）；本单 `docs/redesign-tasks/T136-scan-path.md`、`docs/redesign-tasks/open-tasks.txt`。
- **不改** `select_peak` 的选峰判据和现有跳变提示的阈值、`_scan.py` 的解析、`facts.py`、`irc_compare.py`、`topology.py` 的现有行为、catalog 代码、前端、`CHANGELOG.md`、版本号。

## 要做的

1. **输入**：读取扫描 Attempt 的 `facts.json` 和 `scan_points.xyz`，校验哈希的方式与 `scan-peak` 相同（不一致就拒绝）。电荷取自 manifest（复用 `catalog_v2.manifest_info`），取不到时成键部分照常做（`_pairs` 只用距离），需要电荷的部分标为“未知”。
2. **逐对比较**（相邻两点 i → i+1，两点都有几何时才比较）：
   - **成键**：对全部原子对比较三态。从 bonded 变为 separated，或反过来，算“成键变化”；任一侧为 uncertain 就列入“不确定”。扣除 P2 的预期变化后，其余成键变化全部列出。
   - **二面角**：以第 i 点的成键图确定可旋转单键：两端都是重原子、不在环内、两端各有至少一个其他重原子邻居；扣除扫描坐标。对每个这样的键取一组重原子二面角，比较时按周期差取最小角差。超过阈值的列出（键、四个原子、前后角度、变化量）。
   - **接触**：按 P3 的两种截断比较出现或消失的接触，扣除已成键的原子对；列出原子、元素、前后距离。
   - **能差 / RMSD**：直接沿用 `select_peak` 已算的值和阈值，不重算一份。
3. **输出**（`--json` 结构化，文本为表格）：
   - `points[]`：每个点的点号、坐标值、收敛状态、能量；
   - `segments[]`：每对相邻点的 `status`（`clean` / `flagged` / `unknown`）、`bond_changes`、`uncertain_pairs`、`dihedral_changes`、`contact_changes`、`energy_change_kcal_mol`、`rmsd_angstrom`、`unknown_reason`；
   - `expected_bonds`（自动豁免和人声明的，分开标注）；
   - `thresholds`（实际使用的值）和固定说明文字；
   - `summary`：flagged 和 unknown 段的数量与位置。
4. **并入 `scan-peak`**：
   - 一维扫描时自动调用诊断；报告新增 `path_diagnostics`（`summary` 加上峰前后各两点范围内的 `segments`）；
   - 该范围内有 flagged 段时，在文本输出最前面打印醒目警告（中英文都写），`warnings` 里也加一条；
   - `--register-candidate` 时写入 `transform.path_diagnostics`（只写摘要和峰附近的段，不写整条路径，控制在 T131 的 64 KiB 限制内；超出就截断并注明“已截断”）；
   - 选峰、导出、草稿生成的行为不变，不因诊断结果拒绝或改变选点。
5. **README 与卡片**：写清两条命令的用法、预期变化声明、各阈值的含义（只决定是否列出），以及“非驻点”的说明。

## 不允许

- 不改选峰判据，不自动换峰、不自动选点，不因诊断结果拒绝导出（P4）。
- 不把任何阈值当作科学判据或自动拒绝条件。
- 不另写成键判断或图匹配；不对每个扫描点虚构 Attempt 或 facts；不改已保存的证据。
- 不新增远程操作。
- 夹具和 PR 里不出现真实研究对象、结构、study 名、Attempt 编号。

## 测试

| 场景 | 预期 |
|---|---|
| 合成正丁烷二面角扫描（D 扫描），无意外变化 | 全部段 clean；扫描二面角本身不报 |
| **合成“中途构象跳变”**：键长扫描过程中，某个侧链二面角在第 k→k+1 点翻转约 120° | 该段 flagged，列出该二面角；峰在附近时 `scan-peak` 输出最前面有警告 |
| 键长扫描的那对原子从成键变为分离 | 自动豁免，不报 |
| **合成“未声明的协同质子转移”**：扫描 C–C 键时，某个 H 从 O1 转到 O2 | 两处成键变化都报出 |
| 同一情形加 `--expect-bond` 声明两对 | 不再报 |
| 某对原子在一侧为 uncertain | 列入 uncertain_pairs，该段不因此 flagged |
| 氢键型接触出现或消失 | 列入 contact_changes |
| 中间有一个点未收敛或缺几何 | 它与两侧的段为 unknown，不和更远的点比 |
| 阈值参数调整（例如二面角阈值 30°） | 列出结果随之变化；`thresholds` 记录实际值 |
| 二维扫描运行 `scan-path` | 非零退出并说明不支持；`scan-peak` 二维行为不变 |
| `scan_points.xyz` 哈希不符 | 拒绝（与 scan-peak 一致） |
| `scan-peak --register-candidate` | `transform.path_diagnostics` 写入摘要和峰附近的段；超过限制时截断并标注 |
| 现有 scan-peak 全部用例 | 选峰、导出、草稿行为不变 |

推送前本地跑一次全量 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，之后以 CI 为准；运行 `python scripts/scan_public.py`（带本机词表）和 `git diff --cached --check`。

## 真实环境验证

- 不需要远程验证（纯本地读取已保存的扫描证据）。
- 合并前在开发机上，对一个**非研究**、已取回的 xTB 扫描 Attempt（如果有；没有就用夹具同款合成 Attempt）运行一次 `scan-path` 和带诊断的 `scan-peak`，确认输出正常。不碰研究 study。

## 停止条件

- 需要改选峰判据、`_scan.py` 解析或 `irc_compare` / `topology` 的现有行为。
- 成键判断无法复用 `_pairs`，需要另写一套。
- 同一问题修两次仍未解决。

## 合并前审阅与交付

- 需要监督方审阅：**是，逐行审**（成键比较的口径、可旋转键的判定、二面角周期差、并入 scan-peak 的方式）。合并只由负责人操作。
- PR 描述包括：P1–P4 与默认做法各自对应的改动、输出字段说明、测试表逐项结果，以及两个关键夹具（构象跳变、未声明质子转移）的输出截取。

## 版本记录

- v1（2026-10-26，监督方）：依据 10-26 决定 P1–P4 及默认做法起草；对应审计拆单建议中 T-C 的“沿程诊断”部分。

## 开发记录

- 开工基线：后端 main `6d86346`，T133 #335 已合并，T136 编号及分支未占用。
- 范围补充（2026-10-26，负责人原话：“批准这处测试范围扩展”）：允许仅修改
  `ag/tests/test_scan.py` 的 `one_dimensional_snapshot` helper；剔除 T136 新增诊断展示后，
  继续以原哈希验证选峰、旧警告、扫描事实与导出 XYZ 字节。新增报告使旧的完整输出哈希必然改变。
- 现有测试改动另有 `test_scan_peak_ts_input.py::test_registration_upgrade_hash_and_ledger`
  （default/explicit 两个参数用例）：加入 `transform.path_diagnostics` 字段并核对与报告一致。
- `scan-path` 通过 `scan_peak.register` 内现有可选注册入口挂载，无需修改 CLI 白名单。
  `step_metrics` 共用原能差/RMSD 计算和阈值；`select_peak` 选峰条件不变。
- 距离成键三态沿用 `_pairs`；单键/环信息来自第一个点的 `infer_molecule`；
  每键取原子编号最小的重原子邻居，复用 `dihedral` 与 `periodic_difference`。
  接触复用 `contact_fingerprint`，只报告距离确实跨截断的出现/消失，
  不把供体身份变得不确定单独算作接触消失。
- 缺电荷、推键失败或二面角退化仅使相应部分未知；保留可获得的成键/接触/能差信息。
  已发现变化优先标为 flagged，仍列 unknown_reason；uncertain_pairs 本身不触发 flagged。
- 候选只写全程摘要及峰附近最多四段；超限优先截断最长明细列表，保留段位置、状态、
  警告、原明细计数及“已截断”标记，按整个 transform 的 JSON 字节计算 64 KiB。
- 本单为纯本地工具；流程验证使用合成非研究 Attempt，不连接集群，不提交计算。
- 开发机合成流程验证（2026-10-26）：从合成已取回 xTB 输出生成 facts 后，实际 CLI
  运行 `scan-path` 的文本/JSON、`scan-peak` 的 XYZ/TS 草稿/候选登记，选中点 4，
  诊断报告与候选记录一致，全部原始证据的字节与 mtime 不变，无新 Attempt。
  侧链夹具在 2→3 段报告约 120° 翻转、首行中英文污染警告；质子夹具在 1→2 段
  报 O1–H3 断键与 O2–H3 成键，声明两对预期变化后该段为 clean。
- 本地全量：`PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，
  5157 passed、19 skipped（314.04 s）；18 项为 Linux stat/procfs 方言检查，
  交由 Linux CI，1 项为默认跳过的私有日志。相关扫描回归 234 passed；
  最终诊断与 Skills 定向检查 187 passed。公开词表扫描与暂存区格式检查通过。
- T134 #336 合入后 rebase 到 main `f6cca7c`；仅任务清单末尾冲突，保留两条记录。
  rebase 后扫描、几何、QST、smoke 与全部 Skills 回归 852 passed（75.42 s）。
  全仓库 1815 个文件与暂存区均通过本机词表扫描；后续以 CI 为准。
