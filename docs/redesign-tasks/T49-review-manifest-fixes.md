# T49：修复 `ag review manifest` 的两个引用解析错误，并改两处小问题

## 分支与目标

- 分支：`codex/t49-review-manifest-fixes`；基于 v4.1.0 之后的 main，一张任务单一个 PR。
- **防的事故（2026-10-15 真实发生）：** OPS-2 的 V2 study 签字前生成证据清单时，先后两次失败，签字到现在还没完成：
  1. study 或 review 的说明文字里，`analyses/...` 路径后面紧跟着中文（中间没有空格），中文被并进了文件名，报“引用的分析输出不存在”。原因在 `ag/src/ag/_review_manifest.py` 的 `_references` 末尾：裸路径的正则只在空白和少数中文标点处截断，遇到汉字不会停。
  2. 旧签字 JSON 里的 `frozen_evidence` 字段引用了一个**目录**。`_analysis_reference` 只接受文件，于是报“Missing referenced analysis output”。
- **目标：** 两种写法都能正确识别，同时不放宽现有的安全约束：拒绝符号链接、拒绝越出 study 的路径、不从散文中猜测路径。

## 允许改动的路径

- `ag/src/ag/_review_manifest.py`
- `ag/tests/test_review_manifest.py`
- `ag/src/ag/topology.py`：只把 `_check_fragments_and_mapping` 里与公开函数 `fragments` 同名的局部变量改名，行为不变（T44 审阅时留下的建议）。
- `skills-next/auto-g16-recipes/cards/complex.md`：只把第 6 节“50、100、150 cm⁻¹ 两截断同值”改为“三档（每档熵、焓截断取同值）”（T40 审阅时留下的建议）。
- `docs/LESSONS.md`：新增一条。
- `README.md`、`docs/handoff-v4.md`：只在“已知问题”中删除 T49 这一条。
- `docs/redesign-tasks/T49-review-manifest-fixes.md`：本任务单。

## 要做的

1. **裸路径截断：** 裸写的 `analyses/...` 路径只匹配到最后一个已知扩展名（json、md、csv、tsv、txt、xyz、pdf、png、svg、html）为止。扩展名后面紧跟的汉字、标点或其他字符都不算进路径。在反引号或 Markdown 链接里的路径，行为不变。
2. **引用目录：** 签字 JSON 或 Markdown 显式引用了 `analyses/` 下的一个目录时，展开为目录内的全部普通文件，按相对路径排序后逐个计算哈希写入清单，并记录“由某目录展开”。要求：
   - 目录本身或其中任何一层是符号链接就拒绝；
   - 只展开 `analyses/` 内的目录；
   - 目录为空时报错，而不是静默跳过；
   - 不跟随目录外的任何链接。
3. **不变的行为：** 先前签字的清单（`ag-review-manifest/1`）仍然不再展开；远程 URL 仍然不处理；越出 study 的引用仍然报错。
4. **LESSONS：** 现象是证据清单把中文说明当作文件名，以及引用目录时报缺失。以后：引用证据时用反引号或链接包裹路径；需要引用一批文件时可以直接引用目录。

## 不允许

- 不改签字、提交、取消或证据刷新的逻辑；不改清单的 schema 名。
- 不放宽符号链接和越界检查。
- 不使用研究数据或真实日志做测试。

## 测试

- 新增用例：路径后紧跟汉字或中文标点（`analyses/a.json说明`、`analyses/a.json，见上`），只识别出 `analyses/a.json`；反引号和链接写法的现有测试保持不变。
- 引用目录：正常展开、排序稳定；目录中含符号链接、目录本身是符号链接、目录在 `analyses/` 外、空目录：全部拒绝。
- 已签清单不展开的现有测试原样通过。
- `topology` 的现有测试全部原样通过。
- `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`；暂存精确文件后运行敏感扫描和 `git diff --cached --check`。

## 真实环境验证

- 不连集群。合并后，负责人在 OPS-2 V2 study 所在的电脑上只读运行一次 `ag review manifest`，确认能生成清单、文件数和哈希正确，然后补签 V2。结果写在 PR 评论里，不写路径。

## 停止条件

- 修复需要改变已签清单的格式或含义。
- 需要改动范围外的文件。

## 合并前审阅与交付

- 需要监督方审阅：是（签字证据相关）。
- PR 描述第一行：`Task: T49`。
- 合并只由负责人操作。
