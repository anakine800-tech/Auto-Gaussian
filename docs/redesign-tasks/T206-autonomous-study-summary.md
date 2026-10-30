# T206：自主状态摘要安全写入 study.md

目标：将已有自主状态中的目录链接、待你决定、结束摘要发布到 study.md。
防止外部编辑或慢速整理之后，已经超时或被接管的会话覆盖人的正文及新 owner 的记录。

## 范围与基线

- 当前整合基线：main `807b1e27b15fa4dc1a81011b010e801608310900`，已合并 T186/T185。
- 原父基点：T186 `e4b1c876213c3aaedeb2c166dcd7e3d693f54ea0`；
  原 T206 head：`6e1523fe00299f03acf93043bd5873c5bf2bb824`。
- 分支：`codex/t206-autonomous-study-summary`；PR #385 以 `main` 为 base，
  只重放原父基点之后的 T206 自身增量，不重放旧 T186 父提交。
- 允许修改 `ag/src/ag/study.py`、`ag/src/ag/autonomy.py`、`ag/src/ag/cli.py`、
  相关既有测试或 `ag/tests/test_autonomy_study_summary.py`、`docs/DEVELOPING.md` 与本单。
- 不改提交、取消、远程命令、预算、科学判据或签字；不创建通用任意文件写入器或第二套状态。
- 独立工作树完成，不修改正式运行检出，不再拆开发对话。共享入口由本单先固定，后续接入串行进行。

## 接口与行为

`ag autonomy publish-study --study '<STUDY>' --run '<RUN>' --token '<TOKEN>'
--plan-sha256 '<SHA256>' --json` 调用
`study.publish_autonomy_summary(cfg, name, *, run_id, token, plan_sha256)`。

只读取已有 autonomy summary/pending 和计划来源，生成固定三类区块。
返回 `changed`、`study_sha256`、`source_seq`、`source_journal_sha256`、`plan_sha256`；
不接受任意正文、输出路径或跳过核验的参数。`cli.py` 沿用原注册入口，无须修改。

大文件读取、渲染、哈希及候选文件写入在全机锁外。最终发布复用
`observation_publication_guard(..., action='organize', expected_source=(seq, journal_sha256))`，
`expected_source` 是可选来源断言，旧调用保持兼容。重新核对 owner、计划、版本、时间及源事件身份；
同时检查目录身份、文件身份/类型/大小/纳秒时间、原文及候选文件，拒绝可检测到的并发改动。
只替换完整且内容校验通过的生成区块；保留其他研究正文、换行、签字及未标记的同名章节。
人工改动过的生成区块、重复或破损标记拒绝覆盖；源文本作为缩进代码展示，不能生成签字或额外章节。

暂停和到期计划的 observe-only 租约仍可在有效整理权内发布。
先 update 保存摘要，再 publish-study，最后 finish/end；不自动结束轮次，也不从 ended 状态获取写权限。
没有内容变化时返回 `changed=false`，不写文件、不累计段落，仍重新核验权限与来源。
缺少 study.md 时拒绝重建，避免掩盖人的删除操作。

state 更新与 study.md 发布是两个独立操作，不承诺跨文件原子事务。
发布失败保留源状态和候选临时文件；不回滚、不自动重试。
replace/fsync 阶段错误明确提示可能已经发布，须检查 study.md 后再决定是否调用；再次调用可确认无变化。
原子 rename 保证整份文件替换，元数据检查是乐观并发检查：不宣称能够强制互斥不遵循锁的外部编辑器。

## 验收与验证边界

- 新建/更新三类内容，正文与签字保留；重复调用不改变字节和 mtime。
- 人工编辑、同字节重写、新 owner 编辑、超时/接管、版本/计划失效、损坏来源、符号链接、硬链接、路径替换拒绝。
- 多发布者真实本地锁竞争、候选写入/替换失败、暂停/观察整理、结束前后权限边界。
- CLI 仅加载本地配置，拒绝网络和真实 Transport；首次交付的核心组合验证保留为历史证据。
- 本次 main 整合仅跑相关回归、敏感扫描；新 head 全量交 CI，不跑本地全量或 AST 分析。

## main 整合说明（2026-10-30）

只解决 `autonomy.py` 两处重叠：完整保留 main 新增的 `manual_publication_guard`，
在既有 observation guard 上保留本单 `expected_source`；命令列表保留 main 的
`resolve-attempt` 并追加 `publish-study`。不修改任何提交/取消行为，不复制 T207/T188。

`study.py` 与专用测试逐字保留原 T206 head；`cli.py` 与新 main 一致。
`docs/DEVELOPING.md` 自动合并后仅叠加原 T206 三处文档增量；本任务单更新基线和验证安排。
交付包记录旧 head、原父、新 base、新 head、range-diff、冲突两侧、解法及来源哈希。
原实现和测试功能不变；保持 Draft，待独立复核，不合并或部署。

纯本地开发，不授权真实配置、研究 study、计算、定时任务或部署。
冻结核心组合来源只读使用；在临时隔离副本验证，原验证包保持不变。
交付当前 head、精确改动路径、组合来源清单及可复现证据；本会话不合并。
