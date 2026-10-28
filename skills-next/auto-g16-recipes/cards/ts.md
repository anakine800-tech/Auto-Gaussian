# TS 分阶段入口与结果登记

## 要点

- 初猜准备、TS 搜索/Freq、IRC/端点分阶段执行；见[阶段导航](#3-输入模板)。
- 机理假设、结构与代表集合须已确认，科学判据与原子映射不因拆卡改变；见[前置条件](#2-前置条件)。
- 恰好一个虚频且方向经人审核仍只是候选；双向 IRC 与独立端点验证后才能声称验证；见[结果判据](#6-结果判据清单)。
- G0、程序正常结束、catalog 归属与科学签字分别处理；覆盖结论限于声明范围和预算，见[覆盖与失败记录](#覆盖与失败记录)。

## 1. 适用范围

主族闭壳层、同一势能面的 TS 工作入口。不做自动反应发现、金属、开壳层或跨自旋面搜索。保留 `ts` 卡片名及核心审阅清单，旧 Attempt 的卡片快照不改；新阶段卡不追溯重写历史 review。

## 2. 前置条件

[机理假设](reaction-plan.md)已由人签字，目标步骤、反应物/产物身份与原子对应明确；结构与代表构象集合已确认。列明正在形成、断裂或迁移的原子对（输入行号从 1 开始）、方法依据、溶剂、电荷和多重度。

catalog v2 写入沿用现有前提：**v4.6.0 在两台电脑部署完成之前，真实研究 study 不写 v2 事件**。版本号或合并不证明部署；`--upgrade-catalog` 只确认格式升级，不授权研究写入。所有原话逐字来自本 study 当前对话，CLI 不能验证发言身份。

### 覆盖与失败记录

覆盖结论统一为 **在声明的通道范围与采样预算内稳定**；列明通道范围、预算及未覆盖部分，未再找到新结构不能证明全局完备。catalog 的“候选 / 采用 / 退役”是对象采用状态，不是通道覆盖状态。通道六态按下列优先顺序派生：

| 通道状态 | 含义及来源 |
|---|---|
| 已验证（verified） | 负责人声明并附原话，声明时至少有最新归属 verified 的候选指向该通道；仍须满足第 6 节与双向 IRC 科学要求。 |
| 低置信度排除（excluded_low_confidence） | 负责人以 `excluded-low-confidence` 声明并附理由、原话；只表达有限证据下的判断。 |
| 待确认通道（pending_confirmation） | 采样中新发现，以 `--discovered` 登记且尚未确认；优先于候选归属派生。 |
| 暂定找到（待负责人确认，tentative_found） | 有候选最新归属 tentative 或 verified 指向本通道，但没有有效通道声明；候选 verified 本身不等于通道已验证。 |
| 已尝试未找到（attempted_not_found） | 有关联候选、但不满足以上状态；登记本身即可派生，不保证已运行计算，须查 ledger 的实际结果。 |
| 未尝试（untried） | 无有效声明、无待确认发现、无关联候选。 |

候选通过目标通道或历史任一次归属关联；“暂定找到”只看最新归属，不回退到旧 verified。`cleared` 需负责人原话，撤销声明后按发现/候选规则重算；整体 coverage 不改变通道状态。通道确认可用 `channel --update --confirm`，无需原话，不等于科学验证；具体命令见[初猜准备](ts-guess.md#ts-初猜工作流)。
来源：[catalog v2 第 5 节](../../../docs/ag-catalog-2.md#5-通道派生与查询)、[T139](../../../docs/redesign-tasks/T139-card-wording.md) A4/X3/X4。

保留所有失败搜索、错误鞍点、振动模式塌缩、组分脱离及重复收敛，记录
步骤/通道、初猜策略、构象来源、实际结果与后续处置（R10）。有限预算只能
支持有限覆盖；失败的搜索不等于该机理不存在。

## 3. 输入模板

| 阶段 | 入口 | 交接给下一阶段的材料 |
| --- | --- | --- |
| 初猜准备、来源登记、G0 | [ts-guess](ts-guess.md) | 已审阅几何与映射、诊断、来源和未覆盖部分 |
| TS 优化、Freq、振动方向 | [ts-search](ts-search.md) | 完整优化/频率证据、恰好一个虚频、人的方向审核 |
| 双向 IRC、端点 Opt+Freq | [irc](irc.md) | 两侧完成、独立极小点、端点身份及连接关系 |

### 初猜来源：一维弛豫扫描

操作、输入限制与选峰规则移至 [初猜卡的一维扫描](ts-guess.md#初猜来源一维弛豫扫描)。局部峰只作初猜，不能直接声称 TS。

### 初猜来源：Gaussian 二维弛豫扫描

操作与显式选点规则移至 [初猜卡的二维扫描](ts-guess.md#初猜来源gaussian-二维弛豫扫描)。保留 Gaussian 网格限制，xTB 多维扫描仍未支持。

### TS 初猜工作流

对象/通道、草稿、候选登记和 G0 的步骤见 [初猜工作流](ts-guess.md#ts-初猜工作流)；准备与提交见 [搜索卡](ts-search.md#5-提交前检查清单)。完成相应科学审阅后，按实际结果登记：

1. **登记结果。**审阅后记录实际 outcome 与归属；暂定归属不需原话，已验证归属需负责人原话并满足第 6 节及 IRC 要求：

   ```sh
   ag catalog candidate-result <study> --object <对象> --candidate <候选> --outcome <实际结果> --attempt <结果Attempt> --assign tentative --channel <通道>
   ag catalog member <study> --object <对象> --attempt <已验证Attempt> --role ts
   ag catalog candidate-result <study> --object <对象> --candidate <候选> --outcome accepted --attempt <已验证Attempt> --assign verified --channel <通道> --quote '<负责人原话>'
   ```
   verified 还要求 Attempt 是本对象成员、已 fetched、facts 可读且 n_imag=1；这些机器检查不证明方向或双向 IRC 已验收。accepted 本身不等于 verified；产物不唯一用 `--assign undetermined --channel <候选通道一> --channel <候选通道二>`，并列全体可能通道。
   来源：[catalog v2](../../../docs/ag-catalog-2.md)、[T139](../../../docs/redesign-tasks/T139-card-wording.md) A9/B6/X3/X4。

2. **通道声明与覆盖结论。**先查 `ag catalog ledger <study> --object <对象> --channel <通道> --json`，以实际尝试结果支撑“已尝试未找到”，区分仅登记、诊断与已计算失败。负责人审阅后才声明：

   ```sh
   ag catalog channel-status <study> --object <对象> --channel <通道> --status <声明类别> --quote '<负责人原话>'
   ag catalog coverage <study> --object <对象> --statement stable --scope '<通道范围>' --budget '<采样预算>' --quote '<负责人原话>'
   ```
   声明类别为 verified / excluded-low-confidence / cleared；排除另需 `--reason '<理由>'`，三者都需原话，不能因一次低层失败而排除。整体结论只写“在声明的通道范围与采样预算内稳定”，撤销用 `--statement withdrawn`，保留 scope/budget/quote。原话逐字来自本 study 当前对话，CLI 不能验证发言身份。
   来源：[catalog v2](../../../docs/ag-catalog-2.md)、[T139](../../../docs/redesign-tasks/T139-card-wording.md) B7/X3/X4。

TS 后分岔或产物分支不能唯一确定时，候选结果的归属用 `undetermined` 并列出候选通道；这些 TS 不放入 profile 的简单选择性定义，每个 TS 必须唯一归属，不能把同一 TS 重复塞入多个产物。报告标注“简单 TS 能垒比不适用”。单条 IRC 不能排除另一分支；本期不做轨迹计算。
来源：[T139](../../../docs/redesign-tasks/T139-card-wording.md) A9/X4、[catalog v2](../../../docs/ag-catalog-2.md)、[审计第 11 节](../../../docs/research/ts-guess-audit.md)。

## 4. 资源建议

按 [搜索卡资源说明](ts-search.md#4-资源建议)核对实际入口、档位、节点策略和 walltime；扫描及约束 CREST 另估成本，双向 IRC 和两端独立 Opt+Freq 也计入。默认档位或补齐 Link0 不授权提交，MaxCycles 不保证不超 walltime。

## 5. 提交前检查清单

- 初猜、结构、电荷多重度、立体警告、原子映射与方法方案已审阅；对应阶段输入及科学边界明确。
- 展示完整 route、方法依据、资源、walltime、远程目录和输入哈希；沿用 [Study 流程](../../auto-g16-study/SKILL.md)的批准记录、匹配长期规则或 Mac 人工确认。
- 选择正确的阶段卡片保存审阅判据；旧快照不补写，初猜诊断不代替 TS 搜索/Freq 或 IRC 验收。

## 6. 结果判据清单

以下保留可直接提取的 TS 核心清单，供仍使用 `--card ts` 的入口；详细输入与排障见 [搜索卡](ts-search.md)。

- `termination=normal`、`opt_converged=true`、`freq_step_converged=true`；缺失/不通过则读原日志，不能推定通过。Opt 和 Freq 都已完成，完整模式数应为非线性 3N−6 / 线性 3N−5。
- **恰好一个虚频**：`n_imag=1`，按原始负频计数，小负频也不能删掉凑数。零或多个虚频均不满足 TS 判据。
- **低频残余**：记录末次已完成频率段的 `Low frequencies ---` 第一行及原日志行号，核对平动、转动残余。
  TS 的真实虚频可能排在这些残余之前，软振动也可能混排；必要时连同后续行及投影后的频率、模式辨认，
  不能把首行所有数都当残余或按数值大小直接删除真实虚频。依据：[Gaussian 振动分析说明 §2.1](https://gaussian.com/wp-content/uploads/dl/vib.pdf)。
  **辨认出的平动、转动残余**绝对值超过约 20 cm⁻¹ 时，在 review 标为“残余偏大”，提示几何收敛或积分网格可能不足、
  热化学中的低频熵不可信，不直接接受；提出更严收敛标准或积分网格重新优化并做 Freq 的新 Attempt，经人确认后提交。
  缺该行或无法区分模式则写缺证据。它不是 `facts.json` 的 `frequencies_low`（cclib 提取的最低几个振动频率），不能用该字段代替。
- **振动方向对应目标键变化**：逐项核对 `facts.json` 的 `imag_modes[].pairs[].atoms`、`elements`、`distance`、`distance_change_rate` 与目标原子对。全局振动正负号任意，须查看同一方向上成键缩短/断键伸长等协调变化，不能仅靠频率大小或单个符号判断。
- 当前 `imag_modes` 只列距离小于 3.5 Å 的原子对中变化率绝对值最大的五对；缺目标对并不证明它不动。先用 `ag mode-review <attempt> --study <dir> --pair 1-2 --pair 2-3 --mode 1 --amplitude 0.3 --out analyses/mode-review.json`（替换为目标原子编号，输出须为新文件）报告目标对距离变化并导出正负位移 XYZ，再人工审核协调方向；振幅为最大原子位移 Å，模式按频率升序编号。取向或频率段证据不足时写不通过并停下，命令不判定反应坐标是否正确。
- 出现长键、断键、强电荷转移、SCF 多个解或近简并迹象时，审查电子态并提出独立 Stable 诊断，按 [失败诊断](failure-diagnosis.md#电子态与-stable-诊断) 审阅 T30 的 `wavefunction_stability` 及原文行；未诊断不算稳定，稳定也不证明闭壳层方法足够。需要非限制性或多参考方法时明确超出本卡范围。
- 确认最终身份与预期一致；柔性 TS 列出审阅过的构象和未覆盖部分，不将单个 TS 的能量直接当作唯一反应能垒。
- 可用 [TS 立体标签](../../auto-g16-structures/SKILL.md#ts-立体标签) 按已签参照产物与原子映射标注构型并核对催化剂，通道建议须人工确认，不替代本节判据。
- `review.md` 写清判据、事实位置与人的方向审核意见；更新 study 假设。IRC 按各产物分支内部的重要性和结构新颖性安排，不按全局权重；暂缓的候选仍为“未验证”。未双向完成并识别端点不能写“已验证 TS/机理”。

- IRC 两个方向均须完成并识别端点；末点各自独立 Opt+Freq 收敛为极小点，满足完整模式数和零虚频。逐方向完成四条判据、分支选择及五类必做 IRC 情形统一见 [IRC 卡片](irc.md#6-结果判据清单)；有限路径末点不能直接当稳定物种。

## 7. 常见失败与处理

初猜来源、模板或低层失败见 [ts-guess](ts-guess.md#7-常见失败与处理)；中断接续、错误鞍点、曲率和收敛见 [ts-search](ts-search.md#7-常见失败与处理)；路径或端点失败见 [irc](irc.md#7-常见失败与处理)。保留失败证据，失败搜索不等于机理不存在。真实环境意外先停止报告，新 Attempt 仍须人确认，UNKNOWN 仅只读核对。

## 8. 常见坑

知识衔接：[GKB-0431、GKB-0422：TS 验证与优化排障](../../auto-g16-gaussian-learning-library/references/core-job-types.md)。原指南的来源与更正见 [归档整理](../references/ts-initial-guess-guide.md)。

- 一个负频、G0 clean、程序正常结束或 catalog 的 accepted 都不等于科学签字。
- 候选归属 verified 不等于通道声明 verified；有限覆盖不证明全局完备。
- 按各产物分支内部的重要性安排 IRC，暂缓仍是未验证；分岔与不唯一归属不套简单能垒比。
