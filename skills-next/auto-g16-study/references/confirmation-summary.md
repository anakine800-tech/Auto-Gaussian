# 提交确认摘要

从 `ag prepare` 的输出和已审阅的 study 信息填表，不手算替代其 bundle 值。只展示本次要提交的 Attempt；表内不留未知值。若准备后改动输入，重新 prepare 一个新 Attempt 并重新展示摘要。实时总核数由 `ag` 在提交时复核。

Study：<study_id>；卡片：<manifest.card.name>；Skills 提交：<git_commit 前 7 位>；工作区：<clean / dirty>；用途：<验收 / 研究>。

| Attempt | 结构（SMILES 或结构名） | 电荷 / 多重度 | 立体化学警告 | 方法与依据（文献先例 / 本课题既有方案 / 兜底方法） | 完整 route / 程序参数 | 模板 | 档位 | 核数 | walltime | 远程目录（相对 ag 根） | bundle 哈希前 12 位 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| <id> | <结构> | <Q / M> | <明确列出；无则写无> | <填写> | <完整内容，不用省略号> | <gaussian / crest / xtb> | <simple / general / complex> | <填写> | <HH:MM:SS> | <study_id/attempt_id> | <prepare 输出> |

“方法与依据”列按所属类别填写，与显式传入的 `--method-basis` 及 manifest 的 `science.method_basis` 一致：文献先例写 DOI 加主文页码或 SI 位置；本课题既有方案写来源计算或 study，并声明“不是文献先例，精度未经验证”；兜底方法引用方法表并明确声明。

每个 Gaussian 输入的 Link0：<逐个列出 `%nprocshared`、`%mem`、不带路径的 `%chk`>。
CREST / xTB 没有 Gaussian route，明确写“不适用”并列完整程序参数；本地 RDKit 和 thermo 不提交，不用此摘要。

当前占用 <N> 核（运行 <R>、排队 <Q>；按集群上本人全部作业统计，含挂起、其他电脑和非 ag 提交的作业）；本批新增 <B> 核；**提交后合计 <T> / 上限 <resources.max_committed_cores> 核**。单作业不超过 <resources.max_cores> 核。
ag 不限制运行中的核数：集群空闲时，排队作业可能同时运行，最多 <T> 核。以上数字由 ag 获取，Slurm 包含本地台账中尚未被调度器显示的预留。
若当前工具不能提供可靠的总核数，报告缺口，不能以估计的 0 代填；不要绕过 ag 查询。

同一卡片、同一方法才合并为一张批量摘要；每个 Attempt 一行。若总核数超过上限，拆成可容纳的批次，待先前作业完成后再展示并确认下一批。

3D 预览：http://localhost:<端口>/#/<study>/<attempt>（查看器启动方式见前端 README）

回复‘提交’后我会运行 `ag submit`，届时 Mac 上会弹出确认框，需要你亲手点击。
