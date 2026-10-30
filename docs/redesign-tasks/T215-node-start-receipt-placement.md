# T215：具名 PBS 短作业的启动回执放置证据

## 问题与目标

具名 PBS 短作业可能在提交读回时排队，下一次 status 时已结束且调度器不再提供
exec_host。当前放置核验因此拒绝 finished/fetch。负责人批准：仅在已提交的冻结
bundle 可证明含有审阅过的节点启动 guard，且输入、manifest、submission、status、
确切作业号及合法 ag-start.json 全部匹配时，以 guard 后生成的启动回执作为缺少
exec_host 时的替代放置证据。明确不匹配的 exec_host 始终拒绝。

本单独立分支 `codex/t215-node-start-receipt-placement`，基线为已存在的本地
`b929163ca3a05c7df2a549dd8f2d9691fb6e68ee`（含 T185/T186/T188/T206/T207/T212）。
不携带其他工作树改动；一个任务单、一个分支、一个 Draft PR。

## 允许修改

- `ag/src/ag/node_targeting.py`、`ag/src/ag/status.py`。
- 对应 node_targeting/status/自主观察的离线测试。
- `docs/DEVELOPING.md` 与本任务单。

复用现有脚本/manifest/提交验证 helper。若需要修改 attempt.py 或其他生产文件，
先向协调方报告并等待负责人决定，不静默扩展范围。模板只读核对，不修改。

## 实现与验收边界

1. 实际检查 renderer、模板及其控制流，证明已知 guard 先于开始回执；不以片段
   字符串存在代替证明，不用新版模板为旧提交补证。
2. 冻结脚本/输入的字节与 manifest/bundle/提交身份必须匹配；伪造、篡改、无 guard、
   非已知 guard、缺失/错误/损坏回执均拒绝回退。缺少提交绑定不凭可变 status 放行。
3. 新证据来源须可区分于真实 exec_host，不伪造 exec_host；已有 verified 证据兼容。
4. 保留手动及自主观察的发布围栏；不改授权、核数预算、节点选择、UNKNOWN、取消。
5. 不连接真实集群，不访问真实 study/config，不提交、取消或重跑已有作业。

这些检查针对实际的短作业证据缺口，并防止把篡改脚本或其他作业回执误认作节点证明。

## 离线验证

使用全局 HOME 隔离、合成输入和假 Transport。覆盖手动/自主，调度器残留/消失，
完成短作业，缺/错/损坏开始回执，脚本篡改/无 guard/非已知 guard，明确 exec_host
不匹配不被回执覆盖，旧 verified 证据保持，以及失去 owner 后不得发布。
开发中仅跑受影响测试，全量 ag 测试交 CI，不重复本地全量，不做 AST 比对。
提交前运行公开敏感信息扫描；PR 首行 `Task: T215`。

## 真实环境验证

本单遵从本次负责人明确安排：开发线程不执行真实验证；由协调方在合并后，
对现有整节点 Attempt 只做正式 status/fetch，不新增提交。半节点新 Attempt 须另审批。
这是一项本次明确指定的验证安排，离线/CI 结果不冒充现场证据，也不自动启用自主运行。
短方案：核对执行提交及既有绑定；一次 status 检查来源、作业与放置；确认 finished 后
一次普通 fetch 核验输出；保留原有数据。任何身份/哈希不符、SSH 报错或意外即停止，
不自动重试、不改旧记录、不重新提交。

## 交付与当前阻塞

交付冻结 SHA、最小生产 patch、相关完整源码、离线结果、CI 与未执行短验证方案；
送审包不含测试源码，私有材料仅本地保存。允许推分支并创建/attach Draft PR，
交监督方复核。监督方批准前保持 Draft；本线程不合并，由协调方负责后续合并安排。

离线结果（2026-10-30，Python 3.11.15 / pytest 9.1.1）：

- 新增用例：首轮 79 passed，补充的重复 R 残留观察与 status 同字节改写两项 2 passed；共 81 项。
- 现有 node_targeting/completion：252 passed、1 skipped（Linux stat/ps 方言交 CI）。
- 现有 autonomy 的 status/observation 相关项：29 passed、169 deselected。
- 首两组出现 pytest 清理旧临时目录的 EINVAL 告警，退出码均为 0；定向补测与自主观察无告警。
- 完整冻结脚本在本地假程序上执行：正确节点可写回执，错节点/核数、缺失/链接节点文件
  均在 scratch、回执和程序启动前拒绝。独立只读代码复核未发现需修改的问题。

当前阻塞：监督方敏感复核与 CI 待完成；真实验证按上述安排未执行。
