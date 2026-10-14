# Auto-Gaussian 改造方案（ag + Skills）

> **历史文档。** 本文是 v4.0 改造期的设计记录，v4.0.0 已于 2026-10-14 发布。其中的阶段计划、范围和“唯一方案来源”等表述已由后续任务、README 和 DEVELOPING 取代；现行规则以 AGENTS.md、README 和 DEVELOPING 为准，文档入口见 [文档索引](README.md)。

版本：2026-10-13 初版。规划与监督：Claude；操作与合并：项目负责人；执行：Codex。
改造期间本文件曾是新架构的唯一方案来源；现仅供追溯决策背景。

---

## 0. 目标与范围

**目标**：两周左右做出一个能真正用于 HSS 研究（非金属、柔性 Michael 加成）的计算助手：人和 LLM 在 Codex 里对话推进研究，代码只负责安全地提交、查询、取回和提取数字。

**核心版范围（第 1～2 周）**：结构输入（ChemDraw/SMILES）→ 构象初筛（RDKit 力场或 CREST）→ 去重聚类 → DFT Opt+Freq → 热化学（qRRHO + Boltzmann）→ LLM 审阅 → 人签字。

**之后（第 3 周起，按顺序）**：TS/IRC（人给 TS 初猜）→ 前端改为只读读取 study 目录 → 两分子中间体初筛 → 过渡金属。

**明确不做**：守护进程、多用户、数据库、通用工作流语言、自动 TS 搜索、自动重提交、旧 v2/v3 代码的兼容或迁移。

---

## 1. 决策记录（2026-10-13 讨论定稿）

| 编号 | 决策 |
|---|---|
| D1 | 代码硬内核只管：单次提交、不覆盖不删除、`UNKNOWN` 不重试、指定作业号 qdel、凭据隔离、提交字节与确认哈希一致。科学判断全部交给 Skill + LLM + 人 |
| D2 | 每次提交只有一道人工确认。允许同一卡片、同一方法的多个 Attempt 批量确认 |
| D3 | Gaussian 下新增任务类型 = 只写卡片；新程序 = 一个模板 + 少量解析；新集群 = 改配置 |
| D4 | 运行时是 Codex 桌面端，交互式，人始终在回路里，不做无人值守 |
| D5 | 新写 `ag/`，不 import 旧代码；旧代码打 tag `v3-frozen` 冻结 |
| D6 | 确认方式：`ag submit`/`ag cancel` 弹出 macOS 系统对话框，人亲手点击（Codex 没有原生桌面控制能力）。无任何绕过方式 |
| D7 | 状态全部存文件，不用 SQLite；用 `O_EXCL` 原子创建保证只提交一次 |
| D8 | 日志解析用 cclib，输出 `facts.json`；LLM 解释事实 |
| D9 | 失败后由 LLM 诊断并提出新 Attempt，人确认后再提交；不做白名单自动重提 |
| D10 | Skills 分三层：编排（study）、任务卡片（recipes）、辅助（structures、literature） |
| D11 | 方法优先从文献（含本组已发表文献）学习；无先例时用兜底方法并在确认摘要中声明 |
| D12 | 科学判据：代码给客观数字，卡片给判据清单，LLM 写 `review.md`，人只在三个里程碑签字 |
| D13 | 结构输入沿用现有 ChemDraw/RDKit 通路（复制进新 Skill），初筛可选 RDKit 力场或 CREST |
| D14 | 经验沉淀：LLM 起草经验条目 → 人审阅 → 合入卡片的“常见坑”；Skill 部署改为软链接 |
| D15 | Primitive：一个通用 `ag run` 式作业（prepare/submit）+ 确定性本地工具；只允许审阅过的模板（不允许 LLM 写作业脚本） |
| D16 | 最小 Artifact Graph：每个 Attempt 的 manifest 记录 `parents` 和 `relation`，`ag graph` 展示 |
| D17 | 传输走 Mac 直连 SSH（已实测可用）；RTwin 两段链路暂不支持，以后作为备用 |
| D18 | 远程目录 `<SDL 根>/ag/<study>/<attempt>/`；SDL 下旧项目完全不动 |
| D19 | 集群为单节点 44 核 / 120 GB；三档资源 simple 8 核 12 GB、general 22 核 50 GB、complex 44 核 120 GB；运行上限 44 核，运行加排队按 4.8 节配置 |
| D20 | 验收方法一律用最快可行的方法；正式研究方法按文献 |
| D21 | 热化学：GoodVibes 4.3.0 qRRHO（Grimme，100 cm⁻¹），298.15 K，溶液相 1 mol/L 标准态 |
| D22 | 前端两周内冻结；之后改为只读读取 study 目录，去掉提交功能 |
| D23 | 监督：GitHub PR + 定时巡检在 PR 对话区写审阅评论；ag-dev-relay 冻结归档 |
| D24 | 两分子初筛往后放；当前只做主族体系，`facts.json` 预留自旋信息 |

---

## 2. 目标结构

```
人（目标、化学先验、确认提交、里程碑签字）
  │
Codex + Skills（判断与编排）
  ├─ auto-g16-study       编排：读 study.md，决定下一步，调用 ag，写 review / study.md
  ├─ auto-g16-recipes     任务卡片：每种计算一张 markdown
  ├─ auto-g16-structures  ChemDraw/SMILES → 结构、立体检查、RDKit 力场初筛
  └─ auto-g16-literature  找计算先例、给出方法依据（DOI）
  │
ag 命令行（代码硬内核）
  ├─ 作业：prepare / submit* / status / fetch / cancel* / list / doctor   (*需人点击确认)
  └─ 本地工具：facts / dedup / cluster / thermo / graph
  │
本地 study 目录（文件状态）      集群（Torque 6.1.0，单节点 44 核）
                                   g16 A.03 · xtb 6.7.1 · crest 3.0.2
```

### 仓库布局

```
AGENTS.md                      新规则
docs/REDESIGN-PLAN.md          本文件
docs/redesign-tasks/T*.md      任务单
ag/
  pyproject.toml               独立项目，命令名 ag
  config.example.toml          配置样例（全部占位符）
  src/ag/                      CLI 与工具
  templates/                   审阅过的作业模板 + 每个模板的声明文件
  tests/                       单元测试；tests/fixtures/ 只放脱敏的小分子日志
skills-next/
  auto-g16-study/
  auto-g16-recipes/
  auto-g16-structures/
  auto-g16-literature/
（以下全部冻结）auto_g16/ skills/ scripts/ tests/ contracts/ docs/v3/ ...
```

`ag` 运行在本地 `chem` conda 环境（Python 3.11，已有 RDKit）。新增依赖：cclib、goodvibes==4.3.0（numpy 已有）。`ag/pyproject.toml` 声明 `requires-python >=3.11`。

---

## 3. 运行环境

具体主机名、用户名、路径只写在本地配置 `~/.config/ag/config.toml`，**永不进仓库**。下表只记录结构性事实，具体值由 T1 根据 2026-10-13 的环境盘点报告填入本地配置。

| 项目 | 事实 | 配置键 |
|---|---|---|
| SSH | Mac 直连可用，使用专用 ssh 配置文件和主机别名 | `ssh.config_file`、`ssh.host` |
| 调度器 | Torque 6.1.0，队列 `batch`，队列默认 walltime 很长；每用户上限未知 | `scheduler.queue` |
| 节点 | 单节点 44 核 / 120 GB | `resources.max_cores = 44` |
| 远程根 | SDL 目录存在、非符号链接、可写 | `remote.allowed_root`、`remote.ag_root`（= allowed_root/ag） |
| Gaussian | G16 A.03，安装在 `<g16root>`；非登录 shell 中不在 PATH | `programs.gaussian.g16root` |
| xtb / crest | 用户目录安装，同一根目录；需 `XTBPATH=<root>/share/xtb`、`OMP_NUM_THREADS` | `programs.xtb.root` |
| 本地 Python | `chem` 环境 3.11.15，RDKit 2026.03.3，CDX 支持可用；cclib 未安装 | `local.python` |
| 本地 studies | 目录由人决定，不在仓库内 | `local.studies_root` |

---

## 4. `ag` 规格

### 4.1 study 目录

```
<studies_root>/<study_id>/
  study.md            人和 LLM 共同维护：目标、体系、方法与依据、计划、进度、里程碑签字、结论
  journal.jsonl       ag 的所有动作，只追加
  structures/         结构 Skill 的产物
  attempts/<attempt_id>/
    manifest.json     ag prepare 写入后不再修改
    status.json       ag 维护的状态
    inputs/           提交的文件（含渲染后的 job.pbs）
    outputs/          ag fetch 取回的文件（不覆盖）
    facts.json        ag facts 生成（可重新生成）
    review.md         LLM 按卡片判据写
  analyses/           dedup / cluster / thermo 等本地工具的输出
  lessons/            LLM 起草的经验条目（待人审阅后并入卡片）
```

`ag init <study_dir>` 创建骨架和 `study.md` 模板。

### 4.2 Attempt 标识

`attempt_id = <study_id>-<三位序号>-<label>`，例如 `hss-007-optfreq-c03`。序号通过在本地 `attempts/` 下 `O_EXCL` 创建目录分配。PBS 作业名用 `ag` + attempt_id 的 SHA-256 前 12 位（避免 Torque 作业名长度限制），写入 manifest，用于 `UNKNOWN` 核对。

### 4.3 状态机

```
prepared ──submit(确认)──▶ submitting ──qsub 返回作业号──▶ submitted ──作业离开队列──▶ finished ──fetch──▶ fetched
                              │                                   │
                              ├─ 确定没提交上（远程目录已存在、上传哈希不符、qsub 明确报错）──▶ failed_presubmit
                              └─ 不确定（连接中断、超时、输出无法解析）──▶ unknown
submitted ──cancel(确认)+qdel──▶ cancelled
unknown ──ag status 只读核对：按作业名或远程目录证据找到作业──▶ submitted
unknown ──找不到证据──▶ 保持 unknown，交给人决定（不会自动处理）
```

- 进入 `submitting` 之前先在本地 `O_EXCL` 创建 `attempts/<id>/.submit-claim`；该文件已存在就拒绝提交。
- `failed_presubmit` 和 `unknown` 的 Attempt 永远不能再次提交；要重做就 `prepare` 一个新 Attempt。
- `status.json` 写入方式：写临时文件再原子 rename（本地派生状态，允许更新）；每次状态变化同时追加 `journal.jsonl`。

### 4.4 命令

| 命令 | 作用 | 远程操作 |
|---|---|---|
| `ag doctor` | 环境自检：ssh 连通、`qstat -Q`、g16/xtb/crest 可执行、远程根可写 | 只读 |
| `ag init <dir>` | 建 study 骨架 | 无 |
| `ag prepare` | 建 Attempt：复制输入、渲染模板、校验、写 manifest，打印确认摘要（JSON + 人读 markdown） | 无 |
| `ag submit <id>...` | 批量提交：弹对话框确认 → 声明 → 核数上限检查 → 建远程目录 → 上传 → 远程校验哈希 → qsub | 写（受限） |
| `ag status [<id>|--study S]` | 查询作业状态；核对 `unknown` | 只读 |
| `ag fetch <id>` | 取回模板声明的输出到 `outputs/`，已存在则拒绝 | 只读 |
| `ag cancel <id>` | 弹对话框确认 → `qdel <确切作业号>` | 写（受限） |
| `ag list [--study S]` | 列出 Attempt 和状态 | 无 |
| `ag facts <id>` | 解析输出，写 `facts.json` | 无 |
| `ag dedup` / `ag cluster` | 构象去重、聚类、按能量窗口筛选，输出候选列表和 xyz | 无 |
| `ag thermo <id>...` | GoodVibes qRRHO + Boltzmann，输出到 `analyses/` | 无 |
| `ag graph --study S` | 根据 manifest 的 parents/relation 展示关系 | 无 |

所有命令支持 `--json` 输出，便于 LLM 读取。退出码：0 成功，1 用户取消或校验不通过，2 环境/连接错误，3 结果不确定（`unknown`）。

`ag prepare` 主要参数：`--study`、`--template {gaussian,xtb,crest}`、`--input <文件>`、`--tier {simple,general,complex}`、`--walltime HH:MM:SS`、`--label`、`--parent <attempt_id> --relation <词>`（可重复）、模板专用参数（见 4.7）。

### 4.5 远程操作白名单

`ag` 只通过 `ssh -F <config_file> <host>` 执行以下固定命令模板，所有参数经 `shlex.quote`，路径先做包含性和非符号链接校验：

1. 只读：`test`、`stat`、`ls -la <attempt_dir>`、`sha256sum <attempt_dir>/<文件>`、`qstat -Q`、`qstat -f <作业号>`、`qstat -f`（自己的全部作业，用于核数统计和 `unknown` 核对）、`command -v`/可执行检查（doctor）。
2. 写：`mkdir <ag_root>/<study>`（不存在时）、`mkdir <attempt_dir>`（必须不存在，不用 `-p`）、上传文件到新目录（`scp`/`sftp put`，目标文件必须不存在）、`cd <attempt_dir> && qsub job.pbs`、`qdel <作业号>`。
3. 禁止：其余一切命令。代码里不出现 `rm`、`rmdir`、`mv`、`cp -f`、重定向截断。

### 4.6 提交确认

- `ag submit` 和 `ag cancel` 调用 `osascript` 弹出系统对话框，默认按钮为“取消”，5 分钟无操作视为取消。对话框内容：每个 Attempt 的 id、模板、档位与核数、walltime、bundle 哈希前 12 位，以及提交后的总核数。
- 非 macOS 环境直接拒绝提交。
- 不提供 `--yes`、`--no-confirm`、环境变量或配置项来跳过确认。单元测试通过替换确认函数（monkeypatch）来测试，不经过 CLI。
- bundle 哈希 = 对 `inputs/` 下所有文件按文件名排序后的 `文件名\0sha256\n` 串再做 SHA-256；`prepare` 打印的摘要和对话框显示的是同一个值。

### 4.7 模板

`ag/templates/<name>.pbs` + `<name>.toml`（声明参数白名单、输出文件、完成标记）。每个渲染出的 `job.pbs` 都由 `ag` 在前面拼接统一的安全头（移植自旧 `templates/g16_job.pbs.template`：检查工作目录在允许根之下、不是符号链接、scratch 在工作目录内）。

| 模板 | 资源行 | 环境 | 运行 | 声明的输出 | 完成标记 |
|---|---|---|---|---|---|
| `gaussian` | `nodes=1:ppn=<核数>`、`walltime` | 显式设置 `g16root`、`GAUSS_EXEDIR`、`PATH`、`LD_LIBRARY_PATH`、`GAUSS_SCRDIR=<工作目录>/scratch` | `g16 <输入>.gjf` | `<输入>.log`、`job.pbs.out` | `Normal termination of Gaussian` |
| `xtb` | 同上 | `XTBPATH`、`OMP_NUM_THREADS=<核数>` | `xtb <xyz> <白名单参数> > xtb.out` | `xtb.out`、`xtbopt.xyz`、`xtbopt.log` | `normal termination of xtb` |
| `crest` | 同上 | 同上 | `crest <xyz> <白名单参数> -T <核数> > crest.out` | `crest.out`、`crest_conformers.xyz`、`crest.energies`、`crest_best.xyz` | `CREST terminated normally.` |

- Gaussian 输入的校验：`%nprocshared` 必须等于档位核数；`%mem` 不超过档位内存的 85%；`%chk` 只能是不含路径的文件名；必须有 route 行、标题、电荷多重度行和坐标。
- crest 参数白名单（首版）：`--gfn2`、`--gfnff`、`--alpb <溶剂>`、`--chrg <整数>`、`--uhf <整数>`、`--ewin <数>`、`--quick`、`--squick`、`--mquick`。xtb 参数白名单（首版）：`--gfn 2`、`--opt [级别]`、`--alpb <溶剂>`、`--chrg`、`--uhf`。超出白名单直接拒绝；新增参数需要改模板声明并经审阅。
- `.chk` 默认不取回（体积大）。后续 TS/IRC 需要跨 Attempt 读 chk 时，再增加一条“远程复制父 Attempt 的文件到新目录（目标不存在）”的白名单操作。

### 4.8 核数上限

`submit` 前用 `qstat -f` 统计该用户所有非 C 状态作业的核数（包括不是 `ag` 提交的作业），分别列出运行（R/E）和排队（Q/H/W 等）核数。无法统计时拒绝提交并报告原因。单个作业仍不得超过 `resources.max_cores`（当前 44 核）。

每次提交前复用 `pbsnodes -a` 核验全部节点的总核数。总核数不超过 `max_cores` 时，由硬件保证运行核数上限，允许作业在 PBS 中排队；已占用加本次提交不得超过 `resources.max_committed_cores`（当前计划配置为 88 核），防止误交过多作业。该配置必须为整数，满足 `max_cores ≤ max_committed_cores ≤ 4 × max_cores`，缺省等于 `max_cores`，保持原有严格额度。

节点核验失败、输出无法解析或集群总核数超过 `max_cores` 时，回退严格模式：运行和排队均计入 `max_cores`，并输出原因。确认前检查整个批次并核验硬件容量；每个 Attempt 提交前沿用本批确认前的硬件核验结果和有效上限，只重新读取 qstat 并累计已提交部分；尚未出现在 qstat 中的本批作业也计入，避免调度器读回延迟造成少算。确认对话框和终端摘要显示当前运行、排队、提交后总核数和本次有效上限。

### 4.9 文件格式

`manifest.json`（prepare 后不变）：
```json
{
  "schema": "ag-attempt/1",
  "attempt_id": "hss-007-optfreq-c03",
  "study_id": "hss",
  "label": "optfreq-c03",
  "template": "gaussian",
  "template_params": {},
  "tier": "simple", "cores": 8, "mem_gb": 12, "walltime": "24:00:00",
  "inputs": [{"name": "c03.gjf", "sha256": "...", "size": 1234}, {"name": "job.pbs", "sha256": "...", "size": 987}],
  "bundle_sha256": "...",
  "pbs_job_name": "ag3f9c0a1b2c4d",
  "remote_dir": "hss/hss-007-optfreq-c03",
  "parents": [{"attempt_id": "hss-004-crest", "relation": "conformer_of"}],
  "created_at": "2026-10-15T10:00:00+08:00",
  "ag_version": "0.1.0"
}
```
`remote_dir` 只记录相对 `ag_root` 的部分，避免绝对路径进入可能被分享的文件。

`status.json`：`{"state": "...", "job_id": "...", "exit_status": null, "updated_at": "...", "note": "..."}`。

`journal.jsonl` 每行：`{"ts", "action", "attempt_id", "result", "detail"}`。

`facts.json`（`schema: ag-facts/1`）：
- 通用：`program`、`termination`（normal / error / incomplete）、`error_hint`（如 `L9999`、`SCF 不收敛`、`walltime`）、`n_atoms`、`charge`、`multiplicity`、`route`、`final_geometry`（写成同目录 `final.xyz`，facts 里只记文件名）。
- Gaussian Opt/Freq：`opt_converged`、`energies`（scf、zpe、e_thermal、h、g，单位 Hartree）、`s2`（`<S**2>`，有就记）、`n_imag`、`frequencies_low`（最低 10 个，cm⁻¹）、`imag_modes`（每个虚频：频率和位移最大的 5 对原子）。
- CREST：`n_conformers`、`relative_energies_kcal`、`best_energy`。
- xtb：`total_energy`、`converged`。

### 4.10 依赖与测试

- 单元测试用 pytest，覆盖：状态机、`O_EXCL` 声明、确认函数不可绕过、命令白名单（断言生成的远程命令只来自模板）、模板渲染与参数白名单、Gaussian 输入校验、核数上限、facts 解析、dedup/cluster、thermo。
- 远程交互通过一个 `Transport` 接口注入，测试用假实现；不在测试里连真实集群。
- 测试日志：仓库内只放我们自己新算的小分子（正丁烷、水）日志，提交前删除日志头中的主机名、用户名、路径。研究日志（HSS、BPh₃ 等）留在本地，通过环境变量 `AG_LOCAL_FIXTURES=<目录>` 让额外测试读取，未设置时跳过。

---

## 5. Skills 规格

### 5.1 部署

- `~/.codex/skills/<name>` 改为指向仓库 `skills-next/<name>` 的软链接，Skill 的任何改动都会出现在 git diff 里。
- 旧的 `~/.codex/skills/auto-g16-*` 部署副本移到 `~/.codex/skills-disabled/`（本地移动，可恢复），避免 Codex 误用旧 Skill。

### 5.2 `auto-g16-study`（编排）

职责：
1. 新研究：`ag init`，和人一起写 `study.md` 的“目标”和“体系”；缺电荷、多重度、溶剂、温度等就问。
2. 每次被调用：先读 `study.md` 和 `ag list --json`，判断当前处于哪一步，再决定下一步。
3. 选卡片：按卡片“适用范围”选；没有合适卡片就停下来告诉人。
4. 选方法：先查本组文献和文献 Skill；无先例时用兜底方法并在摘要里声明（见 5.5）。
5. 准备提交：调用 `ag prepare`，然后向人展示确认摘要（格式见 `references/confirmation-summary.md`），等人说“提交”后再运行 `ag submit`（对话框仍会弹出，由人点击）。
6. 收结果：`ag status` → `ag fetch` → `ag facts` → 按卡片判据写 `review.md` → 更新 `study.md` 进度。
7. 失败：按 `failure-diagnosis` 卡片诊断，提出新 Attempt 的修改方案，等人确认。`unknown` 一律报告给人，不做任何处理。
8. 里程碑：结构确认、代表构象集合、最终结果三处请求人签字，签字记录写入 `study.md`。
9. 经验：解决了一个问题或被人纠正后，在 `lessons/` 起草一条经验，并提议修改哪张卡片；不直接改 Skill 文件。

### 5.3 `auto-g16-recipes`（任务卡片）

首版卡片：`opt-freq.md`、`sp.md`、`rdkit-screen.md`、`crest-screen.md`、`thermo.md`、`failure-diagnosis.md`。第 3 周起：`ts.md`、`irc.md`。

每张卡片固定小节：
1. 适用范围（例如“主族、闭壳层、中性或带电、无过渡金属”）
2. 前置条件（需要哪些上游结果）
3. 输入模板（route 写法、Link0、需要的 ag 参数）
4. 资源建议（按原子数和任务类型给档位与 walltime）
5. 提交前检查清单
6. 结果判据清单（LLM 在 `review.md` 中逐条填写“通过 / 不通过 / 依据”）
7. 常见失败与处理（给出新 Attempt 的修改建议，不自动重提）
8. 常见坑（经验沉淀区，人审阅后追加）

### 5.4 `auto-g16-structures` 与 `auto-g16-literature`

- structures：复制并合并旧 `auto-g16-chemdraw-pipeline` 和 `auto-g16-view-rt-win` 中的脚本（CDX 读入保留显式氢、恢复楔形键、笛卡尔坐标审核、ETKDGv3 + MMFF94s/UFF 构象初筛）。输出写到 study 的 `structures/`。GaussView 预览先保留为可选。
- literature：一份 markdown 协议，说明如何找计算先例（优先本组文献、相同反应类型、主文与 SI）、如何标注“直接先例 / 类比”、如何引用（DOI + 页码或 SI 位置）。可使用 Codex 自带的检索能力；人提供的 PDF 优先。

### 5.5 兜底方法（无文献先例或验收时）

负责人于 2026-10-14 确认；具体输入骨架、先例依据和适用边界见
[验收与兜底方法](../skills-next/auto-g16-study/references/acceptance-methods.md)。

| 用途 | 方法 |
|---|---|
| 验收（只证明流程能跑通） | B3LYP-D3(BJ)/6-31G(d)，气相 Opt+Freq；筛选单点用同层级，不做高精度单点；阴离子或明显离域负电荷的优化及筛选单点均用 6-31+G(d) |
| 研究但无先例 | Opt+Freq：ωB97X-D/6-31G(d)；最终几何精化单点：ωB97X-D/def2-TZVPP；溶液相均加 SMD。依据当前本组先例清单最常见的两层组合（DOI 10.1021/jacs.2c00962、10.1021/jacs.4c09067），B3LYP-D3 仅作流程验收兜底 |
| 阴离子或负电荷明显离域 | 优化、频率及筛选单点：ωB97X-D/6-31+G(d)；最终几何精化单点：ωB97X-D/6-311++G(d,p)；溶液相均加 SMD，比较组采用一致的弥散方案 |
| 构象筛选 | CREST GFN2-xTB，溶液相加 ALPB；xTB 相对能 ≤ 6 kcal/mol 的候选去重后做优化层级 DFT 单点重排：研究用 ωB97X-D/6-31G(d) + SMD，阴离子或明显离域负电荷用 ωB97X-D/6-31+G(d) + SMD；DFT 相对能 ≤ 3 kcal/mol 的进入优化，研究最多 20 个、验收最多 10 个；优化后重新去重，研究所需精化单点在最终几何上重算 |
| 方法敏感性 | 决定结论的关键能垒至少用 2 类泛函做单点：ωB97X-D 与 M06-2X；同几何、基组（阴离子含弥散）、溶剂与热修正口径，覆盖 TS 及完整参考物种/竞争通道；结论随方法翻转时必须在 study.md 中写明 |

筛选数量上限在 DFT 重排之后应用；预算截断不代表构象空间已穷尽。
本组先例频次不是精度保证；方法敏感性方案也不替代目标体系的适用性判断。

---

## 6. 工作线与任务单

| 任务单 | 内容 | 位置 | 依赖 | 可并行 |
|---|---|---|---|---|
| T0 | 仓库重置：tag、合入本方案和新 AGENTS.md、新 CI | 本地或云端 | 无 | 先做，最快合并 |
| T1 | `ag` 核心：配置、study/attempt、状态机、prepare/submit/status/fetch/cancel/list/doctor、transport、模板、确认对话框、核数上限 | 本地（需要 SSH 和 macOS） | T0 | 与 T2–T5 并行 |
| T2 | `ag facts` 与 `ag thermo`（cclib、GoodVibes），fixture 日志 | 本地或云端 | T0 | 是 |
| T3 | Skills：study、recipes 卡片、literature；部署软链接；停用旧部署 | 本地或云端（部署一步在本地） | T0 | 是 |
| T4 | structures Skill：迁移 ChemDraw/RDKit 脚本 | 本地（需要 RDKit） | T0 | 是 |
| T5 | `ag dedup` / `ag cluster` / `ag graph` | 本地或云端 | T0 | 是 |
| T6（第 2 周） | 归档旧目录到 `archive/`、清理旧 CI 脚本引用 | 任意 | L1 验收后 | 否 |

文件归属以各任务单“允许改动的路径”为准，互不重叠：T1 拥有 `ag` 的作业生命周期模块、`ag/templates/` 和 `ag/config.example.toml`；T2 拥有 `facts`、`thermo`、`ag/tools/sanitize_log.py` 和 `ag/tests/fixtures/`；T5 拥有 `geometry`、`dedup`、`cluster`、`graph` 和 `ag/tests/data/`；T3 拥有 `skills-next/auto-g16-{study,recipes,literature}/` 和 `skills-next/tests/`；T4 拥有 `skills-next/auto-g16-structures/`。CLI 由 T1 的 `cli.py` 统一挂载，T2/T5 各自提供 `register(subparsers)`（T0 先建好挂载点）。

---

## 7. 日程（按实际进度，2026-10-14 更新）

已合并的工程任务与 study 验收分别记录；PR 合并不代替科学审阅或人的签字。下表日期为北京时间，后续阶段按依赖推进，不再沿用初版的预计日期。

| 日期 / 阶段 | 实际进度与后续工作 | 人需要做的 |
|---|---|---|
| 10/13，已合并 | T0 仓库重置 #205；T0b 操作边界措辞 #211 | — |
| 10/13，已合并 | T1 核心 CLI #209；T2 facts/thermo #210；T3 Skills #208；T4 structures #207；T5 几何工具 #206 | — |
| 10/13，已合并 | T1c 完成回执 #212；T1d Torque 查询兼容 #213 | — |
| 10/14，已合并 | T8 L1 经验迭代 #214；T9 文档 #215；T6 旧架构归档 #216 | — |
| 10/14，已合并 | T7/T7b/T7c/T7d 前端：前端仓库 [#4](https://github.com/anakine800-tech/Auto-Gaussian-Frontend/pull/4)、[#5](https://github.com/anakine800-tech/Auto-Gaussian-Frontend/pull/5)、[#6](https://github.com/anakine800-tech/Auto-Gaussian-Frontend/pull/6)、[#7](https://github.com/anakine800-tech/Auto-Gaussian-Frontend/pull/7)；本仓库 T7b 确认摘要链接 #217 | — |
| 10/14，已合并 | T10 monitor #218；T11 PBS 排队额度 #219；T12 TS/IRC 卡片 #220；T13a TS 工具调研 #221 | — |
| 10/14，L1 当前状态 | 正丁烷计算、热化学、旧结果对照及跨对话续接已完成；最终结果仍待签字，study 尚未完成。跨对话续接不单独证明桌面应用重启 | 核对并签署最终结果 |
| 后续 1：L2 收尾 | HSS 结构与代表集合已签字；完成 Opt+Freq、DFT 后去重、热化学、科学审阅与恢复验证。构象覆盖有限，仅作本轮流程验收 | 确认必要提交；审核并签署最终结果 |
| 后续 2：T12b / T13 / T14 | 补齐科学卡片及后续能力；T13a 已完成不等于 T13 实现完成。T15 并行处理 T11 审阅遗留项和本轮杂项 | 审阅、合并各任务 PR；涉及 submit 的 PR 等监督方审阅 |
| 后续 3：L3 | 小体系 TS/Freq 与双向 IRC 全流程验收，识别端点并完成科学审阅；准备工作可先行，执行须等所需能力就绪 | 确认结构与计算；审核振动方向、端点及结果 |
| 后续 4：HSS 的 TS | 在 L3 通过后推进 HSS 的 TS/IRC 研究，按已签机理假设、构象覆盖和端点证据逐步推进 | 审阅机理假设、确认提交与里程碑签字 |

T15 与 T13-1 若在 `submit.py` 冲突，由后合并的分支 rebase；本表不把在途任务或未签字 study 标作完成。

---

## 8. 验收标准

### L1：正丁烷冒烟验收

1. 从 SMILES 或 ChemDraw 文件开始，结构 Skill 给出结构确认，人签字。
2. CREST（GFN2，快速参数）在集群跑完，`ag dedup` 得到构象候选，人签字确认代表集合。
3. 不超过 10 个构象做 B3LYP-D3(BJ)/6-31G(d) Opt+Freq，全部 `n_imag = 0`，`review.md` 逐条填写判据。
4. `ag thermo` 给出 gauche 与 anti 的 ΔG 和 Boltzmann 布居；与旧架构的正丁烷结果做对照说明（数值差异需能解释）。
5. 中途关闭 Codex，重新打开后能从 `study.md` 和 `ag list` 正确续上。
6. 全过程没有任何自动重提交；`journal.jsonl` 完整；仓库里没有出现任何敏感信息。

### L2：HSS 真实验收

HSS 中最柔性的一个单分子物种（至少 4 根可旋转键，原子数最好不超过 50），使用验收方法，满足 L1 的全部要求，并且 `study.md` 写出结论、三个里程碑都已签字。

---

## 9. 协作与监督

1. 每张任务单由人在 Codex 中开一个任务（本地或云端），并在 GitHub 开一个 Issue 链接到任务单。
2. Codex 开 `codex/<任务名>` 分支和 PR，PR 描述第一行 `Task: Tn`，并写明真实环境验证结果（不含主机信息）。
3. 定时巡检（北京时间 8:48、14:48、22:48）审阅有新提交的 PR，在 PR 对话区发评论（第一行 `<!-- ag-review head=... -->`），并推送简报给人。
4. Codex 用 `gh pr view <编号> --comments` 读取评论并修改。
5. 人决定合并。

---

## 10. 风险与对策

| 风险 | 对策 |
|---|---|
| Codex 回到写合同、加门控的老路 | 新 AGENTS.md 第 4 节；巡检把“新增约束说不清防什么”列为退回理由；第一周每天看提交 |
| 真实环境联调慢（排队、计算时长、SSH） | 先用极小的单点验证链路；CREST 设闸门；Mac 直连已实测可用 |
| LLM 判断不稳定 | 客观数字由代码给；卡片判据清单逐条填写；用正丁烷和 HSS 做回归；卡片按真实结果迭代 |
| 确认被绕过 | 无绕过参数；测试断言；巡检把可绕过列为红线；Codex 无原生桌面控制 |
| 研究数据泄露到公开仓库 | 测试日志脱敏规则；study 目录在仓库外；提交前扫描；巡检红线 |
| 集群上已有作业挤占核数 | `submit` 统计本人全部非 C 作业；硬件核验通过时按运行加排队额度检查，失败时回退 44 核严格上限 |
| 两周不够 | 预留第 3 周缓冲；TS/IRC、前端、两分子初筛严格按顺序往后排 |
