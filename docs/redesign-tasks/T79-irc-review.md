# T79：`ag irc-review` 按卡片四条判据逐方向核对 IRC，并输出路径数据

## 分支与目标

- 分支：`codex/t79-irc-review`；基于最新 main（v4.2.2），一张任务单一个 PR。**开发机做。**
- **目标：**
  1. 新增本地命令 `ag irc-review`，按 irc 卡片第 6 节的四条判据，**逐方向**给出工具能核对的部分（数值、来源、日志位置），把必须人工判断的部分明确列出；
  2. 输出每个方向逐点的能量和关键键长，以及路径结构文件，供下一张前端工单（IRC 查看页）使用；
  3. 修改判据 ②（负责人 10-16 决定）：末点降能低于阈值时，如果 ①（工具核对部分）没有发现问题、③ 满足、④ 满足（末点独立 Opt+Freq 为极小点，且 `irc-compare` 确认该侧身份），② 记为“由端点优化补证”，并在报告中写明实际降能。**阈值本身不改**（默认 3 kcal/mol）。
- **为什么：** 现在四条判据全靠人工逐项核对，容易漏项；L3 的 D 组后退方向末点降能不足 3 kcal/mol，但末点优化后确认就是反应物复合物，按现行文字只能判“未完成”。只凭一个例子调低阈值容易过拟合，端点优化是更直接的证据。
- **原则：** 工具只核对和汇总，**不给出“IRC 已验证”的结论**；化学身份仍以 `irc-compare` 加人工审阅为准。
- 资料：`skills-next/auto-g16-recipes/cards/irc.md`（第 6、7 节）、`ag/src/ag/_irc.py`（`parse_irc`）、`ag/src/ag/irc_compare.py`、`ag/src/ag/scan_peak.py`（`aligned_rmsd`、跳变阈值）、`ag/src/ag/topology.py`（`--pair` 写法）、`ag/src/ag/_profile_sources.py`（`protocol()`）、`ag/src/ag/asm.py`（输入哈希记录方式）。

## 允许改动的路径

- 新增 `ag/src/ag/irc_review.py`。
- `ag/src/ag/_irc.py`：**只新增**一个返回逐点数据（点号、能量、该点几何）的函数，可与 `parse_irc` 共用内部逻辑；`parse_irc` 的返回值和 `ag facts` 的输出**逐字节不变**。
- `ag/src/ag/cli.py`：只在分析命令元组里登记 `'irc_review'`。
- `ag/tests/test_smoke.py`：**已预先批准**，只在固定的分析命令列表断言里追加 `ag.irc_review`。
- 新增 `ag/tests/test_irc_review.py` 和合成夹具；`ag/tests/test_irc.py` 只为新函数加用例。
- 新增 `docs/ag-irc-review-1.md`：输出格式（前端工单依赖）。
- `skills-next/auto-g16-recipes/cards/irc.md`：第 6 节判据 ② 的文字、第 6 节加 `ag irc-review` 用法一段、第 7 节 L3 实例一段（按真实验证结果改写）、卡片开头加“要点”（格式见下）。
- `ag/README.md`：分析命令一节。
- `docs/redesign-tasks/T79-irc-review.md`：本任务单。
- 不改 `irc_compare.py`、`facts.py`、`scan_peak.py`（只 import）。

## 要做的

### 1. 命令

```
ag irc-review --ts <TS Attempt> --forward <IRC Attempt> --reverse <IRC Attempt>
              --pair I-J [--pair I-J ...]
              [--forward-reference <Attempt 或 XYZ>] [--reverse-reference <Attempt 或 XYZ>]
              [--forward-endpoint <末点 Opt+Freq Attempt>] [--reverse-endpoint <Attempt>]
              [--irc-compare <analyses/ 下的 irc-compare 报告>]
              [--energy-threshold 3.0]
              --out <analyses/ 下新的 .json> [--study <study>]
```

- 两个方向必须是各自独立的 Attempt；同一个日志里包含双向（`direction: both`）时拒绝并说明。
- `--pair` 是目标成键 / 断键原子对（从 1 开始，与 `ag topology` 写法相同），至少一对。
- `reference` 是该侧**预期**端点结构（人的假设，原子顺序须与 TS 相同），用于判据 ③。
- 同时输出同名 `.md`，以及 `<stem>.forward.xyz`、`<stem>.reverse.xyz`（第 0 帧为 TS，其后为各已接受的路径点）。任一输出已存在就拒绝。

### 2. 前置核对（不满足就报错）

- TS、两个 IRC、两个末点 Attempt 都在同一 study 内；方法口径一致（用 `protocol()` 比较方法、基组、色散、溶剂）。
- TS 能量：取 IRC 日志中第 0 点（起点）的 SCF 能量作参照；与 TS Attempt facts 的电子能相差超过 1×10⁻⁵ Hartree 时给出警告（不报错），两个数都写进报告。
- 原子数、元素顺序在 TS、路径点、reference、末点之间一致。

### 3. 四条判据，逐方向

每条输出 `status` 和依据（数值、来源文件、日志行号）：

1. **路径连续（工具部分）：** `corrector_failed`、是否报告路径完成或达到 MaxPoints；已接受点的能量是否单调下降（允许 0.01 kcal/mol 的数值噪声，参数可调）；相邻点能量跳变和对齐后 RMSD 跳变（沿用 `scan_peak` 的阈值）；任一点缺能量或几何记为 `unknown`。状态取值：`tool_checks_passed`（并写明“仍需人工审阅 SCF/电子态连续性和逐点几何”）/ `not_met` / `unknown`。**工具不能给出 `met`。**
2. **末点降能：** 降能 ≥ 阈值 → `met`；降能 > 0 且低于阈值，同时 ① 为 `tool_checks_passed`、③ 为 `met`、④ 为 `met` → `met_by_endpoint_optimization`（写明实际降能和阈值）；否则 `not_met` 或 `unknown`。
3. **目标键长越过中点：** 每个 `--pair` 记录 TS、末点、预期端点三个距离和中点；预期端点距离小于 TS 时按成键（末点须小于中点），否则按断键（末点须大于中点）；预期与 TS 相差小于 0.05 Å 时该原子对不能区分，记为 `unknown` 并说明。全部原子对满足才算 `met`。没有给 reference 时整条为 `unknown`。
4. **末点为预期极小点：**
   - 末点 Attempt 的输入几何与该方向最后一个已接受路径点一致（坐标偏差 ≤ 1×10⁻⁴ Å，或通过 `ag graph` 的来源记录确认），否则报错；
   - facts：正常结束、优化收敛、频率完整模式数、零虚频（用与 opt-freq 卡片判据对应的现有 facts 字段）；
   - 身份：读 `--irc-compare` 报告中该方向的结论；报告引用的末点 Attempt 必须就是这里给的 Attempt，否则报错。匹配 → `met`，不匹配 → `not_met`，无法确定或未提供报告 → `unknown`。

**方向汇总：** 四条中 ① 为 `tool_checks_passed`、②③④ 为 `met` 或 `met_by_endpoint_optimization` 时，写“工具核对完成，待人工审阅”；否则写“IRC 未完成”，并列出未满足或无法确定的条目。**任何情况下都不写“已验证”。**

### 4. 路径数据（供前端）

每个方向：逐点的点号、能量（Hartree 原值，另给相对 TS 的 kcal/mol）、各 `--pair` 的距离、对应路径结构文件中的帧号；停止原因（完成 / 达到 MaxPoints / 校正失败 / 截断）及最后一个已接受的点号。格式写进 `docs/ag-irc-review-1.md`（`schema: "ag-irc-review/1"`），所有输入文件用 `path` 加 SHA-256 记录。

### 5. 卡片 `irc.md`

- 第 6 节判据 ②：在“默认判据……写进 review”之后加一句：降能低于阈值但 ①③④ 均满足时，可记为“由端点优化补证”，写明实际降能、阈值和端点证据；阈值不因此调低。
- 第 6 节加一段 `ag irc-review` 用法，强调工具结果不是验证结论。
- 第 7 节 L3 实例：**按本单真实验证的实际结果**改写“reverse 末点降能低于默认阈值”那几句；①“仍缺完整连续性审阅记录”的表述保留，除非真实验证中人工补齐。
- 卡片开头加“要点”：放在标题之后、第 1 节之前，标题为 `## 要点`，3–5 条，每条不超过两行，只复述卡片里已有的规则并链接到对应小节，不新增规则（与 T81 的格式相同；T81 不改 irc.md）。

## 不允许

- 不改默认阈值；不输出“已验证”。
- 不改 `ag facts`、`irc-compare` 的输出。
- 不读 study 外的文件；拒绝符号链接。
- 测试数据不放入真实日志：按 DEVELOPING 的规则，从现场形态改编最小片段，虚构身份和数值，保留解析所需的格式。

## 测试

- 合成双向 IRC：两侧都满足 → 两侧“工具核对完成，待人工审阅”。
- 一侧降能 1.5 kcal/mol 且 ①③④ 满足 → ② 为 `met_by_endpoint_optimization`；同样降能但 ④ 不匹配 → `not_met`；③ 不满足 → `not_met`。
- 校正失败、能量回升、能量或 RMSD 跳变、缺点能量 → ① 对应状态。
- 成键 / 断键两种原子对、无法区分的原子对、未给 reference。
- 末点几何与路径末点不一致、irc-compare 报告引用了别的 Attempt、方法口径不同、原子顺序不同 → 报错。
- `parse_irc` 和 `ag facts` 在现有 IRC 夹具上输出逐字节不变。
- 开发中只跑相关测试；推送前本地跑一次全量 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，之后以 CI 为准。敏感扫描与 `git diff --cached --check`。

## 真实环境验证（合并前，开发机，只读）

- 对 L3 的 IRC 运行 `ag irc-review`，`--out` 写到 L3 study **以外**的临时目录，**不改 L3 的任何文件**：
  - D 组：023/024，加末点 027/028 和已有的 irc-compare 报告；
  - C 组：021/022；A、B 组：017–020；起点失败：015/016（这几组没有末点优化，④ 应为 `unknown`）。
  - 注意：025–026 是扫描，不是 IRC。
- 在 PR 评论中列表：每组每个方向四条判据的状态和关键数值（降能、键长、停止原因），与 irc 卡片第 7 节的历史描述逐条对照；有出入时以日志为准并说明。不写主机、路径和用户名。
- 不连接集群，不提交作业。

## 停止条件

- 需要改 `facts.py`、`irc_compare.py` 或 `ag facts` 的输出。
- L3 真实输出中逐点几何无法可靠对应到已接受的路径点。
- 真实验证结果与 irc 卡片第 7 节的历史描述有原则性矛盾（例如 D 组 forward 不满足 ③）。

## 合并前审阅与交付

- 需要监督方审阅：是。
- PR 描述第一行：`Task: T79`；附 L3 对照表。
- 合并只由负责人操作。


## 执行补充（负责人 2026-10-16）

- 不修改 `skills-next/tests/test_skill_format.py`。T81 已获批为所有卡片兼容第 1 节前可选的 `## 要点`；T79 按同一格式保留 IRC 要点。
- T81 合并前，`test_card_has_eight_sections[irc]` 失败属于预期，不绕开；其余测试必须通过。
- T81 合并后 rebase，再跑一次全量测试，然后推送并请求审阅。
