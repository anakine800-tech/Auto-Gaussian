---
name: auto-g16-literature
description: 为 ag 主族单分子研究查找计算方法先例，优先人提供的本组论文和 SI，区分直接先例与类比并记录 DOI、页码、方法适用边界。
---

# Auto-G16 Literature

在选择方法或解释方法差异时使用；给出可核对的文献依据，科学取舍由人和 LLM 完成，不执行计算。

1. 从 study 获取体系、目标量、电荷 / 多重度、溶剂和温度。优先阅读人提供的论文、SI，再查[本组文献表](references/group-literature.md)；空表表示尚未录入，不能解释为本组没有文献。
2. 用可用检索工具搜索本组已发表研究、相同反应类型与相似物种，再扩大至方法论文。检索得到的摘要只用作线索，计算细节回到论文主文和 SI；拿不到 SI 时标注“未核实”，不补造设置。
3. 提取优化 / 频率 / 单点各层级、泛函、基组、色散、溶剂模型与溶剂、低频处理、温度、标准态、构象搜索及筛选方法。不要把论文的单点方法写成它的优化方法。
4. 分类为“直接先例”（所关心体系、任务及状态匹配）或“类比”（明确差异，如取代基、溶剂、电荷、反应步骤）。引用方法本身的论文不能冒充该体系的直接计算先例。
5. 在 study 的“方法与依据”写下表，提供 DOI 链接及页码 / SI 小节。对未报告的项写“未报告”，对未读到的项写“未核实”。提出适用于当前目标的方案并解释差异，不按“论文用了”直接照搬。

| 来源（作者、年份、DOI） | 主文页码 / SI 位置 | 体系与任务 | 优化 / 频率 / 单点 | 溶剂、温度、标准态、低频 | 先例类型与差异 |
|---|---|---|---|---|---|
| <核对后填写> | <可定位位置> | <填写> | <分开列明> | <填写> | <直接先例 / 类比> |

若检索后没有可用先例，记录查找范围和未解决项，转 `auto-g16-study` 的“验收与兜底方法”表，在提交摘要中明确写“兜底方法”。缺失的体系信息仍须问人；兜底不填补电荷、多重度或溶剂。主文和 SI 冲突时列出原文位置及冲突，不能伪称已核实一致。

课题检索记录按 [literature-record.md](../auto-g16-study/references/literature-record.md) 写进私有 study，并与开题包的假设和方法依据对应。每条 DOI 核对标题、作者、年份；未核实的不作为方法依据，检索同时覆盖反面证据。公开的 `group-literature.md` 只放已发表的本组文献；课题检索记录和未发表工作分析留在私有 study，公开前先读 study.md 的保密行。

## 轻量文献整理（T60）

使用 [literature_records.py](scripts/literature_records.py) 整理元数据；只依赖 Python 标准库，不调用 ag。
在仓库根目录运行，输出保存到私有 study。以下文件名为占位示例，需换成自己的私有输入/输出位置：

```sh
python skills-next/auto-g16-literature/scripts/literature_records.py normalize papers.csv --offline --output normalized.json
python skills-next/auto-g16-literature/scripts/literature_records.py merge crossref.json openalex.json --offline --output merged.json
python skills-next/auto-g16-literature/scripts/literature_records.py verify merged.json --mailto "$CROSSREF_CONTACT" --timeout 20 --output verified.json
python skills-next/auto-g16-literature/scripts/literature_records.py export verified.json --csv literature-record.csv --markdown literature-record.md
```

`normalize` 接收逐行 DOI/标题文本，或含 `doi`/`DOI`、`title`/`标题` 的 CSV；可选 `year`/`年份`、`first_author`。
仅有 DOI 的记录不能完成三项比对，需先补标题、第一作者和年份。
`merge` 接收 Crossref 原始 `message.items`（也支持单篇 `message`）与 OpenAlex 原始 `results` JSON；
同 DOI 合并，没有 DOI 时仅按归一化标题及已知年份合并，缺年份/标题则保留独立行。
来源差异保留在 JSON 的 `variants`，任何来源的标题、第一作者或年份不一致/缺失均不能标为已核实。

在线核实只查 Crossref 公开元数据，每次请求携带命令行 `--mailto`，邮箱不写入结果；不抓正文或 SI。
固定 API 主机且拒绝重定向，防止请求被引向出版商或把联系参数转发给其他站点。
超时、限速等记 `network_error`，404 记 `not_found`，不自动重试；`mismatch` 记录不一致/缺失字段，
`verified` 仅表示 DOI、标题、第一作者、年份相符，不代表方法、相关性或全文已核实。
同名作者、缩写与出版年份差异交给人核对，不自动放宽匹配。核实日期为 UTC 日期。

离线核实用 `verify merged.json --offline --cache cached-works.json --output checked.json`。
缓存是以归一化 DOI 为键、单篇 Crossref 原始响应为值的 JSON 对象；已记录的 404 可写 `{"http_status": 404}`。
缺缓存记 `network_error/offline_cache_missing`，不能推断不存在；输出注明离线缓存比对，日期是比对日期，不是下载日期。
其他三个命令始终离线。核实退出码：0 全部 verified，1 有未通过项（结果已保存），2 参数/输入/输出错误。

导出对齐 T59 的 [literature-record.md](../auto-g16-study/references/literature-record.md)（12 列，含记录编号和作者）；自动测试核对列名及顺序。
记录编号、关系、证据级别、正文/SI 位置、方法摘要、检索式与日期留空，由研究会话填写。
核实状态与日期放在“核实方式”列；Crossref `update-to`、`relation` 和 OpenAlex `is_retracted` 信号放在“未核实项”列，
存在 relation 不等于撤稿，无信号也不等于已排除撤稿。作者与逐字段核实证据保留在 JSON，和表一起保存。
所有输出要求新文件，防止重跑覆盖已人工补充的表；CSV 防公式执行、Markdown 转义表内特殊字符。
