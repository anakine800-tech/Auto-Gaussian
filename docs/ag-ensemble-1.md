# ag-ensemble/1


```json
{
  "schema": "ag-ensemble/1",
  "created_at": "UTC ISO 时间",
  "ag": { "...": "facts.ag_provenance() 的输出" },
  "study_id": "string",
  "label": "string 或 null",
  "inputs": {
    "merged": { "path": "analyses/<group>/<name>.json", "sha256": "hex" },
    "xyz":    { "path": "analyses/<group>/<name>.xyz",  "sha256": "hex", "file": "<name>.xyz" },
    "thermo": { "path": "analyses/....json", "sha256": "hex" }
  },
  "charge": 0,
  "hydrogens": "heavy | polar | all",
  "energy_basis": "shared_hartree | per_source_not_comparable",
  "units": { "energy": "Hartree", "relative": "kcal/mol", "population": "fraction" },
  "routes": [ { "label": "string", "attempts": ["attempt_id", "..."] } ],
  "references": { "xtb": 1, "sp": 3, "opt": null },
  "warnings": ["string"],
  "candidates": [
    {
      "candidate": 1,
      "xyz_frame": 1,
      "geometry_sha256": "hex",
      "sources": ["route label", "..."],
      "route_members": [ { "route": "label", "member": 4, "relative_kcal_within_route": 0.12 } ],
      "xtb_relative_kcal": 0.0,
      "sp":  { "attempts": ["id"], "ambiguous": false, "energy_hartree": -1.0, "relative_kcal": 0.0 },
      "opt": { "attempts": ["id"], "ambiguous": false, "termination": "normal", "n_imaginary": 0,
               "energy_hartree": -1.0, "relative_kcal": 0.0 },
      "thermo": { "attempt": "id", "qh_G": -1.0, "relative_G_kcal": 0.0, "population": 0.42 },
      "missing": ["opt_freq", "thermo"],
      "notes": ["string"]
    }
  ],
  "unmatched_attempts": [ { "layer": "sp | opt | thermo", "attempt": "id", "reason": "string" } ]
}
```

- 某层没有对应的 Attempt 时，该键为 `null`，同时出现在 `missing` 里。
- `ambiguous: true` 时，`energy_hartree` 和 `relative_kcal` 为 `null`。
- `xyz.file` 只是文件名，与清单在同一目录；前端只按这个文件名读，并核对 `xyz.sha256` 和每帧的 `geometry_sha256`。
- 数值只有有限浮点数，没有 NaN；未知值用 `null`。

## 数值与关联语义

- `candidate` 沿用 dedup `kept.index`，可不连续；`xyz_frame` 是输出 XYZ 中从 1 开始的帧序号。
- `geometry_sha256` 只覆盖该帧的元素/坐标行原始 UTF-8 字节，包括空白及原始换行；不含原子数与注释行。
- `route_members.member` 是 dedup member 的 `source_frame`，不复制 `source` 路径。
  路线内相对能由保存的 member 与 excluded 能量按各路线最低值换算；未知能量为 null。
  `relative_energy_kcal` 在 dedup 里可能是全局基准，因此不能直接当成路线内基准。
- `references` 的 SP/Opt 参考只使用唯一匹配且有能量的候选；等能时取最小候选编号。
  Opt 状态/虚频数原样来自 facts 的 `termination` / `n_imag`，不以正常结束或零虚频作为收录门槛。
- 多个 Attempt 匹配同一层时保留全部 ID，标记 ambiguous；Opt 的状态与虚频数也置 null，避免挑选某个 Attempt。
  歧义层列入 missing；无有效 SP facts 时 SP 为 null，并在 notes 记录原因。
- `thermo` 只有唯一 Opt 对应且只有一行时才收录。重复表行或歧义 Opt 不挑选，写入 unmatched_attempts。
  qh_G、relative_G_kcal、population 沿用原表，保留其原始数值精度、参考与归一化全集，即使本清单只覆盖其中一部分。
- 未传 `--thermo` 时 inputs 不包含 thermo；未传的计算层仍列入 missing。未知数值为 null。
- 文件引用都在 study 内，拒绝符号链接。清单生成前复核读取的证据字节未变化；输出两文件均独占创建。
- 将生成清单用明确相对路径引用在 study.md/review.md 后，`ag review manifest` 会递归收录引用的证据。
  ensemble 本身不修改 study.md、Attempt 或源分析文件。

## 可选局部构象描述（T70）

仅在显式传入至少一个 `--dihedral-bins` 或 `--report-distance` 时，增加顶层
`descriptors`、`bin_summary` 及每个候选的 `local`；schema 仍为 `ag-ensemble/1`，
已有字段不变。不传时不增加这些字段，JSON 与 Markdown 保持原有输出
（对比字节时固定生成时间、ag 版本来源及输入证据）。不会自动沿用 merged 中的描述符。

```json
{
  "descriptors": {
    "dihedral_bins": [{"atoms": [1, 2, 3, 4], "boundaries": [-90, 90], "names": ["cis", "trans"]}],
    "distance_pairs": [[5, 14]]
  },
  "bin_summary": [{"bins": ["cis"], "count": 3, "lowest_candidate": 1, "lowest_layer": "sp"}],
  "candidates": [{"candidate": 1, "local": {
    "dihedrals": [12.3], "bins": ["cis"], "near_boundary": false, "distances": [1.587]
  }}]
}
```

以上为新增字段片段，候选仍保留前述全部原有字段。

- 两个参数均可重复，语法、校验及定义内容复用 `ag dedup`。编号按候选
  `xyz_frame` 对应的 XYZ 帧，从 1 开始；不会改编号或使用 Opt 后的几何替代。
  `descriptors` 只包含 `dihedral_bins` 与 `distance_pairs`，不提供接触指纹参数或字段。
- `local.dihedrals` 为有符号度数，范围 `[−180,180)`；`local.distances` 为 Å，
  两者各自按命令行定义顺序排列。`local.bins` 是相应的**组名字符串**，
  与 dedup 的从 1 开始的组号不同；省略组名时沿用 `bin1`、`bin2` 等。
  第 1 组为 `[b1,b2)`，最后一组跨周期回到第一个分界；恰在分界时归入从该分界开始的组。
- `near_boundary` 为布尔值，任一二面角到任一分界的周期差严格小于 5° 时为 true，
  只供审阅，不改变组名。未请求的数组为空；仅报告距离时为 false。
- `bin_summary` 按分组组合首次出现的顺序排列，`count` 包括该组合的全部候选。
  每组按 thermo → opt → sp → xtb 查找首个有非空可用能量的层级，
  仅在该层有能量的候选中取最低值，不跨层比较，也不要求全组都有该层。
  分别使用 `qh_G`、唯一匹配的 Opt/SP `energy_hartree`、`xtb_relative_kcal`；
  ambiguous 层不参与，路线不可比较时 xTB 不参与。Opt 沿用原有收录语义，
  不以正常结束或零虚频过滤，因此此汇总不代表科学验收。
  等能时取最小 `candidate` 编号（不是 XYZ 帧号）。
  无任何可用能量时 `lowest_candidate` 与 `lowest_layer` 均为 null。
- 仅报告距离时，所有候选归为一个 `bins: []` 组合。不会按分组合并、删除或重新排序候选。
- Markdown 候选表相应增加“分组”“近边界”“距离（Å）”列，并追加分组汇总表。
  数组的顺序与 JSON 定义一致。越界编号、共线等无法定义的二面角会报告具体帧与定义，
  不发布部分清单；参数格式错误沿用 dedup 的诊断文本。
