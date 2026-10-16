# T88：`ag irc-review` 报告记录路径 XYZ 的 SHA-256

## 分支与目标

- 分支：`codex/t88-irc-path-hash`；基于最新 main，一张任务单一个 PR。**开发机做。** 小改动。
- **来源：** T87（前端 IRC 查看页）开发中发现，`ag-irc-review/1` 报告的 `path_geometry` 只记录了路径 XYZ 的文件名和帧数，没有哈希；前端只能显示“未核对哈希”。
- **目标：** 在每个方向的 `path_geometry` 中新增 `sha256`（写出的 `<stem>.forward.xyz` / `<stem>.reverse.xyz` 的字节哈希）。只新增字段，其余输出不变，`schema` 仍为 `ag-irc-review/1`（可选字段，旧报告没有该字段仍合法）。

## 允许改动的路径

- `ag/src/ag/irc_review.py`：只改 `path_geometry` 的组装和写出顺序（先确定 XYZ 字节，再计算哈希写入 JSON）。
- `ag/tests/test_irc_review.py`：新增用例。
- `docs/ag-irc-review-1.md`：补字段说明（标明可选、旧报告无此字段）。
- `docs/redesign-tasks/T88-irc-path-hash.md`：本任务单。

## 要做的

1. `path_geometry` 新增 `sha256`：与实际写出的 XYZ 文件字节一致。
2. 写出仍为四个文件独占创建、失败撤回；哈希必须在写出前由待写字节计算，不能写出后再读回计算。
3. 除新增字段外，JSON、Markdown 和 XYZ 输出与 main 逐字节一致（测试中去掉新增字段后对比）。

## 不允许

- 不改其他字段和判据逻辑；不改 schema 名。
- 不回写已有报告（L3 的旧报告保持原样，前端对其显示“未核对哈希”）。

## 测试

- 新报告中两个方向的 `sha256` 与写出文件的实际哈希一致。
- 去掉新增字段后，输出与 main 一致。
- 开发中只跑相关测试；推送前本地跑一次全量 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，之后以 CI 为准。敏感扫描与 `git diff --cached --check`。

## 真实环境验证

- 不需要（纯本地输出字段）。合并后可在开发机上对 L3 D 组重新生成一份报告（写在 study 以外的新目录），供 T87 前端验证“有哈希”路径。

## 停止条件

- 需要改判据逻辑或其他输出字段。

## 合并前审阅与交付

- 需要监督方审阅：是。
- PR 描述第一行：`Task: T88`。
- 合并只由负责人操作。
