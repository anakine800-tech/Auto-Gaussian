# T48：发布 v4.1.0（版本号、CHANGELOG、验收表、今天的结论写回文档）

## 分支与目标

- 分支：`codex/t48-release-v4.1.0`；一张任务单一个 PR。
- **前置条件：** PR #266（T47）已合并。没合并就停下等。
- **目标：** 把 v4.0.0 之后合并的 #252–#266 发布为 v4.1.0，作为首轮正式研究使用的稳定版本。同时把 2026-10-15 已经验证、签字的结论写进仓库文档，让开发机和计算机 `git pull` 后读到的规则一致（计算机看不了在线交接文档）。
- **只改文档和版本号，不改任何程序逻辑。** 已知的代码问题（`review manifest` 的两个解析错误、CREST/xTB 的 OpenBLAS 线程警告）只在“已知问题”里写明，由 T49、T50 修复。
- **防的事故：**
  - 两台电脑上运行的版本对不上，事后说不清某个 Attempt 是用哪个版本算的。manifest 里记录了 ag 版本，但 4.0.0 之后合并的 15 个 PR 都没有改版本号。
  - 今天得出的结论（RCFC 不能接续中断的优化、walltime 规则、两台电脑的分工）只存在于对话里，新会话读不到，会重蹈覆辙。

## 允许改动的路径

- `ag/src/ag/__init__.py`、`ag/pyproject.toml`：版本号改为 4.1.0。
- `ag/tests/test_smoke.py`：只改版本断言那一行。
- `CHANGELOG.md`：新增 v4.1.0 一节，放在 v4.0.0 之前。
- `README.md`：验收表、支持范围、已知问题、前端配套版本说明。
- `docs/handoff-v4.md`：当前状态，以及“两台电脑”一节。
- `docs/DEVELOPING.md`：加一句“运行只用 main 的检出”。
- `docs/LESSONS.md`：新增下列经验条目。
- `skills-next/auto-g16-recipes/cards/ts.md`：只改第 4 节（资源建议）和第 7 节（常见失败与处理）中关于中断与接续的段落。
- `docs/redesign-tasks/T48-release-v4.1.0.md`：本任务单。

## 要做的

1. **版本号：** 4.0.0 → 4.1.0（三处）。
2. **CHANGELOG v4.1.0：** 按主题列出 #252–#266，每条附 PR 链接，写法与 v4.0.0 一节一致：
   - **解析与事实：** T42/T42b 按作业段解析；T45 报错提示按实际原因识别；
   - **新命令：** T38 `topology`、T43 `mode-review`、T44 `fragments`；
   - **剖面：** T39 焓熵分项、动力学换算、`selectivity`、σ 报告；
   - **取回：** T47 `fetch --incomplete`、从中断作业复用 chk；
   - **方案与签字：** T37 必须显式写 `--method-basis`、计算方案签字；
   - **卡片：** T36a/T36b、T40 复合物与双分子步骤卡片、T46 TS Hessian 策略与 IRC“走完”判据；
   - **文档：** #252 文档索引与交接、T41 ORCA 与仓库瘦身调研。

   不写任何研究体系、主机、路径或作业号。
3. **README：**
   - **验收表（截至 2026-10-15）：**
     - SCNet：CREST/xTB 已验证（中性和 +1 体系、ALPB 溶剂、取回解析）；
     - TS 优化中断后接续：已验证（`final_input.xyz` + `Guess=Read Opt=(TS,CalcFC)`；RCFC 不适用于没有 Freq 的中断优化）；
     - 不完整取回（T47）：PBS 强杀、Slurm TIMEOUT 均已真实验证；
     - 某研究验证 study：已终止，双路线覆盖改由实际研究中的使用来检验，不再单独验证。
   - **支持范围：** 双分子步骤与复合物按 complex 卡片执行，只开放以已审阅原子对为约束的采样。
   - **已知问题：**
     - `ag review manifest`：路径后紧跟中文说明时会把说明当作文件名；签字 JSON 中引用的目录会被当作文件；
     - CREST/xTB 输出可能被大量 OpenBLAS/OpenMP 线程警告撑大（不影响结果）；
     - “不完整取回”中缺少声明输出的分支，目前只有离线测试覆盖。
   - **前端配套：** 只读检查 Auto-Gaussian-Frontend 的 main 实际读取的 facts 和 profile 字段。4.1 只新增字段、没有改名或删除时，写“Frontend v4.0.0 配合 ag 4.1.0 使用”；发现不兼容就停下报告。
4. **handoff-v4.md：**
   - 更新当前状态：v4.1.0、T36–T47 已完成；
   - “两台电脑”一节换成以下规则（不写主机名、用户名、路径）：
     1. 两台都可以有集群配置，都可以提交；每次提交由负责人在该电脑上点击确认。
     2. 每个 study 只属于一台电脑，不复制；换电脑必须整体移动，旧电脑上不留副本，移动前确认没有 submitting 或 unknown 状态的 Attempt。
     3. 运行 `ag` 只用跟随 main 的检出，提交前先 `git pull --ff-only`；开发分支和 worktree 只用于开发。
     4. Slurm 的核时预算只统计本机提交的作业，平台余额由负责人自己查看；核数上限按集群上的全部作业统计。
     5. 开发用的 Codex 会话不连接集群。
   - 一台电脑专做某项研究、另一台做其余工作，属于负责人的使用安排，写成一句“可以按研究分配电脑”即可，不写具体课题。
5. **DEVELOPING.md：** 加一句：真实计算只用 main 检出里的 `.venv/bin/ag`；用未合并的代码做真实验证，必须在工单里写明并取得批准，用临时 worktree，验证后删除。
6. **LESSONS（每条按“现象／原因／修复／以后”的格式）：**
   - **RCFC 与中断的优化：** RCFC 只能读取 Freq 计算写入 chk 的笛卡尔力常数；没有做 Freq 的中断优化，chk 里这条记录的长度为 0，接续在初始化阶段就终止。接续改用 `final_input.xyz` + `Guess=Read Opt=(TS,CalcFC)`。
   - **MaxCycles 不等于不超 walltime：** MaxCycles 只限制步数。按 `walltime ≥ 1.3 × (t_CalcFC + t_step × MaxCycles + t_Freq)` 估算，各项用本体系首个作业的实测值校准，小分子的数据不能外推。
   - **SSH 报 `Operation not permitted`：** Codex 沙箱禁止联网时，SSH 会以 255 退出并给出这个信息，不是网络或集群故障；先检查会话的联网权限。
   - **验证方案的设计：** 设计真实验证之前，先逐条对照相关卡片的限制。OPS-3 的作业 2 就是因为没对照 irc 卡片第 63 行，才拿 RCFC 去接续没有 Freq 的中断优化。
7. **ts 卡片：**
   - 第 4 节：加入上面的 walltime 估算规则，写明“首个作业实测校准”；
   - 第 7 节：“中断后接续”只保留一种做法：`fetch --incomplete`（被强杀时）→ 用 `final_input.xyz` 和父 chk 准备新 Attempt，`Guess=Read Opt=(TS,CalcFC)`；写明 RCFC 只适用于父 chk 中有 Freq 力常数的情况；
   - 卡片总长不超过 285 行。

## 不允许

- 不改任何 `ag/src` 下的逻辑，不改模板、测试逻辑和 AGENTS.md。
- 不创建 tag 或 GitHub release；这两件由负责人在 GitHub 页面上操作。
- 不写研究体系、未发表数据、主机、账户、路径、作业号。
- 不改上述范围以外的文件。

## 测试

- `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`：全部通过，版本断言为 4.1.0，卡片格式和一致性测试通过。
- `grep -rn '4\.0\.0' ag/src ag/pyproject.toml ag/tests/test_smoke.py` 没有结果。
- 暂存精确文件后运行敏感扫描和 `git diff --cached --check`。

## 真实环境验证

- 不需要。合并后两台电脑 `git pull --ff-only`，各运行一次 `ag --version`，结果应为 4.1.0。

## 停止条件

- #266 还没合并。
- 前端存在字段不兼容。
- 需要改动代码逻辑，或需要改动范围外的文件。

## 合并前审阅与交付

- 需要监督方审阅：是。
- PR 描述第一行：`Task: T48`。
- 合并后由负责人：在 GitHub 上创建 tag `v4.1.0` 和 release（正文可以直接用 CHANGELOG 的 v4.1.0 一节）；两台电脑把运行用的 main 拉到最新。

## 版本记录

- T116 脱敏：研究标识、编号与环境字面量改为泛称；原工单结构和结论不变。
