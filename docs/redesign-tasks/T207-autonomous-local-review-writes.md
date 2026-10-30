# T207：本地科学审阅工具的会话写入保护

## 目标与事故

已批准的 V4.8 本地工具范围：独立 facts、review init/manifest、mode-review。
防止分析期间租约失效或被接管后，旧会话仍发布正式审阅文件；同时防止分析依据
被修改或替换后发布混合证据。复用 fetch 自动 facts 与 scientific-review 的现有 guard。

## 允许范围

- `ag/src/ag/facts.py`、`review.py`、`_review_manifest.py`、`mode_review.py`。
- `ag/src/ag/cli.py`、`autonomy.py`，仅复用或最小整合现有 guard。
- 相应测试、`docs/DEVELOPING.md` 与本单。

基线为 T186 `e4b1c876213c3aaedeb2c166dcd7e3d693f54ea0`。
分支 `codex/t207-autonomous-local-review-writes`，PR 暂以
`codex/t186-plan-bound-submission` 为 base。共享文件先等待 T206 冻结接口再串行接入。

## 实现边界

现有本地命令增加明确 owner 参数；解析、计算、哈希在锁外，最终短锁重验来源文件
身份及当前 owner。无 owner 的人工写入遵守现有 manual_write_guard；只读 check 和
reparse dry-run 不获得写权限。模式报告保持独占新建，已有证据不覆盖。

不改变科学算法、阈值、签字权限或方法口径；自主 facts 不 refresh/reparse。
临时模型判断保持待人确认。不得扩展任意命令、任意文件或通用研究工具框架。

## 验收

- 有效 owner、原人工流程与现行成功路径。
- 分析期间超时、接管或失权不得发布；人工写入登记与租约获取互斥。
- 输入、facts、manifest、日志或文件/目录身份变化拒绝发布；冲突不覆盖。
- mode 报告到 scientific-review 使用实际模块组合，保留待人确认标识。
- 固定来源组合覆盖 T184/T185/T186/T187/T188，相关测试、全量离线回归、敏感扫描和当前 head CI。

## 真实环境验证

本单为本地发布保护，采用合成 study、真实本地锁、模拟时钟及固定来源离线组合。
无真实集群、研究写入、计算、配置、定时任务或部署授权，不运行现场验证。
开发会话只交付 PR，由协调方独立审阅并按负责人授权处理合并。
