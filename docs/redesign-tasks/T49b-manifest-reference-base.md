# T49b：修复 review manifest 的两类引用解析

## 分支与范围（V1，2026-10-16，监督方批准、负责人授权）

- 基于最新 main，分支 `codex/t49b-manifest-reference-base`；PR 首行 `Task: T49b`。
- 只改 `ag/src/ag/_review_manifest.py`、`ag/tests/test_review_manifest.py`、`docs/LESSONS.md` 和本任务单；README/handoff 不改。
- 真实事故：ag 的 topology/irc-compare JSON 保存 Attempt 相对裸文件名，快照 Markdown 保存 study 根相对路径，清单却按分析文件目录查找，导致已签 study 的只读核查失败。

## 行为与验收

1. JSON 的 `file`、`source`、`path`、`definition` 值不含 `/` 且源 JSON 目录中不存在时，跳过、不报错；`thermo`、`frozen_evidence` 仍显式，含 `/` 的路径行为不变。
2. Markdown/文本相对引用先按源目录解析；非 `./`、`../` 开头的引用允许 study 根目录解析。两处存在且不是同一文件时报歧义；根目录解析成功的收录条目标记 `resolved_from: "study_root"`。
3. analyses 外的文件仍不收录；都不存在按旧规则报错。保留符号链接、越界、已签清单不展开、超长路径及独占发布规则。
4. 合成回归覆盖 topology 裸名、根目录 structures 引用不收录、根目录 analyses 引用收录及标记、歧义；同时覆盖显式相对路径、JSON 显式键、目录展开和安全边界。现有测试全部通过。
5. LESSONS 增补解析基准经验，要求复扫覆盖另一台电脑上的已签 study，由负责人运行。

## 验证与交付

- 运行 manifest 回归及 `ag/tests`、`skills-next` 全套测试，暂存精确文件后敏感扫描与 diff 检查。
- 开发机只读复扫 L1、L2、L3，与 #269 留存文件数和逐项大小/SHA-256 对照，列出全部差异与原因；失败不得当成空清单。
- 清单输出只重定向到临时目录，不修改 study/签字/facts，不连接集群，不提交或取消计算。
- PR 提供负责人可运行的只读脚本与命令，顺序 V2 → OPS-3 → V1 → T47；单项失败记录后继续下一项，最终统一汇总。
- 当前阻塞如实区分解析、环境或科学审阅；L3 既有越界链接不绕过，另一台电脑核查未执行就明确待负责人执行。
- 仅负责人合并；不得扩展允许改动路径。
