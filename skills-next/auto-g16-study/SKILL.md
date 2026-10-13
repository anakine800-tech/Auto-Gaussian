---
name: auto-g16-study
description: 在 ag 新架构中创建、恢复和推进主族闭壳层单分子计算研究；选择任务卡片、准备提交摘要、审阅结果并记录人的三个里程碑签字。
---

# Auto-G16 Study

科学判断由 LLM 和人完成，确定性的作业操作交给 `ag`。study 放在配置 `local.studies_root`，不放仓库；连接与远程根从本地配置读取，不写入 Skill。仅使用已审阅的 `ag` 模板，不自行编写远程命令或作业脚本。

## 每次调用的固定流程

1. **恢复上下文。** 先读目标目录 `study.md` 的“当前阻塞”，再读其余内容和 `ag list --study <study_id> --json`；核对目标、未完成的量、签字和 Attempt 状态。新研究尚无目录时，用 `ag init <study_dir>` 建骨架，按[研究模板](references/study-md-template.md)与人补齐目标和体系，再读取清单。缺电荷、多重度、溶剂或温度时询问，不从旧研究推断。
2. **判断阶段并选卡。** 按下表打开 `auto-g16-recipes` 的对应卡片。首版仅覆盖主族、闭壳层、单分子；没有适用卡片时说明缺口并停下，不借用旧 Skill 执行。真实环境出现异常时先停下报告。
3. **确定方法。** 使用 `auto-g16-literature`，优先人提供的本组论文和 SI，记录 DOI 与位置、直接先例或类比；无先例才使用[兜底方法](references/acceptance-methods.md)，在摘要声明。验收用最快的验收方法，不宣称研究精度。
4. **准备与提交。** 核查卡片输入、资源和前置结果，调用 `ag prepare`，按[确认摘要](references/confirmation-summary.md)展示每个 Attempt。同一卡片、同一方法的多个 Attempt 可以一次批量确认。等人明确说“提交”后运行 `ag submit <id>...`，仍由人亲手点击 Mac 系统对话框；不代点、不提供跳过方式。`ag` 负责单次提交、文件一致性、路径检查和全用户作业核数统计，无法核实就不提交。
5. **接收并解释结果。** 用 `ag status <id>` 查询；`awaiting_second_observation` 表示证据不足，按显示的最早时间再次只读观察，不视为失败或允许取回。结合 `resources_used.cput`、声明输出的大小/mtime 和观察时间判断活动，缺值记未知。完成后 `ag fetch <id>`、`ag facts <id>`，取回后若 `scheduler_residue=true`，提醒人先用 `ag status` 核查残留；仍残留且人明确授权后才调用 `ag cancel`，由人亲手点击确认，只针对 status.json 的确切 job_id，之后只读核查。不自动 qdel，不重试已声明的取消；qdel 返回不等于最终离队。阅读事实和卡片判据，在 Attempt 的 `review.md` 中逐条填写“通过 / 不通过 / 依据”，依据指向数字和本地输出位置。作业离开队列不等于科学成功；缺失事实不能填成零。更新 `study.md` 进度和剩余问题，每次结束前更新“当前阻塞”（无阻塞写“无”）。
6. **处理异常。** 遇到 `unknown` 或 `failed_presubmit` 按[异常说明](references/unknown-and-failures.md)只报告、不自行处理。计算失败转 `failure-diagnosis` 卡片，提出新 Attempt 的修改方案，等人确认；原 Attempt 保留。取消仅使用 `ag cancel <id>`，由人点击确认，作业号来自其 `status.json`。
7. **请求三个签字。** 分别向人展示结构、代表构象集合（含简并度）、最终结果，再将其明确确认的日期和签字人写入 `study.md`。不可代签或把提交按钮当成科学签字；已有签字可以沿用到未改变的对象，发生改变时说明并重新确认对应里程碑。
8. **沉淀经验。** 解决问题或被人纠正后，按[经验格式](references/lessons.md)在 study 的 `lessons/` 起草，提议修改具体卡片小节，不直接改 Skill。
9. **判定完成。** 只有目标中的量都算出、三个里程碑都签字、`study.md` 有结论，才能称 study 完成；否则说明目前结果及尚缺的证据。下次继续从第 1 步恢复。

## 阶段决策

| 当前阶段 | 下一步 | Skill / 卡片 |
|---|---|---|
| 目标或体系未定 | 补全 study；查计算先例 | `auto-g16-literature` |
| 结构未确认 | 读入结构、审阅电荷与立体化学，请人签字 | `auto-g16-structures` |
| 已确认结构，待初筛 | 选择本地 RDKit 或集群 CREST | `rdkit-screen` / `crest-screen` |
| 已有初筛集合 | 去重、聚类、展示代表与简并度，请人签字 | 所选初筛卡片 |
| 已签代表集合 | 同一方法逐个准备 Opt+Freq | `opt-freq` |
| 已接受极小点且计划有单点 | 对最终几何准备单点 | `sp` |
| 作业已提交 | status → fetch → facts → review | 当前计算卡片 |
| 出现计算失败或虚频 | 停下报告，诊断并提出新 Attempt | `failure-diagnosis` |
| unknown / failed_presubmit | 报告状态与已有证据，等待人决定 | [异常说明](references/unknown-and-failures.md) |
| 合格的最终构象已齐 | 再去重、核对简并度，计算自由能和布居 | `thermo` |
| 目标量已齐 | 展示结论和局限，请人签最终结果 | `thermo`，然后更新 study |

这里只描述方案已有接口。运行前读取当前 `ag <命令> --help`；模板参数和本地工具选项按实际接口填写，不猜选项名。若所需能力尚未提供，列出缺口交给人，不用旁路补齐。


## 常见坑

- 首次观察尚无稳定输出证据时，`awaiting_second_observation`（等待第二次观察）不是 `interrupted`；需相隔至少 60 秒且输出不变，并满足正常标记等完整证据，才能取回。明确异常或非零退出不能用等待掩盖。来源：study `butane-l1-20261013`，`lessons/01-await-second-observation.md`。
- PBS R 不等于程序仍在计算：同时查看 CPU 时间、声明输出大小/mtime、观察时间与数据新鲜度；未知不能填 0，时间不替代退出或正常终止证据。来源：study `butane-l1-20261013`，`lessons/02-status-cpu-output-times.md`。
- 结果 fetched 后 PBS 仍可能残留占核；提示可用 `ag cancel`，核查是否自然离开，再由人授权并点击确认。取消响应与最终查询分开记录，不重试已声明取消。来源：study `butane-l1-20261013`，`lessons/03-fetch-residue-reminder.md`。
