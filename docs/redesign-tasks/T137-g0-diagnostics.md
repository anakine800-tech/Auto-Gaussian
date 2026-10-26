# T137：G0 诊断——输入完整性、几何损坏与通道诊断

版本：v2（2026-10-26，依据负责人转发的 #338 复审补充修订 E3/E6）。**开发机做。** 后端出一个 PR，PR 描述第一行写 `Task: T137`。

## 分支与目标

- 分支：`codex/t137-g0-diagnostics`。
- **开工条件：** 以后端 main 为基线，且 **T136（#337）已合并**；T137 编号未被占用。T138 在本单合并后开工（复用本单的报告结构和排序）。
- **目标（规格 T-E，复审口径）：** 在 DFT 之前对 TS 初猜候选做一次本地诊断。**只有两类硬拒绝**：输入完整性、几何损坏。其余一律是标记和排序信号，不影响能否提交。G0 不是门禁：**不改 prepare、submit**。
- **负责人决定（10-26）：**
  - E1 新增独立命令 `ag g0 <study> --object <对象> --candidate <候选>`。硬拒绝只体现为诊断结论 `rejected` 和非零退出码，不在 prepare/submit 中加任何检查。可选 `--record` 把诊断追加为候选结果（`outcome = diagnosed`，`diagnosis` 为本报告），默认只报告、不写任何文件。
  - E2 输入完整性按**候选所属对象**判定，不按 study 统一判定：
    - 原子数和组成对照对象的 `expected.formula`，电荷对照 `expected.charge`，多重度对照对象的 `multiplicity`；
    - 原子顺序默认对照候选的父 Attempt（`parent.attempt`，scan、qst 来源都有）；手工和文献来源用 `--reference-attempt` 指定；只比较元素序列（同种元素原子互换查不出来，报告里写明）；
    - 没有对照的项（期望值为“未提供”或“未知”，没有参考 Attempt）记为“未核对”：这是**标记**，不是拒绝；
    - 候选 XYZ 不带电荷信息，所以“电荷、多重度”的核对，是检查对象期望值与参考 Attempt 的 manifest 是否一致，以及期望电荷、多重度与候选元素组成的电子数奇偶是否相容（复用 `gaussian_input.check_electrons`）。
  - E3 几何损坏的硬拒绝极保守：任意两个原子距离 < 0.5 Å，或 < 0.5 倍共价半径之和。非成键重原子对 < 0.75 倍范德华半径之和只标记为“普通冲突”；适用距离窗口声明的反应原子对除外，单列 `geometry.reaction_center_pairs`，仍检查超窗和两项几何损坏。普通冲突先核对是否为未声明的反应中心，仅确认普通空间冲突后再考虑保持反应坐标的受限松弛。这三个数**写死在代码和文档里，不开放调整**；共价半径、范德华半径都取 RDKit 周期表（与 `irc_compare._pairs` 同源）。
  - E4 通道诊断：
    - 成断键距离窗口由人设，超出窗口就标记；
    - 立体标签 ag 不自己算：读入 Skill 脚本 `skills-next/auto-g16-structures/scripts/ts_stereo_label.py` 生成的 `labels.json`（`--stereo-json`），与人给的 `--expected-label` 比较。不符标记“可能属于其他通道”，含 unknown / needs_review 中心或不能唯一判定时标记“待判”。**都不自动改归属。**
  - E5 批量：`--all`（对象的全部候选）或 `--channel <通道>`（以该通道为目标或曾归属该通道的候选）。结果分三组：拒绝 / 有标记 / 无标记；组内按标记数升序、再按登记顺序排。输出固定写明“顺序只是建议，提交与否由负责人决定”。T138 会在此基础上加入模式信息、细化排序。
  - E6 距离窗口写在 study 的 `analyses/` 下一个 JSON 文件里（按通道分组），用 `--windows <文件>` 指定；也可以用 `--window i-j:最小:最大` 临时补充（可重复，作用于本次诊断的所有候选）。诊断结果记下窗口文件的 SHA-256 和实际用到的窗口。不改 catalog 契约。
    - 顶层仅允许 `channels`、`all`、`reaction_coordinates`，其他键仍报错。T137 不读取或校验 `reaction_coordinates` 内容，由 T138 负责。
  - E7 规格中与 xTB 相关的两项不进本单：虚频、模式相关的放 T138；“xTB 高能、端点塌缩”由人登记为候选结果，T139 在卡片里写清口径。**T137 不跑任何计算。**
- **资料：** 规格 `docs/research/ts-guess-plan-v1.md` T-E 一节；审计第 9、11 节及拆单建议中的 T-E；`ag/src/ag/catalog.py`、`catalog_v2.py`（`manifest_info`、`xyz`、`read_bytes`、`register_candidate`、`ledger`）；`ag/src/ag/irc_compare.py`（`_pairs`）；`ag/src/ag/gaussian_input.py`（`check_electrons`）；`ag/src/ag/geometry.py`（`atom_distance`）；`skills-next/auto-g16-structures/scripts/ts_stereo_label.py`（`labels.json` 的结构）。
- **新增检查防的事故：** 把原子数、电荷或多重度与子任务不符的初猜送去 DFT（按 study 统一判断还会误杀不同计量的子任务）；坐标损坏（原子重叠、键长塌缩）的输入浪费排队；成断键距离明显不在预期范围或立体构型不对的候选混在一起，没有被标出来。

## 允许改动的路径

- **新建** `ag/src/ag/g0.py`：诊断函数与 `ag g0` 命令（按现有可选子命令的方式注册）。
- `ag/src/ag/catalog.py` / `catalog_v2.py`：只在需要以函数方式追加 `candidate-result` 时，做不改行为的最小抽取（参照 T133 的 `register_candidate`）；T131 的测试保证行为不变。
- 测试：新建 `ag/tests/test_g0.py`；受影响的 catalog 测试（PR 中逐个列出）。夹具全部合成。
- 文档：`README.md` 新增一节；**新建** `docs/g0.md`（诊断报告字段、窗口文件格式、三个写死的几何判据、排序规则、与 T138 的分工）；本单 `docs/redesign-tasks/T137-g0-diagnostics.md`、`docs/redesign-tasks/open-tasks.txt`。
- **不改** prepare、submit、模板、facts、`ts_stereo_label.py`、前端、`skills-next` 卡片（口径在 T139）、`CHANGELOG.md`、版本号。

## 要做的

1. **命令行**：

```
ag g0 <study> --object <对象> (--candidate <候选> | --all | --channel <通道>)
      [--reference-attempt <ID>] [--windows <analyses 下的 JSON>] [--window i-j:min:max ...]
      [--stereo-json <labels.json> --stereo-attempt <ID> --expected-label <标签>]
      [--record [--upgrade-catalog] [--dry-run]] [--json]
```

   - `--reference-attempt` 只用于单个候选；批量时每个候选用自己的父 Attempt，没有父 Attempt 的记为“未核对”。
   - 立体三项必须同时给出；只用于单个候选。

2. **候选几何**：读 catalog 存档文件 `catalog/candidates/<sha256>.xyz`，重新计算哈希，必须等于登记值，不等就报错（不当成拒绝，属于数据损坏，需人工处理）。

3. **输入完整性（E2）**，逐项给出 `pass / reject / unchecked`，并附依据：
   - `atom_count_and_formula`：候选组成与对象 `expected.formula`；
   - `atom_order`：候选元素序列与参考 Attempt 的元素序列（用 `manifest_info` 同一套读取方式取得参考几何；QST 参考取第一段）；
   - `charge`、`multiplicity`：对象期望值与参考 Attempt 的 manifest；期望值与候选组成的电子数奇偶是否相容；
   - 任一项为 reject，候选结论就是 `rejected`；unchecked 记入标记。

4. **几何损坏（E3）**：
   - 硬拒绝：任意原子对距离 < 0.5 Å；任意原子对距离 < 0.5 × (r_cov,i + r_cov,j)；
   - 标记（普通冲突）：未成键的重原子对（按 `_pairs` 不为 bonded）距离 < 0.75 × (r_vdW,i + r_vdW,j)，且不是适用距离窗口声明的反应原子对；先核对是否为未声明的反应中心，仅确认普通空间冲突后再考虑保持反应坐标的受限松弛；
   - 适用距离窗口声明的原子对单列 `geometry.reaction_center_pairs`（原子编号、元素、距离），不标普通冲突；仍检查超窗与两项几何损坏；
   - 列出涉及的原子、元素和距离。

5. **距离窗口（E4、E6）**：
   - 窗口文件格式：`{"channels": {"<通道ID>": [{"atoms": [i, j], "min": 1.8, "max": 2.6, "label": "形成键 C1–C5"}], ...}, "all": [...]}`；
   - 文件必须在 study 的 `analyses/` 下，拒绝越界路径和符号链接；
   - 顶层还允许 T138 使用的 `reaction_coordinates`，T137 不读取或校验其内容；其他未知键报错；
   - 对每个候选，适用的窗口 = `all` + 候选目标通道的窗口 + 命令行 `--window`；
   - 超出窗口的列为标记（原子、实际距离、窗口、标签）；没有适用窗口时记“未设窗口”。

6. **立体（E4）**：
   - 读 `labels.json`，按 `--stereo-attempt` 选出对应条目；
   - 核对该 Attempt 的输入几何（manifest 中的几何）与候选存档几何逐原子一致（元素相同、坐标差 ≤ 1e-4 Å），不一致就报错，说明标签不是针对这个候选算的；
   - 比较条目的 `product_configuration` 与 `--expected-label`：相同记 `match`；不同标记“可能属于其他通道”；条目中有 unknown / needs_review 中心或无法唯一判定时，标记“待判”；
   - `labels.json` 结构与预期不符时停下（见停止条件），不要猜字段。

7. **结论与排序（E5）**：
   - 每个候选给出：`verdict`（`rejected` / `flagged` / `clean`）、`reject_reasons`、`flags`（每条有类别和说明）、`unchecked`；
   - 批量时按 E5 分组排序，输出 `order`；固定说明文字写明顺序只是建议；
   - 报告固定写明：“G0 是本地诊断，不是门禁；不替代 DFT 验收；clean 只表示未发现问题。”

8. **`--record`**：
   - 对每个候选追加一条 `candidate-result`：`outcome = diagnosed`，归属 `none`，`diagnosis` 为该候选的报告（不超过 64 KiB，超出时截断并标注，保留结论和各项计数），`attempt` 为空；
   - 走 T131 的同一条路径（升级、`--dry-run`、锁）；批量时一次加锁写入全部事件，任一条校验失败就整批不写；
   - **T140 部署之前，真实研究 study 不使用 `--record`。**

## 不允许

- 不改 prepare、submit，不新增任何门禁或自动提交路径。
- 除 E3 的两类几何判据和 E2 的完整性比对之外，不设任何拒绝条件；三个几何数值不开放调整。
- 不自动改候选归属、不推断化学含义、不自己计算立体标签。
- 不跑任何计算（xTB、Gaussian 都不跑），不新增远程操作，不改 facts 和 manifest。
- 夹具和 PR 里不出现真实研究对象、结构、study 名、Attempt 编号。

## 测试

| 场景 | 预期 |
|---|---|
| 合成对象（期望组成、电荷、多重度齐全）+ 正常候选 | clean |
| 候选组成与期望不符 | rejected（atom_count_and_formula） |
| 元素序列与父 Attempt 不同 | rejected（atom_order） |
| 同元素两个原子互换 | 不能检出，报告写明该局限 |
| **不同计量的两个对象**（一个含一分子显式水，一个不含），各自的候选 | 各按自己对象的期望值判断，**互不误杀** |
| 期望值未提供 / 未知；手工候选没有参考 | unchecked，记为标记，不拒绝 |
| 期望电荷、多重度与电子数奇偶不相容 | rejected |
| 两原子距离 0.4 Å；距离 < 0.5 倍共价半径之和 | rejected（几何损坏） |
| 未声明反应原子对的非成键重原子对 < 0.75 倍范德华半径之和 | flagged（普通冲突），先核对反应中心，再给有条件的受限松弛建议 |
| C–C 2.2 Å，有/没有适用距离窗口 | 有窗口单列 reaction_center_pairs，不标普通冲突；无窗口照常标冲突 |
| 声明了反应原子对，但距离 0.4 Å 或小于半共价半径和 | 仍 rejected（几何损坏） |
| 文件含 reaction_coordinates / 顶层键拼错 | 前者可用且内容不校验；后者运行错误 |
| 距离窗口：通道窗口、all 窗口、命令行窗口；超出与未超出 | 只把超出的列为标记；记录窗口文件哈希 |
| 窗口文件不在 analyses/、是符号链接 | 拒绝运行 |
| 立体：一致 / 不一致 / 含 unknown 中心 | match / “可能属于其他通道” / “待判” |
| 立体条目的几何与候选不一致 | 报错，不给结论 |
| 存档文件哈希与登记不符 | 报错（数据损坏），不当成拒绝 |
| `--all` 三组排序 | 拒绝、有标记、无标记分组；组内按标记数、再按登记顺序 |
| `--record`（单个、批量）；批量中一条失败 | 追加 diagnosed 结果 / 整批不写 |
| `--record` 遇到 /1 catalog 未加 `--upgrade-catalog` | 拒绝写入，报告照常输出 |
| 不带 `--record` | 不创建、不修改任何文件 |

推送前本地跑一次全量 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，之后以 CI 为准；运行 `python scripts/scan_public.py`（带本机词表）和 `git diff --cached --check`。
复审补充：测试中打印 RDKit 的 C–C、C–O、C–N 普通冲突阈值，并记录在 PR 描述中。

## 真实环境验证

- 不需要远程验证。合并前在开发机的**临时非研究 study** 中，用合成对象和候选（含一个 scan 来源、一个 qst 来源、一个 manual 来源）完整跑一次单个、批量和 `--record`，确认台账（`ag catalog ledger`）中能看到 diagnosed 结果。不碰研究 study。

## 停止条件

- `labels.json` 的实际结构与本单假设（条目按 Attempt 区分、有 `product_configuration` 和中心标签）不符。
- 需要改 prepare、submit、catalog 契约或 `ts_stereo_label.py`。
- 同一问题修两次仍未解决。

## 合并前审阅与交付

- 需要监督方审阅：**是，逐行审**（两类硬拒绝的判据、按对象判定的完整性、catalog 写入）。合并只由负责人操作。
- PR 描述包括：E1–E7 对应的改动、`docs/g0.md` 全文、测试表逐项结果、真实验证记录。

## 版本记录

- v2（2026-10-26，负责人转发 #338 复审及补充口径）：允许共享窗口文件的 `reaction_coordinates` 键，但保留顶层键白名单；适用距离窗口声明的反应原子对不作普通冲突，防止将 2.0–2.4 Å 的成键中 TS 反应中心误导去松弛。两项几何硬拒绝不变。
- v1（2026-10-26，监督方）：依据 10-26 两轮问答 E1–E7 起草；对应审计拆单建议中 T-E 的“本地对象完整性、几何、通道诊断”部分（模式诊断另为 T138）。

## 执行记录

- 基线：main `26391ed`，T136 #337 已合并；开工前核对 T137 未占用。
- 范围补充：负责人于 2026-10-26 在本任务对话明确回复“批准这一行范围扩展”，允许仅在 `ag/src/ag/cli.py` 的可选模块列表增加 `g0`；不改 prepare/submit。
- 测试范围补充：负责人于 2026-10-26 明确回复“批准这两行测试范围扩展”，允许仅在 `ag/tests/test_smoke.py` 的完整注册模块预期列表加入 `ag.g0`，并在该测试的参数列表加入 `g0`；保留严格完整列表断言。
- `labels.json` 的实际结构已核对：`attempts[]` 含 `product_configuration`、中心标签和几何来源；兼容 input/final，QST3 立体输入使用第三段。
- 验证与交付结果见本 PR；仅使用合成临时 study，T140 部署前不向真实研究 study 记录诊断。
