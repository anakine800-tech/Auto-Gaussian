# T64：证据清单对解析不了的引用改为“记录 + 签字人确认”，不再整份失败

版本：v3（2026-10-16，负责人转达监督方批准的两次范围调整；取代 v1 的 analyses 外引用规则及 v2 的裸文件名、普通 JSON 路径口径）。

## 分支与目标

- 分支：`codex/t64-manifest-unresolved`；基于最新 main，一张任务单一个 PR。开发机做。
- **为什么换思路：** T49、T49b 两次修解析规则，计算机上的四个已签 study 仍然全部失败。10-16 的诊断（PR #275 评论）显示，四个失败项都是正文里的说明性文字，不是证据文件：
  - V2：`analyses/local-acceptance-20261015/topology.md` 第 15 行 `manifest.json`（Attempt 内的文件名）；
  - OPS-3：`analyses/study-before-signoff-20261015.md` 第 58 行 `final_input.xyz`（Attempt 内的文件名）；
  - V1：`analyses/V1-signed-evidence-20261015/attempts/…/review.md` 第 22 行 `reaction-plan.md#…`（卡片链接）；
  - T47：`analyses/OPS-2-status-and-T47-addendum-20261015.md` 第 18 行 `../../scnet-crest-v2-butylammonium-20261015/analyses/OPS-2-V2-final-review.md`（指向另一个 study）。
  按“同一问题修两次仍未解决”的规则，不再给解析规则加特例。
- **新规则：** 从 Markdown、文本、普通 JSON 字段里识别出、但**在 study 内找不到对应文件**或**越出 study** 的引用，不再让清单生成失败，而是记录进清单的 `unresolved_references`，并在终端列出。签字人看过这份列表、明确确认后，清单才写入。
- **要防的事故：** 一是因为一句说明文字导致已签 study 永远无法补签（现在已经发生）；二是反过来，真正缺失的证据被悄悄跳过。所以必须“列出来 + 人确认”，不能静默忽略。

## 允许改动的路径

- `ag/src/ag/_review_manifest.py`
- 调用清单生成的 CLI 入口（`ag review manifest` 所在文件，Codex 开工前确认是哪个文件并写进 PR；只改这个子命令的参数和退出码）。
- `ag/tests/test_review_manifest.py`
- `ag/README.md`（review manifest 一节）、`docs/handoff-v4.md`（删掉 L3 越界链接那条已知问题，改为说明新机制）、`docs/LESSONS.md`（新增一条）。
- `docs/redesign-tasks/T64-manifest-unresolved.md`：本任务单。

## 要做的

1. **哪些仍然是硬错误（不变）：**
   - study 内符号链接（任何一级）；引用按字面规范化后已越出 study 的，直接归类越界，不检查 study 外路径的符号链接；
   - JSON 中 `thermo`、`frozen_evidence` 键的引用找不到或越界（这是设计好的证据指针）；
   - 证据在收集过程中被改动（哈希前后不一致）；
   - 已签清单（`ag-review-manifest/1`）的现有处理。
2. **哪些改为“未解析引用”：** 其他所有被识别为引用、但最终满足以下任一条件的：在 study 内不存在（按 T49b 的源目录和根目录两种方式都找不到）、越出 study。每条记录：`source`（相对 study 的源文件）、`location`（行号或 JSON 字段）、`value`（原文；绝对路径只写 `"<absolute path>"`）、`reason`（`missing` / `escapes_study`）。
   - 已经存在且在 `analyses/` 内的引用：照常收录，不进这个列表。
   - 在 study 内存在、但不在 `analyses/` 内的显式引用：和 T64 之前一样不收录，也无需确认；只记入信息性 `referenced_outside_analyses`（`source`、`location`、相对 study 的 `path`）。终端一行汇总条数，不改变退出码。
   - v1 的“analyses 外但被显式写出的也算未解析”作废。
   - 裸文件名（不含 `/`）按源目录、study 根目录都找不到时：analyses 下任意位置有同名文件则仍为 missing；否则进入信息性 `unqualified_names`（source、location、value），不收录、不需要确认，终端只汇总条数。普通描述文本等原本不识别为引用的内容继续忽略。
   - 并发合入的 T62 对文本显式 `analyses/` 前缀的 study 根目录语义保持不变；以下普通 JSON 行为按 v3 执行。
   - 普通 JSON 路径沿用 T49b Markdown 的源目录与 study 根目录回退；两处存在且不是同一文件时报歧义，根目录回退记录 resolved_from。`./`、`../` 仍只按源目录解析；thermo、frozen_evidence 保留原规则。
3. **生成与确认：**
   - `ag review manifest <study>`：如果 `unresolved_references` 为空，行为与现在相同。
   - 不为空时：在终端逐条列出，**不写清单**，以专门的退出码（例如 4）退出，提示“核对后加 `--accept-unresolved` 重新运行”。
   - 加 `--accept-unresolved`：写入清单，清单里包含完整的 `unresolved_references` 列表，并记录 `unresolved_accepted: true` 和确认时间。
   - 清单 schema 名不变（新增字段向后兼容）；如果判断必须升版本，停下询问。
4. **复扫（开发机）：** L1、L2、L3 各跑一次，和 T49b 合并后的结果对比：已收录文件的列表和哈希必须完全不变；L3 原来因越界失败，现在应能生成，越界那条进入 `unresolved_references`。把差异贴进 PR。三个 study 分别报告 missing、escapes_study、outside_analyses、unqualified_name 四类条数。L1/L2 已收录列表和哈希须完全一致，普通 JSON 回退导致新增文件也必须停止报告。
   - L3 符号链接先报告引用与路径层级；study 内路径相对化，外部只写“study 外”。外部链接按前述越界规则处理；study 内链接仍硬拒绝并停止报告。
   - L3 剩余 missing/escapes_study 只列前 20 条及分类原因，不逐条判断；本任务不为 L3 签字，只验证能生成清单并解释数量。
5. **写好计算机上的核查命令**（贴在 PR 里）：V2 → OPS-3 → V1 → T47 依次运行，先不加 `--accept-unresolved`，列出每个 study 的未解析引用清单；由负责人核对后，再加 `--accept-unresolved` 生成，V2 补签。

## 不允许

- 不静默忽略任何新类别的引用；不放宽 study 内符号链接和收集期间改动的检查。
- 不修改已有证据、签字和快照。
- 不改签字流程本身（只改清单生成）。

## 测试

- 用合成 study 覆盖诊断里的四种写法：Markdown 中提到 Attempt 内的文件名、study 快照里的 Attempt 文件名、带锚点的卡片链接、`../../` 指向另一个 study。裸名按同名 analyses 文件是否存在分成 missing/unqualified_name；仅 missing/escapes_study 要求确认，未确认退出码 4、不写清单，确认后保存完整列表。
- 硬错误不变：符号链接、`thermo`/`frozen_evidence` 缺失、收集期间文件被改，仍然报错。
- 没有未解析引用且没有信息性条目的 study：固定时间和 provenance 后输出与 main 完全一致（哈希对比）。信息性条目只增加清单字段，不改变已收录文件及哈希。
- study 内现存 analyses 外文件只列信息，退出码 0；外部符号链接按越界分类且不访问外部路径，study 内链接仍拒绝。
- 现有测试全部通过。
- `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`；敏感扫描与 `git diff --cached --check`。

## 真实环境验证

- 合并后，负责人在计算机上运行 PR 里的核查命令：先看四个 study 的未解析引用列表（预期就是诊断里的那几条，以及可能的同类条目），确认它们都不是证据文件后，加 `--accept-unresolved` 生成清单；V2 补签，OPS-2 结束。结果回写本 PR，不写本机路径。

## 停止条件

- 复扫中已收录文件的列表或哈希有任何变化。
- 需要改签字流程或升级清单 schema。
- 剩余 missing 中仍有看起来确实是证据文件的条目时停止报告；L3 按 v3 复扫要求仅列前 20 条及原因，不逐条判断。

## 合并前审阅与交付

- 需要监督方审阅：是（签字证据）。
- PR 描述第一行：`Task: T64`；附 L1–L3 复扫对比和计算机核查命令。
- 合并只由负责人操作。
