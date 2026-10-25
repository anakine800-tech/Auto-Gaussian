# T133：扫描峰 → Gaussian TS 输入草稿，可选登记来源

版本：v1（监督方，2026-10-26）。**开发机做。** 后端出一个 PR，PR 描述第一行写 `Task: T133`。

## 分支与目标

- 分支：`codex/t133-scan-peak-ts-input`。
- **开工条件：** 以后端 main（不早于 `21c27e1`，含 T131）为基线。**与 T134 并行开发，本单先合并**；本单新建的公共函数 `gaussian_input.render_input()`（第 1 节）由 T134 复用，T134 不得另写一份。
- **问题来源（审计第 3 节）：** 扫描、解析、选峰已经接通，断点在峰值 XYZ 之后：要靠人手工去掉 XYZ 前两行、拼进 `.gjf`、去掉扫描段，扫描点号、文件哈希、选择理由也不会进入候选台账。
- **负责人决定（10-26）：**
  - G1 在现有 `ag scan-peak` 上加 `--gaussian-ts`：输出一份 Gaussian TS 输入草稿。route 由人或卡片通过 `--route` 给出；工具只拼几何、电荷、多重度（取自扫描 Attempt 的 manifest）和标题。输出到新文件，不覆盖；**不自动 prepare，也不提交**。
  - G2 route 只拒明显不对的：必须含 TS 优化（`Opt=TS` 或 `Opt=(TS,...)`，大小写和写法不限）；不得含扫描或冻结类关键词（`ModRedundant`、`Scan`、`ReadOpt`、`Opt=(…,ModRedundant…)`、`AddGIC` 等，以 PR 中列出的完整清单为准）；含 `RCFC`、`ReadFC`、`ReadCartesianFC` 时拒绝，并提示这类输入必须走 `prepare --parent-chk` 的父 chk 流程。方法、基组、`CalcFC`、`NoEigenTest` 等科学选择不检查。
  - G3 登记候选是可选项，默认不登记：加 `--register-candidate --object <对象> --candidate-id <ID> [--target-channel <通道>]` 时，用 T131 的登记代码把峰值几何登记为 `origin=scan` 的候选。**T132 部署之前，真实研究 study 不使用这个参数。**
- **资料：** `ag/src/ag/scan_peak.py`（`run` 140、`register` 196）、`ag/src/ag/gaussian_input.py`（`validate` 141、`cartesian`、`check_electrons`）、`ag/src/ag/catalog_v2.py`（`manifest_info`、`plan` 中的 candidate 分支、`archive`）、`ag/src/ag/catalog.py`（`change`）、`skills-next/auto-g16-recipes/cards/ts.md` 第 2 节、审计第 3 节。
- **新增检查防的事故：** 手工拼 `.gjf` 时漏删扫描段或冻结段，或电荷、多重度抄错；用 RCFC/ReadFC 却没有走父 chk 的取向核对（审计第 5 节）。

## 允许改动的路径

- `ag/src/ag/scan_peak.py`：新参数、生成草稿、可选登记。
- `ag/src/ag/gaussian_input.py`：**新增**公共函数 `render_input(route, title, sections)`（`sections` 为若干组 `(charge, multiplicity, symbols, coordinates)`），输出 Link0 之外的 Gaussian 输入正文（route 段、空行、标题、空行、电荷多重度与坐标、末尾空行），并用现有 `validate` 校验；**不改现有函数的行为**。另新增 `ts_route_check(route)` 实现 G2。
- `ag/src/ag/catalog.py` / `catalog_v2.py`：只在需要把 candidate 登记暴露为可调用函数时，做最小的重构（例如抽出 `register_candidate(root, object, id, xyz_bytes, origin, parent, transform, target_channel)`），**行为不变**，由 T131 的测试保证。
- 测试：`ag/tests/test_scan_peak*.py` 中受影响的用例；新建 `ag/tests/test_scan_peak_ts_input.py`；`ag/tests/test_gaussian_input.py` 补 `render_input` 和 `ts_route_check` 用例。夹具全部合成（例如正丁烷二面角扫描）。
- 文档：`README.md` 的 scan-peak 一节；`skills-next/auto-g16-recipes/cards/ts.md` 第 2 节中“手工去掉前两行……”的步骤**改为**使用新参数（只改这一段的操作步骤，其他口径留给 T139）；本单 `docs/redesign-tasks/T133-scan-peak-ts-input.md`、`docs/redesign-tasks/open-tasks.txt`。
- **不改** `attempt.py`（prepare）、`submit.py`、模板、`_scan.py` 的解析、`select_peak` 的选峰判据、`facts.py`、前端、`CHANGELOG.md`、版本号。

## 要做的

1. **命令行**：`ag scan-peak <Attempt> --out <新 XYZ> [--point …] --gaussian-ts <新 .gjf> --route '<route>' [--title '<标题>'] [--register-candidate --object <对象> --candidate-id <ID> [--target-channel <通道>]] [--json]`
   - `--gaussian-ts` 必须同时给 `--route`；`.gjf` 路径已存在就拒绝（与 `--out` 规则相同）。
   - 选峰逻辑、`--point` 规则、现有输出和警告完全不变；`--out` 的 XYZ 照旧写出。
2. **电荷与多重度**：用 `catalog_v2.manifest_info()` 从扫描 Attempt 的 manifest 取得（xTB 的 `--chrg`、`--uhf` 按现有规则换算）。取不到就拒绝生成，并说明缺什么；**不使用默认 0/1**。生成后用 `check_electrons` 核对电子数与多重度相容。
3. **生成**：用 `render_input` 拼出正文。标题默认写“TS guess from scan <Attempt> point <点号>”，不写研究对象名。Link0 行（`%nprocshared`、`%mem`、`%chk`）不写，留给 `prepare` 的现有规则。文件末尾保证有空行。
4. **route 检查**：`ts_route_check` 按 G2 执行，拒绝时说明原因；通过后再调用 `validate` 做通用校验。
5. **可选登记（G3）**：
   - 登记的几何就是 `--out` 写出的 XYZ 的字节（同一哈希）；
   - `parent.attempt` = 扫描 Attempt；
   - `transform` 写入：`{"type": "scan_peak", "point": …, "coordinate_value": …, "energy_hartree": …, "relative_energy_kcal_mol": …, "neighbors": […], "scan_points_sha256": …, "selection": "default_highest" | "explicit_point", "warnings": […]}`；
   - 走 T131 的同一条登记路径（升级规则、`--upgrade-catalog`、`--dry-run`、存档、原话规则全部沿用）。需要升级时必须另加 `--upgrade-catalog`。
   - 登记失败时：`.gjf` 和 XYZ 已写出的照旧保留，报告登记失败的原因，不自动重试。
6. **`--json` 输出**：在现有报告里加 `gaussian_ts`（路径、route、电荷、多重度、标题、SHA-256）和 `candidate`（若登记，返回 T131 的事件摘要）。
7. **卡片与 README**：`ts.md` 第 2 节改为“用 `scan-peak --gaussian-ts --route` 生成草稿，审阅后再 prepare”；README 写明参数和边界（不自动 prepare、不提交、不判断方法）。

## 不允许

- 不改选峰判据，不自动选点（二维仍须 `--point`），不把扫描峰当已验证 TS。
- 不自动 prepare 或提交；不写 Link0；不推断 route 中的方法、基组。
- 不新增远程操作；不改 facts 和 manifest。
- 夹具和 PR 里不出现真实研究对象、结构、study 名、Attempt 编号。

## 测试

| 场景 | 预期 |
|---|---|
| 一维扫描、默认选峰、`--gaussian-ts --route '#p B3LYP/6-31G(d) Opt=(TS,CalcFC,NoEigenTest) Freq'` | 生成 `.gjf`，几何与 `--out` 的 XYZ 一致，电荷多重度来自 manifest，通过 `validate` |
| `--point` 显式选点 | `transform.selection = explicit_point` |
| 二维扫描不带 `--point` | 与现在一样拒绝 |
| route 不含 TS；含 ModRedundant；含 RCFC/ReadFC | 分别拒绝，并说明原因 |
| route 写法 `opt=ts`、`OPT=(TS, CALCFC)` | 都接受 |
| manifest 缺电荷或多重度 | 拒绝，不用默认值 |
| 电荷、多重度与电子数不相容 | 拒绝 |
| `.gjf` 已存在 | 拒绝，不覆盖 |
| 不带 `--register-candidate` | 不碰 catalog，不创建任何 catalog 文件 |
| 带登记、catalog 为 /1、未加 `--upgrade-catalog` | 拒绝登记；`.gjf` 和 XYZ 保留；说明需要升级 |
| 带登记且升级 | 候选 `origin=scan`，哈希与 XYZ 一致，`transform` 字段齐全；`ag catalog ledger` 能查到 |
| 登记的对象不存在、目标通道不存在 | 拒绝登记，文件保留 |
| `--dry-run` 与登记同用 | 不写 catalog（`.gjf`、XYZ 是否写出按 PR 说明，并在 README 写清） |
| `render_input` 多段（供 T134 使用） | 生成的多段正文通过 `validate` 的 QST2 校验 |
| 现有 scan-peak 全部用例 | 行为不变 |

推送前本地跑一次全量 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，之后以 CI 为准；运行 `python scripts/scan_public.py`（带本机词表）和 `git diff --cached --check`。

## 真实环境验证（合并前，开发机；不提交作业）

- 在临时非研究 study 里放一个合成的已取回 xTB 扫描 Attempt（夹具同款即可），运行生成和登记全流程，确认 `ag prepare --template gaussian --input <生成的 .gjf>` 的 **`--dry-run`**（若 prepare 无 dry-run，则只运行到输入校验为止，不建 Attempt）能接受这份输入。**不提交。**
- 不碰任何真实 study。PR 里只写结果。

## 停止条件

- 需要改 prepare、模板或选峰判据。
- 抽取 T131 登记函数时需要改变它的行为。
- 同一问题修两次仍未解决。

## 合并前审阅与交付

- 需要监督方审阅：**是，逐行审**（route 检查、电荷多重度来源、catalog 写入）。合并只由负责人操作。**本单先于 T134 合并。**
- PR 描述包括：G1–G3 对应的改动、G2 的完整关键词清单、`render_input` 的接口说明（供 T134 复用）、测试表逐项结果、真实验证记录。

## 版本记录

- v1（2026-10-26，监督方）：依据 10-26 决定 G1–G3 起草；对应审计拆单建议中 T-C 的“输入与来源衔接”部分（沿程诊断另为 T136）。

## 接口补充（2026-10-26，负责人转达监督方协调）

T134 的 QST2 两段需要各自的标题。本单内将
`gaussian_input.render_input(route, title, sections)` 的 `title` 扩为 `str | Sequence[str]`：
字符串用于每一段，保留现有调用兼容；序列长度必须等于结构段数，第 i 个标题用于第 i 段。
所有标题都必须非空且不能含换行。补单段字符串、多段字符串、逐段标题序列、长度不符、
空标题和换行拒绝测试；PR 描述写明接口，改完向负责人报告新 head。

## 实现与验证记录（2026-10-26）

- 基线 `21c27e1`（含 T131）；选择函数和现有 Gaussian validate 行为不变。
- 新增 `render_input` / `ts_route_check`；前者内部用临时资源行调用现有 validate，
  返回正文没有 Link0。坐标格式与 XYZ 相同；逐段标题遵循上面的接口补充。
- 候选登记复用 T131 的 change/plan/replay、锁、存档和升级规则。
  `--dry-run` 只预览登记、不写 catalog，XYZ 与 Gaussian 草稿仍独占写出；
  登记失败保留导出文件、返回非零、不重试。二维 `coordinate_value` 为两维值列表。
- 完整 route 拒绝清单见 README 的 scan-peak 说明；方法、基组和科学选项不判断。
- 相关回归初轮 674 passed、Skills 509 passed；接口补充后相关测试 411 passed。
- 最终全量 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`：
  5129 passed、19 skipped；18 项需要 Linux GNU stat/procfs，由 Linux CI 执行，
  1 项私有日志测试按默认跳过。全仓库/暂存区本机词表扫描及 diff 空白检查均通过。
- 开发机临时非研究 study：以合成已取回 xTB 扫描运行实际 CLI 生成、升级登记和 ledger，
  几何与存档哈希一致，扫描证据不变，新增 Attempt 数为 0；没有集群操作或作业提交。
- 现状差异：prepare 无 `--dry-run`，也不自动补 `%nprocshared`。无 Link0 正文不能直接 prepare；
  本次按工单的输入校验替代路径，在内存补匹配资源档位的 `%nprocshared` 后，
  现有 fill_memory + validate 通过。README 与 TS 卡片写清审阅后补 Link0 再 prepare；
  未改 prepare、模板或输入资源规则。验证脚本的临时路径别名及模块入口问题已改正，产品规则不变。
- 当前无实现阻塞；等待监督方逐行审阅和负责人合并。本单先于 T134 合并；
  T132 部署前真实研究 study 不使用可选登记参数。
