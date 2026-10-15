# T43：虚频方向审阅命令 `ag mode-review`

## 分支与目标

- 分支：`codex/t43-mode-review`；基于最新 main（T42 合并后 rebase），一张任务单一个 PR。
- 目标：新增本地只读命令。对一个已取回的频率计算，沿指定的振动模式正、负两个方向位移，报告研究者指定的原子对的距离变化，并导出两份位移后的 XYZ 供人查看。方向是否符合目标反应坐标，仍由人判断。
- 资料：
  - `ag/src/ag/_parse_outputs.py:38–55`：`imaginary_modes` 目前只列 3.5 Å 内变化率最大的五对原子；
  - `skills-next/auto-g16-recipes/cards/ts.md:182`：缺目标对不能证明它不动，“不杜撰模式查看命令”；
  - 旧版知识来源（只读参考，不 import，提交说明注明来源）：`archive/skills/auto-g16-ts-irc/scripts/ts_irc.py:3860` 的 `create_mode_review`。
- 防的事故：TS 方向审核时，目标成键或断键的原子对不在前五对里，或者距离超过 3.5 Å，现有输出看不到它是否参与振动，只能凭印象判断方向。极小点出现小虚频时，也没有可复现的“沿模式位移后的几何”，供提出新 Attempt 使用。

## 允许改动的路径

- `ag/src/ag/mode_review.py`：新模块。
- `ag/src/ag/cli.py`：只在本地工具元组中加入 `'mode_review'`（命令名 `mode-review`）。
- `ag/tests/test_mode_review.py`（新增）及合成数据。
- `skills-next/auto-g16-recipes/cards/ts.md`：只改第 182 行所在条目。
- `skills-next/auto-g16-recipes/cards/failure-diagnosis.md`：在虚频处理处加一句，指向本命令。
- `README.md`：命令表加一行。
- `docs/DEVELOPING.md`：模块地图加一行。
- `docs/redesign-tasks/T43-mode-review.md`：本任务单。

## 要做的

1. **命令形式：** `ag mode-review <attempt> --study <dir> --pair i-j [--pair ...] [--mode 1] [--amplitude 0.3] --out <analyses/新文件.json> [--json]`。
   - 原子编号从 1 开始；`--mode` 按频率从低到高排序，默认第 1 个（最低频率，TS 时即虚频）；
   - `--amplitude` 是笛卡尔位移的最大原子位移，单位 Å，写进输出。
2. **几何与振动向量取向一致：** 使用频率段的几何（与振动向量同一取向）。取向不一致或无法确认时拒绝。依赖 T42 的分段结果，只接受正常结束的频率段。
3. **输出：**
   - 所选模式的频率；
   - 每个原子对在原几何、+位移、−位移下的距离；
   - 变化的符号（哪一侧缩短）；
   - 该原子对沿模式的距离变化率（与现有 `imag_modes` 同一定义）；
   - 全部原子对中变化率排名，以便看出目标对是否主导。
4. **导出 XYZ：** 两份文件，`<out 主名>.plus.xyz` 和 `.minus.xyz`，独占创建。注释行写明模式、振幅和来源 Attempt。
5. **报告说明：** 写明 ag 版本与提交号、所用日志段号及其 SHA-256，以及“方向判断由人完成，本输出不判定反应坐标是否正确”。
6. **卡片：**
   - ts 卡片第 182 行改为：先用 `ag mode-review` 输出目标原子对的位移，再人工审核；
   - failure-diagnosis 指出：极小点有小虚频时，可以用导出的位移几何提出新 Attempt（由人确认）。

## 不允许

- 不改 facts 和 `imag_modes` 的既有输出。
- 不自动判定方向正确与否，不自动提出或准备新 Attempt。
- 不使用研究数据或真实日志做测试；不连接集群。
- 不修改上述范围外文件。

## 测试

- 合成数据（手工构造几何与一个振动向量，不用真实日志）：目标原子对沿模式缩短或伸长，符号和距离与手算一致。
- 目标原子对距离超过 3.5 Å 时，同样能报告。
- 频率段未正常结束、取向不一致、原子编号越界：都拒绝。
- 输出文件已存在：拒绝；三个输出文件都是独占创建。
- 后端：`PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`；记录通过数和跳过原因。
- 暂存精确文件后运行敏感扫描与 `git diff --cached --check`，人工核对 PR 文本和 Git 身份。

## 真实环境验证

- 合并后由负责人另行安排：在计算机上对 L3 已接受的 TS 只读运行，指定 C–F 和 C–Cl 原子对，核对方向与当时的人工审核一致。结果写在 PR 评论里，不含主机信息。

## 停止条件

- cclib 给出的振动向量取向与几何无法对应：停下报告。
- 要改范围外文件；同一问题修两次仍未解决。

## 合并前审阅与交付

- 需要监督方审阅：是（新命令、卡片修改）。不涉及 remote、submit、cancel、status、fetch。
- 修改 AGENTS.md：无。
- PR 描述第一行：`Task: T43`；写改动、测试结果和参考的旧版文件。
- 用 `gh pr view <编号> --comments` 读取评论，逐条处理并回复；冲突本地 rebase；合并只由人操作。
- 与 T38 都改 `cli.py` 的同一行元组，后合并者 rebase；须在 HSS 第二批 TS 方向审核（K2）前合并。
