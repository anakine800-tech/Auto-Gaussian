# Gaussian 学习知识地图

用下表把问题快速路由到最相关的知识文件。只读取完成当前回答所需的文件。

| 问题类型 | 关键词示例 | 知识文件 |
| --- | --- | --- |
| 零基础入门与学习顺序 | 什么是计算化学、先学什么、如何练习 | `learning-roadmap.md` |
| 理论与方法 | HF、SCF、MP2、CCSD(T)、DFT、泛函、多参考 | `theory-and-methods.md` |
| 基组与 ECP | 6-31G、def2、cc-pVnZ、极化、弥散、GenECP | `basis-sets.md` |
| 输入与输出 | gjf、route、Link 0、电荷、多重度、坐标、终止信息 | `gaussian-input-output.md` |
| 常用作业与排障 | Scan、SP、Opt、TS、QST2、IRC、Freq、SCF 不收敛 | `core-job-types.md` |
| 环境与性质 | SMD、显式溶剂、BSSE、NMR、TDDFT、重元素、外场 | `advanced-properties.md` |
| 研究工作流 | 机理、金属催化、能量跨度、TOF、数据表、论文写作 | `research-workflow.md` |

## 组合读取规则

- “怎样写输入并确认计算成功”：读取输入输出文件，再读取对应作业类型文件。
- “怎样选方法和基组”：读取理论方法文件与基组文件；若涉及溶剂、激发态或重元素，再读取进阶性质文件。
- “怎样研究反应机理”：读取研究工作流与常用作业文件；过渡金属或不对称催化仍需专门的科学编排技能。
- “输出报错怎么办”：先定位作业类型和最后一个正常步骤，再搜索具体报错文本；不要只凭一个关键词叠加排障选项。
