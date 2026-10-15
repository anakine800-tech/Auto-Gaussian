# T46：TS 的 Hessian 策略、低频残余判据，以及大体系 IRC 的“走完”定义

## 分支与目标

- 分支：`codex/t46-ts-hessian-irc-completion`；基于最新 main，一张任务单一个 PR。
- 目标：只改卡片，不改代码。
  1. ts 卡片写明推荐的 Hessian 策略：先用小基组做 TS 优化并算频率，再用 RCFC/ReadFC 读进完整方法的 TS 优化；同时写明 RecalcFC、MaxStep 的使用条件，以及 NoEigenTest 的限制。
  2. opt-freq、ts 卡片补上“低频残余”判据：日志 `Low frequencies ---` 第一行中，平动和转动的残余超过约 20 cm⁻¹ 时，提示几何或网格不足，熵不可信。
  3. irc 卡片明确大体系 IRC 怎样算“走完”：有限步数的 IRC 已离开 TS 区域，两侧端点分别优化为极小点，并由 `irc-compare` 确认身份，满足这三条即视为该方向走完。
- 资料：
  - `skills-next/auto-g16-recipes/cards/ts.md` 第 3 节（第 113–165 行，RCFC/ReadFC 与父 chk 校验）、第 6 节（第 177–186 行）；
  - `skills-next/auto-g16-recipes/cards/irc.md` 第 5 行、第 6 节（第 90–99 行）、第 7 节（第 100–108 行）、第 8 节第 131 行；
  - `skills-next/auto-g16-recipes/cards/opt-freq.md` 第 6 节；
  - 已合并 #230（跨 Attempt 父 chk）、#240（RCFC 取向校验）；AGENTS.md 第 6 节（“IRC 必须两个方向都走完并识别端点后才能声称验证”，本任务只明确“走完”的判据，不改这条规则）。
  - 注意：`facts.json` 的 `frequencies_low` 是 cclib 给出的最低几个振动频率，**不是** `Low frequencies ---` 那一行的平动、转动残余，卡片里不能把两者混为一谈。
- 防的事故：
  - 84 原子级别的 TS 优化，直接对完整方法做 CalcFC 要多算一次完整 Hessian（约等于一次频率计算）；卡片没写更省的已支持路径，HSS 会白白多花核时。
  - 几何没收敛好或积分网格不足时，平动、转动残余偏大，低频熵不可信，现在的卡片没有提示。
  - irc 卡片目前写着“仅达到 MaxPoints 不能写走完”。对大体系来说，完整走到极小点的 IRC 成本很高，又常在平坦区失败，结果没有一种可执行的验证路径；而“有限步 IRC 加端点优化”是常见的专业做法。

## 允许改动的路径

- `skills-next/auto-g16-recipes/cards/ts.md`：第 3、6、7 节。**不改第 182 行所在条目（T43 正在改）。**
- `skills-next/auto-g16-recipes/cards/irc.md`：第 1 节第 5 行的说明、第 6、7 节、第 8 节第 131 行。**不改第 116–119 行（留给 T36b 回写 L3）。**
- `skills-next/auto-g16-recipes/cards/opt-freq.md`：第 6 节。**不改第 103 行所在条目（T38 正在改）。**
- `docs/redesign-tasks/T46-ts-hessian-irc-completion.md`：本任务单。

## 要做的

1. **ts 卡片的 Hessian 策略**（第 3 节，写成可选路径，不作为强制要求）：
   - 路径 A：完整方法 `Opt=(TS,CalcFC)`，最稳，成本最高。
   - 路径 B（体系较大时推荐）：先用小基组（例如方法表中不含弥散的同泛函组合，具体组合由计算方案签字确定）做 `Opt=(TS,CalcFC) Freq`，审核恰好一个虚频且方向正确；再以它为父 Attempt，用 `--parent-chk` 加 `Opt=(TS,RCFC)` 做完整方法的 TS 优化，按现有规则取 `final_input.xyz` 的坐标。小基组 TS 只作中间步骤，不进入剖面。
   - 难收敛时可以用 `RecalcFC=N`，或减小 `MaxStep`；每次修改都作为新 Attempt，经人确认后提交。
   - `NoEigenTest` 只在初始 Hessian 已确认有且只有一个正确的负本征值时使用，在 review 里写明理由（保留现有措辞的含义）。
2. **低频残余判据**（opt-freq、ts 卡片第 6 节各加一条）：
   - 记录日志中 `Low frequencies ---` 第一行（平动加转动），写明行号。
   - 残余的绝对值超过约 20 cm⁻¹ 时，在 review 里标为“残余偏大”，提示几何收敛或积分网格可能不足，热化学中的低频熵不可信；处理办法是用更严的收敛标准或网格重新优化（新 Attempt），不直接接受。
   - 写明这一行不是 `facts.json` 的 `frequencies_low`。
3. **irc 卡片的“走完”定义**（第 6 节改写相关条目，第 1 节第 5 行补一句引用）：同时满足以下四条，该方向才算“走完”：
   1. 已接受的路径点没有校正器失败，也没有能量跳跃或折返；
   2. 最后一个路径点的能量比 TS 至少低 3 kcal/mol（默认值，计算方案可以另定，要写进 review）；
   3. 目标成键或断键的键长，已从 TS 值越过它与该侧预期端点值之间的中点；
   4. 从最后一个路径点出发的 Opt+Freq 收敛为极小点（零虚频，频率阶段收敛），并且 `irc-compare` 确认它就是预期的物种。

   达到 MaxPoints 但满足以上四条，算走完；不满足任意一条，仍写“IRC 未完成”。第 7 节的失败处理顺序保持不变（先缩小 StepSize，再增大 MaxCycle；不能用增加 MaxPoints 代替校正器收敛）。第 131 行改为与新定义一致的表述。
4. 三张卡片都不超过 285 行，“常见坑”不超过 10 条；超出时把理由挪到参考文档，不删判据。

## 不允许

- 不改代码、模板、方法表（acceptance-methods），不改 AGENTS.md。
- 不改上面明确排除的行（T43、T38、T36b 正在改或将要改）。
- 不放宽“两个方向都要验证”的要求，不放宽“端点必须独立做 Opt+Freq 并核对身份”的要求。
- 不提交真实主机、用户名、作业号、绝对路径、凭据、研究数据或日志。

## 测试

- 后端：`PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`；卡片一致性与格式测试必须通过，记录通过数和跳过原因。
- 卡片中出现的命令和选项必须能通过一致性检查（例如 `--parent-chk`）。
- 暂存精确文件后运行敏感扫描与 `git diff --cached --check`，人工核对 PR 文本和 Git 身份。

## 真实环境验证

- 不需要。（“walltime 中断后能否用 RCFC 接续”是另一项真实环境验证，由负责人另行安排，不在本任务范围。）

## 停止条件

- 发现新定义必须改 AGENTS.md 才能成立：停下询问。
- 要改上面排除的行，或范围外的文件。
- 卡片行数超限且无法通过挪到参考文档解决：停下说明。

## 合并前审阅与交付

- 需要监督方审阅：是（卡片修改，涉及科学判据）。
- 修改 AGENTS.md：无。irc“走完”的定义由负责人于 2026-10-15 确认采用推荐方案，在 PR 中写明。
- PR 描述第一行：`Task: T46`；列出三张卡片各改了哪几节。
- 用 `gh pr view <编号> --comments` 读取评论，逐条处理并回复；冲突本地 rebase；合并只由人操作。
- 与 T38、T43、T36b 都可能改到同一张卡片的不同行，后合并者 rebase。

## 实施记录（2026-10-15）

- `ts.md` 第 3、6、7 节：补充可选 Hessian 路径、RCFC/ReadFC 来源与适用性、
  NoEigenTest 限制、低频残余审核及 RecalcFC/MaxStep 的使用条件。
- `opt-freq.md` 第 6 节：补充低频残余审核，静默失败检查清单由六项更新为七项。
- `irc.md` 第 1、6、7、8 节：定义逐方向四项完成判据；比对示例明确使用独立
  Opt+Freq 的端点 Attempt，保留 StepSize → MaxCycle → Hessian 的失败处理顺序。
- 科学措辞澄清：保留 `Low frequencies ---` 首行及行号记录，但该行不保证只有
  平动、转动残余。Gaussian 官方[振动分析说明 §2.1](https://gaussian.com/wp-content/uploads/dl/vib.pdf)
  指出 TS 的真实虚频可能排在近零模式前；必要时结合后续行和投影后的频率/模式辨认，
  只对辨认出的平动、转动残余使用约 20 cm⁻¹ 阈值，防止误拒绝正常 TS。
- 本次不改代码、模板、方法表或 AGENTS.md；任务单排除的三个条目/段落逐字保留。
  三卡行数：TS 233、IRC 143、Opt+Freq 131；常见坑分别为 5、4、4 条。
- 真实环境验证：按任务单不需要，未执行；卡片实现与离线验证不构成研究结果验收。
- 离线全量测试：`PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，
  1711 通过、1 失败、2 跳过。唯一失败为 `ag/tests/test_review.py:313` 固定判据数 12，
  而新增低频残余条目后为 13；卡片一致性与格式测试通过。
  跳过原因：远端 stat/ps 方言仅在 Linux CI 验证；私有本地日志未启用。
- 当前阻塞（环境/离线验证）：测试文件不在允许范围内；需负责人决定是否仅放行
  `ag/tests/test_review.py` 的计数断言由 12 更新为 13，然后重新验证。
  未擅自修改测试，未将未通过的全量测试写成通过；科学判据另需监督方审阅。
