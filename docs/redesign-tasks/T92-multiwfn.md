# T92：`multiwfn` 提交模板（fchk + IGM / IGMH）与本地结果解析

## 分支与目标

- 分支：`codex/t92-multiwfn`；基于最新 main，一张任务单一个 PR。**开发机做。**
- **目标：** 在 RTwin（组里 PBS 集群）上用 Multiwfn 做非共价相互作用分析：
  1. 新增提交模板 `multiwfn`：一个作业内依次完成“复制父 Attempt 的 chk（用 ag 现有的专用复制操作）→ `formchk` → Multiwfn 固定菜单脚本”；只取回结果文件，fchk 留在集群上；
  2. 分析类型白名单：`igm`（前分子密度，只需坐标，可批量）和 `igmh`（需真实波函数，即 fchk）；格点精度只有 `low` / `medium` / `high` 三档；
  3. 新增本地命令 `ag nci-report`：把取回的数值表解析为 `ag-nci/1` JSON（每个原子对片段间作用的贡献、按片段汇总、输入哈希）。
- **负责人 10-17 决定：** Multiwfn 在 RTwin 上跑（不在 Mac 上）；两级流程——IGM 快速筛，关键 TS 用 IGMH 细看；IGMH 波函数用与几何同层级的 Opt 方法，单点层级的波函数为可选；fchk 按需由本模板生成，不改 Gaussian 模板；片段用 CSV 定义，默认两个、最多四个，由人确认；这一轮只支持 RTwin，不做 SCNet；不做前端显示和图形渲染。
- **属于新增远程模板和远程复制操作的扩展：** 必须审阅，并在合并前在 RTwin 上做真实验证。
- 资料：`ag/templates/`（`gaussian.pbs`、`xtb.pbs`、各 `.toml` 声明、`_guard.sh`）、`ag/src/ag/render.py`、`ag/src/ag/config.py`（`programs` 配置与校验）、`ag/src/ag/parent_chk.py`、`parent_chk_remote.py`、`ag/src/ag/remote.py`（`copy_parent_chk`）、`ag/src/ag/attempt.py`（prepare）、`ag/src/ag/fetch.py`（输出名单）、`docs/DEVELOPING.md`（新增远程命令须写明防的是哪个事故）；Multiwfn 所用版本的官方手册（IGM、IGMH 章节）。

## 前提（10-17 已完成，不进仓库）

- RTwin 已在用户目录装好 **Multiwfn 2026.10.1 Linux noGUI**（负责人单次授权安装；安装包 SHA-256 本地与集群一致；登录节点单线程读入自带 `H2.fch` 成功）。可执行文件路径记录在仓库外的安装记录中，开发机本机 ag 配置写入 `programs.multiwfn` 时取该值；**路径、主机、用户名不进仓库、PR 和测试夹具**。
- 版本固定为 2026.10.1：菜单编号、输入顺序、输出文件名一律以**该版本手册**（IGM、IGMH 章节，以及命令行参数和 `settings.ini` 说明）为准，模板注释写明版本和章节号。
- `formchk` 取已配置的 Gaussian 目录下的程序（与 `gaussian.pbs` 使用的 Gaussian 环境相同），不另配路径。
- 验证用的父 chk 由真实验证第一步新算的 Gaussian Attempt 产生，不依赖旧 chk。

## 运行环境要求（新增，写进 `multiwfn.pbs`）

- **配置值：** `programs.multiwfn` 为集群上的可执行文件路径；允许以 `~/` 开头，渲染时转为 `"$HOME/…"`；其余情况必须是绝对路径；渲染时加引号，不允许空格以外的 shell 特殊字符（复用现有路径校验写法）。
- **线程数：** 等于作业申请的核数。优先用手册中的命令行参数（如 `-nt <核数>`）设置；如果 2026.10.1 手册没有该参数，改为在 Attempt 目录内**新建**只含线程设置的 `settings.ini`（文件已存在就报错，不覆盖），并在 PR 中说明依据。两种都不可行时停下。
- **栈设置：** 按手册对 Linux 版的建议设置 `ulimit -s unlimited`（失败时记录但不中止）和 `OMP_STACKSIZE`（取手册推荐值，写在模板中并注明出处）。
- **不依赖环境变量 `Multiwfnpath`、不读用户家目录下的 `settings.ini`：** 作业在 Attempt 目录内运行，保证每次结果只由模板决定。作业开始时把 Multiwfn 版本行写入标准输出，供 `nci-report` 读取。
- **非交互：** 菜单脚本通过标准输入喂入，末尾必须明确退出；作业设 walltime，Multiwfn 卡在菜单等待输入时由 walltime 终止，`nci-report` 应把“标准输出中无正常退出标记”判为失败，不解析半成品。

## 允许改动的路径

- 新增 `ag/templates/multiwfn.pbs`、`ag/templates/multiwfn.toml`，以及 Multiwfn 菜单脚本模板（固定文本，按分析类型和格点档位各一份，放在 `ag/templates/multiwfn/` 下）。
- `ag/src/ag/config.py`：新增可选的 `programs.multiwfn`（`root` 或可执行文件路径），只在使用 `multiwfn` 模板时要求。
- `ag/src/ag/render.py`：为 `multiwfn` 模板提供参数。
- `ag/src/ag/parent_chk.py`、`parent_chk_remote.py`：只把父 chk 附件从“仅 gaussian 模板”扩展到“gaussian 或 multiwfn 模板”，其余检查（同 study、同集群、独占创建、复制前后核对哈希、父文件只读）一条不放宽。
- `ag/src/ag/attempt.py`：`multiwfn` 模板的 prepare 校验（分析类型、格点档位、片段 CSV、输入 XYZ 或父 chk 的约束）。
- 新增 `ag/src/ag/nci_report.py`；`ag/src/ag/cli.py` 登记 `nci_report`（命令名 `nci-report`）。
- `ag/tests/test_smoke.py`：**已预先批准**，只在固定的分析命令列表断言里追加 `ag.nci_report`。
- 新增测试：`ag/tests/test_multiwfn_template.py`、`ag/tests/test_nci_report.py` 及合成夹具；`ag/tests/test_parent_chk.py` 新增用例。
- 新增 `docs/ag-nci-1.md`；`ag/README.md`；新增或补充卡片：`skills-next/auto-g16-recipes/cards/complex.md` 或 `profile.md` 中补“非共价相互作用分析”一小节（只写用法和适用边界）。
- `docs/redesign-tasks/T92-multiwfn.md`：本任务单。
- **不改 `gaussian.pbs`、`submit.py` 的确认流程、`status.py`、`transport.py`。**

## 要做的

1. **模板参数：**
   - `--analysis igm|igmh`；`--grid low|medium|high`；`--fragments <片段 CSV>`（列 `fragment`、`atoms`，`atoms` 用 `1-40,52` 写法；2–4 个片段，互不重叠、覆盖全部原子，否则 prepare 报错）。
   - `igmh`：必须 `--parent <Attempt> --parent-chk <Attempt>:<chk 名>`；父 Attempt 必须是 Gaussian 且正常结束；几何取父 chk 中的结构，prepare 时核对片段 CSV 的原子数与父 Attempt 一致。
   - `igm`：输入为一个多帧 XYZ（上限 50 帧，帧间原子一致，复用 `crest_input.xyz_ensemble` 的检查），不需要父 chk；每帧在同一个作业内依次计算，输出按帧编号命名。
2. **作业脚本：** 先运行现有守卫（`_guard.sh` 的写法）；`igmh` 时调用 ag 现有的父 chk 复制（不新写复制命令）→ `formchk parent.chk parent.fchk` → 用固定菜单脚本运行 Multiwfn；Multiwfn 的菜单编号和输入顺序**以 RTwin 上所装版本的手册为准**，写进脚本模板时注明版本和手册章节；不在作业中删除任何文件；fchk 留在 Attempt 目录内，不在输出名单中（不取回）。
3. **输出名单（`multiwfn.toml`）：** Multiwfn 标准输出、片段间 δg 格点文件（cube）、原子贡献数值表等实际文件名以真实运行为准；`ag fetch` 照常工作。为防止取回过大，`high` 档位预计输出大小写进确认摘要。
4. **确认摘要：** 显示分析类型、格点档位、片段定义（每个片段的原子范围和元素组成）、父 Attempt 及其方法口径、预计输出大小，以及“结果仅为相互作用的可视化与半定量分析，不是能量分解”。
5. **`ag nci-report <Attempt> --out <analyses/ 下新的 .json>`：** 解析取回的数值表：每个原子对片段间 δg 的贡献（原子序号、元素、所属片段、数值）、按片段汇总；记录 Multiwfn 版本（从标准输出读取）、分析类型、格点档位、片段定义、所有输入 / 输出文件的 SHA-256；`igm` 多帧时逐帧输出。格式写进 `docs/ag-nci-1.md`（`schema: "ag-nci/1"`）。
6. **新增远程命令说明（DEVELOPING 规则）：** 在 PR 中写明新增或改变的远程操作、防的是哪个事故（例如：父 chk 只读、不覆盖、复制前后核对哈希；fchk 不取回以免占满本地空间）。

## 不允许

- 不改 Gaussian 模板；不放宽父 chk 复制的任何检查；不在远程删除或覆盖文件。
- 分析类型、格点档位不开放白名单以外的值；不允许用户传入自定义 Multiwfn 菜单脚本。
- 不做图形渲染和前端显示。

## 测试

- prepare：合法 `igm` / `igmh` 参数；片段重叠、未覆盖、超过四个、原子数与父 Attempt 不符、`igmh` 缺父 chk、`igm` 超过 50 帧 → 报错。
- 渲染出的作业脚本：只调用守卫、ag 的父 chk 复制、`formchk`、Multiwfn；菜单脚本为固定文本；无删除、无覆盖。
- `parent_chk`：`multiwfn` 模板可用，其余检查与 gaussian 模板完全相同（同 study、同集群、不同 Attempt 等）。
- `nci-report`：用按真实格式改写的合成数值表测试解析、片段汇总、多帧、文件缺失或格式不符时报错。
- 开发中只跑相关测试；推送前本地跑一次全量 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，之后以 CI 为准。敏感扫描与 `git diff --cached --check`。

## 真实环境验证（合并前，开发机，RTwin）

- 在**非研究 study** 中：一个小的双分子体系（例如水二聚体或甲醇–水，低理论级别）先做一个 Gaussian Opt+Freq（保留 chk），再提交：
  1. `igm`：3 帧（同一体系的不同取向），medium；
  2. `igmh`：以该 Gaussian Attempt 为父 chk，medium，两个片段。
- 每个提交由负责人说“提交”并亲手点击，每个 Attempt 只提交一次。
- 菜单脚本先用 `igm` + `low` 的最小作业试一次（同一非研究 study，也须负责人点击提交）；菜单走错时只修模板、新建 Attempt 重提，不重提同一 Attempt。
- 核对：作业正常结束；标准输出中的线程数等于申请核数、版本行为 2026.10.1；父 chk 哈希复制前后一致、父文件未改变；输出文件名与 `multiwfn.toml` 一致；`ag fetch` 正常、未取回 fchk；`ag nci-report` 解析成功，片段汇总合理（例如氢键供体 / 受体原子贡献最大）。
- 结果写进 PR 评论，不写主机、路径、用户名。HSS 不作为验证对象；HSS 的实际使用在合并后另行安排。

## 停止条件

- RTwin 上 Multiwfn 2026.10.1 的菜单与手册不符，或需要交互输入才能完成；线程数无法按“运行环境要求”设置。
- 需要放宽父 chk 复制的任何检查，或修改 Gaussian 模板、提交确认流程。
- 真实验证中出现任何意外（按 AGENTS.md 停下汇报）。

## 合并前审阅与交付

- 需要监督方审阅：是（新增远程模板）。
- PR 描述第一行：`Task: T92`；附远程操作清单和真实验证结果。
- 合并只由负责人操作。

## 10-17 范围补充（监督方批准，负责人在开发对话中转述）

- 允许修改 `ag/src/ag/remote.py`，只限 `output_names()` 新增 `multiwfn` 分支；其他模板输出完全不变。
- 帧数必须取本 Attempt manifest 的 prepare 记录，显式校验 1–50；缺失不默认。编号三位补零。
- fchk 不取回；high 的 cube 取回策略与确认摘要估算一致。
- 在 `test_multiwfn_template.py` 覆盖旧模板输出不变、1/3/50 帧、缺失/越界帧数。
- RTwin 的 3 帧 IGM 验证须逐帧通过 status 与 fetch。其他 remote 函数及 fetch/status/transport 不在扩展范围。
