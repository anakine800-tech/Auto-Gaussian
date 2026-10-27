# T150：新 Gaussian 输入自动补齐核数

版本：v1.0，2026-10-27。开发机做。后端一个分支、一个 PR；PR 描述第一行写 `Task: T150`。本单不授权提交计算或部署。

## 1. 分支与目标

- 分支：`codex/t150-gaussian-resource-fill`。
- 已核实基线：后端 main / v4.6.2 `020475a81bf0354ecc5c25941ace2fd584969bbf`。代码可独立准备；合并前基于已合并的 T148/T149 更新，核对共享文档。
- 目标 G01：新输入缺少 `%nprocshared` 时，由 prepare 按已明确选择的资源档位补齐。
- 负责人决定 X1：按监督推荐范围准备本单；X2：只补缺失项，显式冲突仍拒绝；旧 Attempt、manifest、输入和哈希不改。
- 默认做法（已告知负责人）：覆盖 `gaussian` 与 `gaussian-cp` 的共同准备入口；单结构、QST2/QST3、合法父 chk 流程复用相同补齐步骤。方法、结构、电荷、多重度、route 和 walltime 不自动决定。
- 新检查/记录防的事故：自动补齐覆盖人工资源值；校验与确认看见的输入不是上传的字节；把新规则反向应用到旧 bundle。
- 资料（上述基线）：`ag/src/ag/attempt.py:106`（prepare）、`:154`（fill_memory 调用）、`:264`（auto_mem 元数据）、`:287`（verified_files）、`:436`（resource_summary）；`ag/src/ag/gaussian_input.py:191`（fill_memory）；`ag/tests/test_resources_monitor.py:26`；README 的资源与 TS/QST 草稿段落。

## 2. 允许改动的路径

- `ag/src/ag/gaussian_input.py`：小型字节补齐函数，保留现有 `fill_memory` 接口和内存规则。
- `ag/src/ag/attempt.py`：在创建新 Attempt 前调用补齐、保存可选说明并展示。
- `ag/tests/test_resources_monitor.py`、`ag/tests/test_gaussian_input.py`、`ag/tests/test_counterpoise.py`、`ag/tests/test_node_targeting.py`：对应行为与字节回归。
- `README.md`、`docs/DEVELOPING.md`、`docs/LESSONS.md`：仅更新本单相关的准备能力说明。
- `skills-next/auto-g16-recipes/cards/ts.md`：仅更正“必须手工补核数”的现有句子，不拆卡、不扩写科学策略、不增加行数。
- `docs/redesign-tasks/T150-gaussian-resource-fill.md`、`docs/redesign-tasks/open-tasks.txt`：本单归档和自身标记。

不改模板、提交、批准、配置、扫描/QST 草稿生成器、前端资源编辑器、版本号或冻结目录。

## 3. 要做的

1. 在 prepare 已完成档位与 walltime 检查之后、现有 `fill_memory` 之前，对 Gaussian 输入字节执行“只补缺失核数”。仍必须在 Attempt 序号占用、目录创建和写文件之前完成全部输入校验。
2. 建议新增局部函数 `fill_nprocshared(data, cores)`，返回补齐后的 bytes 和“本次是否补齐”的值；这是本单拟新增接口，不是现有 API。不要改为一个通用输入重写框架。
3. 仅识别文件开头连续 Link0 行，大小写与空白规则和现有校验一致。已有 `%nprocshared` 无论合法、冲突、重复或值非法，都不覆盖、不修正；交原校验器决定接受或拒绝。标题/route/坐标里的同名文本不视为 Link0。
4. 真缺失时，在最前面插入 `%nprocshared=<档位核数>` 一行，不重新排列已有 `%mem`、`%chk`、`%oldchk` 或其他字节。插入行使用第一条现有行的 LF/CRLF；空输入仍按原规则拒绝，不把空文件修成合法作业。
5. 随后复用 `fill_memory`：内存缺失才补，仍为 `min(cores * 2, mem_gb * 85 // 100)` GB；显式内存保持原字节，超过 85% 仍拒绝。不改变 85% 校验或其他单位处理。
6. 已完整合法的普通 Gaussian 输入必须逐字节不变；只缺内存的历史路径仍产生原有字节。gaussian-cp 自身现有的片段输入转换继续按原逻辑执行，不把其既有转换误称为本单的字节保留承诺。
7. 只在确实自动补核数的新 manifest 增加可选 `auto_nprocshared` 整数，值为实际插入核数；资源摘要写明“%nprocshared 由 ag 自动填写：N”。沿用 `auto_mem_gb`。这两个说明均不是额外授权。
8. input SHA-256 与 bundle SHA-256 必须以补齐、校验和既有 CP 转换后的实际 inputs 字节计算。源 `.gjf` 不变；后续 verified_files/submit 只验证保存字节，绝不再次补齐或更新旧哈希。
9. 缺少新元数据的旧 manifest 正常读取与核验。显式资源冲突、非法 Link0、危险 chk 路径、电子态错误、QST 不一致仍在创建 Attempt 前拒绝。
10. 同步 README 和 TS 卡现有说明：草稿仍无资源选择；人先明确档位，prepare 可以补缺失资源行；不把自动补齐写成自动 prepare/submit，也不删除结构、方法或 TS/IRC 审核要求。

## 4. 不允许

- 不覆盖用户输入，不改任何已有 Attempt、manifest、Claim、submission、批准记录或研究数据。
- 不把档位冲突改成静默采用另一方，不自动选档位、节点、集群、方法或 walltime。
- 不新增 `--force`、跳过校验或确认的选项；不增加远程操作。
- 不修 G02、C01/C02，不拆 TS 卡，不归档额外指南，不发布或部署。

## 5. 测试

| 场景 | 预期 |
|---|---|
| 核数与内存都缺失 / 只缺核数 / 只缺内存 | 按本单顺序补齐，保留既有 R1 内存值 |
| 已完整合法输入，LF/CRLF、合法大小写与空白 | 保存字节不变，未补字段不新增说明 |
| `%mem`、`%chk`、`%oldchk` 的不同合法顺序 | 只插入缺失行，其他字节与顺序不变 |
| 标题含 `%nprocshared`、重复/无效/冲突 Link0、空输入 | 不误识别；非法情况拒绝，不分配序号或目录 |
| 本机档位核数、多入口资源、显式节点约束 | 使用已选有效档位，不绕过 node_targeting |
| 普通单结构、QST2、QST3、gaussian-cp、合法父 chk | 同一补齐入口，其他校验与既有转换保持 |
| 输入缺失或显式超限内存 | R1 行为不变，超限仍拒绝 |
| 摘要、manifest 输入哈希、bundle、verified_files | 都绑定最终保存字节；源文件哈希不变 |
| 旧无 auto_nprocshared manifest / 旧 bundle | 正常核验且字节不变；损坏输入仍拒绝 |

推送前一次全量 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，记录跳过原因。保留既有 PBS/Slurm 脚本字节回归；本单不改模板。

暂存精确文件后运行 `python scripts/scan_public.py --staged --terms-file <PRIVATE_TERMS_FILE>`、`git diff --cached --check`，人工核对 PR 和 Git noreply 身份。不得修改扫描器或弱化测试以通过。

## 6. 真实环境验证

不需要真实计算或 SSH。用开发机仓库外、独立合成 study 与合成配置，完成新输入 prepare、摘要、保存字节和哈希核验；测试不读取真实研究数据。

不创建 approval、不调用 submit、不占用计算资源。`verified_files` 的纯本地合成验证不等于真实上传/执行已验收。涉及父 chk 的回归使用已有假传输和合成附件，不借用真实 chk。

## 7. 停止条件

需要修改模板/submit 或旧 manifest 才能实现；已有完整输入字节回归变化且不能解释为既有 CP 转换；需超出卡片授权范围；同一问题修两次仍失败。报告实际阻塞，不自动扩大功能。

## 8. 合并前审阅与交付

- 逐行审阅补齐、创建 Attempt 的先后顺序和哈希绑定；逐段核对文档与 TS 卡，禁止顺带重排长段落。
- PR 写准确 HEAD、源/保存字节关系、完整输入兼容、假传输与真实验证边界、扫描和全量测试结果。
- 读取监督评论并逐项处理；负责人合并。本单代码可独立准备，建议在 T149 后合并，先 rebase 处理 README/LESSONS/任务标记交叉改动。

## 9. 版本记录

- v1.0：按负责人确认范围编制；新输入可补核数，旧输入和既有安全检查不迁移、不放宽。

## 10. 执行与验收记录（2026-10-27）

- 初始开发基线：`830ce69e69ff3559bbc72ab603fe3a7ed3e8eb43`，已包含 T148 / PR #347；初始 HEAD `19b2f9ccaf0eaa6c38b7872b77c3d36499f1a821` 已由负责人在会话中确认监督复核通过、无必改项。
- T149 / PR #349 合并后，已 rebase 到最新 main `06f3dfe2d4a62452bbd003a51cd3472c427834a1`（含已复核的 T149 HEAD `23aad6441a7ac8a542d639f75b39c5cf7e1a76c6`）。README 和共享测试自动合并；LESSONS 的末尾追加冲突按 T149、T150 顺序完整保留。DEVELOPING、TS 卡及任务标记已核对。T150 实现及原有测试内容不变，T149/T151 共享字段不变；新 HEAD 与对应检查结果另交监督方增量复核。
- 实现：只新增局部 `fill_nprocshared`；位于共同 Gaussian prepare 入口的 `fill_memory` 之前。全部既有输入校验先于序号声明和目录创建；只在确实补齐时保存整数说明。
- 源文件保持原字节；普通完整输入、仅缺内存的旧路径保持原字节结果。CP 沿用已有片段转换。输入和 bundle 哈希绑定最终 inputs；verified_files 不调用补齐函数、不改旧 manifest、输入或时间戳。
- 本单未列在 open-tasks.txt，无自身标记可移除；保留其他工单记录。TS 卡只替换原句，行数不变。

| 验收项 | 可复现证据 |
|---|---|
| 缺核数/内存的四种组合、有效入口与档位、R1 内存 | `test_resources_monitor.py::test_resource_fill_selected_entry_bytes_and_hashes`（16 例）及 `test_memory_tiers_and_bundle`（16 例） |
| LF/CRLF、大小写和空白、完整字节、Link0 排列 | 上述 16 例；`test_gaussian_input.py::test_fill_cores_preserves_link0_order_and_all_other_bytes`（12 例，含混合换行） |
| 显式合法/非法/重复核数不覆盖；标题/route/坐标不误识别 | `test_fill_cores_never_repairs_explicit_directive`（8 例）、`test_fill_cores_only_scans_initial_contiguous_link0`（5 例） |
| 冲突、非法 Link0、空输入、超限内存、chk 路径、电子态、QST 不一致在分配前拒绝 | `test_fill_cores_invalid_prepare_never_allocates`（15 例）及节点拒绝测试（4 例），断言 attempts 连隐藏序号文件都不存在 |
| 单结构、QST2/QST3、合法父 chk | `test_fill_cores_single_and_qst_titles_are_not_link0`（6 例）与 `test_fill_cores_declared_parent_chk_preserves_source_and_binding`（2 例）；父记录使用现有合成 fixture |
| gaussian-cp 既有转换与最终哈希 | `test_counterpoise.py::test_cp_auto_cores_precede_existing_fragment_conversion`（4 例，PBS/Slurm） |
| 显式节点半/四分之一与约束拒绝 | `test_node_targeting.py::test_auto_cores_use_explicit_node_fraction_tier`（2 例）及 `test_auto_cores_do_not_bypass_node_or_walltime_checks`（4 例） |
| 说明字段、摘要、源/保存哈希、bundle | 多入口 16 例独立重算每文件 SHA-256 和 bundle 摘要；开发机独立合成验证另有 8 例 |
| 旧无说明 manifest / bundle 不改写；损坏拒绝 | `test_resources_monitor.py::test_existing_bytes_and_old_bundle` 禁止调用两种补齐函数，比较核验前后字节和 mtime，损坏后拒绝 |

开发机独立验证通过显式 `load_config(path)` 读取仓库外合成配置；8 例覆盖四种资源缺失组合 × LF/CRLF，调用真实本地 prepare、summary、read_manifest 和 verified_files。核对源文件不变、保存字节、可选说明、逐文件/整包哈希以及核验不改写。未创建 approval、未调用 submit、未发起 SSH、未运行 Gaussian、未读取真实研究数据；父 chk 与上传/执行路径的既有测试只使用合成附件和假传输，不能据此声称真实上传或执行通过。准确最终 HEAD、全量测试和扫描结果记录在本 PR。
