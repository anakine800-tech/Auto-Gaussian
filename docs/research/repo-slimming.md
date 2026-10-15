# T41：仓库瘦身评估

评估日期：2026-10-15（北京时间）。基线：`a820049e2f1581370f09639fc16d14e611a4dea9`。
本文只列候选和取舍，**没有删除、移动或修改代码、模板、卡片、测试**。范围是公开仓库；不读取研究目录。下文均为仓库相对路径。

## 1. 结论与盘点方法

- 优先精简过时的阶段计划、交接待办和较长的跨卡片重复段落，收益主要是减少误读及维护漂移。
- 已完成任务单适合原位历史归档；机械移动会破坏开发手册和 PR 中的链接。不能用 `open-tasks.txt` 为空证明所有工程或 study 已完成。
- 未发现足以立即删除的废弃测试或 fixture。平台跳过、私有数据 opt-in 和缺少可选依赖分别有用途；相似测试要看它防什么事故。
- 两个零文本引用的模板生成脚本仍有再生资产用途；建议保留，先补用途说明。绝不因 grep 零结果就删除。
- `archive/` **整体保留不动**，不列删除候选，不读取旧规则来决定新工作。依据：[AGENTS](../../AGENTS.md)、[DEVELOPING](../DEVELOPING.md)、[LESSONS](../LESSONS.md)。

本次用 `git ls-files` 枚举受版本控制文件，排除冻结历史后，基线共有 307 个文件；`docs/` 约 190 KB（十进制），任务目录有 17 张 T 编号任务单及模板/待办索引两个文件。这些是基线快照，**不是可节省空间的估计**；不计本 PR 新文件、Git 历史、环境依赖或未跟踪文件。

核查方法：相对路径/文件名文本搜索，加 Python import 检查；读取所有 skip/xfail 标记；对测试函数 AST 去掉函数名及位置后比对；卡片按空行分段做逐字相等比较；逐项回读候选及调用方。AST 只发现少量短 helper 重复，没有发现顶层 `test_*` 函数的完全重复体；这不证明不存在语义重复。文本搜索不能证明运行时无人使用，本文没有运行资产生成器、清理脚本或研究命令。

## 2. 文档与任务单

| 路径/位置 | 现状与可精简理由 | 风险 | 建议 |
| --- | --- | --- | --- |
| `docs/REDESIGN-PLAN.md` §7 日程 | 仍含旧阶段、旧签字状态；顶端已有历史声明，`docs/README.md` 已将其列入历史 | 单独删历史记录会丢当时决策背景；照着旧计划推进会误认现状 | **删除候选：仅过时阶段计划正文**，由负责人决定是否替换为一段带基线提交的历史链接；不删全文，不再维护第二份实时进度 |
| `docs/REDESIGN-PLAN.md` §3、§4.3、§4.4、§5.1、§8 | 初版环境、状态机、命令、部署和验收定义是设计快照，现行实现已扩展；与 README/DEVELOPING 存在多份说明 | 历史规格与现行行为混用；直接“修成最新”反而丢设计史 | **保留**历史快照，现行入口只链接 README/DEVELOPING；下一次瘦身只考虑删掉重复的现行操作指引，不迁移旧命令为新规则 |
| `docs/handoff-v4.md`“卡片修订”第一批与第二批 | 固定于发布时，已有 T36a、T37、T39 合并证据；不能继续逐项当作未开发清单 | 工程功能合并不证明全部卡片建议已落实，更不证明研究验收 | **合并**已完成工程事项到带 PR 的历史小结，仍需核对的项留下；依据 `git log` 的 #253/#254/#255 与相应任务单，不能整批标完 |
| `docs/REDESIGN-PLAN.md` §9 与 `docs/handoff-v4.md`“运维与注意事项” | 前者写定时巡检，后者写手动请求监督审阅 | 改造期调度记录会被当成当前服务承诺 | **合并**现行操作说明到 DEVELOPING；历史页仅保留当时安排和历史标记。本次没有检查或更改任何自动化状态 |
| `docs/redesign-tasks/T0-repo-reset.md`、`T1-ag-core.md`、`T2-facts-thermo.md`、`T3-skills.md`、`T4-structures.md`、`T5-geometry-tools.md` | 最初六张实现任务的历史范围；合并记录可从 CHANGELOG/设计记录追溯 | 删除会失去原始验收条件，移动会断引用；完成日期不能靠编号推断 | **保留、原位归档**：未来在现有索引列任务/合并 PR/状态，任务单保留原名；无需为了 6 个文件建归档系统 |
| `docs/redesign-tasks/T16-slurm.md`、`T19-clusters-json.md` | 历史任务仍是接入细节来源；DEVELOPING 直接链接 T16 | 移动导致开发手册失链；旧任务中的计划也不代表现行缺陷 | **保留**原路径，若以后按发布版本分目录需同 PR 更新所有相对链接并保留旧入口 |
| `docs/redesign-tasks/T29-thermo-audit.md` 至 `T39-profile-decomposition.md` 中现存任务单 | 保存近期更改的范围和测试要求；编号有缺口，不存在的文件不应补造 | 未读 PR 的当前状态就批量删除/移走会误伤在途任务 | **保留**，逐项核对合并提交后再在索引归档；不根据编号连续性或空待办推断完成 |
| `docs/redesign-tasks/open-tasks.txt`、`TEMPLATE.md` | 前者被卡片一致性测试使用，后者被 DEVELOPING 与任务编写引用 | 删除空列表会破坏检查入口；删除模板又造成任务格式漂移 | **保留**；“当前无任务号”不是废文件依据 |
| `docs/research/ts-tooling.md` | 旧工具实测和适用性限制仍有依据价值；部分建议对应后续已实现能力 | 不加日期限定容易误读为最新状态；删掉会丢负面结果和源码来源 | **保留**带日期的调研；需要时在现有索引加后续实现链接，不重写当时实测结论 |

原位归档建议的具体顺序：先核对每张任务单对应合并 PR/提交，再在 `docs/README.md` 的现有历史区整理链接；任务原文件不动。若负责人确实选择物理移动，应另开允许相关路径的清理任务，移动前搜 Markdown 链接、测试字符串及外部 PR 引用，保留旧入口，不能扩大本次 T41 改动。

## 3. 跳过与相似测试

| 路径/测试 | 现状与是否冗余 | 风险 | 建议 |
| --- | --- | --- | --- |
| `ag/tests/test_completion.py:310` `test_remote_receipt_limit_and_symlink_output_rules` | 非 Linux 跳过；验证 GNU stat/ps 方言、回执大小与符号链接；CI 是 Ubuntu | macOS 跳过不等于长期失效；删除会丢远程路径防护回归 | **保留**；以 Linux CI 补覆盖，记录实际 skip 原因 |
| `ag/tests/test_facts.py:133` `test_private_ts_and_optional_irc` | 未设置 `AG_LOCAL_FIXTURES` 就跳过；需仓库外私有日志，公开 CI 按设计不提供 | 删除会丢可选真实日志回归；为消除 skip 而上传私有数据违反仓库规则 | **保留** opt-in，不能用于宣称公开 CI 已验证真实 TS/IRC；长期实际调用频率未知 |
| `skills-next/auto-g16-structures/tests/test_structures.py:11,22` | 缺 RDKit 时模块跳过；缺 CDX 支持时仅相关用例跳过 | optional dependency guard 与废弃测试不同；CDX 支持依构建变化 | **保留**；CI 明确安装 RDKit，但是否具备 CDX 仍看测试结果，不由安装命令推断 |
| `ag/tests/test_clusters.py:15`、`test_irc.py:287`、`test_monitor.py:84` 的 tree/snapshot helper | 函数体逐字/AST 等价，都是局部文件字节快照；用于不同的只读检查 | 为省几行引入共享测试工具反而增加耦合；删掉调用将损失“未改文件”断言 | **保留**当前短 helper；仅在未来相关测试大改且能减少净代码时考虑合并，不建通用测试框架 |
| `ag/tests/test_core.py` fetch 用例与 `ag/tests/test_fetch.py` | 名称相似但前者覆盖生命周期、确认后字节/失败不发布，后者覆盖已 fetched 补取与竞态 | 只按函数名归并会漏掉状态与已存在文件的不同边界 | **保留**独立断言；若以后重构，先列输入状态/故障/预期行为再判断冗余 |
| `ag/tests/test_smoke.py` 与 `test_facts.py::test_cli_registration_does_not_import_chemistry` | 前者测安装版命令与配置/依赖分发，后者在子进程阻止 eager chemistry import | 两者运行入口和事故不同，去掉任一会减少覆盖 | **保留**，没有相同断言的整例删除依据 |

本次标记检索没有发现 `xfail` 或无理由永久 `skip`。这是基线静态结果；“长期从未执行”需要 CI 历史或本地执行记录，本次未作该推断。本次全量离线测试为 **1648 passed, 2 skipped**：仅 Linux 方言用例与私有日志用例跳过；RDKit/CDX 用例本次未跳过。命令为 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，使用独立 worktree 的 `.venv`，未设置私有 fixture 环境变量。不能仅凭静态搜到 skip 就估算运行节省。

## 4. 脚本与 fixture

| 路径 | 现状与删除/合并理由评估 | 风险 | 建议 |
| --- | --- | --- | --- |
| `ag/tools/scan_sensitive.py` | CI、开发手册和专用测试均引用 | 删除直接移除提交前检查 | **保留** |
| `ag/tools/sanitize_log.py` | `test_sanitize.py` 调用，fixture 说明依赖脱敏流程 | 脱敏仍需人工复核，不能因日志已脱敏就删工具 | **保留** |
| `skills-next/auto-g16-structures/scripts/cdx_stereo.py` | 完整文件名仅少量文档引用，但 `prepare_preview.py`、`inspect_chemdraw.py`、`make_gaussian_input.py` 与测试通过模块名 import | 只搜 `.py` 文件名会误判孤儿，删除破坏结构读入 | **保留** |
| `skills-next/auto-g16-chemdraw-structures/scripts/generate_common_templates.py` | 其他受版本控制文本中未找到完整文件名引用；从 common-depictions 目录生成 MOL 与可选预览 | 是离线资产再生工具，不是必须有 Python 调用方的库；会改写模板，不能为盘点直接执行 | **保留**，未来在所属 Skill 说明维护入口，实际人工使用频率未知 |
| `skills-next/auto-g16-chemdraw-structures/scripts/generate_ligand_scaffold_templates.py` | 同样零完整文件名引用；另有保留人工坐标、CIP 与可选 PubChem 刷新逻辑 | 与 common 生成器有相同 transform，但不等价；机械合并可能丢立体化学/人工坐标行为 | **保留**；不为短 transform 抽出公共层。若后续统一维护，先证明两类资产字节/身份保持 |
| `ag/tests/fixtures/water_opt_freq.log`、`butane_anti_freq.log`、`butane_gauche_freq.log` | 合计约 279 KB，facts、thermo、profile、sanitize 等数值回归读取 | 压成短片段可能丢 cclib、GoodVibes、几何/频率联动覆盖；收益很小 | **保留**已脱敏小分子日志 |
| `ag/tests/fixtures/error_l502.log`、`error_l9999.log`、`incomplete.log` | 三个极小合成片段，`test_facts.py` 参数化读取 | 不同错误/截断语义，合并会降低可读性；几乎无体积收益 | **保留** |
| `ag/tests/fixtures/fluoride_freq_synthetic.log` | `test_facts.py` 与 `test_profile.py` 使用的单原子合成边界 | 删除会漏掉单原子零模式/热化学边界 | **保留** |
| `ag/tests/data/butane.xyz`、`profile_legacy_output.json` | 前者由几何/聚类/采样等测试共享；后者被 T39 测试作为旧输出兼容基准 | 文件名带 legacy 不等于冻结旧架构；删掉会丢 T39 兼容证据 | **保留** |
| `skills-next/auto-g16-structures/tests/fixtures/butane.cdxml`、`chiral_explicit_h.cdxml` | `test_structures.py` 的参数化 fixture，覆盖结构与显式氢立体化学 | 小文件却覆盖关键差异，不能用一个替代两个 | **保留** |

没有发现可直接删除的孤立 fixture；其余 Skill 脚本均找到文档或代码入口。完整文件名零引用仅是候选线索，本次没有证明任何脚本已无人使用。脚本/fixture 改动须由后续任务授权，T41 只记录此结论。

## 5. 卡片逐字重复段落

以下行号均属于上述基线；这里只列位置和重复内容的主题，不复制整段来增加第三份规则。

| 位置 | 重复主题与现状 | 风险 | 建议 |
| --- | --- | --- | --- |
| `skills-next/auto-g16-recipes/cards/opt-freq.md:11`、`reaction-plan.md:13`、`sp.md:24` | 同一段双路线采样、覆盖报告与扩样建议，逐字相同；各处都已链接 conformer-workflow | 三处继续扩写会漂移；删到只剩裸链接可能漏掉本卡前置条件 | **合并**长说明到已存在的 `auto-g16-structures/references/conformer-workflow.md`，各卡保留一句适用条件和链接；审阅判据仍留各卡第 6 节，不新建公共规则层 |
| `skills-next/auto-g16-recipes/cards/irc.md:15`、`sp.md:42`、`ts.md:115` | 两行方法表链接与输入占位符替换提醒完全相同 | 这是降低方法骨架漂移的短提示，抽取会增加跳转，省不了有效内容 | **保留**；方法数值继续只在 acceptance-methods 定义 |
| `skills-next/auto-g16-recipes/cards/irc.md:35,58` | 两个不同输入骨架中的 charge/multiplicity 和 TS 坐标占位行相同 | 算法会报重复，但删掉后示例不再完整 | **保留**，代码块相同片段不是独立可删段落 |

卡片去重必须保留八小节、第 6 节判据以及旧 Attempt 已保存的卡片快照语义，不能以“统一措辞”为由回写旧快照。依据：[DEVELOPING“卡片”](../DEVELOPING.md)、[`cards.py`](../../ag/src/ag/cards.py)、[`review.py`](../../ag/src/ag/review.py)。

## 6. 建议的后续清理顺序

1. 文档小改：负责人选择是否删 REDESIGN-PLAN §7 过时正文，归并交接页已落实项，原位整理历史任务链接；保留设计决策和原验收条件。
2. 卡片小改：仅合并上表第一行的长重复段落到现有参考文件，复查各卡前置条件与判据；不机械去重代码块或安全摘要。
3. 暂不删测试/fixture/生成器。需要减少测试耗时时先记录实际耗时和重复覆盖；平台 skip 与私有日志 opt-in 不作为删除理由。

当前未发现阻塞 T41 文档交付的事项。后续清理需负责人选择候选并给出相应任务范围；本文不授予删除权限，也不创建新的审批制度。预计收益以减少维护漂移为主，未声称已节省磁盘或测试时间。
