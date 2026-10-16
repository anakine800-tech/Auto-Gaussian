# ag-irc-review/1

`ag irc-review` 是本地证据汇总，不作科学验收。JSON 的 `schema` 固定为
`ag-irc-review/1`；同名 Markdown 包含四条判据、数值、来源与行号。
前端应显示每条原始状态和缺口，不能将工具汇总显示为科学通过。

## 调用与文件边界

```sh
ag irc-review --study '<STUDY_DIR>' --ts '<TS>' \
  --forward '<FORWARD_IRC>' --reverse '<REVERSE_IRC>' \
  --pair 1-2 --pair 1-3 \
  --forward-reference '<EXPECTED_FORWARD_ATTEMPT_OR_XYZ>' \
  --reverse-reference '<EXPECTED_REVERSE_ATTEMPT_OR_XYZ>' \
  --forward-endpoint '<FORWARD_OPT_FREQ>' --reverse-endpoint '<REVERSE_OPT_FREQ>' \
  --irc-compare analyses/comparison.json --out analyses/new-review.json
```

TS、两侧 IRC 及可选端点 Opt+Freq 必须在同一 study，两侧 IRC 分属独立 Attempt，
不接受 `direction: both`。输入显式坐标的哈希须符合 manifest；方法、基组、色散及
溶剂用现有 `protocol()` 核对，原子数及元素行序须一致。所有输入只读，拒绝符号链接与越界。
`--study` 接受目录；省略时用当前 study 目录或绝对 TS Attempt 路径推定 study。
reference 可为 study 内的单帧 XYZ 或 Attempt；它代表人的预期，不从数学方向推测身份。

正常输出为 analyses 下的新 `.json`；为只读核对已签字的 study，也允许显式指定
study 外的新输出目录。这个例外仅适用于输出，所有输入仍限同一 study。
目标父目录须已存在；JSON、同名 `.md`、`<stem>.forward.xyz`、`<stem>.reverse.xyz`
任一个存在就拒绝。四个文件独占创建，失败只撤回本次创建的文件。
不读取集群配置、不连接远端、不生成或刷新 facts，不改任何 study 证据。

## 顶层字段

| 字段 | 含义 |
| --- | --- |
| `schema`, `ag_version` | 格式与工具版本 |
| `notice` | 仍需人工审阅的说明，前端应展示 |
| `ts` | TS Attempt ID |
| `protocol` | method、basis、dispersion、solvent_model、solvent |
| `pairs` | 去重排序后的目标原子对数组，编号从 1 开始 |
| `units` | energy 为 hartree，relative_energy 为 kcal/mol，distance 为 angstrom |
| `thresholds` | 本次使用的所有数值阈值 |
| `inputs` | 所有读入文件的 `{path, sha256}`；path 相对输入 study 根目录 |
| `directions` | `forward`、`reverse` 两个独立方向对象 |

`inputs` 包含实际读入的 manifest、输入、facts、XYZ、IRC 日志和比对报告。
SHA-256 绑定原始字节；写出前复查全部来源未变化。报告不包含 study 绝对路径。
判据内的 `source`、`log`、`reference`、`ts`、`manifest` 等文件引用复用 `{path, sha256}`。
日志行号从 1 开始；缺少来源或数值为 `null`，不写 NaN，不以零代替未知。
JSON facts 的依据包含 `field` 和该字段在 facts.json 的 `line`，不是虚构的日志行号。

## 每方向字段与路径帧

| 字段 | 含义 |
| --- | --- |
| `attempt`, `log` | IRC Attempt ID 和日志路径/哈希 |
| `criteria` | continuity、energy_drop、midpoint、endpoint 四条判据 |
| `summary` | 工具核对完成，待人工审阅 / IRC 未完成 |
| `unresolved` | 不满足或未知的判据键名 |
| `warnings` | 例如起点与 TS facts 电子能不一致 |
| `ts_reference` | IRC 第 0 点与 TS facts 的能量、差值、TS facts 来源 |
| `stop_reason` | completed / max_points / corrector_failed / truncated |
| `last_accepted_point` | 最后一个非零已接受点号，无则 null |
| `path_geometry` | 输出 XYZ 文件名 path、frame_index_base=0、frame_count，以及可选的 sha256 |
| `points` | 起点及按日志顺序接受的路径点；不包括失败的试探点 |

`path_geometry.sha256` 为对应 `<stem>.forward.xyz` / `<stem>.reverse.xyz` 文件原始字节的
SHA-256（64 位小写十六进制），在写出前由待写 XYZ 字节计算。该字段为可选字段，
旧报告没有此字段仍合法，前端应显示“未核对哈希”；不回写已有报告，schema 保持 `ag-irc-review/1`。

每个 `points[]`：

```json
{
  "point": 1,
  "path": 1,
  "point_line": 100,
  "energy_hartree": -75.001,
  "energy_line": 90,
  "energy_kind": "scf",
  "geometry_line": 101,
  "geometry_kind": "current_structure",
  "geometry_frame": 1,
  "relative_energy_kcal_mol": -0.6275094740631,
  "distances_angstrom": {"1-2": 1.4, "1-3": 1.6}
}
```

示例为虚构格式。相对能量 = (该点 SCF − 该方向第 0 点 SCF) × 627.5094740631；
负值表示比起点低。降能 `drop_kcal_mol` 使用相反符号，正值表示降能。
优先取各点接受标记前的最后一个 SCF；RCFC 起点未重算 SCF 时可读该起点明确打印的
`Energy From Chk`，`energy_kind=scf_from_checkpoint`，保留原精度和行号。
绝不从路径汇总表舍入值或 TS facts 补写缺失的起点能量。与 TS facts 相差超过 1e-5 Hartree
只警告，两个原值都保留；缺失的起点能量使相对能量及降能为 null。

几何优先取接受标记紧随的 `CURRENT STRUCTURE`，否则使用该点标记前的 orientation。
`geometry_kind` 为 current_structure / preceding_orientation；RCFC 第 0 点没有取向表时，
可使用已核对 manifest 哈希的 IRC 输入坐标，标为 irc_input、日志 geometry_line=null。
不跨点借用能量/几何；不把后续 Link1 的数据混入 IRC。重复接受点号会报错。

XYZ 第 0 帧为该方向 TS 起点，其后依次存有几何的已接受点，保留行序与原坐标。
缺几何的点仍保留在 JSON，`geometry_frame=null`，不制造 XYZ 帧；后面的帧号连续编号，
前端必须按 geometry_frame 映射，不能假定点号总等于帧号。缺能量时仍可导出已有几何。

## 判据与状态

1. `continuity.status` 仅为 `tool_checks_passed` / `not_met` / `unknown`，永不为 met。
   `steps` 记录相邻点有符号能量变化、按原子编号刚体对齐的全原子 RMSD 及两点日志行号。
   `evidence_lines` 记录校正失败、路径完成、MaxPoints、正常/错误结束的行号。
   已知失败、超过容许噪声的回升、能量/RMSD 跳变为 not_met；缺点数据、点号不连续、
   缺完成/MaxPoints 或正常终止证据为 unknown。已知失败优先于同时存在的缺失。
   最高状态仍要求人工审阅 SCF/电子态连续性和逐点几何。
2. `energy_drop` 记录实际降能、阈值、起末点电子能、对应能量行号和日志引用。
   降能 ≥ 阈值为 `met`；正降能低于阈值且① tool_checks_passed、③④ met 时为
   `met_by_endpoint_optimization`，理由写“由端点优化补证”；其余为 not_met 或未知数值时 unknown。
   默认阈值 3 kcal/mol，`--energy-threshold` 可显式指定方案阈值；不因端点补证自动调低。
3. `midpoint.pairs` 逐对记录 TS、最后路径点、预期端点距离及中点，形成/断裂方向和状态。
   目标距离小于 TS 时末点须严格小于中点，否则须严格大于中点。
   预期距离与 TS 相差 < 0.05 Å 的原子对为 unknown。全部满足才 met；任一明确不满足为
   not_met，否则缺 reference/末点/不能区分为 unknown。来源包含 TS、reference 与末点日志位置。
4. `endpoint` 记录 facts 字段、失败/缺失字段、身份和末点来源。
   优先检查端点输入逐原子坐标偏差 ≤ 1e-4 Å，满足时 `provenance=coordinates`（坐标一致）。
   否则须同时满足：manifest 的 `endpoint_of` 关联指向该方向（即 `ag graph` 使用的来源记录），
   且输入与最后已接受点按固定行序刚体对齐的全原子 RMSD ≤ 1e-3 Å，复用 `aligned_rmsd`，不交换原子。
   后备路径记为 `provenance=endpoint_of_and_alignment`（来源关系加对齐核对）；
   只有来源声明而结构不同仍报错，缺末点几何也不能建立关联。
   两条路径均记录 `input_max_displacement_angstrom`、`input_aligned_rmsd_angstrom` 和中文 `provenance_note`；
   顶层 `thresholds.endpoint_aligned_rmsd_angstrom=0.001`。两条来源路径都不成立则报错，不写出报告。
   检查独立 Opt+Freq、normal、opt_converged、freq_step_converged、完整模式数及 n_imag=0。
   同时保留 facts 自带的 frequency_convergence、fact_sources 与 job_sections；旧 facts 缺少时为 null。
   若端点日志存在，绑定其哈希并列出终止、优化、频率的 log_lines 作为人工回查位置；
   这些行号不另行推断跨计算段的结论，最终字段仍按现有 facts 核对。
   身份读取 irc-compare 的该方向唯一 assignment/comparisons；比对引用的 TS、末点 Attempt
   必须相同，提供 reference 时还须对应同一预期来源。错用其他 Attempt/预期来源报错。
   匹配且极小点字段齐全满足为 met；不匹配或极小点条件失败为 not_met；缺报告、方向不确定
   或字段缺失为 unknown。`identity` 保留报告引用、原始结论与字段定位。

数值噪声默认 0.01 kcal/mol，可用 `--energy-noise` 调整。相邻点跳变沿用 scan-peak：
绝对能量变化 > 20 kcal/mol 或 RMSD > 0.5 Å。阈值与异常都列出，人工仍须解释化学连续性。

只有① tool_checks_passed、②③④ met 或 met_by_endpoint_optimization 才显示
“工具核对完成，待人工审阅”；其他情况显示“IRC 未完成”并列出 unresolved。
停止原因优先顺序为校正失败、截断/异常终止、MaxPoints、报告完成。
达到 MaxPoints 并不自动令四条判据失败；首点失败的 last_accepted_point 为 null，②③为 unknown。
