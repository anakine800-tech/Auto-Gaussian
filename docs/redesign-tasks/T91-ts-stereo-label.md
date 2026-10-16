# T91：TS 立体标签——由 TS 几何判定将生成的产物构型，并给出通道归属建议

## 分支与目标

- 分支：`codex/t91-ts-stereo-label`；基于最新 main（含 T80），一张任务单一个 PR。**开发机做。**
- **目标：** 新增脚本 `ts_stereo_label.py`：对一个或多个 TS Attempt，借助**参照产物结构**和**原子映射**，判断每个 TS 将生成的产物在各立体中心上的构型，给出产物构型标签（例如“Cβ-R / C5-S”）；同时核对催化剂自身立体中心在 TS 中未变；并生成一份**通道归属建议** CSV 草稿，由人确认后再使用。
- **为什么：** HSS 已遇到“中间体 CIP 标签与产物相反”的问题；直接按产物构型标注 TS，可以避免中间体和产物 CIP 定义不同造成的混淆。通道归属目前要人逐个对照。
- **负责人 10-17 决定：**
  - 标签按**产物构型**定（不是按进攻面）；
  - 不从 TS 几何推断键级：用参照产物分子（键级确定）+ 原子映射，在 TS 几何中按映射的相邻原子计算**局部手性（带符号体积）**，与参照产物在同一中心的手性比较，相同则与参照同构型，相反则构型相反；
  - 同时核对催化剂立体中心（例如 HSS 的 23R/24S）在 TS 中没有改变，作为自检；
  - 输出通道归属**建议**草稿，人确认后生效；`ag channel-coverage` 仍不推断通道归属。
- 资料：`skills-next/auto-g16-structures/scripts/check_species.py`、`make_gaussian_input.py`（`read_molecule(..., preserve_explicit_h=True)`）、`cdx_stereo.py`；`skills-next/auto-g16-study/references/intake-template.md`（第 4 节原子对应、第 5 节立体通道表）；`docs/ag-channel-coverage-1.md`。

## 允许改动的路径

- 新增 `skills-next/auto-g16-structures/scripts/ts_stereo_label.py`。
- 新增 `skills-next/auto-g16-structures/tests/test_ts_stereo_label.py` 和合成夹具。
- `skills-next/auto-g16-structures/SKILL.md`：加“TS 立体标签”一节。
- `skills-next/auto-g16-recipes/cards/ts.md`：只在结果判据或审阅相关处补一句用法，不改规则；如无合适位置，只改 SKILL.md。
- `docs/redesign-tasks/T91-ts-stereo-label.md`：本任务单。
- 不改 `ag/` 下任何文件。

## 要做的

### 1. 输入

```
python ts_stereo_label.py --study <study> --name <名称>
    --ts <Attempt>[,<Attempt>...] [--geometry final|input]
    --product <参照产物结构文件，study 内> --product-map <映射 CSV>
    [--catalyst <参照催化剂结构文件> --catalyst-map <映射 CSV>]
    [--channels <通道表 CSV>]
    [--min-chirality 0.05]
```

- 参照产物：study 内经 T80 核验并签字确认的结构文件（.cdxml / .mol / .sdf），所有关心的立体中心均已指定（未指定的中心报错）；用 `read_molecule(..., preserve_explicit_h=True)` 读入。
- 映射 CSV：列 `reference_atom`（参照文件中从 1 开始的序号）、`ts_atom`（TS 几何中从 1 开始的序号）。**只需映射到每个立体中心及其全部相邻原子**（含 H；参照文件中没画出的 H，用 `reference_atom` 写 `H@<中心序号>` 表示该中心上的隐含氢）。可以从开题模板的原子对应表（atoms.csv）导出。映射中元素必须一致，否则报错。
- TS 几何：默认取 Attempt 的 `final_input.xyz`（TS 优化后的最终几何）；`--geometry input` 取输入几何（用于检查初猜）。
- 催化剂参照与映射：同样格式，可选。
- 通道表 CSV：可选，至少含 `channel_id`、`product_branch` 两列（与 `ag channel-coverage` 的通道表一致）；`product_branch` 的写法须能与本脚本输出的产物构型标签对应（在文档中规定格式，例如 `C12:R;C15:S`，用参照产物的原子序号）。

### 2. 判定

- 对参照产物的每个已指定四面体立体中心：取参照分子中该中心的相邻原子顺序及 RDKit 手性标记；在 TS 几何中按映射取同样顺序的相邻原子坐标，计算以中心为原点的带符号体积（单位向量，范围约 −1 到 1）。
- 符号与参照分子按同一顺序计算出的手性一致 → “与参照相同”，标签取参照 CIP；相反 → “与参照相反”，标签取相反 CIP。
- |带符号体积| < `--min-chirality`（默认 0.05，TS 中正在成键的中心通常处于部分锥化状态）→ 该中心记为 `unknown`，并报告数值；不猜。
- 对假手性中心（r/s）、依赖其他中心的 CIP（翻转一个中心可能改变另一个的标签）：检测到时该中心标 `needs_review` 并说明，不给自动结论。
- 催化剂：同法核对每个立体中心，与参照不同 → 报告中醒目警告（TS 中催化剂构型改变通常意味着结构或映射有错）。

### 3. 输出

- `analyses/ts-labels/<名称>/labels.json` / `.md`：每个 TS 的每个中心（参照序号、TS 序号、带符号体积、与参照关系、标签或 unknown / needs_review）、产物构型标签、催化剂自检结果、输入文件相对路径与 SHA-256。
- 给了 `--channels` 时，另写 `channel-suggestions.csv`：列 `attempt`、`product_configuration`、`suggested_channel_id`（与通道表 `product_branch` 唯一匹配时填，否则空）、`status`（固定写 `pending_confirmation`）、`note`（不匹配、多重匹配、有 unknown 中心等）。**脚本不修改通道表，不生成 `ag channel-coverage` 的输入。**
- 目录已存在就拒绝；拒绝符号链接；不出 study。

## 不允许

- 不从 TS 几何推断键级或成键；不推断 CIP 优先级（全部来自参照分子）。
- 不自动归类，不修改通道表或 study.md。
- 测试只用合成分子。

## 测试

- 合成例子：一个手性中心的 SN2 型 TS（构型翻转）与保持构型的 TS，标签分别相反 / 相同。
- 两个立体中心同时生成的合成 TS（类似 Michael 加成形成两个相邻中心）：四种组合标签正确。
- 中心几乎平面（带符号体积很小）→ unknown；隐含氢映射 `H@<中心>` 正确处理；映射元素不符、映射缺相邻原子 → 报错。
- 催化剂中心被人为翻转 → 自检警告。
- 通道建议：唯一匹配、不匹配、多重匹配三种情况；`status` 恒为 `pending_confirmation`。
- 开发中只跑相关测试；推送前本地跑一次全量 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，之后以 CI 为准。敏感扫描与 `git diff --cached --check`。

## 真实环境验证

- 纯本地。合并前在开发机上用合成样例完整跑一遍，结果写进 PR。
- 合并前由 HSS 主会话用 HSS 已有的 TS 或 TS 初猜只读跑一次（输出写到 study 以外），与 HSS 通道表的人工判断对照，结果只汇报监督方，不写进 PR 和公开仓库。

## 停止条件

- 带符号体积方法在合成 TS 上无法区分构型（给出数据后停下）。
- 需要从 TS 几何推断键级才能完成判定。

## 合并前审阅与交付

- 需要监督方审阅：是。
- PR 描述第一行：`Task: T91`。
- 合并只由负责人操作。
