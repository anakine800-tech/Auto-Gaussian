# T186：绑定计划的自主提交与已结束失败补救

## 分支、目标与当前范围

- 分支 `codex/t186-plan-bound-submission`，一单一 PR；依赖 T184 的本地轮次/租约和 T185 的阶梯选择器。T188 放宽输入组合另验，不复制其实现。
- 目标：仅当前计划、有效规则、当前 owner、冻结输入、真实消费及资源/路由证据一致时允许自主准备和一次提交；保留普通手动流程。
- 2026-10-30 最终范围不依赖 T187。自主取消、取消停止证明、改投及取消/改投后继入口关闭，移除 Slurm 26 探针、原始实例与绑定提交接线；不新增远端命令。
- **需要取消时，由负责人在 Mac 上亲手确认。** 自主会话只把对应分支记为“需要你看”，简报第一行提醒人工取消，绝不执行取消命令。
- 已有作业被确切证据证实结束且失败后，仍可在原计划方法范围内新建 Attempt 补救，同对象同失败最多两次。保留失败来源及实际消费谱系；UNKNOWN、仍运行和取消来源不能冒充普通失败补救。
- 事故依据：旧规则缺少完整计划/方法/数量限制；并发和调度器延迟可能漏计占用；过期或失权会话可能继续发动作；取消接受、作业消失或旧实验停止记录不能证明可安全重投。

## 允许改动的路径

- `ag/src/ag/config.py`、`approval.py`、`submit.py`、`submission.py`、`attempt.py`、`cli.py`。
- `ag/src/ag/autonomy.py`、`_autonomy_store.py`、`autonomy_policy.py`、`autonomy_submission.py`。
- `ag/src/ag/route.py`：只接已审阅选择器，不另写路由算法。
- `ag/tests/test_approval.py`、`test_autonomy.py`、`test_route.py`、`test_autonomy_policy.py`、`test_autonomy_submission.py`。
- `ag/config.example.toml`、`ag/config.clusters.example.toml`、`ag/README.md`、`docs/DEVELOPING.md`、本工单。

既有追加授权继续有效：

- 负责人确认“允许补齐四处写入保护（推荐）”：`status.py`、`fetch.py`、`snapshot.py`、`facts.py` 的最终本地发布保护。网络、解析和大型文件 staging 在全机/study 锁外，发布时重验 owner。覆盖普通、补缺、不完整 fetch、auto_facts 和相关 journal。
- 负责人确认“允许补齐预算结算保护（推荐）”：`budget.py` 的 `settle(..., publication=None)`；仅增加发布钩子，保持算法。配置锁 → 全机锁 → study 锁；预算和状态各自复核，后一步失权不回滚此前合法结算。
- 本轮共享 `cli.py` 仅撤下 `--reroute-source` 及对应上下文传递；保留观察 owner 参数。T206/T207 的 study/facts/review/mode 新入口不在本轮删减范围。

## 最终实现

1. `approval.autonomous_policies` 与旧手动规则隔离。字段为 `schema/study_id/study_key/round_id/plan_sha256/routing_sha256/templates/clusters/max_cores_per_job/max_walltime/max_attempts/quote/set_at/expires_at/methods/allow_relaxed`；各 cluster 明列节点、总核数、排队核数和作业数上限。未知字段、矛盾限额及无效身份拒绝。自主拒绝不回退聊天批准或弹框。
2. 计划 `spec.submission_policy` 限制模板、集群、单作业资源、方法、路由哈希及放宽例外；Attempt 上限与到期复用计划原字段。`ag route --config-identity --json` 在首次计划之前只读取得 T185 同一算法的哈希，不要求 study/规则/租约，不输出账号、主机或路径，不产生文件或远端查询。
3. 普通 Gaussian 依据冻结输入核验方法、基组类型、色散、溶剂、积分网格和最终 Opt/Freq/SCF 收敛。T188 正式标记组合时才允许计划/规则均批准的放宽例外；保存跳过清单，方法口径未核验，仍不放宽最终收敛。非 Gaussian 只使用其受支持参数。
4. 全机不可变登记、reservation、claim、摘要、submission/status 和重放消费双向核对；缺失、截断及 UNKNOWN 不当零。共享实际账号和所有 study/轮次的占用计入；prepare 和本地意图不消费提交次数，规则改名或新唤醒不清零。
5. prepare 分配、远端建目录、父 chk 复制、上传和 dispatch 分别重验。每 Attempt 最多一次提交；授权绑定输入/bundle 字节并在上传后核对。达到 90% 实际消费即暂停；已消费而未 dispatch 的 abort 保留次数，晚到响应仅补确切绑定。
6. T185 的原始快照、placement、waiting 和选择输入持久化并重放，提交时再次核对真实账号额度。CREST/xTB 保留既有建议顺序及可信占用。普通 PBS/Slurm 提交不依赖 T187 版本、probe 或原始实例接口。
7. 普通 PBS 的确切 `ag-exit.json`、Slurm 的确切 `sacct` 终态及正常 status/fetch 接口保留。完整输出、正式不完整失败取回和科学 review 可作为其已实现范围内的补救证据。PBS 诊断性不完整取回不自行证明失败；Slurm CANCELLED 不当普通失败。
8. 失败补救通过 `prepare/refresh/verify_remedy_evidence` 绑定原实际消费、状态/输出哈希和 canonical failure；省略或改名 `--failure-class` 不能清零。已证明 dispatch 前 abort 的处理保留。取消 ledger/claim/旧取消文件不重放，只保守保留占用并交人处理；旧 probe/reroute 记录不获得新动作资格。
9. 手动 writer 与有效自主 owner 互斥；status/fetch/snapshot/facts/预算最终发布重验。耗时 IO、科学解析及大文件写入在共享锁外，短事务仅发布已核验结果。独立 facts 的既有手动保护保留，自主 refresh/reparse 不在本单开放。

## “需要你看”的既有记录入口

卡片在识别到卡住、需要取消或改投的分支时，由唯一 owner 使用现有
`ag autonomy update --study '<STUDY>' --run '<RUN>' --token '<TOKEN>' --input '<UPDATE_JSON>'`。
JSON 只含 `summary`、`pending`、`objects`；读取当前值并保留其他分支条目，给当前对象
记录“需要你看”、对应 Attempt 和原因，把 summary 第一行设为 Mac 人工取消提醒。
这是已有本地记录接口，不是取消命令，不把旧 `count/check` 意图记录当执行资格。
`ag cancel` 仍是负责人亲手点击 Mac 确认的人工路径，自主卡片不调用它。

## 验证与交付

- 本地只跑此次受影响模块/流程；全量在 CI 跑，真实验证前对最终源码组合另跑一次。不得逐增量重跑全量，不做 AST 比对。
- 覆盖普通 PBS/Slurm 提交不调用 T187；拒绝旧改投上下文、已准备改投 manifest 和取消来源；保留已结束失败的新 Attempt、两次补救上限、owner/暂停/到期、哈希、真实额度、UNKNOWN 及只读恢复。
- 提交前敏感扫描与 diff 检查。测试、源码清单、哈希和日志私有归档；旧含 T187 的组合结果仅是历史记录，不是本版证据。
- 送监督方（Claude）一次定稿：冻结提交号、仅敏感生产路径文件及 diff、逐项检查对应事故依据、非研究真实验证方案草稿。测试源码不放入送审源码包；之后只复核回应审阅的增量。
- PR 首行 `Task: T186`，标题/说明以本版最终范围为准。监督方意见转贴到 PR，带 `<!-- ag-review head=... -->`，逐条处理并回复。此前协调审阅不替代本次监督审阅；不得自行合并。

## 合并前非研究真实验证草稿（未执行、未授权）

对象仅合成水分子：0 电荷、单重态、无手性；验证用兜底方法
`B3LYP/6-31G(d) Opt=Tight Freq Int=UltraFine SCF=(XQC,Conver=8)`。
候选输入 158 字节 SHA-256：
`734a7d6f671b18f236776856323c8ea671bab32aafd23fde262ae96a9e45faa5`。
候选资源为 8 核、程序内存 10 GB、档位内存 12 GB、walltime 00:30:00；仅在最终
配置/阶梯确实匹配时使用，否则停止完善草稿，不能现场修改获批字节。

私有方案须绑定最终源码、非研究 study、入口/节点、计划/规则、Attempt/input/bundle
哈希，并列固定命令与次数：初始化/计划确认/一次 prepare/一次 submit/一次确切绑定
核验/一次取回；到期、方法、网格、节点、计划、上限各一次无提交拒绝检查。
调度器观察次数和间隔在正式批准包固定，不执行无界轮询；仍运行或结果不确定即停止
本次验证并保留作业，不能自动取消或补投。取消验收只检查提醒与本地“需要你看”记录。

任何 UNKNOWN、哈希不一致、意外 SSH 错误、异常结束或不确定结果立即停止并报告。
不删除远端文件、不重试提交。当前没有真实提交、取消、查询、配置或部署授权。

## 本版离线证据与当前阻塞

- 普通 submit/status/fetch/UNKNOWN/预算相关定向：262 passed、1 skipped、141 deselected。
- 四模块初跑 604 passed、60 skipped；12 个新增错误文本断言修正后相关子集 25 passed；旧 reservation 拒绝补测 2 passed。跳过不计为通过。
- 删除无事故依据的纯列表/方法重复拒绝及 SCF 上限后，受影响策略用例 49 passed；SCF 最低值和共享账号上限仍保留。
- 固定 T185 `47ac8986`、T188 `9bbebcc5` 的无 T187 组合共 13 个实际 driver 用例：8 个初跑通过，5 个按真实自动暂停和下一唤醒语义修正测试后通过。覆盖普通 PBS/Slurm、UNKNOWN 恢复、旧改投拒绝，以及初始提交后两次已结束失败补救、第三次拒绝。每次定向执行前后源码哈希一致。
- 上述均为离线合成数据；没有真实提交、取消、查询、配置或部署操作。通用及私有词表敏感扫描 1910 文件无错误。

提交/环境：本版 CI 全量、Claude 定稿审阅及合并前真实验证尚待完成；自主运行未启用。
实际规则和现场验证包尚未获批准。真实验证前须在最终源码组合上另跑一次全量。
T206/T207 保持独立，待本单进入 main 后重定向与核验，不提前合入父功能分支。
