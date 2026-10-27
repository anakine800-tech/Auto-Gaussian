# Auto-Gaussian v4.6.2

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
- `submit` 必须核对一次性聊天批准记录、明确指定的本机长期规则，或由人在 Mac 系统对话框亲手确认；`cancel` 始终须人点击。显式授权核对失败不回退弹框，不提供跳过核对的入口。
- 确认摘要、实际提交字节和上传后的远程哈希必须一致。
- 取消只针对绑定记录中的确切作业号与所属集群；历史 PBS Attempt 使用原有状态记录。
- 只执行审阅过的模板和白名单参数；拒绝任意远程命令、符号链接及根目录之外的路径。
- 按集群统计该用户全部作业，包含非 ag 作业。PBS 和 Slurm 单作业均受 `max_cores` 限制，运行加排队（含挂起）计入 `max_committed_cores`。同一 scheduler、规范化 SSH 配置文件和 host 别名的入口共享最小总上限；Slurm 另计全组未观测预留。ag 不限制运行中的核数；核时预算不再拦截提交。
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
| `clusters.<CLUSTER>.resources` | 本入口单作业上限、总上限、可选排队上限及档位；budget_core_hours 仅兼容读取 |
| `clusters.<CLUSTER>.allowed_templates` | 可选模板名列表；省略允许全部，空列表不允许 prepare；不追溯已有 Attempt |
| `clusters.<CLUSTER>.programs` | Gaussian、xTB/CREST 安装位置、可选 Gaussian 模块与 Multiwfn |
| `clusters.<CLUSTER>.queue` | PBS 队列占位值 |
| `clusters.<CLUSTER>.partition/account/qos/expires` | Slurm 可选设置与到期日期 |

入口的 `[clusters.<CLUSTER>.ssh]` 可配置 `connect_timeout_seconds`：整数 **15–60**，默认 **15**；
旧单集群配置写在 `[ssh]`，布尔值、字符串和小数均拒绝。经转发等建立连接较慢的链路可设为 **40**，
每个入口独立生效，覆盖该入口所有 SSH/scp 操作，不影响共享核数上限分组。
命令总超时、上传超时和下载无进展阈值均自动顺延 `connect_timeout_seconds − 15` 秒：
设为 40 时，60 秒变为 85 秒、提交的 120 秒变为 145 秒、存储查询的 30 秒变为 55 秒。
省略或设为 15 时参数与超时不变；下载 24 小时硬上限、只读连接失败后等待 15 秒重试一次的规则、
写操作不重试及提交/取消确认流程保持不变。此字段只在入口配置中设置，没有全局开关或环境变量。

`prepare --cluster '<CLUSTER>'` 固定 Attempt 所属集群；后续操作遵循该绑定，不能靠切换当前配置把作业送往别处。
`cluster` 子命令是**构象聚类**，并非集群切换命令。

同组入口的 partition/account/qos 不影响分组；远程本人作业只计一次，各入口台账分别保留与结算。
确认前、确认后都核对全组核数，UNKNOWN 与尚未被 squeue 显示的本地预留仍计入；组内台账损坏、读不出，或缺失但有提交痕迹时拒绝。
只有台账不存在且全部本地 studies 中该入口没有声明、提交绑定或提交状态痕迹时才按空台账处理；同组其他入口只在内存中按零处理，目标入口由 reserve 创建台账，不迁移历史。不同 SSH 文件或别名不自动合并，doctor 仅按入口名提示“未合并”。
迁移 study 或切换配置目录必须同时带上各 Slurm 入口的台账。已有提交痕迹但缺账时，从备份或原配置目录找回该入口的台账；找不到则停止并交给负责人核对，不自动重建或归零。
同组上限不一致时摘要列出各入口数值并采用最小值，单作业仍按目标入口的 max_cores 检查。

新 Attempt 准备前运行 `ag route --template gaussian --tier general --study <study>`，按建议显式选择 `--cluster`；偏离建议时在 study.md 记明原因。
建议顺序由本机可选 `[routing]` 配置：Gaussian（含 gaussian-cp、multiwfn）为 `default → newhpc → scnet`，CREST（含 xTB）为 `scnet-test → default → newhpc`。
仅列已配置的入口，名字不能重复；`[routing.studies."<study>"]` 可按研究覆盖某一程序族的顺序，未签字允许的入口应从该研究顺序中去掉。
`allowed_templates` 仍逐入口生效，例如 scnet-test 只允许 CREST 时，xTB 虽使用相同顺序也会跳过该入口。
没有配置对应程序族顺序时仍列出所有入口状态，并显示“未配置路由顺序”；空顺序不建议任何入口。
`ag route --template crest --tier mini --json` 输出相同的结论、原因、快照时间、本人上限是否允许及建议，便于 Skills 和前端读取。

路由命令只读本机 `.ag-monitor/<入口>/latest.json`，不创建目录、不写文件、不运行 SSH 或调度器命令；旧单集群读取 `.ag-monitor/latest.json`，两种 default 来源并存时按未知处理。
快照须成功且在采样间隔的三倍以内；失败、过期、缺字段、核数未知均为“没地方”。单次采样没有间隔，不能用于路由建议；请使用常驻监控快照。
本人占用取同一配置共享组最新的一份有效快照，不跨入口相加；总上限及可选排队/运行限额取组内最小值，单作业上限按目标入口检查。
PBS 需要一个 free 节点同时容纳所选档位，Slurm 按分区空闲核数与内存判断；内存显式未知时只按核数判断并标注“内存未知”，有他人排队则不判为可立即运行。
依次选择“可以马上运行”的入口；都不行时选择顺序中第一个本人上限允许的入口，并标“需要排队”；本人占用未知时不猜测上限允许。
建议只是快照时刻的判断，不能保证调度器立即启动，也不包含未被快照观察到的变化；提交时原有额度、预留和批准检查照常执行。
prepare 的文本摘要在所选入口不同于建议时追加一行提示；缺可读快照或无顺序时静默，JSON 和 manifest 不加路由字段，已有 Attempt 不迁移。
核时摘要只显示本次最大消耗（核数 × walltime；实际以平台计费为准）；budget_core_hours 可删除，doctor 会提示。
旧单集群 [config.example.toml](ag/config.example.toml) 仍支持为 `default` PBS 配置。
`ag clusters --json` 只读列出本机配置的集群及资源档位；它不连接服务器，程序启用标记不等于远程安装验证。

资源示例：`mini` 4 核/10 GB、`simple` 8 核/12 GB、`general` 22 核/50 GB、`complex` 44 核/120 GB，均按实际配置调整。

前四档仍必需；每个入口可另外配置 `resources.tiers.max` 和/或 `resources.tiers.ultra`，
使用相同的整数 `cores` / `mem_gb` 字段和资源限制。只识别固定六名，
入口列表与监控按 `mini → simple → general → complex → max → ultra` 顺序输出实际配置项，
没有的档位不补空值，既有未知元数据不透传。prepare 拒绝该入口未配置的档位；
route 对缺档入口显示“不支持该档位”，不把它列为立即运行或排队建议。

PBS 档位内存默认最高 **120 GB**。负责人明确授权后，可在该入口的
`[clusters.<CLUSTER>.resources]`（旧单集群为 `[resources]`）设置
`pbs_max_mem_gb`：严格整数 **120–200**，各档位 `mem_gb` 不得超过该值。
例如显式设为 200 后才允许最高 200 GB 的档位；省略时仍拒绝超过 120 GB，
不会扩大其他入口的范围。布尔值、字符串、小数及越界值拒绝；Slurm 不接受此 PBS 专用字段，
未配置该字段的 Slurm 内存行为不变。这只是本机授权上限，不证明节点容量、调度器许可或账号配额；
仍需按一个合格节点留足系统余量，Gaussian 的 85% 限制和每次提交批准规则不变。
回退至不支持该字段的版本前，须先恢复不超过 120 GB 的 PBS 档位配置；不能只保留新字段来延续授权。

PBS 与 Slurm 都可配置入口级 `resources.max_walltime`，如 `"36:00:00"`；
必须为正值 `HH:MM:SS`，小时使用 2–4 位 ASCII 数字，分秒为 00–59。
省略时没有额外 AG 入口时限，**不代表调度器无限制**。prepare 在写入新 Attempt 或远程检查之前拒绝超限；
旧 prepared 在下一次 submit 时按本次调用加载的有效配置重核，在 Transport/日志/锁/批准消费/claim 前拒绝，
确认后与 claim 前再核对；人工批准记录、长期规则和对话框均不能覆盖此上限。
配置收紧只会拒绝提交，不改 manifest、输入或脚本；确认期间不重新加载整份磁盘配置。
`ag clusters --json` 的 `resources.max_walltime` 与监控的 `own.max_walltime` 仅配置时出现，
未配置时省略；失败快照也更新当前限制，移除配置后不保留旧限额。共享排队上限机制保持不变。

PBS 和 Slurm 的 `resources.max_cores` 均由配置的正整数决定；default 必须在本机配置里明确写 `max_cores = 44`，代码不再提供 PBS 44 核硬上限。Gaussian 仅在单节点运行，单作业上限不得超过队列中最小可用节点的核数，内存档位也按该节点并为系统留余量。
`max_committed_cores` 不小于 `max_cores`，总上限由负责人按集群设定，没有四倍上限。可选 `max_queued_cores` 在确认前和确认后限制排队（含挂起、本人非 ag 作业及适用的未观测预留）加本次申请；同集群取所有已配置排队上限的最小值，未配置的入口也不能绕过。
可选 `scheduler_max_running_cores` 仅记录同时运行上限：**由调度器执行，ag 未核实**，不是 ag 的运行限流。确认框显示单作业上限、排队/排队上限和运行加排队/总上限；未设排队上限时保持原提交行为。

仅有 Gaussian 安装的入口须显式设置 `allowed_templates = ["gaussian"]`；也可只列 `gaussian-cp` 或同时列这两个 Gaussian 家族模板。此时可省略整个 `programs.xtb` 表，`doctor` 仅检查 Gaussian，静态入口列表将 xTB/CREST 标为未配置。`programs.gaussian.g16root` 仍必须填写直接包含 `g16` 的真实绝对目录；不填空串、占位路径或假软件。省略 `allowed_templates`、空白名单或包含其他模板时仍须提供原有完整程序配置；独立 CREST 路径仍要求 xTB 配置。已有完整配置的程序检查和脚本字节保持不变，`prepare` 在创建 Attempt 前拒绝白名单外模板。静态配置通过不替代远程 `doctor` 或实际运行验收。

CREST 可选 `programs.crest.executable`（多集群为 `clusters.<CLUSTER>.programs.crest.executable`），用于与 xTB 分开安装的情况。设定后配置校验、doctor 和脚本使用同一个绝对路径，prepare 在创建 Attempt 前执行一次只读可执行检查，失败（含 SSH 错误）立即拒绝、不重试、不回退到旧位置；省略时继续从 xTB 根目录的 `bin/crest` 定位，旧 PBS/Slurm 渲染字节保持不变。
配置独立 CREST 路径后，`ag prepare --template crest` 需要连接目标集群；SSH 不可用时无法 prepare，也不会创建 Attempt。这是准备前核实可执行文件的取舍；未配置独立路径时，prepare 仍保持纯本地行为。

Gaussian `%nprocshared` 必须等于档位核数，`%mem` 不超过档位内存的 85%。
Gaussian（包括 `gaussian-cp`）输入可省略 `%mem`：prepare 在 `%nprocshared` 后填入
`min(核数 × 2, floor(档位内存 × 0.85))` 整数 GB，并纳入输入哈希、在确认摘要注明。
显式填写的 `%mem` 保持原字节并继续检查 85% 上限；旧 Attempt 不重写。
确认摘要附本机已完成且有 facts 的资源参考：模板、规范化方法/基组相同，原子数 ±20%，
按原子数接近程度最多列 5 条。耗时只取开始/退出回执，缺失写“未知”；没有匹配写“无参考”，不会自动选档位或 walltime。
SSH 准备说明见 [ag/README.md](ag/README.md)；配置后按需运行 `ag doctor --cluster '<CLUSTER>' --json` 做只读自检。

Multiwfn 为可选程序：只有使用 `multiwfn` 模板时才需配置 `programs.multiwfn`；多集群配置对应 `clusters.default.programs.multiwfn`。值使用仓库外安装记录中的可执行文件位置，不在仓库保存机器路径。目前只支持 `default`（PBS）集群，提供 IGM / IGMH 与本地 `ag nci-report`（`ag-nci/1`）；配置及使用边界见 [Multiwfn 说明](ag/README.md#multiwfn-非共价相互作用分析)。未使用该模板时无需增加配置。

## 命令一览

尖括号表示需替换的占位符。`<STUDY_ID>` 是配置的 studies 根目录下的直接子目录名；
`<STUDY_DIR>` 是完整本地目录。各命令支持 `--json`，完整参数以 `ag <命令> --help` 为准。

| 命令 | 用途 |
| --- | --- |
| `ag init '<STUDY_ID>'` | 创建 study 骨架 |
| `ag prepare --study '<STUDY_ID>' ...` | 本地建立独立 Attempt、校验输入并显示确认摘要；三种模板均须显式填写非空 `--method-basis`；`--card` 保存卡片来源 |
| `ag approve --study <S> --attempt <ID> --quote "<逐字原话>"` | 纯本地创建最长 24 小时、一次性批准；批次重复 `--attempt` |
| `ag submit '<ATTEMPT_ID>' ... [--approval <批准ID> / --policy <规则名>]` | 核对显式批准/规则后提交；省略时人点击 Mac 确认；支持批次 |
| `ag status '<ATTEMPT_ID>' --json` | 只读查询远程证据并更新本地状态；也可 `--study` |
| `ag fetch '<ATTEMPT_ID>' [--add-missing \| --incomplete]` | 首次取回、为 fetched 补取，或有结束证据时显式取回不完整输出；拒绝覆盖 |
| `ag cancel '<ATTEMPT_ID>'` | 人点击 Mac 确认后取消确切作业 |
| `ag list --study '<STUDY_ID>' --json` | 列出本地 Attempt |
| `ag doctor --cluster '<CLUSTER>' --json` | 只读检查连接、调度器和程序环境 |
| `ag monitor --watch 30` | 前台只读采样并保存监控快照；PBS 每 30 秒、Slurm 至少 60 秒，Ctrl-C 退出 |
| `ag facts '<ATTEMPT_ID>' --study '<STUDY_ID>' [--refresh] --json` | 解析日志、几何、频率、扫描、IRC 和波函数稳定性事实；显式刷新保留旧证据 |
| `ag thermo '<ATTEMPT_A>' '<ATTEMPT_B>' --study '<STUDY_ID>' --json` | GoodVibes qRRHO 与所选构象集合的布居 |
| `ag dedup '<XYZ_FILE>' --charge 0 --out '<ANALYSES_DIR>' --json` | 按已确认电荷去重；此例为中性体系 |
| `ag cluster '<DEDUP_JSON>' --max 20 --json` | 从去重结果选择代表构象 |
| `ag graph --study '<STUDY_DIR>' --json` | 展示 Attempt 父子关系 |
| `ag catalog show '<STUDY_DIR>' --json` / `ag catalog suggest '<STUDY_DIR>'` | 只读查看对象与当前采用结果，或打印 parents 分组建议；登记命令和前端字段见 [ag-catalog/1](docs/ag-catalog-1.md) |
| `ag irc-compare --ts '<TS>' --forward '<FORWARD>' --reverse '<REVERSE>' --reactant '<REACTANT>' --product '<PRODUCT>' --out '<NEW_REPORT_JSON>' --json` | 双向 IRC 端点与参考结构的映射比较 |
| `ag topology '<ATTEMPT_ID>' --study '<STUDY_ID>' --out '<NEW_REPORT_JSON>' --json` | 比较提交与最终结构，报告成键、质子及立体差异；TS 用 `--pair i-j` 仅报告距离，同时生成 Markdown 摘要 |
| `ag fragments '<ATTEMPT_OR_XYZ>' --study '<STUDY_DIR>' --out 'analyses/<NEW_REPORT>.json' --json` | 按共价半径识别片段，报告编号映射、分子式和跨片段不确定接触，独占导出 JSON、Markdown 与各片段 XYZ；单片段仅报告，电荷与多重度由人确认 |
| `ag mode-review '<ATTEMPT>' --study '<STUDY_DIR>' --pair 1-2 --mode 1 --amplitude 0.3 --out analyses/mode-review.json --json` | 导出正常频率段的正负位移 XYZ、目标对距离变化与全对排名；编号从 1 开始，振幅为最大原子位移 Å，输出必须新建，方向由人判断 |
| `ag profile '<PROFILE_JSON>' --json` | 组装已审阅物种的自由能曲线、焓熵分项、Eyring 换算、按产物汇总的选择性、σ 报告及适用时的能量跨度 |
| `ag review init '<ATTEMPT_ID>' [--card '<CARD>']` / `ag review check '<ATTEMPT_ID>'` | 创建审阅骨架、核对判据及事实快照；旧 manifest 可在审阅时补指定卡片 |
| `ag review manifest --study '<STUDY_DIR>' --json` | 签字前生成不可覆盖的本地证据清单 |
| `ag clusters --json` | 本地集群和资源档位查询，不返回连接凭据或核时预算 |
| `ag coverage --merged '<DEDUP_JSON>' --energies '<ENERGY_JSON>' --out '<NEW_REPORT_JSON>' --json` | 按匹配的 DFT 能量统计采样路线重叠与低能覆盖 |
| `ag scan-peak '<ATTEMPT_ID>' --study '<STUDY_ID>' --point 9 --out '<NEW_GUESS_XYZ>' --json` | 按原扫描点序号选择严格局部极大，导出 TS 初猜 |

作业命令退出码：0 成功，1 取消或校验失败，2 环境/连接错误，3 状态不确定。
`unknown`、`failed_presubmit` 或计算失败不构成重提同一 Attempt 的理由。

## 新增命令用法与证据维护

`ag catalog object/member/adopt/retire/report-kind <study>` 在独立 catalog 日志登记对象、归属、采用和报告类别，
支持 `--dry-run`，不改已有研究证据。`adopt --quote` 只能逐字引用负责人在本 study 当前对话的原话；
已签结论也要按 study 逐个授权补登记。采用状态不替代科学签字。格式与示例见 [ag-catalog/1](docs/ag-catalog-1.md)。

`catalog object --formula/--charge` 登记三态期望值；`object-suggest` 只打印 manifest 来源建议。
`channel`、`candidate`、`candidate-result` 追加通道、候选几何来源和每次尝试结果，`ledger` 只读查询完整台账；
候选 XYZ 按哈希只读存档，`channel-status` 与 `coverage` 记录负责人原话声明，登记不替代科学验收。
首次写扩展事件须 `--upgrade-catalog`，`--dry-run` 预览不创建文件；原 /1 日志字节保留，纯旧事件仍生成 state/1。
升级后旧 ag 和 v4.5.x 前端不能读取该 catalog；T131/T132 合并并在两台部署前不升级真实研究 study。
命令、兼容性和前端字段见 [ag-catalog/2](docs/ag-catalog-2.md)。

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

# 先读逐点路径诊断；除 B 扫描原子对外，预期成断键须逐对声明
ag scan-path '<SCAN_ATTEMPT>' --study '<STUDY_ID>' \
  --expect-bond 1-3 --expect-bond 2-3 --dihedral-threshold 60 \
  --contact-cutoff 3.5 --hbond-cutoff 2.5 --json
# 9 是原始扫描点序号示例，必须是列出的合格局部极大
ag scan-peak '<SCAN_ATTEMPT>' --study '<STUDY_ID>' \
  --point 9 --out '<NEW_TS_GUESS_XYZ>' --json
# 同时生成 TS 输入正文；route 的方法和选项由人或卡片给出
ag scan-peak '<SCAN_ATTEMPT>' --study '<STUDY_ID>' \
  --out '<NEW_TS_GUESS_XYZ>' --gaussian-ts '<NEW_TS_GUESS_GJF>' \
  --route '# <METHOD>/<BASIS> Opt=(TS,CalcFC) Freq' --json
ag profile '<STUDY_DIR>/analyses/<PROFILE_JSON>' --name '<NEW_PROFILE_NAME>' --json
```

- `review init` 不覆盖已有审阅；`--card` 的补指定来源明确记在 review 中，不修改 manifest。`review check` 核对已保存的判据与事实，不代签。签字前先在 study/review 中引用全部依据，再生成 `review manifest`；清单独占创建在 `analyses/`，记录相对路径、大小、SHA-256 与 ag 提交号。签字记录应包含清单路径和清单哈希，生成清单本身不是签字。
- `facts` 在解析内容相同时保持原字节和 mtime，即使解析器提交号变化也不重写；内容不同时默认显示差异并拒绝。人工核对后用 `--refresh`，先保留 `facts.<旧哈希前12位>.json` 再发布新版；已有几何仍不能覆盖。thermo/profile/review check 不改写 facts。
- `fetch --add-missing` 只适用于 fetched：先核对全部声明远程输出与本地已有文件的大小/哈希，不一致就拒绝；只独占写入缺失项，另存补取记录，原 status、manifest 和 fetch journal 保留。补取成功不表示解析或科学审阅完成。
- `fetch --incomplete`：PBS 必须为 interrupted，并有至少相隔 300 秒、输出大小/mtime 相同、均不活跃且无退出回执的两次 status 观察；Slurm 必须为 finished，取回时重新确认 squeue 无此作业、sacct 有受支持终态。COMPLETED 且输出齐全用普通 fetch。
- 不完整取回只下载声明中确认存在且可读的输出，逐文件前后核对大小/SHA-256，确认缺失项写入独占的 `fetch-incomplete-<UTC时间>.json`；权限或连接等无法核实就整次失败，暂存证据留在 `.partial`。状态不变，重复取回、普通 fetch 和 `--add-missing` 均拒绝已有不完整取回记录。
- 不完整 facts 不是正常终止，不能用于 thermo/profile；有绑定完整取回记录的 interrupted 父作业可声明 parent chk，复制检查及提交授权核对不变。chk 是否被 Gaussian 读入需另行验证。
- `dedup --hydrogens heavy|polar|all` 默认 `polar`（重原子加 N/O/S/P 上的氢）；反应相关氢若不属该集合，使用 `all`。旧无氢模式记录按 heavy 解释。仅几何来源合并不混排能量；`--representative lowest` 要求同方法、有限 Hartree 能量，并应用能差容差（默认严格小于 0.05 kcal/mol）。ETKDG 候选先经 CREST `--mdopt` 优化后才能与同层级 CREST 能量合并，不能混用力场能量。
- dedup / cluster 的 RMSD 映射只看元素与连接关系并保持立体中心构型，不受芳香键的 Kekulé 写法限制；连接 / 立体改变的排除规则不变。每对最多枚举 10,000 个映射，超限报错并提示 `--hydrogens heavy`，不截断；改氢模式前仍须审阅相关氢是否重要。dedup 重复记录的 `mapping` 为 `identity`（原编号）或 `symmetry`（等价置换），`rmsd` 为实际采用值。
- dedup 顶层 `algorithm` 说明按能量升序、同能按输入顺序、归入第一个满足条件的已保留代表，结果依赖顺序；能量不可比的 `--source` 模式按输入顺序。`boundary_pairs` 列出代表间 RMSD < 2 倍阈值的配对，以及已并入项 RMSD > 阈值一半的归属配对，附映射与绝对能差（不可比时为 null），只供复核。
- `dedup --mirror off|report` 默认 off；report 在已保留代表间报告 `mirror_pairs`（镜像 RMSD < 阈值），含普通 / 镜像 RMSD 及各自映射，不合并、不改变简并度。手性体系附说明，仍排除 `stereo_changed` 帧；非手性镜像简并继续使用 `ag cluster --mirror`，该命令仍拒绝有已指定手性中心的体系。新版本不自动重跑已有 study。
- `coverage` 的 `--energies` 可给单点 Attempt 目录/ID、JSON 路径列表或原生 thermo JSON；按坐标和来源证据匹配，SCF 与 qh_G 分开统计。单路线独有低能项会提示补采样；报告不是构象穷尽证明。
- `scan-peak` 仅接受内部点及左右紧邻点均收敛、有能量，且中点严格高于两侧的候选；列出全部局部峰，默认选最高局部峰，`--point` 选择指定原序号。无合格峰、指定非候选、单调曲线或平台都不导出；仍须审阅扫描范围与跳变，并继续 TS/Freq/双向 IRC。
- `scan-path` 只读现存 `facts.json` / `scan_points.xyz` 并核对几何哈希，输出点表、相邻段表和全程摘要；仅支持一维，二维非零退出。未收敛或缺几何点的两侧为 unknown，不跨点比较。JSON 包含 `points`、`segments`、`expected_bonds`（automatic/declared）、`thresholds`、`notes`、`summary`；段列出成键变化、不确定原子对、二面角/接触变化、能差、RMSD 和 `unknown_reason`。flagged/unknown 数量及点对位置在 summary 中。
- 一维 `scan-peak` 自动使用同一诊断；`path_diagnostics` 包含全程摘要及峰前后各两点之间最多四段。附近有 flagged 段时在文本最前方及 `warnings` 中给出中英文污染警告和点对，照常选峰、导出和生成草稿；二维行为不变，不附路径诊断。`--register-candidate` 把摘要和附近段写入 `transform.path_diagnostics`；整个 transform 按 64 KiB 控制，超限标“已截断”并保留原计数和警告，完整明细可重跑 `scan-path` 查看。
- 两命令均支持可重复的 `--expect-bond i-j`（从 1 开始，原子编号不重排）。B 扫描的原子对自动豁免成断键；例如协同质子转移须显式声明断键和成键两对。豁免不屏蔽接触、二面角或原有能差/RMSD 提示。三态成键中的 uncertain 原子对单列，既不算变化也不算一致。
- `--dihedral-threshold` 默认 60°：比较第一个点中非环、重原子单键且两端各有其他重原子邻居的二面角；每键取编号最小的重原子邻居，按最小周期角差比较，D 扫描的中心键不计。缺 manifest 电荷、推键失败或退化二面角记未知，不猜键级。
- `--contact-cutoff` 默认 3.5 Å：重原子非成键接触；`--hbond-cutoff` 默认 2.5 Å：与 N/O/F 成键的 H 到其他 N/O/F 的距离接触（无角度条件，不判定真实氢键）。仅列距离跨截断的出现/消失，任一侧已成键的原子对排除；保留原相邻绝对能差 >20 kcal/mol、全原子对齐 RMSD >0.5 Å 提示。**所有阈值只决定是否列出，不是科学判据或拒绝条件。沿程点多为受约束的非驻点；成键差异只说明几何变化，不说明极小点身份。** clean 只表示未列出变化；flagged 仍可带未知部分，须查看 `unknown_reason`，不能据此断言路径连续或 TS 已验证。
- `scan-peak --gaussian-ts <新 .gjf> --route '<route>' [--title '<标题>']` 同时独占输出 XYZ 和 Gaussian TS 输入正文，不覆盖文件。电荷与多重度取扫描 Attempt 的 manifest（xTB 的 `--uhf` 转为多重度时加 1），缺失或电子数奇偶不相容就拒绝，不默认 0/1。默认标题仅含扫描 Attempt 和点号；正文保留原子顺序，坐标与导出 XYZ 相同，末尾有空行。二维仍须 `--point i,j`。
- TS route 必须含 `Opt=TS` 或 `Opt=(TS,...)`，大小写、空格及 `Opt(...)` 写法均支持。扫描/冻结拒绝清单为 `ModRedundant`、`ModRedun`、`ModRed`、`AddRedundant`、`AddRedun`、`AddRed`、`Scan`、`ReadOptimize`、`ReadOpt`、`RdOpt`、`ReadFreeze`、`RdFreeze`、`Freeze`、`FreezeAll`、`AddGIC`、`ReadGIC`、`ReadAllGIC`；`RCFC`、`ReadFC`、`ReadCartesianFC` 必须另走 `prepare --parent-chk` 的父 chk 流程。通用 Gaussian 校验仍适用（包括拒绝 `Geom=Check/AllCheck`、External、Link1）。工具不判断方法、基组、CalcFC 或 NoEigenTest，不自动 prepare、不提交，也不把峰当作已验证 TS。
- 草稿不含 Link0。当前 `prepare` 要求输入已有匹配档位的 `%nprocshared`，仅自动补缺少的 `%mem`，且没有 `--dry-run`。审阅正文后按现有规则补齐所需 Link0 再 prepare；正文校验使用仅在内存中的临时资源行，不写入草稿，也不代表实际资源已选择。
- 默认不读写 catalog。显式加 `--register-candidate --object <已有对象> --candidate-id <新 ID> [--target-channel <已有通道>]`，才登记同一 XYZ 字节为 `origin=scan`，保存父 Attempt、点号、坐标值、能量、邻点、扫描文件哈希、选择方式和警告；二维的 `coordinate_value` 为两维值列表。`--json` 的 `gaussian_ts` 返回路径、route、电荷、多重度、标题和 SHA-256，`candidate` 返回 T131 的事件摘要。catalog /1 升 /2 须另加 `--upgrade-catalog`；`--dry-run` 仅预览登记、不写 catalog，XYZ 和 `.gjf` 仍会独占写出。登记失败返回非零、说明原因并保留导出文件，不重试；需要后续登记时复用文件走 `ag catalog candidate`。来源登记不作科学签字，T131 的原话规则不变。**T132 部署前，真实研究 study 禁用此登记选项。**
- `profile` 输入定义放在 study 的 `analyses/`，引用已审阅物种及可比的热化学来源；输出到新的名称，不覆盖。`--perturb 1` 可逐个 TS 状态做 ±1 kcal/mol 扰动分析。新增焓熵分项、分子数、正反 Eyring 速率/半衰期和 σ 来源/警告；可选 `selectivity: [{"id": "products", "products": {"R": [{"species": "ts_r1"}, {"species": "ts_r2", "paths": 2}], "S": [{"species": "ts_s"}]}, "perturb_kcal": 1.0}]` 按产物汇总同组成同电荷 TS，输出产物比例、有效能垒、两两比例及最低构象对照。两产物给有符号 ee（首标签占优为正），多产物给分布/dr；可选扰动逐 TS 物种报告比例区间和翻转。paths 与构象简并度分开，省略标为默认 1。换算均为 κ=1 的简单 TST，缔合用标准态准一级近似，不等同于实验速率/ee。schema 保持 `ag-profile/1`，既有能量不变。SP/Freq 配对须有几何证据，热化学审计分项不能重复加到 qh_G；无势垒步骤不支持表达。
  选择性另以 `lowest_ts` 给出“最低 TS / 系综 / 差值”：每个产物分支在所有 TS species 的全部构象中取修正后自由能最低的单个结构，复用该 species 的标准态与浓度修正；保留所选通道的真实 paths，不对构象求和、不乘构象简并度（仅报告其值），并列出 species、Attempt 和修正后自由能。相差不超过 1e-9 kcal/mol 的最低候选按通道定义顺序、再按 Attempt ID 选取；`ties` 列出所有并列项，无并列时为空。每对产物的符号为 G_eff(b)−G_eff(a)，系综数值直接沿用原结果，差值为系综减最低 TS；两产物另报同符号约定的单结构 ee。原 `lowest_conformer` 仍对每个 TS species 各取最低构象后汇总多个通道及 paths，字段与数值不变。单结构结果和系综结果不是同一个物理量，差值大说明结论对构象采样敏感，不代表哪个更正确。

## QST2 端点映射与输入草稿

`ag qst-endpoints` 只接受同一 study 的两个精确 Attempt ID：状态为 `fetched`、
facts 可读且 `opt_converged=true`。已知 `n_imag` 必须为零，未知时报告警告；
电荷、多重度从 manifest 读取，缺失或两端不一致即拒绝。优先读取 `final_input.xyz`，
否则读取 `final.xyz`，报告所用文件及 SHA-256；不接受任意 XYZ 端点。

```sh
ag qst-endpoints '<STUDY_DIR>' --reactant '<REACTANT_ATTEMPT>' \
  --product '<PRODUCT_ATTEMPT>' --mapping '<MAPPING_JSON>' \
  --route '# <METHOD/BASIS> Opt=(QST2,CalcFC)' --out '<NEW_QST2_GJF>' --json
```

映射文件示例为 `{"product_to_reactant": [[1, 3], [2, 1], [3, 2]]}`：
每一对是“产物原编号、反应物原编号”，均从 1 开始，必须完整、一一对应、元素相同。
工具不推断原子映射，只按人工映射重排产物，再通过 Kabsch 正规旋转和平移对齐；
不镜像，不改变反应物坐标。默认全部原子等权参与，可用 `--align-atoms 1-3,5`
指定反应物编号子集。报告子集 RMSD、该次对齐的全原子 RMSD、位移最大的十个原子，单位 Å。

分别在两端分子图上复用 `rms_atom_maps` 的元素、连接和四面体手性规则枚举自同构，
对每个非恒等排列使用同一对齐子集重算 RMSD。若比人工映射低超过 0.01 Å，报错且不写草稿，
列出端点、原子对和 RMSD；原子对表示重排后反应物编号空间中的有向置换，可能含多原子循环。
人可修改映射，或明确使用 `--keep-mapping --reason '<保留理由>'`；理由及跳过的更优排列
进入报告和可选登记。**0.01 Å 仅为报告比较容差，不是科学判据**；任何绝对 RMSD 都不自动判定路径适用性。
报告分别列出两端已检查的非恒等映射数。单端超过 `RMS_MAX_MAPPINGS=10000` 即拒绝，不截断；
需人重新审阅并缩小问题范围，`--align-atoms` 不会减少全图枚举数。图推断失败或按既有半径规则
存在不确定连接时拒绝，工具不猜成键关系。

正文复用 `gaussian_input.render_input()`，反应物在前、产物在后；默认标题分别为
`QST2 reactant <Attempt>`、`QST2 product <Attempt>`，可用 `--title-reactant`、`--title-product`
覆盖。route 必须包含 QST2 优化且不含 QST3；扫描、冻结及 RCFC/ReadFC/ReadCartesianFC
检查复用 scan-peak 的 TS 草稿规则。输出通过现有 Gaussian 校验、末尾有空行、不写 Link0、不覆盖。
审阅后按资源档位补 `%nprocshared` 等 Link0，再走现有 prepare；工具不自动 prepare 或提交。
**新取向不能用于读取旧 chk 的 Cartesian 力常数**；相关复用必须另走 `prepare --parent-chk`
的来源和取向核对，不能以对齐 RMSD 代替。

默认不访问或创建 catalog。可加 `--register-candidate --object '<OBJECT>' --candidate-id '<ID>'`
及可选 `--target-channel '<CHANNEL>'` 登记 `origin=qst`：候选 XYZ 是重排并对齐的产物，
父 Attempt 为反应物，transform 保存两端来源哈希、映射哈希、对齐集合/RMSD及保留映射理由。
沿用 T131 登记、存档和升级规则，需要升级时须显式 `--upgrade-catalog`；失败保留已生成草稿并返回非零。
`--dry-run` 仍写新草稿，但只预览登记，不写 catalog。**T132 部署前，真实研究 study 不使用登记参数。**

## G0 本地候选诊断

`ag g0 '<STUDY>' --object '<OBJECT>' --candidate '<CANDIDATE>' --json`
读取并复核 catalog 存档，按所属对象检查组成、电荷、多重度与参考元素顺序；只把完整性不符和
极端几何损坏记为 rejected。`--all` 或 `--channel '<CHANNEL>'` 支持批量分组排序。
人设距离窗口通过 `--windows analyses/windows.json` 或可重复 `--window 1-5:1.8:2.6` 输入；
普通冲突、超窗、立体不符和未核对项只作标记，不改 prepare/submit。
适用窗口或 distance 反应坐标声明的原子对单列为反应中心，不标普通冲突，但仍检查适用窗口和几何损坏。
窗口文件只读一次，顶层允许 `channels`、`all`、`reaction_coordinates`，其他未知键报错。
三个几何数固定为 0.5 Å、0.5 倍共价半径和、0.75 倍范德华半径和。

单候选可加 `--modes-attempt '<FREQ_ATTEMPT>'`，读取已取回的 Gaussian 频率；批量取最新一条
attempt 非空的 candidate-result 关联的 Attempt，跳过诊断等空来源结果；无可用频率时记“无模式数据”。反应坐标来自同一窗口文件的
`reaction_coordinates[目标通道]`，或可重复 `--reaction-coordinate distance:3-7:forming`。
按 Wilson B 行逐坐标投影，报告全部虚频、最低三个实频参考及最佳虚频；模式标记只影响分组与排序，
不拒绝候选。距离/角度零容差分别为 1e-3 Å / 1e-3 rad，不设重叠度阈值。

默认只报告、不写文件、不跑计算。可选 `--record [--upgrade-catalog] [--dry-run]` 追加 diagnosed
候选结果；**T140 部署之前，真实研究 study 不使用 `--record`。**
G0 是本地诊断，不是门禁；不替代 DFT 验收；clean 只表示未发现问题。
顺序只是建议，提交与否由负责人决定。报告字段、立体来源校验、窗口格式、排序及截断规则见
[G0 使用说明](docs/g0.md)。

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

4. 负责人在本 study 当前会话明确批准后，用 `ag approve --study <S> --attempt <ID> --quote "<逐字原话>"` 保存记录，再执行 `ag submit <ID> --approval <批准ID>`；适用已设长期规则时用 `--policy <规则名>`，省略两者时仍由人亲手点击 Mac 对话框。`status → fetch → facts` 收集证据；失败时按诊断卡片提出新 Attempt，不自动重提。
5. `review init` 后由 LLM 逐项审阅收敛、虚频、结构身份等，`review check` 检查事实来源；优化后重新去重，统一方法与程序版本，再做 `thermo`，需要反应曲线时使用 `profile`。
6. 人审核最终结果并签字；`study.md` 写入结论与适用边界。续接时读取 `study.md`、`ag list` 和已有文件，不凭对话记忆重复提交。

TS 必须恰好一个虚频且振动方向与反应坐标一致；只有双向 IRC 完成、端点被识别并科学审阅后，才能声称验证。

## 前端

ag 4.6.2 配合前端 [Auto-Gaussian-Frontend](https://github.com/anakine800-tech/Auto-Gaussian-Frontend) v4.6.2 使用；两边同号发布，启动方式见其 README。T145 具名 PBS 节点能力仅对显式配置入口启用，必须明确选择节点；分组、实时复查与现场限制见 [节点说明](docs/T145-node-targeting.md)。发布候选须经审阅后按明确授权发布，部署与真实计算分别验收。
已只读核对前端 main（`e224d5a`）：结果表读取 `route`、`termination`、`energies.scf`、`energies.g`、`n_imag` 和 `frequencies_low`，这些字段未改名或删除；缺失值显示为空。
分析页将 profile 作为完整 JSON 展示，没有专用剖面字段依赖。`ag-facts/1` 和 `ag-profile/1` 保持不变，新增字段不影响读取；分段解析修正可能改变旧值，不能把字段兼容理解成重新解析后数值必然不变。
默认只读，读取本地 study、结果与保存的监控快照。`--enable-actions` 显式开启经本机 ag 执行的准备、提交、状态刷新、取回和取消；不绕过 ag 的提交授权核对或取消确认，也不直接执行远程命令。

T7e 已适配多集群（[Frontend #9](https://github.com/anakine800-tech/Auto-Gaussian-Frontend/pull/9)）：
操作模式通过 `ag clusters --json --verify-studies-root` 获取档位并核对目录，新建 Attempt 显式选择集群；
提交与取消继续遵循 Attempt 绑定。服务器页分集群读取
`<STUDIES_ROOT>/.ag-monitor/<CLUSTER>/latest.json`，同时兼容旧单集群的
`<STUDIES_ROOT>/.ag-monitor/latest.json`；两种 default 来源并存时显示歧义，不能擅自视为最新。
监控数据始终来自 ag monitor 快照，前端不启动采样器；缺失、过期或失败不当成空闲或零预算。
更新、备份、LaunchAgent 替换与回退、睡眠判断及部署观察统一见 [运维文档](docs/OPERATIONS.md)。
监控每轮重读启动时的配置文件，新增入口开始采样，移除入口停止采样并在最后快照新增
`config_removed=true` 与“配置已移除”说明。配置损坏时沿用上一轮配置，快照附 `config_warning` 和警告。
采样失败只影响该入口；连续失败 1–2 次仍用基础间隔，第 k ≥ 3 次失败后间隔为
`min(600, 基础间隔 × 2^(k−2))` 秒，成功一次清零。硬件或存储的局部失败不计入退避。
SSH 认证失败（明确的认证方法列表）或主机指纹失败会暂停该入口，其他入口继续采样。
暂停在该入口配置变化、监控重启，或明确确认修复后的手动采样成功时解除；暂停期间不反复登录。
监控传输保持只读且不立即重试。
Slurm 存储用量每小时查询一次，独立超时 30 秒；失败查询也计入这一小时。
间隔内沿用最近值；`storage_checked_at`、`storage_sampled_at`、`storage_error` 区分最近尝试、最近成功及失败。
没有成功值时 `storage_kib=null`；存储失败只更新 `storage_error`，保留最近成功值和时间，不改变本轮 `ok`。
成功/失败快照的 `own.tiers`（各档位 `cores`、`mem_gb`）与 `own.max_cores` 始终取当前有效配置。
`--watch` 接受 30–600 秒。入口可设整数 `monitor_interval_seconds = 90`（30–600）；
未配置时 PBS 使用 watch，Slurm 使用 `max(watch, 60)`。`interval_seconds` 始终是基础间隔，
`sampling.current_interval_seconds` 是退避后的间隔，`next_sample_at` 是下次自动采样时间。
`sampling` 还含状态 normal/backoff/paused、连续失败数、暂停原因、触发来源和 retry_pending。
一次性采样状态为 normal，当前间隔和下次时间为 null；`sample_duration_ms` 仍是采样耗时。
入口按到期时间串行采样，慢采样结束后紧接处理其他到期入口，不并发叠加。

`ag monitor --retry <入口> [--auth-fixed] [--json]` 只登记本地请求，由运行中的 watch 处理，
不直接连接服务器。旧单集群入口名为 default；--retry 与 --watch 互斥。
任何状态均可请求重试；认证/主机指纹暂停须在修复后显式带 `--auth-fixed`，只试一次。
同入口正在采样或已排队的请求合并，成功恢复基础间隔，普通手动失败不改连续失败数和自动时间，
认证/主机指纹失败仍暂停。JSON 返回 queued/already_queued/in_progress（退出 0）或 refused（退出 1），
原因是 monitor_not_running/auth_confirmation_required/unknown_entry；无运行监控不登记请求。
本地心跳每 30 秒更新，超过 90 秒或进程不存在即视为未运行，启动会丢弃遗留请求并在首条摘要记录。

默认 stdout 在有采样的循环仅输出一行 `ag-monitor-line/1` JSON 摘要，含本人作业数及警告数，
不含作业明细和用户名；空闲唤醒不输出。`--json` 输出完整快照（多入口使用 clusters 包装）。
本地 latest.json 仍保存完整 `ag-monitor/1`；history.jsonl 增加 sampling_state、consecutive_failures、trigger。
常驻服务直接运行 `ag monitor`，不再需要包装脚本。LaunchAgent 样例见
[local.autogaussian.monitor.plist.example](docs/ops/launchd/local.autogaussian.monitor.plist.example)；
将占位符换为本机路径，最小 PATH 的 SYSTEM_BIN_DIR/SYSTEM_SBIN_DIR 通常为 `/usr/bin` 和 `/bin`，
须包含系统 ssh。日志写入指定 LOG_DIR；部署、日志保留策略和旧包装脚本替换在 T129 处理。
PBS 的 `cluster.jobs` 列出全员非 C 作业，先本人、再运行开始时间、再排队提交时间排序，最多 500 条；
`jobs_omitted` 记录省略数，`job_summary` 始终统计截断前的作业。本人作业关联本地 Attempt。
`own.jobs` 与 `cluster.jobs` 的运行作业核数按实际分配显示，排队作业按申请显示，`cores_kind` 标明口径；
`own.cores_in_use`、`cores_running`、`cores_queued` 等额度统计仍沿用原预留口径，不能用作业显示值替代提交检查。
`mem_gb` 按 1024 进位折算 GB，`own.mem_running_gb` / `mem_queued_gb` 分别合计申请内存；任一相关作业未知则合计未知。
明确的开始时间用于计算 `elapsed_seconds`，否则退回已用 walltime，并用 `elapsed_source` 标明；
`start_time` / `qtime` 只在时区明确时输出 UTC ISO 时间。时区不明或字段缺失写 null，不猜服务器时区。
PBS 入口可配置 `scheduler_timezone = "Asia/Shanghai"` 等 IANA 时区名，必须先确认调度器实际使用的时区；
不配置时保留原行为，epoch 和带时区 ISO 的解析不使用配置时区。文本时间按固定英文月份/星期解析，支持日期空格补齐；
星期与日期不符、夏令时重复或不存在的本地时间均写 null。Slurm 入口拒绝此配置。
配置时区后，若“采样时间 − 开始时间”比已用 walltime 少超过 120 秒或多超过 3600 秒，
或开始时间晚于采样时间超过 120 秒，本入口本轮依赖配置时区的全部 `start_time` / `qtime` 置为 null（含排队作业）。
直接触发异常的开始时间即使来自 epoch / 带偏移 ISO 也置为 null；其他显式绝对时间和绝对 `qtime` 保留。
开始时间被清空的作业耗时退回 walltime（缺失则为 null），`elapsed_source` 同步；可信度处理先于排序和 500 条截断。
每入口每轮最多一条 `timezone-mismatch` 警告，不含作业名、作业号或用户名；恰好等于阈值时不触发。
快照新增 `cluster.scheduler_timezone`（配置值或 null），失败快照也显示当前有效配置；
失败时保留的作业仍属于 `last_ok_at` 对应旧样本，不能用新时区字段重新解释旧样本。
Slurm 明细仅有本人；`cluster.job_summary` 按配置分区给出运行/排队作业数和核数，并减去本分区本人作业得到他人汇总。
两次查询不一致导致负数时，他人汇总为 null。本人占用覆盖共享账号，各入口硬件及汇总只覆盖自己的分区。
`cluster.hardware` 提供 CPU 总数/分配/空闲/其他和总内存/已分配内存；PBS 节点另有内存与作业数，Slurm 不保存节点明细。
PBS 明确写 `cluster.scheduler="pbs"`。Torque 总内存取 status.physmem（不含 swap），
优先保留 PBS Pro 的 resources_available.mem；Torque 已分配内存按节点上的完整作业集合汇总申请值。
任一申请缺失/无法解析、跨节点或作业号不能精确对应时写 null，并在 hardware.notes 解释；无作业为 0.0。
仅在 Torque 内存的跨节点判断中，短名/FQDN 可在节点记录与 exec_host 的联合名称集合内唯一对应；
同短名多个域名或多个节点记录竞争时保持未知并说明歧义。精确名称匹配优先，CPU 分配、节点名及定向提交身份不变。
不使用 physmem − availmem，不按核数分摊。PBS Pro 的 resources_assigned.mem 保持原口径。
`sinfo` 异构节点内存显示为最小值加 `+` 时，总内存为 null；AllocMem 单独按节点汇总后保存。
异构内存和他人汇总不一致的说明放入 `hardware.notes` 字符串列表，不使已采到的核数失效；
`hardware.error` 记录查询或解析失败，旧缓存没有 notes 时补空列表。
未配置分区时不查询分区作业或硬件。现有 Slurm 本人查询不提供申请内存、开始/提交时间和 walltime 上限，这些字段为 null。
硬件查询/解析失败（包括完整节点名称重复，即使内容相同）只将节点列表清空、硬件数值置为 null 并写脱敏错误；
本人作业、额度及队列的独立成功结果保留，不把未知容量当作零或空闲。作业查询失败仍令 `ok=false`，保留旧数据及 `last_ok_at`，不能当作最新。
`history.jsonl` 仅追加作业/告警计数与摘要，不保存全员作业明细。配置移除时即使缓存损坏，也写合法的移除快照。
入口可配置整数 `display_order`，快照 `cluster.display_order` 缺省为 null；前端默认 PBS 在前、Slurm 在后，再按入口名排序。
入口可配置 `display_name`（1–32 个可打印字符）。监控 `cluster.display_name`、`ag clusters --json`
和 prepare/submit 确认摘要提供显示名；摘要显示“显示名（入口名）”，缺省仍用入口名。
显示名变更不改 manifest、台账文件名、作业号前缀或共享入口分组；失败快照也刷新当前显示名。
Slurm 的 `cluster.budget` 为 null，clusters 查询省略 budget；本地台账仍用于核数预留与结算，不代表平台余额。
监控所有快照（含初始/失败）均含有效共享 `committed_cap`；`core_cap` 仍为目标入口单作业上限。
同组入口增加 `own.shared_with`，over-cap 告警计入全组未观测预留；原有运行/排队字段仍表示远程观测值。
前端 T103 已独立显示总上限与单作业上限；旧快照缺少 `committed_cap` 时显示“总上限未知（旧快照）”，同组入口显示共享说明，不跨入口汇总容量。

## 验收状态

截至 2026-10-15，按负责人在 T48 任务单中提供的已验证、已签字结论更新；T47 细节见 [#266](https://github.com/anakine800-tech/Auto-Gaussian/pull/266)。以下是已完成的验证与适用边界；本次文档更新没有重新运行计算、补取输出或代签。

| 项目 | 状态 | 结果与边界 |
| --- | --- | --- |
| SCNet | **已验证** | Gaussian 16 A.03 学习版；已验证提交、状态、取回与解析链路。CREST/xTB 已验证中性和 +1 体系、ALPB 溶剂、取回及解析。平台免责条款由使用者自行评估，不据此承诺所有方法/任务已验证 |
| L1 正丁烷 | **已签字（流程验收）** | 正丁烷构象、Opt+Freq、热化学及续接流程验收；不外推为任意体系的精度保证 |
| L2 柔性主族体系 | **已签字（流程验收）** | 构象覆盖不完整；所选集合的结果不代表完整构象空间或正式研究结论 |
| L3 小体系 TS/IRC | **已签字（流程验收）** | 历史签字早于 T46；现行判据下仍缺完整连续性审阅，reverse 末点降能低于默认阈值，不能声称按 T46 双向完成。能垒只代表 B3LYP-D3(BJ) 层级 |
| V-T21 扫描 | **已完成** | ① Gaussian 026 + scan-peak 选中第 9 点，与 TS 的 RMSD 为 0.002 Å；修复前会误选第 2 点。② xTB 789 沿 C–F 严格单调下降，本次扫描范围内无复合物势阱、无能垒，scan-peak 按设计拒绝导出。③ 浅能垒气相离子–分子 SN2 不宜用 xTB 扫描找 TS 初猜；xTB 无峰不代表真实反应无能垒 |
| 某研究验证 study 双路线覆盖 | **已终止** | 不再单独验证，双路线覆盖改由实际研究中的使用来检验；终止不等于覆盖验证通过 |
| TS 优化中断后接续 | **已验证** | 使用 `final_input.xyz` + 父 chk 的 `Guess=Read Opt=(TS,CalcFC)`；RCFC 不适用于没有 Freq 的中断优化。只证明已验证的 chk 可读，不保证任意中断 chk 完整 |
| 不完整取回（T47） | **已验证** | PBS 强杀、Slurm TIMEOUT 均已真实验证；取回与来源记录不代表科学成功；T66 已验证 Slurm 缺少声明输出分支，见 [#282](https://github.com/anakine800-tech/Auto-Gaussian/pull/282) |

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

- `timezone-mismatch` 触发时按时间来源置未知并退回 walltime；walltime 本身可能滞后，时区仍须由负责人实测确认。
- 路由建议不考虑 walltime；超算公共分区几乎总有他人排队，通常被判为“没地方”，不保证实际启动。
- 父 chk 是否来自频率计算、是否含可用力常数，仍由卡片和人工审阅保证；程序的坐标框架核验不能替代该检查。
- 已有 study 的 facts 是否按 T108 重算、catalog 是否补登记，由负责人逐 study 决定；升级不自动改写已签字证据。
- `cp-report --solvent-sp` 只接受复合物的溶剂相单点，缺两个片段的 SMD 单点，溶剂相相互作用能仍为“未知”；CP 仅作诊断，不进入 thermo/profile。
- 取回按连续 60 秒无进展判断超时，另设 24 小时兜底；超时不自动重试，不支持断点续传。
- 二维扫描的前端能量面显示尚未支持；Gaussian 二维扫描与人工指定候选的 `scan-peak` 已在后端提供（T75，[#289](https://github.com/anakine800-tech/Auto-Gaussian/pull/289)）。
- 证据清单会列出缺失或越界的说明性引用，须由签字人核对后显式 `--accept-unresolved`，不能静默忽略；不需改写历史卡片副本。study 内符号链接及专用证据指针的安全检查仍保留。
- T66 已验证 Slurm 缺少声明输出的不完整取回分支；T102 允许取消证据、绑定和独立结束证据齐全的 `cancelled` Attempt 使用 `ag fetch --incomplete`。取消本身不证明作业已停止，取回成功也不等于计算成功。
- 组里集群的 PBS 有时在作业结束后仍短暂显示 R，曾观察到约 6 分钟后自行消失；ag 会把残留计入已占用核数，只会多算，不保证所有残留都会自行消失。
- T89 已支持固定编号下的共振等价识别，但枚举失败或超限保留 `unknown`；拓扑和立体化学仍须人工审阅，不能从共振等价推断电子密度。
- 升级前查看 [v4.5.0 升级须知](CHANGELOG.md#v450)：确认提交批准方式、监控 30–600 秒采样参数与重启、catalog 锁迁移、路由与 PBS IANA 时区配置、本机扫描 hook；Gaussian prepare 可自动补缺失 `%mem`。从更早版本升级仍须查看 [v4.4.0 升级须知](CHANGELOG.md#v440)：迁移须携带各 Slurm 入口台账，default 明写 `max_cores = 44`，独立 CREST 路径在 prepare 时通过 SSH 核验。较早版本升级仍须遵循 [v4.3.0 升级须知](CHANGELOG.md#v430)：facts 重新解析先预览并保留旧证据，thermo/profile 继续检查口径与频率证据。

- PBS 队列解析支持数组父/子作业，节点显示支持数组子作业槽位；其他用户的数组不会阻断本人核数统计和监控。本人有数组记录时，因无法可靠统计核数，`ag submit` 和 `ag doctor` 会明确拒绝，`ag monitor` 也会报错。已完成但仍保留在 `qstat` 中的本人数组记录（C 状态）也会导致拒绝，须等记录消失后再提交。ag 不提交或取消数组作业，命令参数仍只接受普通作业号；未知格式仍报错。逗号组合槽位范围已支持（#243）；数组行为见 T77（[#291](https://github.com/anakine800-tech/Auto-Gaussian/pull/291)）。
- 分子很大时，少数极性氢的局部变化会被整体 RMSD 平均稀释，灵敏度下降；仍需结合相关二面角、氢键模式和结构审阅，不能仅凭去重报告证明等价。
- IRC StepSize 的单位须按本机 Gaussian 手册和实际输出核实，记录实际打印的步长及坐标类型，不把不同版本中的单位描述通用化。
- `profile` 要求极小点与 TS 交替的离散路径，不能表达无势垒步骤；不得虚构 TS 来凑齐曲线。

## 开发检查与版本历史

```bash
python -m pytest ag/tests skills-next -q -rs
# 仅暂存本任务文件后：
python scripts/scan_public.py --staged
```

开发前阅读 [DEVELOPING.md](docs/DEVELOPING.md) 和 [LESSONS.md](docs/LESSONS.md)。
离线测试不连接真实集群。开发范围以任务单或负责人明确任务指令为准，PR 首行写 `Task: Tn`；实际阻塞注明结构、提交、解析、科学审阅或环境类别。合并由人完成。

- **v2.7、v3**：已归档于 [archive/](archive/README.md)，原始 v3 基线为 `v3-frozen`。旧 [CHANGELOG](archive/CHANGELOG.md) 保持原样。
- **v4.0 → v4.1.0**：ag + Skills 文件状态架构与后续解析、分析工具、卡片和不完整取回更新，详见 [CHANGELOG.md](CHANGELOG.md)。[REDESIGN-PLAN](docs/REDESIGN-PLAN.md) 作为设计记录保留。
- **v4.2.0**：更新提交额度与 SSH 日志、取回后自动 facts、CREST/xTB 线程设置、证据引用解析、ensemble 和研究准备文档；升级前检查本机资源配置，详见 [CHANGELOG.md](CHANGELOG.md#v420)。
- **v4.2.1**：T62 保留小修、T64 证据引用分类、T65 远程观察回退、T66 Slurm 不完整取回、T68 RDKit 风险报告、T69 通道覆盖、T70 局部构象描述与 T72 文献模板；配合前端 T71，详见 [CHANGELOG.md](CHANGELOG.md#v421)。
- **v4.2.2**：T73 topology 不确定接触修复、T74 SSH 日志与命令示例引用修复、T75 Gaussian 二维扫描、T76 畸变–相互作用分析、T77 PBS 数组观察兼容；前端保持 v4.2.1，详见 [CHANGELOG.md](CHANGELOG.md#v422)。
- **v4.3.0**：开题核验与准备、定向复合物构建和分组枚举、TS 立体标签、逐方向 IRC 审阅与路径哈希、运行日志快照、共振等价、Multiwfn IGM / IGMH 与 NCI 报告，以及 thermo / profile、输入和 route 解析修复；配合前端 v4.3.0，详见 [CHANGELOG.md](CHANGELOG.md#v430)。

- **v4.4.0**：T101 共享队列核数与核时提示、T102 按进展取回与取消后取回、T105 气相 Counterpoise 诊断、T106 可配置 PBS/排队上限与独立 CREST 路径；配合前端 v4.4.0，详见 [CHANGELOG.md](CHANGELOG.md#v440)。

- **v4.6.2**：T145 显式 PBS 具名节点、半数/四分之一档位匹配、优先级分组、实时提交检查与运行位置核对；配套前端明确选择节点。原入口兼容，特殊 CPU 与现场竞争限制保留。[发布说明](CHANGELOG.md#v462)
- **v4.6.1**：T141 Gaussian-only 显式模板白名单、T142 可选六档资源、入口级 PBS 高内存与单作业时限硬上限；配合前端 T143 节点分配与资源展示。升级和回退须同时核对配置兼容性，发布不等于服务器接入验收。[发布说明](CHANGELOG.md#v461)
- **v4.6.0**：T130–T139 的 C 批 TS 初猜工具链：catalog v2、扫描峰 TS 与端点 QST2 草稿、scan-path、G0/模式诊断、profile 三数报告、卡片及连接超时；配合前端 v4.6.0，catalog 升级不可降级。[发布说明](CHANGELOG.md#v460)
- **v4.5.1**：T127 监控退避、暂停、手动重试、Torque 内存及拒绝零新增文件；新增运维文档，配合前端 v4.5.1。[发布说明](CHANGELOG.md#v451)
- **v4.5.0**：T108 facts 语义、T109 等价映射、T111 提交批准、T112 自动内存与配置重读、T114/T123/T124 监控与时区、T117 路由建议、T119 采用登记、T116 公开扫描和 T125 TS 初猜审计；配合前端 v4.5.0，详见 [CHANGELOG.md](CHANGELOG.md#v450)。

许可：[MIT](LICENSE)。


### Counterpoise 诊断（T105）

`gaussian-cp` 为双片段气相单点模板，prepare 校验四列片段 CSV 并生成 Gaussian 片段标签。
G16 A.03 实测拒绝 CP 与 SCRF 同用，因此在 prepare 阶段拒绝 SCRF。
本地 `ag cp-report` 输出独立 `ag-cp/1` JSON/Markdown，可核对同几何的普通溶剂 SP、并列 ASM 形变能。
缺溶剂片段能量时明确记未知，不用气相值替代；CP 不进入 thermo/profile。
见 [报告格式与验证边界](docs/ag-cp-1.md) 和 [counterpoise 卡](skills-next/auto-g16-recipes/cards/counterpoise.md)。
