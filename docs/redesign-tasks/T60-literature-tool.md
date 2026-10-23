# T60：轻量文献整理脚本（从 v2.7 `literature_search.py` 提取）

## 分支与目标

- 分支：`codex/t60-literature-tool`；基于最新 main，一张任务单一个 PR。
- **目标：** 在文献 skill 里提供一个小脚本，帮研究会话把检索结果整理成 `literature-record.md`（T59）格式的记录表：
  1. DOI 和标题归一化；
  2. 多个来源（Crossref、OpenAlex）的结果合并去重；
  3. 按 DOI 向 Crossref 查询，核对标题、作者、年份，记录核实日期和结果；
  4. 输出 CSV 和 Markdown 表，保留“未核实”“SI 位置”“方法摘要”等需要人填的空列。
- **为什么：** 负责人要求“原始文献、DOI 逐条核实”。现在核实全靠会话手工做，容易漏，也没有留下核实记录。
- **定位：** 放在 `skills-next/auto-g16-literature/scripts/`，**不进 ag 内核**（核心保持稳定）。关键词打分只用于安排阅读顺序，不代表相关性结论。
- 资料：`archive/skills/auto-g16-reaction-literature/scripts/literature_search.py`（约 1500 行；`normalize_doi`、`crossref_url`、`openalex_url`、`fetch_json`、`normalize_crossref`、`normalize_openalex`、去重合并部分）；T59 的 `literature-record.md`（列定义以 T59 为准）。

## 依赖

- 列定义来自 T59。T59 未合并前，按 T59 工单“要做的”第 3 条的列开发；T59 合并后如有出入，在本 PR 里对齐。
- 和其他开发中的工单不改同一个文件，可以同时开发。

## 允许改动的路径

- 新增 `skills-next/auto-g16-literature/scripts/literature_records.py`。
- 新增 `skills-next/tests/test_literature_records.py` 和 `skills-next/tests/fixtures/literature/` 下的合成响应（虚构的 DOI 和标题，或公开元数据的最小片段）。
- `skills-next/auto-g16-literature/SKILL.md`：加一段用法；T59 也改这个文件（加一段不同的说明），后合并的一方 rebase 解决。
- `docs/redesign-tasks/T60-literature-tool.md`：本任务单。

## 要做的

1. **命令：**
   - `normalize`：读入 DOI 或标题列表（文本或 CSV），输出归一化后的 DOI（小写、去掉 `https://doi.org/` 前缀和空白）。
   - `merge`：读入多个来源的检索结果 JSON（Crossref、OpenAlex 原始响应），按 DOI 合并去重；没有 DOI 的按归一化标题加年份合并，并标“无 DOI，待人工确认”。
   - `verify`：对每个 DOI 查询 Crossref `works/{doi}`，与记录里的标题、第一作者、年份比较，写 `verified / mismatch / not_found / network_error`，以及核实日期。**网络失败不能写成已核实。**
   - `export`：输出 CSV 和 Markdown 两种格式，列与 `literature-record.md` 一致；需要人填的列留空。
2. **网络：** 只访问 Crossref 和 OpenAlex 的公开 API；Crossref 请求带 `mailto`（从命令行参数读取，不写进代码或输出）；超时、限速和错误都要有明确报错；可以用 `--offline` 只处理已下载的 JSON。
3. **撤稿和更正：** 保留 v2.7 对 Crossref `update-to`、`relation` 和 OpenAlex `is_retracted` 的检查，有就在表里标出来。
4. **从 v2.7 只提取函数逻辑**（归一化、URL 构造、响应解析、合并）。不恢复 intake 合同、payload 哈希绑定、上游绑定校验和旧的命令结构；文件头注明“改编自 archive/…”。
5. 输出里不写检索人的邮箱、API 密钥、本机路径。

## 不允许

- 不进 ag 内核，不改 `ag/`。
- 不抓取付费全文，不绕过出版商的访问限制；只用元数据 API。
- 不根据检索结果自动下结论（比如“无先例”）；只整理记录。

## 测试

- 全部离线：用合成的 Crossref、OpenAlex 响应测试归一化、合并去重（同 DOI 不同大小写和前缀、无 DOI 按标题加年份）、核实比较（标题一致、标题不一致、作者不一致、年份不一致、404）、撤稿标记、网络错误不被写成已核实、导出的列与 `literature-record.md` 一致。
- 测试中不发真实网络请求（用假的请求函数）。
- `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`；敏感扫描与 `git diff --cached --check`。

## 真实环境验证

- 合并后，在研究 B 试点的文献调研中实际使用：对王组手性硼烷的原始论文和归档中的“王组计算先例汇总”（14 篇）跑一遍 `verify`，把核实结果数（verified / mismatch / not_found）写进 PR 评论。不需要连集群。

## 停止条件

- 需要访问 Crossref、OpenAlex 以外的网站。
- 需要改 ag 代码或 T59 的列定义。
- 从 v2.7 提取时发现逻辑依赖已舍弃的合同或绑定，拆不开。

## 合并前审阅与交付

- 需要监督方审阅：是。
- PR 描述第一行：`Task: T60`。
- 合并只由负责人操作。

## 版本记录

- T116 脱敏：研究标识、编号与环境字面量改为泛称；原工单结构和结论不变。
