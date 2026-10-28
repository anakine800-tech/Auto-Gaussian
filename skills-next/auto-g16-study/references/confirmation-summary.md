# 提交确认摘要

从 `ag prepare` 的输出和已审阅的 study 信息填表，不手算替代其 bundle 值。只展示本次要提交的 Attempt；表内不留未知值。若准备后改动输入，重新 prepare 一个新 Attempt 并重新展示摘要。实时总核数由 `ag` 在提交时复核。

Study：<study_id>；卡片：<manifest.card.name>；Skills 提交：<git_commit 前 7 位>；工作区：<clean / dirty>；用途：<验收 / 研究>。

实际入口：<cluster>；partition：<本机配置核对值；PBS 写不适用>。仅在本次使用 SCNet 时：CREST 显式 `--cluster scnet-test`（`赠送分区`），Gaussian 只能 `--cluster scnet`（`正式分区`）；default 与 SCNet 的选择沿用 study 安排。`赠送分区` 不可用、无权限或额度满时停下报告，不自动改投 `scnet`。资金来源：<负责人核对的赠送 / 正式专项说明；不明写未知>，不代表实时余额。

| Attempt | 结构（SMILES 或结构名） | 电荷 / 多重度 | 立体化学警告 | 方法与依据（文献先例 / 本课题既有方案 / 兜底方法） | 完整 route / 程序参数 | 模板 | 档位 | 核数 | 调度内存 GB | walltime | 远程目录（相对 ag 根） | bundle 哈希前 12 位 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| <id> | <结构> | <Q / M> | <明确列出；无则写无> | <填写> | <完整内容，不用省略号> | <manifest.template> | <manifest.tier> | <manifest.cores> | <manifest.mem_gb> | <HH:MM:SS> | <study_id/attempt_id> | <prepare 输出> |

档位按所选入口实际配置填写，可为 `mini / simple / general / complex / max / ultra` 中已配置的档位，不限三档；新 prepare 省略 `--tier` 时须有该入口的 `resources.default_tier`。保存后以 manifest 的实际档位、核数、调度内存及 walltime 为准，不按当前默认值重算旧摘要。配置变更后的旧资源是否仍可提交须由 ag 核验，不承诺兼容、不重写旧 manifest 或 bundle。

“方法与依据”列按所属类别填写，与显式传入的 `--method-basis` 及 manifest 的 `science.method_basis` 一致：文献先例写 DOI 加主文页码或 SI 位置；本课题既有方案写来源计算或 study，并声明“不是文献先例，精度未经验证”；兜底方法引用方法表并明确声明。

每个 Gaussian 输入的 Link0：<逐个列出 `%nprocshared`、`%mem`、不带路径的 `%chk`>。缺失的核数/内存由新 prepare 按实际档位补齐；显式值不自动覆盖。`%mem` 不超过调度申请内存的 85%，保留程序开销余量；此余量不减少调度申请量，也不用于判断节点能否容纳作业。
CREST / xTB 没有 Gaussian route，明确写“不适用”并列完整程序参数；本地 RDKit 和 thermo 不提交，不用此摘要。

当前占用 <N> 核（运行 <R>、排队 <Q>；按集群上本人全部作业统计，含挂起、其他电脑和非 ag 提交的作业）；本批新增 <B> 核；**提交后合计 <T> / 上限 <resources.max_committed_cores> 核**。单作业不超过 <resources.max_cores> 核。
ag 不限制运行中的核数：集群空闲时，排队作业可能同时运行，最多 <T> 核。以上数字由 ag 获取，Slurm 包含本地台账中尚未被调度器显示的预留。
若当前工具不能提供可靠的总核数，报告缺口，不能以估计的 0 代填；不要绕过 ag 查询。

同一卡片、同一方法才合并为一张批量摘要；每个 Attempt 一行。若总核数超过上限，拆成可容纳的批次，待先前作业完成后再展示并确认下一批。

3D 预览：http://localhost:<端口>/#/<study>/<attempt>（查看器启动方式见前端 README）

负责人在本 study 当前会话明确批准后，先执行 `ag approve --study <study_id> --attempt <id> --quote "<负责人逐字原话>"`，批次重复 `--attempt`，再执行 `ag submit <id> ... --approval <批准ID>`。

不得自行生成批准记录、概括原话或扩大 Attempt 范围；只批准点名或原话明确覆盖的 Attempt，含糊时先问清楚。跨会话或跨 study 转述无效。有效期默认 24 小时且不得超过 24 小时；整条批准只消费一次，提交部分成员也会消耗整条。记录、输入、集群、核数或 study 不匹配即停止，不回退弹框。

批次中途失败或停止，已消费的批准不恢复，剩余成员不能继续沿用。先停止并报告；只有仍为 prepared 且没有 `.submit-claim` 的成员，才可在重新展示摘要、取得新批准后提交，或改由负责人点击 Mac 对话框提交。已有 claim 的成员不能重提，不自动继续批次。摘要随每个 Attempt 的 claim 独占存档，未 claim 成员不预写摘要。

负责人明确设定且本 study 在名单内的长期规则，可用 `ag submit <id> ... --policy <规则名>`，逐项核对模板、集群、核数和 walltime；不得自行写入或扩展规则。未指定批准/规则时仍用 Mac 人工确认。任何方式都展示并存档摘要，保留两次核数检查；取消始终用 `ag cancel` 并由负责人亲手点击。
