# Auto-Gaussian v4.2.0

Auto-Gaussian 是人在回路中的计算化学助手：LLM 按 Skills 规划研究，人签字和确认，`ag` 负责安全把关与确定性计算。

## 架构

```text
人：研究目标、结构/代表构象集合/最终结果签字、提交与取消确认
  ↓
Codex + Skills：文献依据、方法选择、任务卡片、科学审阅、下一步建议
  ↓
ag：作业生命周期 + 日志解析、热化学、构象去重、关系图与反应能量曲线
  ├─ study 目录中的文件：研究状态、输入、事实、审阅与结论
  └─ Mac → SSH → PBS/Torque 或 Slurm → Gaussian / xTB / CREST
```

研究状态全部保存在 study 目录的文件中，不依赖数据库、常驻调度服务或旧 v3 运行时。
`ag/` 是独立 CLI 和确定性工具；`ag/templates/` 保存经审阅的程序模板；
`skills-next/` 保存编排、任务卡片、结构、文献及辅助 Skills。

```text
<STUDY_DIR>/
  study.md                 目标、方法、进度、当前阻塞、签字、结论
  journal.jsonl            只追加的操作记录
  structures/              结构与初筛材料
  attempts/<ATTEMPT_ID>/
    manifest.json          准备时固定的输入、哈希、父子关系及可选卡片快照
    submission.json        新多集群提交的作业绑定记录
    status.json            本地派生状态
    inputs/                提交文件
    outputs/               取回的声明输出
    facts.json             确定性解析事实
    review.md              LLM 按卡片逐项审阅
  analyses/                去重、热化学、IRC 比较与能量曲线
  lessons/                 待人审阅、整理进卡片的经验
```

一个 study 同时只由一个主会话推进，其他会话只读。只有目标中的量齐备，结构、代表构象集合、最终结果三处均有人签字，且 `study.md` 写有结论，才算完成。
作业结束、解析成功或 PR 合并都不替代科学验收。

## 安全内核

完整规则见 [AGENTS.md](AGENTS.md)。

- 每个 Attempt 至多提交一次；`O_EXCL` 原子声明存在即拒绝再次提交。
- 每个 Attempt 使用新的远程目录；服务器文件不覆盖、不删除、不截断。
- `UNKNOWN` 只做只读核对，不自动重提；失败后的新 Attempt 仍需人确认。
- `submit`、`cancel` 必须由人在 Mac 系统对话框亲手确认，无参数、环境变量或配置可绕过。
- 确认摘要、实际提交字节和上传后的远程哈希必须一致。
- 取消只针对绑定记录中的确切作业号与所属集群；历史 PBS Attempt 使用原有状态记录。
- 只执行审阅过的模板和白名单参数；拒绝任意远程命令、符号链接及根目录之外的路径。
- 按集群统计该用户全部作业，包含非 ag 作业。PBS 和 Slurm 单作业均受 `max_cores` 限制，运行加排队（含挂起）计入 `max_committed_cores`。ag 不限制运行中的核数；Slurm 配置了核时预算时另行检查。
- 真实主机、用户名、账户、分区、机器路径、凭据和研究数据只留在本机配置及仓库外 study，不进入 Git。

## 安装

使用 Python 3.11 或更新版本的 `chem` conda 环境；RDKit 用于结构与几何工具。
**每个 worktree 单独创建 `.venv`**，避免多个 editable 安装争用同一个 `ag` 入口。
在所选 worktree 根目录执行：

```bash
conda activate chem
python -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install -e 'ag[test,chem]'
# 仅当 chem 环境尚无 RDKit 时：
python -m pip install rdkit
python -m pip check
ag --version
ag --help
```

`--system-site-packages` 允许复用 chem 中的 RDKit；ag 的安装和命令入口仍属于本 worktree。
`chem` extra 包含 cclib、NumPy、GoodVibes 4.3.0；`test` extra 包含 pytest。
Gaussian、xTB、CREST、调度器及本机 OpenSSH 需另行准备，外部软件遵守各自许可。

## 配置

以 [多集群占位符样例](ag/config.clusters.example.toml) 为准，将本机配置保存到
`~/.config/ag/config.toml`。已存在时先检查，不能直接覆盖。样例中的路径、SSH 别名、
队列、账户、分区及模块名称均须在本机替换；study 根目录位于 Git 仓库之外。

| 配置 | 用途 |
| --- | --- |
| `local.python` / `local.studies_root` | 本机 Python 与仓库外 study 根目录 |
| `clusters.<CLUSTER>.scheduler` | `pbs` 或 `slurm` |
| `clusters.<CLUSTER>.ssh` | 专用 SSH 配置与别名 |
| `clusters.<CLUSTER>.remote` | 允许根目录与其 `ag/` 子目录 |
| `clusters.<CLUSTER>.resources` | 本集群核数、档位及可选核时预算 |
| `clusters.<CLUSTER>.programs` | Gaussian、xTB/CREST 安装位置及可选 Gaussian 模块 |
| `clusters.<CLUSTER>.queue` | PBS 队列占位值 |
| `clusters.<CLUSTER>.partition/account/qos/expires` | Slurm 可选设置与到期日期 |

`prepare --cluster '<CLUSTER>'` 固定 Attempt 所属集群；后续操作遵循该绑定，不能靠切换当前配置把作业送往别处。
`cluster` 子命令是**构象聚类**，并非集群切换命令。
旧单集群 [config.example.toml](ag/config.example.toml) 仍支持为 `default` PBS 配置。
`ag clusters --json` 只读列出本机配置的集群及资源档位；它不连接服务器，程序启用标记不等于远程安装验证。

资源示例：`mini` 4 核/10 GB、`simple` 8 核/12 GB、`general` 22 核/50 GB、`complex` 44 核/120 GB，均按实际配置调整。
Gaussian `%nprocshared` 必须等于档位核数，`%mem` 不超过档位内存的 85%。
SSH 准备说明见 [ag/README.md](ag/README.md)；配置后按需运行 `ag doctor --cluster '<CLUSTER>' --json` 做只读自检。

## 命令一览

尖括号表示需替换的占位符。`<STUDY_ID>` 是配置的 studies 根目录下的直接子目录名；
`<STUDY_DIR>` 是完整本地目录。各命令支持 `--json`，完整参数以 `ag <命令> --help` 为准。

| 命令 | 用途 |
| --- | --- |
| `ag init '<STUDY_ID>'` | 创建 study 骨架 |
| `ag prepare --study '<STUDY_ID>' ...` | 本地建立独立 Attempt、校验输入并显示确认摘要；三种模板均须显式填写非空 `--method-basis`；`--card` 保存卡片来源 |
| `ag submit '<ATTEMPT_ID>' ...` | 人点击 Mac 确认后提交；支持批次 |
| `ag status '<ATTEMPT_ID>' --json` | 只读查询远程证据并更新本地状态；也可 `--study` |
| `ag fetch '<ATTEMPT_ID>' [--add-missing \| --incomplete]` | 首次取回、为 fetched 补取，或有结束证据时显式取回不完整输出；拒绝覆盖 |
| `ag cancel '<ATTEMPT_ID>'` | 人点击 Mac 确认后取消确切作业 |
| `ag list --study '<STUDY_ID>' --json` | 列出本地 Attempt |
| `ag doctor --cluster '<CLUSTER>' --json` | 只读检查连接、调度器和程序环境 |
| `ag monitor --watch 120` | 前台只读采样并保存监控快照；Ctrl-C 退出，无自动提交或取消 |
| `ag facts '<ATTEMPT_ID>' --study '<STUDY_ID>' [--refresh] --json` | 解析日志、几何、频率、扫描、IRC 和波函数稳定性事实；显式刷新保留旧证据 |
| `ag thermo '<ATTEMPT_A>' '<ATTEMPT_B>' --study '<STUDY_ID>' --json` | GoodVibes qRRHO 与所选构象集合的布居 |
| `ag dedup '<XYZ_FILE>' --charge 0 --out '<ANALYSES_DIR>' --json` | 按已确认电荷去重；此例为中性体系 |
| `ag cluster '<DEDUP_JSON>' --max 20 --json` | 从去重结果选择代表构象 |
| `ag graph --study '<STUDY_DIR>' --json` | 展示 Attempt 父子关系 |
| `ag irc-compare --ts '<TS>' --forward '<FORWARD>' --reverse '<REVERSE>' --reactant '<REACTANT>' --product '<PRODUCT>' --out '<NEW_REPORT_JSON>' --json` | 双向 IRC 端点与参考结构的映射比较 |
| `ag topology '<ATTEMPT_ID>' --study '<STUDY_ID>' --out '<NEW_REPORT_JSON>' --json` | 比较提交与最终结构，报告成键、质子及立体差异；TS 用 `--pair i-j` 仅报告距离，同时生成 Markdown 摘要 |
| `ag fragments '<ATTEMPT_OR_XYZ>' --study '<STUDY_DIR>' --out 'analyses/<NEW_REPORT>.json' --json` | 按共价半径识别片段，报告编号映射、分子式和跨片段不确定接触，独占导出 JSON、Markdown 与各片段 XYZ；单片段仅报告，电荷与多重度由人确认 |
| `ag mode-review '<ATTEMPT>' --study '<STUDY_DIR>' --pair 1-2 --mode 1 --amplitude 0.3 --out analyses/mode-review.json --json` | 导出正常频率段的正负位移 XYZ、目标对距离变化与全对排名；编号从 1 开始，振幅为最大原子位移 Å，输出必须新建，方向由人判断 |
| `ag profile '<PROFILE_JSON>' --json` | 组装已审阅物种的自由能曲线、焓熵分项、Eyring 换算、按产物汇总的选择性、σ 报告及适用时的能量跨度 |
| `ag review init '<ATTEMPT_ID>' [--card '<CARD>']` / `ag review check '<ATTEMPT_ID>'` | 创建审阅骨架、核对判据及事实快照；旧 manifest 可在审阅时补指定卡片 |
| `ag review manifest --study '<STUDY_DIR>' --json` | 签字前生成不可覆盖的本地证据清单 |
| `ag clusters --json` | 本地集群、资源档位和可选预算查询，不返回连接凭据 |
| `ag coverage --merged '<DEDUP_JSON>' --energies '<ENERGY_JSON>' --out '<NEW_REPORT_JSON>' --json` | 按匹配的 DFT 能量统计采样路线重叠与低能覆盖 |
| `ag scan-peak '<ATTEMPT_ID>' --study '<STUDY_ID>' --point 9 --out '<NEW_GUESS_XYZ>' --json` | 按原扫描点序号选择严格局部极大，导出 TS 初猜 |

作业命令退出码：0 成功，1 取消或校验失败，2 环境/连接错误，3 状态不确定。
`unknown`、`failed_presubmit` 或计算失败不构成重提同一 Attempt 的理由。

## 新增命令用法与证据维护

```bash
# 只读查询本机集群；附加目录核对只返回是否匹配，不公开路径
ag clusters --json --verify-studies-root '<STUDIES_ROOT>'

# 新审阅骨架；只有旧 manifest 未记录 card 时才补指定 --card
ag review init '<ATTEMPT_ID>' --card opt-freq --json
ag review check '<ATTEMPT_ID>' --json
ag review manifest --study '<STUDY_DIR>' --json

# fetched Attempt 补取新声明的缺失文件；不会顺带刷新 facts
ag fetch '<ATTEMPT_ID>' --add-missing --json
# 已有 facts 时比较解析内容；确认差异后再显式刷新并保留旧版
ag facts '<ATTEMPT_ID>' --study '<STUDY_ID>' --json
ag facts '<ATTEMPT_ID>' --study '<STUDY_ID>' --refresh --json

# 两条路线已在相同 xTB 方法优化、能量可比时，才使用 lowest/统一窗口
ag dedup --source 'crest=<CREST_XYZ>' --source 'mdopt=<MDOPT_XYZ>' \
  --charge 0 --hydrogens polar --representative lowest --window 6 \
  --out '<NEW_DEDUP_DIR>' --json
ag coverage --merged '<DEDUP_JSON>' --energies '<DFT_ENERGIES_JSON>' \
  --window 3 --top 5 --out '<NEW_COVERAGE_JSON>' --json

# 9 是原始扫描点序号示例，必须是列出的合格局部极大
ag scan-peak '<SCAN_ATTEMPT>' --study '<STUDY_ID>' \
  --point 9 --out '<NEW_TS_GUESS_XYZ>' --json
ag profile '<STUDY_DIR>/analyses/<PROFILE_JSON>' --name '<NEW_PROFILE_NAME>' --json
```

- `review init` 不覆盖已有审阅；`--card` 的补指定来源明确记在 review 中，不修改 manifest。`review check` 核对已保存的判据与事实，不代签。签字前先在 study/review 中引用全部依据，再生成 `review manifest`；清单独占创建在 `analyses/`，记录相对路径、大小、SHA-256 与 ag 提交号。签字记录应包含清单路径和清单哈希，生成清单本身不是签字。
- `facts` 在解析内容相同时保持原字节和 mtime，即使解析器提交号变化也不重写；内容不同时默认显示差异并拒绝。人工核对后用 `--refresh`，先保留 `facts.<旧哈希前12位>.json` 再发布新版；已有几何仍不能覆盖。thermo/profile/review check 不改写 facts。
- `fetch --add-missing` 只适用于 fetched：先核对全部声明远程输出与本地已有文件的大小/哈希，不一致就拒绝；只独占写入缺失项，另存补取记录，原 status、manifest 和 fetch journal 保留。补取成功不表示解析或科学审阅完成。
- `fetch --incomplete`：PBS 必须为 interrupted，并有至少相隔 300 秒、输出大小/mtime 相同、均不活跃且无退出回执的两次 status 观察；Slurm 必须为 finished，取回时重新确认 squeue 无此作业、sacct 有受支持终态。COMPLETED 且输出齐全用普通 fetch。
- 不完整取回只下载声明中确认存在且可读的输出，逐文件前后核对大小/SHA-256，确认缺失项写入独占的 `fetch-incomplete-<UTC时间>.json`；权限或连接等无法核实就整次失败，暂存证据留在 `.partial`。状态不变，重复取回、普通 fetch 和 `--add-missing` 均拒绝已有不完整取回记录。
- 不完整 facts 不是正常终止，不能用于 thermo/profile；有绑定完整取回记录的 interrupted 父作业可声明 parent chk，复制检查及 Mac 提交确认不变。chk 是否被 Gaussian 读入需另行验证。
- `dedup --hydrogens heavy|polar|all` 默认 `polar`（重原子加 N/O/S/P 上的氢）；反应相关氢若不属该集合，使用 `all`。旧无氢模式记录按 heavy 解释。仅几何来源合并不混排能量；`--representative lowest` 要求同方法、有限 Hartree 能量，并应用能差容差（默认严格小于 0.05 kcal/mol）。ETKDG 候选先经 CREST `--mdopt` 优化后才能与同层级 CREST 能量合并，不能混用力场能量。
- `coverage` 的 `--energies` 可给单点 Attempt 目录/ID、JSON 路径列表或原生 thermo JSON；按坐标和来源证据匹配，SCF 与 qh_G 分开统计。单路线独有低能项会提示补采样；报告不是构象穷尽证明。
- `scan-peak` 仅接受内部点及左右紧邻点均收敛、有能量，且中点严格高于两侧的候选；列出全部局部峰，默认选最高局部峰，`--point` 选择指定原序号。无合格峰、指定非候选、单调曲线或平台都不导出；仍须审阅扫描范围与跳变，并继续 TS/Freq/双向 IRC。
- `profile` 输入定义放在 study 的 `analyses/`，引用已审阅物种及可比的热化学来源；输出到新的名称，不覆盖。`--perturb 1` 可逐个 TS 状态做 ±1 kcal/mol 扰动分析。新增焓熵分项、分子数、正反 Eyring 速率/半衰期和 σ 来源/警告；可选 `selectivity: [{"id": "products", "products": {"R": [{"species": "ts_r1"}, {"species": "ts_r2", "paths": 2}], "S": [{"species": "ts_s"}]}, "perturb_kcal": 1.0}]` 按产物汇总同组成同电荷 TS，输出产物比例、有效能垒、两两比例及最低构象对照。两产物给有符号 ee（首标签占优为正），多产物给分布/dr；可选扰动逐 TS 物种报告比例区间和翻转。paths 与构象简并度分开，省略标为默认 1。换算均为 κ=1 的简单 TST，缔合用标准态准一级近似，不等同于实验速率/ee。schema 保持 `ag-profile/1`，既有能量不变。SP/Freq 配对须有几何证据，热化学审计分项不能重复加到 qh_G；无势垒步骤不支持表达。

## Skills 部署

将以下六个目录从长期保留的仓库 `skills-next/` 软链接到 `~/.codex/skills/`：
`auto-g16-study`、`auto-g16-recipes`、`auto-g16-structures`、`auto-g16-literature`、
`auto-g16-chemdraw-structures`、`auto-g16-gaussian-learning-library`。

先检查旧副本/软链接，将旧部署保存在 `~/.codex/skills-disabled/` 下的新备份目录。
确认目标名空闲后，对每个名称执行（替换占位符）：

```bash
mkdir -p "$HOME/.codex/skills"
ln -s '<REPO_ROOT>/skills-next/<SKILL_NAME>' "$HOME/.codex/skills/<SKILL_NAME>"
```

不要指向将被删除的临时 worktree。检查链接中的 `SKILL.md`，再在 Codex 新会话确认可见。
后续只修改仓库源文件并经 PR 审阅；经验先进入 study 的 `lessons/`，每周整理进卡片。

## 一个 study 的典型流程

1. `ag init`，在 `study.md` 中记录目标、结构、电荷、多重度、溶剂、温度及方法依据；人确认结构。
2. 按结构/文献/recipes 卡片做 RDKit 或 CREST 初筛、去重、DFT 单点重排；人签署代表构象集合。
3. 用 `prepare` 准备 Opt+Freq 等 Attempt，向人展示结构、立体警告、完整 route、方法依据（文献先例 DOI 及位置 / 本课题既有方案来源并声明“不是文献先例，精度未经验证” / 兜底声明）、资源、walltime、远程目录和输入哈希。例如：

   ```bash
   ag prepare --study '<STUDY_ID>' --cluster '<CLUSTER>' \
     --template gaussian --input '<INPUT_GJF>' --card opt-freq \
     --tier simple --walltime 01:00:00 --label optfreq \
     --method-basis '<文献先例 DOI 及位置 / 本课题既有方案及来源（不是文献先例，精度未经验证） / 兜底方法声明>'
   ```

4. 获得提交指令后执行 `ag submit`，由人亲手点击 Mac 对话框。`status → fetch → facts` 收集证据；失败时按诊断卡片提出新 Attempt，不自动重提。
5. `review init` 后由 LLM 逐项审阅收敛、虚频、结构身份等，`review check` 检查事实来源；优化后重新去重，统一方法与程序版本，再做 `thermo`，需要反应曲线时使用 `profile`。
6. 人审核最终结果并签字；`study.md` 写入结论与适用边界。续接时读取 `study.md`、`ag list` 和已有文件，不凭对话记忆重复提交。

TS 必须恰好一个虚频且振动方向与反应坐标一致；只有双向 IRC 完成、端点被识别并科学审阅后，才能声称验证。

## 前端

ag 4.2.0 配合前端 [Auto-Gaussian-Frontend](https://github.com/anakine800-tech/Auto-Gaussian-Frontend) v4.2.0 使用；前端版本待 T57 合并后由负责人发布，启动方式见其 README。
已只读核对前端 main（`e224d5a`）：结果表读取 `route`、`termination`、`energies.scf`、`energies.g`、`n_imag` 和 `frequencies_low`，这些字段未改名或删除；缺失值显示为空。
分析页将 profile 作为完整 JSON 展示，没有专用剖面字段依赖。`ag-facts/1` 和 `ag-profile/1` 保持不变，新增字段不影响读取；分段解析修正可能改变旧值，不能把字段兼容理解成重新解析后数值必然不变。
默认只读，读取本地 study、结果与保存的监控快照。`--enable-actions` 显式开启经本机 ag 执行的准备、提交、状态刷新、取回和取消；不绕过 Mac 确认，也不直接执行远程命令。

T7e 已适配多集群（[Frontend #9](https://github.com/anakine800-tech/Auto-Gaussian-Frontend/pull/9)）：
操作模式通过 `ag clusters --json --verify-studies-root` 获取档位并核对目录，新建 Attempt 显式选择集群；
提交与取消继续遵循 Attempt 绑定。服务器页分集群读取
`<STUDIES_ROOT>/.ag-monitor/<CLUSTER>/latest.json`，同时兼容旧单集群的
`<STUDIES_ROOT>/.ag-monitor/latest.json`；两种 default 来源并存时显示歧义，不能擅自视为最新。
监控数据始终来自 ag monitor 快照，前端不启动采样器；缺失、过期或失败不当成空闲或零预算。
Slurm 核时预算来自 ag 本地台账，不等于平台余额。

## 验收状态

截至 2026-10-15，按负责人在 T48 任务单中提供的已验证、已签字结论更新；T47 细节见 [#266](https://github.com/anakine800-tech/Auto-Gaussian/pull/266)。以下是已完成的验证与适用边界；本次文档更新没有重新运行计算、补取输出或代签。

| 项目 | 状态 | 结果与边界 |
| --- | --- | --- |
| SCNet | **已验证** | Gaussian 16 A.03 学习版；已验证提交、状态、取回与解析链路。CREST/xTB 已验证中性和 +1 体系、ALPB 溶剂、取回及解析。平台免责条款由使用者自行评估，不据此承诺所有方法/任务已验证 |
| L1 正丁烷 | **已签字（流程验收）** | 正丁烷构象、Opt+Freq、热化学及续接流程验收；不外推为任意体系的精度保证 |
| L2 柔性主族体系 | **已签字（流程验收）** | 构象覆盖不完整；所选集合的结果不代表完整构象空间或正式研究结论 |
| L3 小体系 TS/IRC | **已签字（流程验收）** | 历史签字早于 T46；现行判据下仍缺完整连续性审阅，reverse 末点降能低于默认阈值，不能声称按 T46 双向完成。能垒只代表 B3LYP-D3(BJ) 层级 |
| V-T21 扫描 | **已完成** | ① Gaussian 026 + scan-peak 选中第 9 点，与 TS 的 RMSD 为 0.002 Å；修复前会误选第 2 点。② xTB 789 沿 C–F 严格单调下降，本次扫描范围内无复合物势阱、无能垒，scan-peak 按设计拒绝导出。③ 浅能垒气相离子–分子 SN2 不宜用 xTB 扫描找 TS 初猜；xTB 无峰不代表真实反应无能垒 |
| V-T22 双路线覆盖 | **已终止** | 不再单独验证，双路线覆盖改由实际研究中的使用来检验；终止不等于覆盖验证通过 |
| TS 优化中断后接续 | **已验证** | 使用 `final_input.xyz` + 父 chk 的 `Guess=Read Opt=(TS,CalcFC)`；RCFC 不适用于没有 Freq 的中断优化。只证明已验证的 chk 可读，不保证任意中断 chk 完整 |
| 不完整取回（T47） | **已验证** | PBS 强杀、Slurm TIMEOUT 均已真实验证；取回与来源记录不代表科学成功。缺少声明输出分支仅有离线测试覆盖 |

发布 PR 不自动合并；tag 和 release 由负责人在 GitHub 页面操作。

## 支持范围与限制

- 当前科学工作范围：主族闭壳层体系，Opt+Freq、单点、构象筛选、热化学；已有人提供初猜的 TS/QST2/QST3、IRC 卡片及本地分析工具。
- 双分子步骤与复合物按 [complex 卡片](skills-next/auto-g16-recipes/cards/complex.md)执行，只开放以已审阅原子对为约束的采样；通用对接搜索不开放。
- 支持 PBS/Torque 与 Slurm 配置；适配实现与离线测试不等于任意站点的真实环境验收。
- 不支持金属体系、开壳层、激发态、多参考等专门方法的可靠研究流程；不把可传入的程序参数解释为科学支持承诺。
- 不提供全自动 TS 搜索、无人值守研究、自动重提、多用户服务或旧 v3 数据库/工作流兼容迁移。
- `prepare --parent-chk` 支持同 study、同集群内受限复用父 checkpoint：父作业必须结束且已离开调度器，复制到新 Attempt 时校验确认过的哈希、不覆盖。RCFC/ReadFC 按父 `final_input.xyz` 的 Input 坐标框架校验（父 route 含 NoSymm 时允许匹配任一已导出取向）；对齐 RMSD 或 chk 哈希相同不等于取向匹配。
- 构象数量上限、成功日志和布居都不能证明采样完备；研究方法按文献与体系审阅选择。

### 已知限制

- study 内保存的卡片副本若含指向仓库文档的相对链接，生成证据清单时会因越出 study 被拒绝；签字前需将这些链接改为仓库 URL 或删除链接。
- `fetch --incomplete` 的“缺少声明输出”分支目前只有离线测试覆盖；两次真实取回的声明输出均存在。

- PBS 节点显示的数组作业号仍可能无法解析并使监控采样失败；提交不再读取节点，不受此显示限制影响。提交仍须从 `qstat` 可靠统计全部本人作业；不能解析队列时拒绝提交。逗号组合槽位范围已支持（#243）。
- 分子很大时，少数极性氢的局部变化会被整体 RMSD 平均稀释，灵敏度下降；仍需结合相关二面角、氢键模式和结构审阅，不能仅凭去重报告证明等价。
- IRC StepSize 的单位须按本机 Gaussian 手册和实际输出核实，记录实际打印的步长及坐标类型，不把不同版本中的单位描述通用化。
- `profile` 要求极小点与 TS 交替的离散路径，不能表达无势垒步骤；不得虚构 TS 来凑齐曲线。

## 开发检查与版本历史

```bash
python -m pytest ag/tests skills-next -q -rs
# 仅暂存本任务文件后：
python ag/tools/scan_sensitive.py --staged
```

开发前阅读 [DEVELOPING.md](docs/DEVELOPING.md) 和 [LESSONS.md](docs/LESSONS.md)。
离线测试不连接真实集群。开发范围以任务单或负责人明确任务指令为准，PR 首行写 `Task: Tn`；实际阻塞注明结构、提交、解析、科学审阅或环境类别。合并由人完成。

- **v2.7、v3**：已归档于 [archive/](archive/README.md)，原始 v3 基线为 `v3-frozen`。旧 [CHANGELOG](archive/CHANGELOG.md) 保持原样。
- **v4.0 → v4.1.0**：ag + Skills 文件状态架构与后续解析、分析工具、卡片和不完整取回更新，详见 [CHANGELOG.md](CHANGELOG.md)。[REDESIGN-PLAN](docs/REDESIGN-PLAN.md) 作为设计记录保留。
- **v4.2.0**：更新提交额度与 SSH 日志、取回后自动 facts、CREST/xTB 线程设置、证据引用解析、ensemble 和研究准备文档；升级前检查本机资源配置，详见 [CHANGELOG.md](CHANGELOG.md#v420)。

许可：[MIT](LICENSE)。
