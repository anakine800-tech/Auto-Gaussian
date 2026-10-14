# Auto-Gaussian v4.0

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
- 按集群统计该用户全部作业，包含非 ag 作业。PBS 硬件核验通过时区分运行上限与运行加排队额度；失败时回退严格额度。Slurm 无硬件保证，运行加排队均计入 `max_cores`；核时预算另行检查。
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
前端当前的配置兼容限制见下文。

资源示例：`mini` 4 核/10 GB、`simple` 8 核/12 GB、`general` 22 核/50 GB、`complex` 44 核/120 GB，均按实际配置调整。
Gaussian `%nprocshared` 必须等于档位核数，`%mem` 不超过档位内存的 85%。
SSH 准备说明见 [ag/README.md](ag/README.md)；配置后按需运行 `ag doctor --cluster '<CLUSTER>' --json` 做只读自检。

## 命令一览

尖括号表示需替换的占位符。`<STUDY_ID>` 是配置的 studies 根目录下的直接子目录名；
`<STUDY_DIR>` 是完整本地目录。各命令支持 `--json`，完整参数以 `ag <命令> --help` 为准。

| 命令 | 用途 |
| --- | --- |
| `ag init '<STUDY_ID>'` | 创建 study 骨架 |
| `ag prepare --study '<STUDY_ID>' ...` | 本地建立独立 Attempt、校验输入并显示确认摘要；`--card` 保存卡片来源 |
| `ag submit '<ATTEMPT_ID>' ...` | 人点击 Mac 确认后提交；支持批次 |
| `ag status '<ATTEMPT_ID>' --json` | 只读查询远程证据并更新本地状态；也可 `--study` |
| `ag fetch '<ATTEMPT_ID>'` | 取回声明输出，拒绝覆盖 |
| `ag cancel '<ATTEMPT_ID>'` | 人点击 Mac 确认后取消确切作业 |
| `ag list --study '<STUDY_ID>' --json` | 列出本地 Attempt |
| `ag doctor --cluster '<CLUSTER>' --json` | 只读检查连接、调度器和程序环境 |
| `ag monitor --watch 120` | 前台只读采样并保存监控快照；Ctrl-C 退出，无自动提交或取消 |
| `ag facts '<ATTEMPT_ID>' --study '<STUDY_ID>' --json` | 解析日志、几何、频率、IRC 等事实 |
| `ag thermo '<ATTEMPT_A>' '<ATTEMPT_B>' --study '<STUDY_ID>' --json` | GoodVibes qRRHO 与所选构象集合的布居 |
| `ag dedup '<XYZ_FILE>' --charge 0 --out '<ANALYSES_DIR>' --json` | 按已确认电荷去重；此例为中性体系 |
| `ag cluster '<DEDUP_JSON>' --max 20 --json` | 从去重结果选择代表构象 |
| `ag graph --study '<STUDY_DIR>' --json` | 展示 Attempt 父子关系 |
| `ag irc-compare --ts '<TS>' --forward '<FORWARD>' --reverse '<REVERSE>' --reactant '<REACTANT>' --product '<PRODUCT>' --out '<NEW_REPORT_JSON>' --json` | 双向 IRC 端点与参考结构的映射比较 |
| `ag profile '<PROFILE_JSON>' --json` | 组装已审阅物种的反应自由能曲线、能垒及适用时的能量跨度 |
| `ag review init '<ATTEMPT_ID>'` / `ag review check '<ATTEMPT_ID>'` | 创建审阅骨架或检查事实快照是否仍匹配；不代替科学判断或签字 |

作业命令退出码：0 成功，1 取消或校验失败，2 环境/连接错误，3 状态不确定。
`unknown`、`failed_presubmit` 或计算失败不构成重提同一 Attempt 的理由。

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
3. 用 `prepare` 准备 Opt+Freq 等 Attempt，向人展示结构、立体警告、完整 route、DOI 或兜底声明、资源、walltime、远程目录和输入哈希。例如：

   ```bash
   ag prepare --study '<STUDY_ID>' --cluster '<CLUSTER>' \
     --template gaussian --input '<INPUT_GJF>' --card opt-freq \
     --tier simple --walltime 01:00:00 --label optfreq \
     --method-basis '<DOI_OR_FALLBACK_STATEMENT>'
   ```

4. 获得提交指令后执行 `ag submit`，由人亲手点击 Mac 对话框。`status → fetch → facts` 收集证据；失败时按诊断卡片提出新 Attempt，不自动重提。
5. `review init` 后由 LLM 逐项审阅收敛、虚频、结构身份等，`review check` 检查事实来源；优化后重新去重，统一方法与程序版本，再做 `thermo`，需要反应曲线时使用 `profile`。
6. 人审核最终结果并签字；`study.md` 写入结论与适用边界。续接时读取 `study.md`、`ag list` 和已有文件，不凭对话记忆重复提交。

TS 必须恰好一个虚频且振动方向与反应坐标一致；只有双向 IRC 完成、端点被识别并科学审阅后，才能声称验证。

## 前端

[Auto-Gaussian-Frontend](https://github.com/anakine800-tech/Auto-Gaussian-Frontend) v4.0.0 配合 ag 4.0.0 使用，启动方式见其 README。
默认只读，读取本地 study、结果与保存的监控快照。`--enable-actions` 显式开启经本机 ag 执行的准备、提交、状态刷新、取回和取消；不绕过 Mac 确认，也不直接执行远程命令。

**当前兼容边界**：前端操作模式读取旧单集群配置的顶层 `resources.tiers`；服务器页只读取
`<STUDIES_ROOT>/.ag-monitor/latest.json`。多集群配置下，ag 将快照保存在
`<STUDIES_ROOT>/.ag-monitor/<CLUSTER>/latest.json`，前端尚未适配该布局和多集群操作。
多集群用户当前使用 ag CLI；前端仍可只读浏览本地 study，不把缺少监控快照当成服务器空闲。

## 验收状态

截至 2026-10-14，依据本地 study 文件核对，仅公开流程状态，不公开研究数据或连接信息；本次发布准备未重新连接集群或执行计算。

| 层级 | 已有证据 | 尚未完成 |
| --- | --- | --- |
| L1 正丁烷 | 结构、代表集合已签字；CREST、去重、代表 Opt+Freq、热化学及旧结果对照已完成；跨对话文件续接已验证 | 最终结果签字；实际关闭并重开桌面应用未独立验证 |
| L2 真实柔性主族体系 | 结构、有限代表集合已签字；CREST 已取回；四个 Opt+Freq 已提交 | DFT 完成证据、优化后去重、热化学、科学审阅、恢复验证及最终签字；覆盖有限，仅作流程验收 |
| L3 小体系 TS/IRC | 机理假设、结构、代表集合已签字；首批四个分子 Opt+Freq 已提交 | TS 与离子 Freq 尚未提交；TS 振动方向、双向 IRC、端点、能垒及最终签字未完成 |

以上均不标记为整体验收通过。发布 PR 保持未合并，等待负责人确认验收；tag 和 release 由负责人在 GitHub 页面操作。

## 支持范围与限制

- 当前科学工作范围：主族闭壳层体系，Opt+Freq、单点、构象筛选、热化学；已有人提供初猜的 TS/QST2/QST3、IRC 卡片及本地分析工具。
- 支持 PBS/Torque 与 Slurm 配置；适配实现与离线测试不等于任意站点的真实环境验收。
- 不支持金属体系、开壳层、激发态、多参考等专门方法的可靠研究流程；不把可传入的程序参数解释为科学支持承诺。
- 不提供全自动 TS 搜索、无人值守研究、自动重提、多用户服务或旧 v3 数据库/工作流兼容迁移。
- `prepare --parent-chk` 支持同 study、同集群内受限复用父 checkpoint：父作业必须结束且已离开调度器，复制到新 Attempt 时校验确认过的哈希、不覆盖。TS/IRC 工具存在不代表 L3 已通过。
- 构象数量上限、成功日志和布居都不能证明采样完备；研究方法按文献与体系审阅选择。

## 开发检查与版本历史

```bash
python -m pytest ag/tests skills-next -q -rs
# 仅暂存本任务文件后：
python ag/tools/scan_sensitive.py --staged
```

离线测试不连接真实集群。开发范围以任务单或负责人明确任务指令为准，PR 首行写 `Task: Tn`；实际阻塞注明结构、提交、解析、科学审阅或环境类别。合并由人完成。

- **v2.7、v3**：已归档于 [archive/](archive/README.md)，原始 v3 基线为 `v3-frozen`。旧 [CHANGELOG](archive/CHANGELOG.md) 保持原样。
- **v4.0**：ag + Skills 文件状态架构，详见 [CHANGELOG.md](CHANGELOG.md)。[REDESIGN-PLAN](docs/REDESIGN-PLAN.md) 作为设计记录保留。

许可：[MIT](LICENSE)。
