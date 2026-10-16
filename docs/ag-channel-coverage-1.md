# ag-channel-coverage/1

`ag channel-coverage` 只读 UTF-8 通道 CSV 与其明确引用的 `ag-ensemble/1` 清单，
不推断归属、不读取清单指向的几何/Attempt、不重算能量或布居、不作覆盖合格判定。
输出为独占创建的同名 JSON 和 Markdown；任一个已存在时拒绝，源文件不变。

## 输入与路径

```bash
ag channel-coverage --study '<STUDY_DIR>' \
  --channels analyses/channels.csv --out analyses/channel-coverage.json \
  --imbalance-ratio 0.5
```

CSV 的 `channel_id`、`product_branch`、`ensemble_manifests` 必填，`note` 可选且可空。
一行一个通道；通道编号不可重复。支持 UTF-8 BOM、CSV 引号、带空格的文件名。
多个清单以分号分隔，空项拒绝；清单路径必须相对 study 根目录。
同一清单在同一通道内或多个通道重复均拒绝，防止重复计数。
缺列、缺值、重复或错误引用报告 CSV 行号（多行字段用记录起始物理行）。

```csv
channel_id,product_branch,ensemble_manifests,note
channel-a,R,analyses/a.json;analyses/a-extra.json,补充采样
channel-b,S,analyses/b.json,
```

CSV 与输出必须位于 study 的 `analyses/` 下；清单必须在 study 内，拒绝符号链接及越界。
提供 `--study` 时文件参数相对 study 根目录；可给目录或配置的 study ID。
省略时从 `--channels` 的当前工作目录相对路径推断 study，`--out` 仍相对 study 根目录。
清单的 `schema`、`study_id`、汇总所需字段与能量单位会校验。
读取字节在发布前复核，避免同次报告混入不同修订。

## 输出字段

顶层字段：

| 字段 | 含义 |
| --- | --- |
| `schema` | 固定 `ag-channel-coverage/1` |
| `created_at` | UTC ISO 时间 |
| `ag` | 当前 ag 来源版本信息 |
| `study_id` | 当前 study 编号 |
| `inputs.channels` | CSV 的 `{path, sha256}` |
| `imbalance_ratio` | 本次阈值，有限数，范围 `[0, 1]`，默认 `0.5` |
| `channels` | 按 CSV 顺序的通道汇总 |
| `product_branches` | 按分支首次出现顺序的分支汇总 |

每个通道有 `channel_id`、`product_branch`、`note`；每个分支有 `product_branch` 和
`channel_ids`。二者都有以下字段：

| 字段 | 含义 |
| --- | --- |
| `manifests` | 全部引用清单的 `{path, sha256}` 列表 |
| `manifest_count` | 清单数 |
| `candidate_count` | 清单中候选记录总数，不跨清单重新去重 |
| `by_route` | 路线标签 → 候选数；候选每条 `sources` 路线各计一次，保留零候选路线 |
| `sp_count`, `opt_count`, `thermo_count` | 对应层非 null 的候选数，含歧义及能量未知的已保存记录 |
| `ambiguous_count` | SP 或 Opt 的 `ambiguous=true` 的候选数；同一候选两层歧义只计一次 |
| `unmatched_attempts_count` | 各清单 `unmatched_attempts` 条目总数，不跨清单或层去重 |
| `lowest` | 最高可用层最低候选，或 null，格式见下 |
| `lowest_unavailable_reason` | 无最低候选时的原因，否则 null |
| `lowest_by_manifest` | 每清单 `{manifest: {path, sha256}, lowest, unavailable_reason}` |
| `warnings` | `{message, manifest?: {path, sha256}}` 列表 |
| `imbalances` | `{metric, count, maximum, threshold}` 列表，无提示时为空 |

路线数的和可大于候选数，因为一个候选可能被多条路线找到。
分支直接合计所含通道的清单；相同候选在不同清单出现仍分别计数。
SP/Opt/热化学数表示保存记录的覆盖，**不是有效能量数、正常终止数或科学验收数**。
`unmatched_attempts_count` 同样不是唯一 Attempt 数。

## 最低候选的层级与边界

先选整个汇总组中有有限、非歧义能量的最高层：`thermo > opt > sp > xtb`，
再在该层选最小值。不把低层更负的能量与高层混排。
thermo 用保存的 `qh_G`，Opt/SP 用 `energy_hartree`，单位为 Hartree。
Opt 不按终止状态或虚频数过滤；这只是清单数值汇总。
xTB 只使用 `energy_basis=shared_hartree` 的 `xtb_relative_kcal`，单位 kcal/mol。
空集合、所有能量未知、只有不可比较路线的 xTB 时 `lowest=null`，原因为 `no_usable_energy`。

```json
{
  "channel_id": "channel-a",
  "manifest": {"path": "analyses/a.json", "sha256": "64位十六进制哈希"},
  "candidate": 3,
  "routes": ["crest", "directed"],
  "layer": "opt",
  "energy": -157.1,
  "unit": "Hartree"
}
```

候选编号保留原值，所有来源路线都保留，不挑一条代表路线。
等能时按清单相对路径的字典序、候选编号升序选一个，便于稳定复现；不代表其他等能候选被排除。

**xTB 的特殊限制：** `ag-ensemble/1` 不保存 xTB 绝对能，不同清单的相对能零点无法对齐。
若最高层是 xTB 且有能量的候选来自多个清单，则整体 `lowest=null`，原因是
`xtb_relative_energies_have_different_manifest_zeros`；保留 `lowest_by_manifest`，
不从各清单的 0 kcal/mol 推断全局最低候选。
只有一个清单有可用 xTB 值时，最低值仅覆盖该清单的可用证据。

`per_source_not_comparable` 总会产生警告；输入清单的 warnings 也保留并绑定清单。
多个清单间的 SP/Opt/thermo 数值比较不会验证方法、体系或热化学条件相同，报告提醒人工审阅。
最低候选只描述可用记录，不表示完整势能面上的最低结构或已验证 TS。

## 不均衡与证据收录

分别对所有通道、所有产物分支计算 `opt_count`、`sp_count`、`candidate_count` 的最大值。
当本项计数 **严格小于** `maximum × imbalance_ratio` 时记录提示；相等不提示。
最大值为零时没有提示，比例为零可关闭提示。无提示不等于覆盖充分或平衡已获认可。

所有生成的文件引用都用 study 相对 `path` 和原始字节 SHA-256，不含绝对文件路径。
将报告以 `analyses/channel-coverage.json` 引用到 study.md/review.md 后，
`ag review manifest` 可递归收录 CSV、引用的 ensemble 清单及其分析证据。
本命令不修改 study.md 或签字，也不验证 ensemble 内部所引源文件的当前哈希；
该递归证据检查留给审阅清单。
