# T134：端点原子映射、刚体对齐与 QST2 输入草稿

版本：v1（监督方，2026-10-26）。**开发机做。** 后端出一个 PR，PR 描述第一行写 `Task: T134`。

## 分支与目标

- 分支：`codex/t134-endpoint-qst2`。
- **开工条件：** 以后端 main（不早于 `21c27e1`，含 T131）为基线。**与 T133 并行开发，T133 先合并**；本单的 `.gjf` 正文**必须**复用 T133 新增的 `gaussian_input.render_input()`，不得另写一份。T133 合并前，可以先按 T133 工单写明的接口开发，T133 合并后 rebase，删除任何临时实现。
- **问题来源（审计第 4 节）：** 没有工具能接收两个独立优化的极小点和人确认的原子映射，重排原子顺序、对齐取向并输出 QST2 输入。现有 QST 校验只检查元素序列，同种元素原子互换会通过检查。
- **负责人决定（10-26）：**
  - Q1 两端只接受**已取回**的优化 Attempt：取最终几何，核对两端电荷、多重度一致；来源（Attempt 和几何文件哈希）可追溯。不接受随手给的 XYZ 文件。
  - Q2 原子映射由人给出**完整的一一映射文件**，逐个核对元素；工具不推断映射。
  - Q3 对称歧义：在分子图上等价的同种原子之间试着交换；如果某种交换后对齐 RMSD 比给定映射更低，就**报错**并列出这些交换和各自的 RMSD。人要么改映射，要么加 `--keep-mapping --reason '<理由>'`；工具不自动换。
  - Q4 对齐默认用全部原子，只做旋转和平移（正规旋转），**禁止镜像**；可以用 `--align-atoms` 指定子集。报告对齐后的 RMSD 和位移最大的原子。
  - Q5 登记候选是可选项，默认不登记，规则同 T133 的 G3（`origin=qst`）。**T132 部署之前，真实研究 study 不使用这个参数。**
- **资料：** `ag/src/ag/gaussian_input.py`（`_qst_structures` 70、`_qst_displacements` 95、`validate`）、`ag/src/ag/geometry.py`（`infer_molecule` 89、`rms_atom_maps` 214、`best_rms` 241）、`ag/src/ag/facts.py`（`final_geometry`、`final_input_geometry`）、`ag/src/ag/cp_report.py` 102 行（最终几何的取法）、`ag/src/ag/catalog_v2.py`（`manifest_info`）、T133 工单、审计第 4、5 节。
- **新增检查防的事故：** 两端原子顺序不一致却通过了 QST 校验（同种元素互换），QST2 在错误的原子对之间插值；对称原子随手编号，导致路径无谓扭曲；镜像对齐悄悄改变手性。

## 允许改动的路径

- **新建** `ag/src/ag/qst_endpoints.py`：读取两端、映射校验、对称歧义检测、对齐、生成草稿、可选登记；命令 `ag qst-endpoints`，按现有可选子命令的方式注册。
- `ag/src/ag/geometry.py`：**只新增**一个正规旋转的 Kabsch 函数（例如 `kabsch(left, right) -> rotation, rmsd`）；`gaussian_input._qst_displacements` 改为调用它，**行为不变**（有现有测试保证）。如需新增“对单个分子图枚举等价映射（自同构）”的小函数，必须复用 `rms_atom_maps` 的同一套规则（元素、连接、四面体手性），不另写一套图匹配。
- `ag/src/ag/gaussian_input.py`：只为改用 `geometry.kabsch` 修改 `_qst_displacements`；其余复用 T133 的 `render_input`。
- 测试：新建 `ag/tests/test_qst_endpoints.py`；`ag/tests/test_gaussian_input.py`、`test_geometry*.py` 中受影响的用例。夹具全部合成（例如 SN2 型 Cl⁻ + CH₃Cl、带甲基的小分子质子转移；坐标虚构）。
- 文档：`README.md` 新增一节；`skills-next/auto-g16-recipes/cards/ts.md` 中 QST2 一段的操作步骤改为使用新命令（只改操作步骤，口径留给 T139）；本单 `docs/redesign-tasks/T134-endpoint-qst2.md`、`docs/redesign-tasks/open-tasks.txt`。
- **不改** prepare、submit、模板、facts、parent_chk、前端、`CHANGELOG.md`、版本号。

## 要做的

1. **命令行**：`ag qst-endpoints <study> --reactant <Attempt> --product <Attempt> --mapping <映射文件> --route '<route>' --out <新 .gjf> [--align-atoms <原子列表>] [--keep-mapping --reason '<理由>'] [--title-reactant …] [--title-product …] [--register-candidate --object <对象> --candidate-id <ID> [--target-channel <通道>]] [--upgrade-catalog] [--dry-run] [--json]`
2. **两端读取（Q1）**：
   - 两个 Attempt 都必须是本 study 的精确 ID、状态 fetched、facts 可读、优化已收敛（`opt_converged` 为 true）；
   - 最终几何按 `cp_report` 的取法（优先 `final_input.xyz`，否则 `final.xyz`），记录所用文件和 SHA-256；
   - facts 里已知 `n_imag` 且不为 0 时拒绝（不是极小点）；未知时警告；
   - 电荷、多重度用 `catalog_v2.manifest_info()` 取得，两端必须一致，取不到就拒绝。
3. **映射文件（Q2）**：JSON `{"product_to_reactant": [[1, 3], [2, 1], …]}`，编号从 1 开始。
   - 必须覆盖产物全部原子、一一对应、不重复、元素逐个相同；
   - 原子数不同直接拒绝；
   - 产物按映射重排为反应物的顺序。
4. **对称歧义（Q3）**：
   - 对重排后的产物分子图，用 `rms_atom_maps` 同一套规则枚举保持元素、连接和四面体手性的等价映射；对反应物也做一次；
   - 对每个非恒等的等价映射，计算交换后（按 Q4 的对齐原子集合）的 RMSD；
   - 若存在 RMSD 比给定映射低超过 0.01 Å 的交换，就报错，列出每个交换（涉及哪些原子对、交换后的 RMSD），不生成文件；
   - 加 `--keep-mapping --reason` 时照常生成，并在报告和登记里记下理由和被跳过的更优交换；
   - 等价映射超过上限（沿用 `RMS_MAX_MAPPINGS`）时报错，说明需要人缩小范围，不截断。
   - 分子图推断失败（例如成键判断不确定）时报错并说明，不猜。
   - **0.01 Å 只是报告用的比较容差，不是科学判据**；写在 README 里。
5. **对齐（Q4）**：用 `geometry.kabsch` 把重排后的产物对齐到反应物：
   - 默认用全部原子；`--align-atoms` 用反应物编号（从 1 开始）；
   - 只做旋转和平移，行列式为负时强制改为正规旋转，**不做镜像**；
   - 报告：对齐 RMSD、全部原子 RMSD、位移最大的 10 个原子（编号、元素、位移）。
6. **生成（复用 T133）**：
   - route 必须含 `QST2`（写法不限），不得含 `QST3`、扫描或冻结类关键词；RCFC/ReadFC 类的规则同 T133 的 G2；
   - 用 `render_input` 生成两段（反应物在前、产物在后），标题默认“QST2 reactant <Attempt>”“QST2 product <Attempt>”；
   - 生成后用现有 `validate` 校验（元素序列、电荷多重度一致等）；
   - 输出到新文件，不覆盖；不写 Link0；不自动 prepare，不提交。
7. **可选登记（Q5）**：
   - 候选几何用重排、对齐后的**产物**几何的 XYZ 字节；
   - `parent.attempt` = 反应物 Attempt；
   - `transform` 写入：`{"type": "qst2_endpoints", "reactant": {attempt, geometry_sha256}, "product": {attempt, geometry_sha256}, "mapping_sha256": …, "align_atoms": […] | "all", "align_rmsd": …, "skipped_better_swaps": […], "keep_mapping_reason": … | null}`；
   - 走 T131 的同一条登记路径（升级、`--dry-run`、存档规则全部沿用）。
8. **README 与卡片**：写清输入要求、映射文件格式、歧义处理、不镜像、不推断映射、生成的新取向**不能**拿来读取旧 chk 的 Cartesian 力常数（审计第 4 节）。

## 不允许

- 不推断原子映射，不自动选择“最优”映射，不做镜像对齐。
- 不接受 XYZ 文件作为端点；不放宽现有 QST 校验。
- 不自动 prepare 或提交；不新增远程操作；不改 facts、manifest。
- 不把 0.01 Å 或任何 RMSD 当作科学判据或自动拒绝阈值（它只用于判断“是否存在更低的交换”）。
- 夹具和 PR 里不出现真实研究对象、结构、study 名、Attempt 编号。

## 测试

| 场景 | 预期 |
|---|---|
| 合成 SN2 型两端、正确的完整映射 | 生成 QST2 草稿，通过 `validate`，两段原子顺序一致 |
| 映射缺原子、重复、元素不符、原子数不同 | 拒绝 |
| 两端电荷或多重度不同 | 拒绝 |
| 端点未 fetched、facts 不可读、未收敛、`n_imag ≠ 0` | 拒绝；`n_imag` 未知时警告 |
| 甲基三个 H 故意编错（交换后 RMSD 更低） | 报错，列出更优的交换和 RMSD，不生成文件 |
| 同一情形加 `--keep-mapping --reason` | 生成，报告与登记记下理由和被跳过的交换 |
| 等价交换后 RMSD 不更低 | 正常生成，报告列出已检查的等价映射数 |
| 等价映射超过上限 | 报错，不截断 |
| 产物是反应物的镜像构型 | 只用正规旋转；RMSD 如实报告，不镜像 |
| `--align-atoms` 子集 | 只用子集对齐，报告两种 RMSD |
| route 不含 QST2、含 QST3、含 ModRedundant | 拒绝 |
| 不带登记 / 带登记且升级 / 未加 `--upgrade-catalog` | 不碰 catalog / 候选 `origin=qst` 且 `transform` 齐全 / 拒绝登记但草稿保留 |
| `_qst_displacements` 改用 `geometry.kabsch` 后 | 现有测试（不镜像、不重映射）全部通过 |
| 输出文件已存在 | 拒绝，不覆盖 |

推送前本地跑一次全量 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，之后以 CI 为准；运行 `python scripts/scan_public.py`（带本机词表）和 `git diff --cached --check`。

## 真实环境验证（合并前，开发机；不提交作业）

- 在临时非研究 study 中放两个合成的已取回 Opt Attempt（夹具同款），走完生成和登记全流程；用 `ag prepare` 只运行到输入校验为止（或 `--dry-run`），确认它接受生成的 QST2 草稿。**不建 Attempt，不提交。**
- 不碰任何真实 study。PR 里只写结果。

## 停止条件

- 需要改 prepare、QST 校验规则或模板。
- 自同构枚举无法复用 `rms_atom_maps` 的规则，需要另写一套图匹配。
- T133 的 `render_input` 接口不够用：停下，由监督方协调两单，不要在本单另写一份。
- 同一问题修两次仍未解决。

## 合并前审阅与交付

- 需要监督方审阅：**是，逐行审**（映射校验、对称检测、对齐的旋转矩阵、catalog 写入）。合并只由负责人操作，**排在 T133 之后**。
- PR 描述包括：Q1–Q5 对应的改动、映射文件格式说明、测试表逐项结果、真实验证记录。

## 版本记录

- v1（2026-10-26，监督方）：依据 10-26 决定 Q1–Q5 起草；对应审计拆单建议中的 T-D。
- 接口补充（2026-10-26，负责人转达监督方协调）：T133 的 `render_input` 接受
  `title: str | Sequence[str]`；字符串重复用于各段，序列长度必须等于段数，每项非空且无换行。
  T134 传入反应物、产物两个标题；共享函数仅由 T133 实现，T133 合并后 rebase。
- 范围补充（2026-10-26，负责人在开发会话批准“批准这两处测试清单更新”）：
  允许 `ag/tests/test_smoke.py` 的注册测试命令列表与预期模块列表各增加 `qst_endpoints`，
  不改变测试逻辑；与 CLI 的一项可选子命令注册同步。

## 开发验证记录（2026-10-26）

- T133 共享接口已按协调补充实现并合并（PR #335，`6d86346`）；本单不含渲染器副本。
- 专项 67 项通过；原 Gaussian 输入及几何回归 278 项通过。两单临时集成源码与
  T133 `0f9d889` 加本单改动逐文件核对一致。
- rebase 到 `6d86346` 后，在实际分支运行完整离线测试：5203 passed、19 skipped。
  跳过项为 Linux 方言与未启用私有日志；获批补齐的 smoke 测试文件 25 项通过。
- 开发机临时非研究 study 完成合成 fetched 端点生成、catalog 升级登记和 ledger 查询；
  草稿另存副本补资源头后，实际 prepare 运行至现有输入 validate 成功即停止。
  临时集成副本与 rebase 后实际分支均通过，草稿哈希一致；prepare 阶段未创建 Attempt，
  未提交，study 原有文件字节保持不变。
- 暂存内容和 PR 正文使用本机词表扫描，无命中；格式检查通过。
- 当前阻塞（科学审阅）：待监督方逐行审阅；仅负责人合并。
