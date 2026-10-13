# CREST 构象初筛

## 1. 适用范围

主族闭壳层单分子的构象搜索，可中性或带电；也可从已审阅的 TS 初猜进行下述约束构象搜索。不包括金属、开壳层、双分子结合或反应路径搜索。

## 2. 前置条件

已签字的结构及审阅过的 XYZ；电荷、多重度和溶剂明确；CREST 模板可用。闭壳层 `--uhf 0`，不从 XYZ 推断电荷。

## 3. 输入模板

方案允许的 CREST 程序参数是：`--gfn2`、`--gfnff`、`--alpb <溶剂>`、`--chrg <整数>`、`--uhf <整数>`、`--ewin <数>`、`--quick`、`--squick`、`--mquick`。只用当前模板声明实际接受的组合和值，不自行追加参数。

首选 GFN2-xTB；正丁烷气相验收可用 `--gfn2 --chrg 0 --uhf 0 --ewin 3 --quick`。溶液相加经过模板验证的 ALPB 溶剂。快速模式选一种；GFN-FF 是另一个方法选项，不能把其能量当 GFN2 能量。

```text
ag prepare --study <study_id> --template crest --input <reviewed.xyz> --tier simple --walltime 04:00:00 --label crest
```

上述是通用 prepare 参数，还须按当前 `ag prepare --help` 将完整 CREST 参数交给模板；它们不是随意透传的 shell 命令。准备后走确认摘要及 `ag submit`。完成后 status → fetch → facts，读取 `crest_conformers.xyz` 等声明输出，调用 `ag dedup` / `ag cluster`。保留 xTB 相对能量 3 kcal/mol 内的候选，去重后研究最多 20 个、验收最多 10 个进入 DFT。

非手性分子（如正丁烷）聚类时使用 `ag cluster` 的 `--mirror`：将互为镜像的 gauche+ / gauche− 合并为一个代表，简并度为 2，只需对该代表做一个 Opt+Freq。手性分子不要使用 `--mirror`，避免把不同立体异构体混入同一代表；运行前仍核对当前接口支持。

### 约束构象搜索

做 TS 构象搜索时，固定正在形成或断裂的键的距离，以免搜索离开目标反应区域。先与人核对 TS 初猜、XYZ 原子编号和目标距离，再用 `--constraints <文件>` 交给 `ag prepare --template crest`。例如将以下内容保存为本地约束文件（编号和值须按实际结构修改）：

```text
$constrain
  force constant=0.5
  distance: 1, 2, auto
$end
```

`auto` 采用输入结构中的距离，也可填目标距离（Å）；angle、dihedral 的值以度为单位。这里的“固定”是约束势，搜索后仍需检查实际键长。[xTB 约束语法说明](https://xtb-docs.readthedocs.io/en/latest/xcontrol.html#constraining-potentials)。

文件只接受单个 `$constrain` / `$end` 块，以及 `force constant=<数>`、`atoms:`（逗号分隔的编号或递增范围，如 `1-3,5`）、`distance:`（2 个编号）、`angle:`（3 个编号）、`dihedral:`（4 个编号）；后三者末项为有限数值或 `auto`。编号从 1 开始且不得超过 XYZ 原子数。其他指令、注释和附加内容均拒绝，包括 `$write`、`$external`、`$set`。

prepare 将原文件字节作为 `constraints.inp` 纳入 bundle 和逐文件 SHA-256 摘要，模板自动加 `--cinp constraints.inp`；不要通过 `--param` 直接传 `--cinp`。提交前同时审阅约束内容、输入结构、完整参数和摘要中的文件哈希。

搜到的结构只是 TS 候选，仍需用 DFT 重新优化为 TS，并逐个按 [TS 卡片](ts.md) 审阅：恰好一个虚频，且振动方向与目标成键/断键坐标一致。需要 IRC 验证时，必须双向完成并识别端点，才能声称验证；CREST 正常终止不能代替 TS 验证。

## 4. 资源建议

正丁烷和约 50 原子以内快速验收先用 simple（8 核、12 GB）、04:00:00；更柔性或已有耗时证据时提出 general（22 核、50 GB）、24:00:00。复杂体系确有需要再考虑 complex（44 核、120 GB）；模板负责线程数，不能额外拼接线程参数。

## 5. 提交前检查清单

- XYZ 与签字结构匹配，电荷和 `--uhf` 已显式给定；ALPB 溶剂与 study 一致，气相无溶剂参数。
- 参数在模板白名单内；摘要将 Gaussian route 标“不适用”，改列完整 CREST 参数、资源和目录。
- 窗口、候选上限和快速模式已说明；等人说“提交”及点击系统对话框。

## 6. 结果判据清单

- CREST 正常终止，`n_conformers` 为非零，能量与输出构象数量对应；不能只凭文件存在就接受。
- 逐一审阅连通性、质子位置和立体化学，排除变化为其他物种的结构并记原因。
- dedup / cluster 输出能追溯代表、成员、相对能量、阈值和筛选原因；截断到数量上限时写明覆盖局限。
- 把代表构象及其简并度展示给人签字。聚类样本数可能含重复采样，不等于物理简并度；复制工具输出时保留这一含义，未确认则不用于最终布居。
- 记录初筛能量是 xTB 能量，随后用同一 DFT 方法精化；快速搜索完成不代表已穷尽全构象空间。

## 7. 常见失败与处理

异常结束、缺构象或解析不一致先停下报告，转 failure-diagnosis。搜索改变物种时先确认化学身份，不能自动进入原物种 DFT 集合；提出新 Attempt，等人确认。

## 8. 常见坑

- 排队不代表失败，也不能仅凭排队推断节点满载；不以重复计算解决等待。来源：`skills/auto-g16-rtwin-pbs/references/environment-and-failures.md`。
- 不同初始构象可能在 DFT 后合并，最终布居前还要再去重。来源：`skills/auto-g16-view-rt-win/references/conformer-workflow.md`。
