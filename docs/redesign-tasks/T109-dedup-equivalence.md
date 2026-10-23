# T109：dedup 修正——等价原子映射、镜像报告、顺序依赖与边界候选

版本：v1（监督方，2026-10-23）。**开发机做。** 后端出一个 PR，PR 描述第一行写 `Task: T109`。公开入库版省略研究体系标识、候选编号和未发表数值；功能范围与验收要求不变。

## 分支与目标

- 分支：`codex/t109-dedup-equivalence`。
- **开工条件：** 后端 main 为 `6419a04` 或其后；T109 编号没有被占用。T108 是另一个独立 PR，和本单不涉及同一批文件。
- **问题来源：** 研究现场问题汇总：原生 `ag dedup` 曾高估等价构象的 RMSD，原因是芳香键的表示方式限制了映射。以合成正丙苯复现，研究结构与数值不入库。
- **负责人 2026-10-23 决定**（按监督方推荐）：
  - D1 去重时要能识别芳香环翻转等**拓扑等价原子**的置换。
  - D2 增加 `--mirror report`：只报告镜像 RMSD，**不合并**。手性体系禁止合并镜像，这条规则不变；非手性体系的镜像简并仍由 `ag cluster --mirror` 处理。
  - D3 报告中写明算法依赖输入顺序，并列出接近阈值的"边界候选"。
- **资料：** `AGENTS.md`、`docs/DEVELOPING.md`、`docs/LESSONS.md`；`ag/src/ag/dedup.py`、`ag/src/ag/geometry.py`（`infer_molecule`、`graph_key`、`rms_molecule`、`best_rms`）、`ag/src/ag/cluster.py`；卡片 `crest-screen.md`、`conformer-workflow.md`。

## 背景（main `6419a04` 的代码现状）

1. `best_rms()` 调用 `rdMolAlign.GetBestRMS(probe, reference)`，用分子自身的子结构匹配来枚举对称映射。每一帧都由 `infer_molecule()` 单独推断键级，所以两帧的 Kekulé 双键位置可能不同。这时苯环翻转后的映射（邻位与邻位、间位与间位互换）因为键级对不上而被排除，RMSD 被高估，本该合并的构象被保留下来。
2. `dedup` 按能量从低到高逐个处理，每个构象只和已保留的代表比较，结果和处理顺序有关；报告里没有说明这一点。
3. `dedup` 没有镜像选项。`cluster` 有 `--mirror`，但只用于非手性体系的简并计数。

## 允许改动的路径

- `ag/src/ag/geometry.py`：只改用于 RMSD 比较的副本以及映射的生成方式。`infer_molecule`、`graph_key`、`stereo_key` 的判定**不改**。
- `ag/src/ag/dedup.py`：映射、`--mirror report`、报告字段。
- `ag/src/ag/cluster.py`：只在它共用的 `best_rms` 改动需要同步时才改；改动后的行为变化要在 PR 中说明。
- 测试：相关的现有测试（在 PR 中列出），新建 `ag/tests/test_dedup_equivalence.py`。
- 文档：`docs/LESSONS.md`、`README.md`（dedup 说明）；`skills-next/auto-g16-recipes/cards/crest-screen.md`、`skills-next/auto-g16-structures/references/conformer-workflow.md`（只写判读方式）。
- `docs/redesign-tasks/T109-dedup-equivalence.md`（本单）、`docs/redesign-tasks/open-tasks.txt`。

## 要做的

### 1. 等价原子映射（D1）

- 计算 RMSD 时，对称映射要按**与键级无关**的分子图来枚举：只看元素和连接关系；芳香环可以先统一做芳香化，或者直接忽略键级。不能受每一帧各自的 Kekulé 写法影响。
- 用 `GetBestRMS` 的 `map` 参数显式传入映射，或采用等价做法。映射数量要设上限：超过上限时报错，并提示改用 `--hydrogens heavy`，**不能静默截断**。
- 立体化学仍然要守住：拒绝会让立体中心构型反转的映射。`graph_key` / `stereo_key` 的"连接改变 / 立体改变"判定照旧。
- 报告里记录每一对重复构象所用映射的类型：`identity`（原编号）或 `symmetry`（等价置换），以及采用的 RMSD。
- `cluster` 共用 `best_rms`，会因此一起受益。PR 中说明这一行为变化。

### 2. `--mirror report`（D2）

- 新增 `--mirror {off,report}`，默认 `off`，行为和现在完全一样。
- `report` 模式下，对保留下来的代表两两计算镜像 RMSD（复用 `best_rms(..., mirror=True)`，同样使用第 1 节的映射）。镜像 RMSD 低于阈值的列为 `mirror_pairs`，同时给出普通 RMSD 和镜像 RMSD。**不合并**。
- 分子含有已指定构型的手性中心时，报告里写明"手性体系，镜像对不是同一构象，仅供识别对映构象"。

### 3. 顺序依赖与边界候选（D3）

- 报告顶层写明算法：按能量从低到高排序，逐个与已保留的代表比较，遇到第一个满足条件的就归入；结果依赖顺序。
- 新增 `boundary_pairs`：
  - 保留下来的代表之间，RMSD 小于 2 倍阈值的配对；
  - 被并入的构象中，RMSD 高于阈值一半的。

  每条记录都给出 RMSD、能量差和映射类型，供人工复核。只报告，不改变去重结果。

## 不允许

- 不改默认阈值、默认氢原子选择，以及 `graph_changed` / `stereo_changed` 的判定。
- `--mirror` 不提供合并模式；不改 `cluster --mirror` 的规则（手性体系拒绝）。
- 不自动对已有 study 重新去重。已有的 dedup 报告和分析文件不改。
- 测试夹具不得使用研究体系的结构（AGENTS 第 3.10 条）。

## 测试

| 场景 | 预期 |
|---|---|
| 正丙苯：同一构象的两帧，苯环 Kekulé 写法不同 / 苯环翻转 180° | 被识别为重复，`mapping=symmetry`，RMSD 接近 0 |
| 原来按原编号就能合并的情况 | 结果不变，`mapping=identity` |
| 两个真正不同的构象 | 仍然各自保留 |
| 映射会使立体中心反转 | 该映射被拒绝 |
| 等价映射数超过上限 | 报错，并提示改用 heavy；不静默截断 |
| `--mirror off`（默认） | 输出和现在逐字段一致，只新增顶层的算法说明和 `boundary_pairs` |
| `--mirror report`，非手性体系，存在镜像对 | 列出 `mirror_pairs`，不合并 |
| `--mirror report`，手性体系 | 列出镜像对并附说明，不合并 |
| 构造一组 RMSD 在阈值附近的数据 | `boundary_pairs` 正确，结果与顺序的关系在报告中写明 |
| `cluster` 的现有测试 | 通过；如有变化，逐条说明 |

开发中只跑相关测试；推送前本地跑一次全量 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，之后以 CI 为准；另外做敏感信息扫描和 `git diff --cached --check`。

## 真实数据验证（合并前，开发机，非研究体系；不需要提交作业）

dedup 只在本地运行，不连接集群。

1. 用 T106 验证得到的正丙苯结构（以及开发机上已有的其他非研究 CREST 系综，例如正丁烷）各跑一次，把新旧版本的组数和映射类型对照着报告出来。
2. 用 RDKit 从正丙苯结构生成苯环翻转的副本，验证能被合并。
3. **可选（需负责人另行批准）：** 在开发机本地，对指定研究 study 的 CREST 结果跑一次新版 dedup（输出放在 study 之外），只向负责人汇报组数，不把任何结构或数值写进 PR。

## 停止条件

- 等价映射的数量在常见体系上就超出上限，需要另行设计。
- 需要修改连接或立体判定，或者需要改动范围外的文件。
- 同一问题修两次仍未解决。

## 合并前审阅与交付

- 需要监督方审阅：**是**。合并只由负责人操作。
- PR 描述要写：D1–D3 对应的改动，`cluster` 的行为变化，新旧版本对照，全量测试结果。
- **合并后：** 开发机同步。已有 study 是否重新去重，由负责人逐个决定；研究候选如需重新去重，须另行授权。

## 版本记录

- v1（2026-10-23，监督方）：依据研究现场问题汇总、芳香环等价映射经验，以及负责人 10-23 的决定起草。

## 开发与本地验证（2026-10-23）

基线 `6419a04`；开工时没有同编号工单、PR 或分支。D1 在 RMSD 查询副本中按元素 / 任意键枚举，保留立体中心置换奇偶性；查询第 10,001 个以检测超出 10,000 的上限。原编号拟合用 SVD 复核，避免刚体旋转的数值误差把 identity 标成 symmetry。`infer_molecule`、`graph_key`、`stereo_key`、`rms_molecule` 经 AST 核对均未改动。

D2 仅比较最终保留代表；指定手性中心时附说明，`stereo_changed` 仍排除，因此镜像报告不是被排除对映体的清单。D3 新增 `algorithm` / `boundary_pairs`，可比能量按能量升序、同能按输入顺序，非可比来源按输入顺序、配对能差为 null。重复记录按 D1 另新增 `mapping`。

cluster 源码无需改动；普通比较、镜像比较、medoid 共用新映射与超限错误，其手性镜像拒绝、能差及简并度规则不变。新增 `test_dedup_equivalence.py`；修改既有 `test_dedup.py` 的兼容测试，扣除两个新顶层字段后仍核对原 JSON / stdout 哈希，XYZ 哈希不变。

以下仅为**非研究小分子的工程验证**。对象来自 [T106 工单](T106-newhpc-limits-crest.md) 中明确声明“均为中性单重态、气相、非研究分子”的验证，另以本地拓扑确认 `CCCc1ccccc1`（C9H12）及 `CCCC`（C4H10）；没有使用可选研究系综。T109 本单要求对这些对象报告新旧组数与映射。RDKit 2026.03.3；旧版 `6419a04`，新版为本 PR；charge=0、polar、RMSD=0.125 Å、de=0.05 kcal/mol、window=3 kcal/mol。

| 非研究验证对象 | 帧数 | 旧组数 | 新组数 | 重复映射 / 说明 |
| --- | ---: | ---: | ---: | --- |
| 正丙苯最终几何 | 1 | 1 | 1 | 单帧，无重复配对，不冒充系综验证 |
| 上述几何 + RDKit 苯环翻转副本 | 2 | 2 | 1 | symmetry；RMSD 1.288440 → 0.034419 Å |
| 正丁烷 CREST 验证系综 | 5 | 4 | 4 | 无重复配对；两版均排除 1 个窗口外帧 |
| 另一已存在的正丁烷 CREST 验证系综 | 3 | 3 | 3 | 无重复配对；两套正丁烷均报告 1 对镜像，不合并 |

旧版不记录映射类型；没有重复项时不存在重复映射。源文件读取前后 SHA-256 一致，对照输出与输入哈希清单留在仓库及 study 外；未连接集群、未改已有分析或签字。相关代码 / Skills 测试 649 项通过。

2026-10-23 负责人明确回复“批准这项测试修改”，授权 `ag/tests/test_ensemble.py` 的 5 行兼容测试修正：历史哈希测试保留旧版输入夹具，新版输入测试另断言实际 SHA-256。原因是 ensemble 记录完整 dedup 文档的哈希，T109 新增字段会按预期改变它；ensemble 产品代码不改。

推送前一次全量 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`：4311 passed、19 skipped、1 failed（556.37 s）。唯一失败是上述旧哈希夹具；获批修正后 `ag/tests/test_ensemble.py` 全部 49 项通过（64.67 s），之后以 CI 检查最终提交，不重复本地全量。跳过项为 18 项 Linux stat/procfs 方言检查和 1 项未启用的私有日志测试。敏感信息扫描及 `git diff --cached --check` 通过。功能提交 `6afd8b8` 的 [CI #358](https://github.com/anakine800-tech/Auto-Gaussian/actions/runs/39887077166) 全绿：后端 3821 passed、1 skipped，Skills 509 passed。

## 监督意见与性能补证（2026-10-23）

负责人在开发对话转述监督方结论：T109 通过，CI 全绿后可由负责人合并；并建议用约 80 原子的非研究体系记录 polar / all 耗时与映射数。以下补证使用功能提交 `6afd8b8`，后续只改本文及 LESSONS；更新后的 head 按仓库流程复核。

使用合成正二十六烷 C26H54：`Chem.AddHs(Chem.MolFromSmiles('C' * 26))`，共 80 原子。以 RDKit ETKDGv3 生成 300 帧，`randomSeed=109`、`numThreads=1`、`pruneRmsThresh=-1`；没有力场优化，各帧能量人为设为 0 kcal/mol，专用于全体可比的性能压力样例，不代表真实能量或构象布居。Python 3.11.15、RDKit 2026.03.3、macOS，Python 进程架构为 x86_64；charge=0、RMSD=0.125 Å、de=0.05 kcal/mol、window=3 kcal/mol、mirror=off，每种氢模式各运行一次。

计时覆盖 `ag.cli.main` 读入、成键/立体推断、去重和输出；不含 import 与 58.01 s 的几何生成。临时包装 `rms_atom_maps` 统计调用次数、返回映射数与枚举耗时，包装开销计入；源代码与 10,000 上限均不改。计时是一次本机观测，非重复测量或跨机器基准。

| 模式 | 参与比较原子 | 总耗时 | 映射调用 / 每次映射数 | 枚举耗时 | 结果 |
| --- | ---: | ---: | --- | ---: | --- |
| polar | 26 | 103.86 s | 44,850 次 / 均为 2 | 71.47 s | 300 帧均保留，无排除项及边界候选 |
| all | 80 | 1.60 s（至拒绝） | 首次调用 / 至少 10,001 | 0.57 s | 超出上限，退出码 1，提示 `--hydrogens heavy`；未输出去重结果 |

all 的 10,001 只是触发检测的下界，不是全部映射总数，1.60 s 也不是完整去重耗时。此样例没有极性氢，因此 polar 实际比较 26 个碳；不能外推为所有 80 原子体系的耗时。按监督意见记录预期的 all 超限，没有截断、提高上限或自动改模式。输入 SHA-256 前后一致；合成坐标、原始计时和 CLI 输出保留在仓库外，未接触研究数据或集群。
