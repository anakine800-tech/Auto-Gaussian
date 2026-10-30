# T212：CREST/xTB 建议的低优先过期快照不再整体阻塞

## 已证实问题

`route.select_legacy` 注释写只拒绝更靠前的未知入口，实际 `relevant` 包含建议顺序
全部入口；低优先入口快照过期会阻断已经合格的更靠前推荐。负责人要求试点前修复。

## 范围

从最新 main 建立独立工作树、`codex/t212-legacy-route-priority` 分支和 Draft PR。
起步基线为 `8a6f296d`（T188 已合并）；后续组合由协调串行整合。

仅允许修改：

- `ag/src/ag/route.py` 的 `select_legacy` 及必要局部 helper。
- `ag/tests/test_route*.py` 或既有该函数相关测试。
- `docs/DEVELOPING.md` 与本任务单。

禁止改 Gaussian `select_ladder`、提交/授权/取消、缓存/快照生成、生产配置或科学判据。
新鲜度与 usage 只预检查既有建议顺序中排在推荐入口之前（含推荐入口）的相关入口，
继续复用原 `suggest` 结果，不引入第二套排序。不能因缩短预检查前缀而丢弃同账号
其他入口的预留、降低限额或缩减全机统计范围。

## 验收

- CREST/xTB 首选新鲜合格、后续过期/失败/缺失时返回原建议；中间入口与 study 顺序覆盖同样成立。
- 推荐入口或更靠前且实际相关入口未知仍拒绝；原节点/账号证据错误仍拒绝。
- disabled/不支持档位的更靠前入口不额外阻断；无推荐与原成功路径行为保持。
- 较低入口的共享账号预留仍计入；共享账号取最小限额，同账号自主活跃 4 个、全机兜底排队 2 个、parent_cluster 和同对象占用不放宽。
- 原建议的候选顺序、模板、档位与证据重放保持；不因预留不足另造回退选择。

## 实现与离线验证

生产改动只在 `select_legacy`：用 `suggest` 返回的原顺序截取截至推荐入口的前缀，
保留原模板/档位过滤。`_ladder_usage` 仍接收完整 snapshots 与 records；后续节点、
共享账号、同对象和全机排队检查未修改。

静态检查先行：Python 语法编译与 `git diff --check` 通过，不做 AST 比对。
测试使用合成 cfg/snapshots/placements；受控 Python launcher 在导入 pytest 前将
`Path.home` 指向临时目录，关闭外部 pytest 插件自动加载。`test_route.py` 另加每项测试
独立临时 home fixture；相关提交重放模块已有同类 fixture。不读取真实 home 登记。

- 红灯：在未修改生产实现时，首选合格、低优先入口过期/失败/缺失的两模板 6 项均失败，原因均为 `snapshot_missing_failed_or_stale`。
- 绿灯：`ag/tests/test_route.py` 共 323 项通过，包括上述 6 项、共享账号冲突、低优先别名未观测预留、额度边界及绑定回归。
- 关联重放：`ag/tests/test_autonomy_submission.py::test_legacy_selection_replays_only_reviewed_legacy_function` 1 项通过。
- 本地仅定向回归；全量交 CI，当前 head 结果记录在 PR。最终组合一次本地全量由协调统一运行。
- 提交前扫描暂存内容并检查提交身份；结果记录在 PR。

## 真实环境验证与交付

本单未授权也未执行集群、SSH、真实 study/运行配置访问或部署；全部结果仅为合成
离线证据，不代表真实调度验收或自主启用。最终组合验证、敏感路径监督复核及非研究
试点仍须由协调按授权另行完成。

PR 第一行 `Task: T212`，保持 Draft，不自行合并。给监督方交冻结完整 SHA、最小
生产 patch、相关测试/当前 head CI 结果与验证缺口；送审包不含测试源码。
当前阻塞类别为提交路径审阅：等待监督方对冻结 SHA 的敏感增量复核；没有运行或部署授权。
