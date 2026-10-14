# T32：分析命令不改写 facts，签字前保存证据清单

依据：负责人本次 T32 指令及追加的 `ag review manifest` 要求。
分支：`codex/t32-preserve-facts`；基于当前 main；一个 PR，不合并。

## 目标与事故

防止 thermo 等分析命令重写已审阅 facts，导致签字绑定哈希失效且原始字节丢失；
防止签字只引用可变文件名，事后无法确认当时的证据和解析代码版本。

## 允许改动的路径

- `ag/src/ag/facts.py`、`thermo.py`、`_profile_sources.py`、`review.py`、`cli.py`、`_review_manifest.py`。
- `ag/tests/` 中对应 facts、thermo、profile、review 及其集成回归测试。
- `skills-next/auto-g16-study/`、`skills-next/auto-g16-recipes/` 中签字流程与卡片。
- `docs/DEVELOPING.md` 与本任务单。

不改 AGENTS.md、远程操作、配置或依赖；不连接集群。

## 验收标准

1. 分析只在内存使用解析结果；thermo（含 SP 配对）、profile、review check 前后 Attempt 证据字节不变。
2. 仅 facts 命令写 facts.json；不同字节默认拒绝并显示 diff 和新旧哈希。
   人确认差异后用 `--refresh`，先独占保存 `facts.<旧 SHA-256 前12位>.json`，再原子更新当前文件。
   相同字节不改 mtime；备份冲突或发布失败保留旧版；不删除任何旧版。
3. 新 facts 保存实际 ag 代码提交号与 dirty 状态，review 快照绑定该来源。
   哈希不符明确报告“证据文件已变化”和绑定版本提交号；旧记录缺版本或 dirty 时诚实说明复现限制。
4. `ag review manifest --study <dir>` 收集全部 facts.json、review.md、study.md 和被引用的分析输出；
   每项记录 study 相对路径、字节数、SHA-256，清单记录生成时 ag 提交号和 dirty 状态。
   使用 O_EXCL 在 analyses/ 新建清单，不覆盖；缺失引用、符号链接或越界引用报错。
5. 签字卡片先生成清单，再向人请求签字；记录清单路径及其哈希，不将生成清单当作科学接受。
6. ag 与 Skills 测试、敏感信息扫描通过；先推送任务分支并手动运行已有 CI，成功后创建 PR。

## 真实环境验证

本任务只使用合成 study 与已有脱敏水/正丁烷 fixture 离线验证。
不执行真实研究分析、提交、取消或部署；无需集群验证。

## PR

首行 `Task: T32`；报告实现、兼容变化、验证和实际阻塞。合并由人完成。
