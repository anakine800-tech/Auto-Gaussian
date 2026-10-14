# T35：fetch 补取缺失输出

## 目标与事故

T34 新增 xTB 调度器输出声明后，已有 fetched Attempt 无法补取缺失文件。
增加 `ag fetch <attempt> --add-missing`；普通 fetch 保持原行为。
分支：`codex/t35-fetch-add-missing`，基于最新 main。

## 允许改动的路径

- `ag/src/ag/fetch.py`：补取与独占写入记录。
- `ag/src/ag/cli.py`：新增 fetch 参数。
- `ag/tests/test_fetch.py`、`ag/tests/test_core.py`：假 Transport 和 CLI 回归。
- 本任务单：用法、验证与交付边界。

## 实现要求与用法

1. `--add-missing` 仅接受 fetched；先读取全部当前模板声明输出的远端大小与 SHA-256。
2. 本地已有文件逐一比较；不同则在下载前整次拒绝，报告文件名、两边大小与哈希。
3. 只下载本地缺失项；全部暂存并核验后以 O_EXCL 写入 outputs，再核对字节。
4. 原文件、status、manifest 和原 fetch 日志不变。成功补取另以 O_EXCL 写入
   `fetch-add-missing-<UTC时间>.json`，包含本次新增文件名及全部声明输出的大小、SHA-256。
5. 远端缺失/不可读、路径检查失败如实指出文件；状态不变。不自动补造或删除文件。
6. 再次运行，仍核验全部文件，然后返回“没有可补取的文件”；不新增空操作记录。
7. 只复用 metadata（stat/sha256sum）和下载，不新增远程命令或写操作。

防范已有结果被替换：全部前置核验、独占创建，发布前再次核对远端与本地已有文件。
下载失败的暂存证据保留；发布阶段 I/O 失败也不删除已独占创建的文件，需人工检查。
补取是文件收集，不表示 facts 已刷新或科学结果已通过审阅。

## 测试与真实环境验证

假 Transport 覆盖只补缺失、已有文件不一致整次拒绝、远端缺失、状态拒绝、重复运行，
并检查下载损坏、核验期间文件变化、独占创建竞争、路径链接拒绝和 CLI 参数。
全量 `ag/tests` 与 `skills-next` 回归、敏感扫描及 diff 检查。
真实集群与已有研究数据不在本次验证范围；合并后另行授权。

## 交付

不改 AGENTS.md。CI 通过后提 PR，描述第一行 `Task: T35`。
涉及 fetch 与远程交互，合并前等待负责人审阅；Codex 不合并。
停止条件沿用 AGENTS.md：范围外修改、同一问题修复两次仍失败、真实环境意外。
