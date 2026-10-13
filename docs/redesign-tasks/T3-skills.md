# T3：编排 Skill、任务卡片、文献 Skill

分支：`codex/redesign-t3-skills`　位置：本地或云端（最后的部署步骤在本地）　依赖：T0 已合并　预计：1.5～2 天

## 目标

写出让 LLM 能按卡片推进研究的三个 Skill。规格见方案第 5 节、决策 D2、D9～D12、D14、D20。这是“新功能只写卡片”的核心，写作质量比代码量重要。

## 允许改动的路径

- `skills-next/auto-g16-study/`
- `skills-next/auto-g16-recipes/`
- `skills-next/auto-g16-literature/`
- `skills-next/tests/test_skill_format.py`（格式检查）

## 不允许

- 改旧 `skills/` 目录（只读参考）。
- 在 Skill 里写主机名、用户名、本机或服务器路径（用配置键或占位符）。
- 让 Skill 指示 LLM 绕过 `ag` 直接用 ssh、scp、qsub、qdel，或在 Skill 中出现“自动重提交”“失败后自动修复重跑”。
- 在 Skill 中引入审批包、receipt、哈希链、owner 等旧治理概念。哈希只在 `ag` 的确认摘要中出现。

## 格式

每个 Skill 一个目录，`SKILL.md` 带 YAML 头（`name` 与目录名相同，`description` 写清楚何时使用），格式参考旧 Skill（例如 `skills/auto-g16-view-rt-win/SKILL.md` 及其 `agents/openai.yaml`）。`SKILL.md` 正文尽量短，细节放进 `references/` 或 `cards/`，用相对链接引用。

## 步骤

1. **`auto-g16-study`**：
   - `SKILL.md`：方案 5.2 的九项职责，写成 LLM 每次被调用时的固定流程（先读 `study.md` 和 `ag list --json`，再判断阶段）。包含一张“阶段 → 下一步 → 用哪张卡片”的决策表。
   - `references/study-md-template.md`：`study.md` 模板，小节为：目标、体系（物种、电荷、多重度、溶剂、温度）、方法与依据、计划、进度日志、里程碑签字（结构 / 代表构象集合 / 最终结果，每项含日期和签字人）、结论。
   - `references/confirmation-summary.md`：提交确认摘要的固定格式，必须包含：每个 Attempt 的结构（SMILES 或结构名）、电荷与多重度、立体化学警告、方法与依据（DOI 或“兜底方法”声明）、完整 route、模板、档位、核数、walltime、远程目录（相对 ag 根）、bundle 哈希前 12 位、提交后集群总核数；批量提交时用表格。摘要最后一句固定为“回复‘提交’后我会运行 `ag submit`，届时 Mac 上会弹出确认框，需要你亲手点击。”
   - `references/acceptance-methods.md`：方案 5.5 的兜底与验收方法表。
   - `references/lessons.md`：经验条目的格式（现象、原因、处理、建议修改哪张卡片的哪一节），以及“只起草到 study 的 `lessons/`，不改 Skill 文件”的规则。
   - `references/unknown-and-failures.md`：`unknown` 和 `failed_presubmit` 的含义（方案 4.3），LLM 遇到时只报告、不处理；失败时转 `failure-diagnosis` 卡片。
2. **`auto-g16-recipes`**：
   - `SKILL.md`：卡片索引表（卡片名、适用范围、前置条件），以及每张卡片固定的 8 个小节说明（方案 5.3）。
   - `cards/opt-freq.md`、`cards/sp.md`、`cards/rdkit-screen.md`、`cards/crest-screen.md`、`cards/thermo.md`、`cards/failure-diagnosis.md`，每张都写满 8 个小节。要点：
     - `opt-freq`：极小点判据 `n_imag = 0`；对 < 50 cm⁻¹ 的低频说明处理方式；`%nprocshared`、`%mem` 与档位一致；`opt freq` 合并在一个作业。
     - `crest-screen`：CREST 参数白名单（方案 4.7）；能量窗口与上限（方案 5.5）；之后调用 `ag dedup`/`ag cluster`，把代表构象及其简并度交给人签字。
     - `rdkit-screen`：调用 `auto-g16-structures` 的初筛脚本，再 `ag dedup`。
     - `thermo`：`ag thermo` 的参数（D21）；简并度从 `ag cluster` 的输出抄写；输出表格写进 `study.md`。
     - `failure-diagnosis`：按 `facts.json` 的 `error_hint` 分类给出修改建议（l9999 → 从上一步几何重启并调整优化参数；l502 → SCF 选项；walltime → 提高档位或时长；极小点出现虚频 → 沿虚频方向扰动后重新优化），每条都以“提出新 Attempt，等人确认”结尾。
   - 从旧文档中挖掘真实踩过的坑，写进对应卡片的“常见坑”，每条注明来源文件（只读参考）。至少阅读：`skills/auto-g16-rtwin-pbs/references/environment-and-failures.md`、`protocols.md`、`scientific-workflows.md`；`skills/auto-g16-view-rt-win/references/conformer-workflow.md`、`chemistry-boundaries.md`；`skills/auto-g16-ts-irc/SKILL.md`。与 RTwin 链路相关、对 Mac 直连不再适用的坑不要搬。
3. **`auto-g16-literature`**：方案 5.4 的协议；`references/group-literature.md` 留一个空表格（作者、年份、DOI、体系、方法），由人以后填写本组文献。
4. **格式检查** `skills-next/tests/test_skill_format.py`：每个 `SKILL.md` 有合法 YAML 头且 `name` 与目录名一致；所有相对链接指向存在的文件；每张卡片都有 8 个固定小节标题；全部文件不含 IPv4 地址和真实用户目录路径（正则 `/(home|Users)/[A-Za-z0-9_.-]+`）。

## 合并后的部署（本地，由人确认后在 main 检出上执行）

1. 把 `~/.codex/skills/` 下现有的 `auto-g16-*` 目录移动到 `~/.codex/skills-disabled/`（只是本地移动，可随时恢复）。
2. 为三个新 Skill 建软链接：`~/.codex/skills/<name>` → `<仓库 main 检出>/skills-next/<name>`。
3. 在 Codex 新开一个对话，问“列出你可用的 auto-g16 Skill”，确认只出现新 Skill。

## 验收标准

- 格式检查通过（CI 的 `ag-tests` 会一并运行）。
- 监督方审阅：用正丁烷做一次“纸面演练”——按 Skill 写出从 `ag init` 到 `ag thermo` 的完整步骤和一份示例确认摘要，放在 PR 描述里。
- L1 验收中实际使用后，根据结果再迭代一轮（另开 PR）。

## 停止条件

- 发现需要 `ag` 提供方案里没有的命令或参数才能写通某张卡片：在 PR 中列出，不要自己发明命令。

## PR 要求

PR 描述第一行 `Task: T3`；附上纸面演练和示例确认摘要；列出从旧文档搬过来的“常见坑”条目及来源文件。
