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
