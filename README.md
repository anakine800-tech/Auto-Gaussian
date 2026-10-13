# Auto-Gaussian — ag + Skills

Auto-Gaussian 是人在回路中的计算化学助手：人在 Codex 中与 LLM 对话推进研究，
`skills-next/` 提供科学任务卡片，`ag/` 负责确定性操作和有副作用操作的安全控制。
当前研究范围以主族、闭壳层单分子为主；方法选择、结果判断和下一步决策由
Skills、LLM 和人共同完成，不做无人值守计算或自动重提交。

开始前阅读 [AGENTS.md](AGENTS.md)、[改造方案](docs/REDESIGN-PLAN.md) 和
[对应任务单](docs/redesign-tasks/)。开发时以任务单允许的路径为范围，一个任务一个
`codex/` 分支和一个 PR，合并由人完成。

## 当前架构

```text
人：目标、结构确认、提交/取消确认、科学结果签字
  ↓
Codex + skills-next：研究编排、任务卡片、结构处理、文献依据
  ↓
ag：prepare / submit / status / fetch / cancel，以及确定性本地工具
  ├─ 本地 study 目录：输入、文件状态、事实、科学审阅和结论
  └─ Mac 直连 SSH → Torque → Gaussian / xTB / CREST
```

| 路径 | 职责 |
| --- | --- |
| `ag/` | 独立 Python CLI、日志解析、热化学、构象去重/聚类和测试 |
| `ag/templates/` | 经审阅的程序模板及参数白名单 |
| `skills-next/auto-g16-study/` | 研究编排、进度记录和三个里程碑签字 |
| `skills-next/auto-g16-recipes/` | Opt+Freq、单点、初筛、热化学和失败诊断卡片 |
| `skills-next/auto-g16-structures/` | ChemDraw/SMILES 处理、立体检查和 RDKit 初筛 |
| `skills-next/auto-g16-literature/` | 计算方法先例、DOI 和适用边界 |
| `skills-next/auto-g16-chemdraw-structures/` | 继续维护的 ChemDraw 结构与反应式绘制辅助 |
| `skills-next/auto-g16-gaussian-learning-library/` | 继续维护的 Gaussian 知识库与学习辅助 |

新功能优先写成任务卡片；新的确定性操作或计算程序才增加代码。
状态存文件，不使用数据库或守护进程。每个 study 包含 `study.md`、只追加的
`journal.jsonl`、`structures/`、`attempts/`、`analyses/` 和 `lessons/`。
每个 Attempt 保留不可变的 `manifest.json`、派生状态 `status.json`、输入、输出和
`facts.json`；LLM 按卡片写 `review.md`。

研究完成意味着目标中的量都已算出，结构、代表构象集合、最终结果三个里程碑均有人
签字，且 `study.md` 写有结论。作业结束或解析成功本身不是科学验收。
实际阻塞写在 `study.md` 的“当前阻塞”中，说明属于结构、提交、解析、科学审阅还是环境问题。

## 硬内核规则

完整规则以 [AGENTS.md](AGENTS.md) 为准：

1. 每个 Attempt 至多提交一次；提交前用 `O_EXCL` 原子创建声明，存在即拒绝再次提交。
2. 服务器文件不得覆盖、删除或截断；每个 Attempt 使用新的远程目录，已存在就失败。
3. `UNKNOWN`（状态文件中的 `unknown`）只做只读核对，不重新提交。失败后由 LLM
   提出新 Attempt，经人确认后才提交。
4. `ag submit` 和 `ag cancel` 必须由人在 Mac 系统对话框中亲手点击确认；没有绕过参数、
   环境变量或配置项，非 macOS 环境拒绝提交和取消。
5. 提交字节必须与人确认时看到的哈希一致；上传后再次校验远程哈希。
6. `qdel` 只能使用 `status.json` 记录的确切作业号，每次都需确认。
7. 仅运行 `ag/templates/` 中经审阅的模板，参数必须在白名单内；不执行 LLM 拼接的任意远程命令。
8. 远程操作限定在本地配置的 SDL 根目录下的 `ag/` 子目录内，拒绝符号链接和越界路径。
9. 统计该用户在集群上的全部作业，包含非 `ag` 作业；提交后总核数不得超过配置上限（最高 44 核）。
10. 密钥、密码、真实主机信息、用户名、机器绝对路径、配置、study、未发表数据、Gaussian
    输出及 checkpoint 不进仓库；公开测试日志仅使用脱敏小分子结果。

提交前须向人展示结构、电荷与多重度、立体化学警告、方法与依据（DOI 或“兜底方法”声明）、
完整 route、资源档位、walltime、远程目录及输入哈希。人同意提交后再调用 `ag submit`，
系统对话框仍须人亲手确认。出现真实环境意外时停下来报告，不自行扩大操作范围。

## 安装

本地使用 Python 3.11 或更新版本，推荐已有 RDKit 的 `chem` conda 环境。
以下命令在仓库根目录、所选环境中运行；安装入口是独立项目 `ag/`：

```bash
conda activate chem
python -m pip install -e 'ag[test,chem]'
# 若所选环境尚无 RDKit：
python -m pip install rdkit
ag --version
ag --help
```

`chem` 可选依赖包含 cclib、NumPy 和固定为 4.3.0 的 GoodVibes；`test` 包含 pytest。
Gaussian、xTB、CREST、Torque 和本机 OpenSSH 需单独准备，Python 安装不会部署远程程序。
Gaussian、GaussView、ChemDraw 等外部软件遵循各自许可。

## 本地配置

将 [ag/config.example.toml](ag/config.example.toml) 复制到本机
`~/.config/ag/config.toml`（已有文件则先检查，不覆盖），把占位符替换为本机实际值。
CLI 从这个固定位置加载配置；study 目录必须放在 Git 仓库之外。

| 配置项 | 含义 |
| --- | --- |
| `ssh.config_file` / `ssh.host` | 专用 OpenSSH 配置文件的绝对路径 / 其中的 `Host` 别名 |
| `remote.allowed_root` / `remote.ag_root` | 远程 SDL 根目录 / 同一根目录下的 `ag` 子目录 |
| `scheduler.queue` | 实际可用的 Torque 队列 |
| `resources.max_cores` / `resources.tiers.*` | 总核数上限及资源档位 |
| `programs.gaussian.g16root` | 直接包含 `g16` 可执行文件的目录；不要填高一层目录 |
| `programs.xtb.root` | 包含 `bin/xtb`、`bin/crest` 和 `share/xtb` 的安装根目录 |
| `local.python` / `local.studies_root` | 所选化学环境的 Python 绝对路径 / 仓库外 studies 根目录 |

样例资源档位为 `mini`（4 核 / 10 GB）、`simple`（8 核 / 12 GB）、
`general`（22 核 / 50 GB）和 `complex`（44 核 / 120 GB）；总上限为 44 核。
Gaussian 输入的 `%nprocshared` 必须与所选档位一致，`%mem` 不得超过该档内存的 85%。

新机器重建 SSH 配置、主机密钥准备及验证步骤见 [ag/README.md](ag/README.md)。
填好配置后运行 `ag doctor --json` 做只读环境检查。

## 常用命令

尖括号均表示需替换的占位符，不是可直接执行的输入。`<STUDY_ID>` 是
`local.studies_root` 的直接子目录名，只使用小写字母、数字和连字符。
`<STUDY_DIR>` 表示该 study 的完整本地目录。

| 命令 | 作用 |
| --- | --- |
| `ag doctor --json` | 只读检查 SSH、身份、调度器、远程根和程序可执行性 |
| `ag init '<STUDY_ID>'` | 创建本地 study 骨架 |
| `ag list --study '<STUDY_ID>' --json` | 列出本地 Attempt 与状态 |
| `ag status '<ATTEMPT_ID>' --json` | 只读查询；不确定时保持 `unknown` 并报告 |
| `ag status --study '<STUDY_ID>'` | 查看整个 study 的作业状态 |
| `ag fetch '<ATTEMPT_ID>'` | 取回模板声明的输出，不覆盖已有本地结果 |
| `ag facts '<ATTEMPT_ID>' --study '<STUDY_ID>' --json` | 解析已取回的输出，生成事实和最终坐标 |
| `ag thermo '<ATTEMPT_A>' '<ATTEMPT_B>' --study '<STUDY_ID>' --json` | 对已审阅的频率结果计算 qRRHO 与有限构象集合的 Boltzmann 布居 |
| `ag dedup '<XYZ_FILE>' --charge 0 --out '<ANALYSES_DIR>' --json` | 按已确认电荷做构象去重；示例为中性体系 |
| `ag cluster '<DEDUP_JSON>' --max 20 --json` | 从去重结果选取代表构象 |
| `ag graph --study '<STUDY_DIR>' --json` | 展示 manifest 中的 parents/relation 关系 |

准备一个 Gaussian Attempt（仅本地操作；输入、方法和资源须先审阅）：

```bash
ag prepare --study '<STUDY_ID>' --template gaussian \
  --input '<GAUSSIAN_INPUT_FILE>' --tier simple --walltime 01:00:00 \
  --label optfreq --method-basis '<DOI_OR_FALLBACK_STATEMENT>'
```

`--template` 还支持 `xtb` 和 `crest`；参数经 `--param` 传入，例如
`--param=--gfn=2` 或 `--param=--quick`，以各模板白名单为准。
每条 `--parent '<ATTEMPT_ID>'` 需对应一条 `--relation '<RELATION>'`。
使用 `ag <命令> --help` 查看完整参数。

以下两条会产生远程副作用，分别按需调用，每次都需要人在 Mac 对话框中确认：

```bash
ag submit '<ATTEMPT_ID>'
ag cancel '<ATTEMPT_ID>'
```

所有子命令支持 `--json`。作业命令的退出码：0 成功，1 取消或校验不通过，
2 环境/连接错误，3 提交或状态不确定。程序失败或 `unknown` 不能作为重提同一 Attempt 的理由。

## Skill 部署

将下列六个 Skill 软链接到 `~/.codex/skills/`，源码保持在长期保留的仓库目录中：

- `auto-g16-study`
- `auto-g16-recipes`
- `auto-g16-structures`
- `auto-g16-literature`
- `auto-g16-chemdraw-structures`
- `auto-g16-gaussian-learning-library`

部署前检查已有 `auto-g16-*` 副本和软链接。将旧部署移到
`~/.codex/skills-disabled/` 的新备份子目录，保留可恢复副本，避免加载旧卡片。
不要覆盖现有条目，也不要把新链接指向以后会删除的临时 worktree。

在确认目标名称空闲后，对六个名称分别执行以下命令（先替换两个占位符）：

```bash
mkdir -p "$HOME/.codex/skills"
ln -s '<REPO_ROOT>/skills-next/<SKILL_NAME>' "$HOME/.codex/skills/<SKILL_NAME>"
```

检查软链接指向的 `SKILL.md`，在 Codex 的新会话中确认六个 Skill 可见。
后续改动直接进入 `skills-next/` 并通过 Git 审阅，不另行编辑部署副本。
部署步骤仅安装卡片，不代表授权提交计算。

## 开发检查

在选定的 Python 环境中运行：

```bash
python -m pytest ag/tests
python -m pytest skills-next
# 只暂存本任务文件后，提交前扫描：
python ag/tools/scan_sensitive.py --staged
```

单元测试使用离线替身，不连接真实集群。真实验证按任务单执行并在 PR 描述中记录；
PR 首行写 `Task: Tn`，不放机器信息或研究数据。

## 旧架构归档

2.7.0 及以前的旧架构已移至 [archive/](archive/README.md)，冻结内容仅供参考，不再维护；原始状态见 tag `v3-frozen`。

- [旧代码](archive/auto_g16/)、[旧脚本](archive/scripts/)、[旧 Skills](archive/skills/)、[旧测试](archive/tests/)
- [旧文档](archive/docs/)、[旧 contracts](archive/contracts/)、[旧配置](archive/config/)
- [旧 studies](archive/studies/)、[旧模板](archive/templates/)、[旧 requirements](archive/requirements/)
- [OWNER_DECISIONS.md](archive/OWNER_DECISIONS.md)、[CHANGELOG.md](archive/CHANGELOG.md)、[旧 pyproject.toml](archive/pyproject.toml)
- [environment.yml](archive/environment.yml)、[environment-chem.yml](archive/environment-chem.yml)

上列两个继续维护的辅助 Skill 已迁入 `skills-next/`。停用的 `offline-tests.yml` 已移除；
[ag-tests](.github/workflows/ag-tests.yml) 继续检查新架构。

Auto-Gaussian 使用 [MIT License](LICENSE)。
