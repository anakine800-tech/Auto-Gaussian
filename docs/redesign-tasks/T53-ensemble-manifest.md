# T53：`ag ensemble` 输出构象集合清单（`ag-ensemble/1`）

## 分支与目标

- 分支：`codex/t53-ensemble-manifest`；基于最新 main，一张任务单一个 PR。
- **目标：** 新增本地命令 `ag ensemble`，把一个构象集合的信息整理成一份 JSON 清单，供人工审阅（K4：代表构象集合）和前端构象集合页（T54）使用。清单包括：去重后的候选、每个候选来自哪条采样路线、各层能量（xTB、DFT 单点、Opt+Freq、热化学）、哪一层的计算还缺。另外输出一份同名的 Markdown 表格，前端没做好时也能直接审。
- **要防的事故：** 现在这些信息分散在 dedup JSON、coverage 报告、各 Attempt 的 facts 和 ag-thermo 表里。K4 审阅时只能靠人或 LLM 手动对，容易对错行，或者把不同路线、不能直接比较的 xTB 能量放在同一列排序。
- **原则：** 只汇总已保存的结果，不推断科学关系，不重新计算布居，不选代表构象，不做验收判断。
- 资料：`ag/src/ag/dedup.py`（`--source` 输出：`kept`、`excluded`、`sources`、`members`、`energy_basis`、`xyz_sha256`）、`ag/src/ag/coverage.py`（`input_geometry`、`same_geometry`、`energy_rows`）、`ag/src/ag/thermo.py`（`ag-thermo/1`）、`ag/src/ag/facts.py`（`ag_provenance`、`resolve_attempt`）。

## 允许改动的路径

- 新增 `ag/src/ag/ensemble.py`。
- `ag/src/ag/cli.py`：只在第 159 行的分析命令元组里加 `'ensemble'`，不改其他行。
- 新增 `ag/tests/test_ensemble.py` 和 `ag/tests/fixtures/` 下的合成小分子数据（如需）。
- 新增 `docs/ag-ensemble-1.md`：格式说明（内容即附录 A，可补充示例）。
- `ag/README.md`：分析命令一节加一段用法。
- `docs/LESSONS.md`：不需要改；有新经验再加。
- `docs/redesign-tasks/T53-ensemble-manifest.md`：本任务单。

**不改 `coverage.py`、`dedup.py`、`thermo.py`：** 只 import 它们的函数。如果发现必须改它们，停下询问。

## 执行补充（2026-10-16）

- 监督方批准范围扩大：允许 `ag/tests/test_smoke.py` 仅在固定断言分析命令列表的一处追加 `ag.ensemble`，不改其他行。

## 命令

```
ag ensemble --merged <dedup --source 输出的 JSON>
            --out <新文件，扩展名 .json；必须与 merged JSON 在同一目录，且在 study 的 analyses/ 内>
            [--label <物种或集合名，自由文本，≤ 80 字>]
            [--route LABEL=ATTEMPT_ID[,ATTEMPT_ID...]] ...   # 采样路线对应的 Attempt，可重复
            [--sp ATTEMPT_ID ...]                            # DFT 单点 Attempt，或者一个 JSON 列表文件
            [--opt ATTEMPT_ID ...]                           # Opt+Freq Attempt
            [--thermo <ag-thermo/1 JSON>]
            [--study <study 目录或 ID>]
```

- 输出 `<out>.json` 和同名 `<out>.md`；两者已存在任一个就拒绝，不覆盖。
- `--route` 的 LABEL 必须出现在 merged JSON 的 `routes` 里；Attempt 必须存在于该 study。不给 `--route` 时，路线只显示标签。
- 匹配候选与计算：用 `coverage.input_geometry` 读 Attempt 的输入几何，用 `coverage.same_geometry` 和候选几何比较（固定原子顺序，不对齐、不改编号），电荷取 merged JSON 的 `charge`，氢的处理取它的 `hydrogens`。
  - 一个 Attempt 匹配到 0 个候选：放进 `unmatched_attempts`，写原因。
  - 一个 Attempt 匹配到多个候选：同样放进 `unmatched_attempts`，原因写“匹配多个候选”，不挑。
  - 一个候选匹配到同一层的多个 Attempt：全部列出，该层标 `ambiguous: true`，不选，也不算相对能。
- SP 能量取 facts 的 `energies.scf`，只接受 `program == gaussian`、`termination == normal`、route 不含 opt/irc/scan/force/freq（与 coverage 的规则相同）；不满足的写进该候选的 `notes`，该层视为缺失。
- Opt 层只取 facts 里已有的值：`termination`、虚频数、`energies.scf`；不判断是否合格。
- 热化学：按 `--thermo` 表里的 `attempt_id` 对应到 Opt Attempt，只复制表里的 `qh_G`、`relative_G_kcal`、`population`，**不重新计算**。表里有但对不上任何候选的行，放进 `unmatched_attempts`。
- xTB 能量：
  - merged JSON 的 `energy_basis == "shared_hartree"`：给出 `xtb_relative_kcal`（相对本集合最低者）。
  - `energy_basis == "per_source_not_comparable"`：**不给**跨路线的 `xtb_relative_kcal`（设为 null），只在每个 `route_members` 里保留该路线内部的相对能，并在顶层 `warnings` 写明“各路线 xTB 能量不可直接比较”。
- 相对能（SP、Opt）都以“本清单中该层已匹配、且无歧义的最低值”为参考，参考的候选编号写进顶层 `references`。
- `missing`：每个候选列出缺的层（`sp`、`opt_freq`、`thermo`），只依据本次给的输入；没给 `--opt` 时，所有候选都缺 `opt_freq`。
- 几何哈希：对候选在 XYZ 中那一帧的文本（元素和坐标行，原样）做 SHA-256；前端用它核对帧没有被替换。
- 文件引用：清单里引用的 merged JSON、XYZ、thermo JSON，统一写在键名为 `path` 的字段里（相对 study 根目录），并附 SHA-256。这样 `ag review manifest` 能自动把它们收进证据清单。
- 不在清单里写任何绝对路径。dedup `members` 里的 `source` 字段可能含路径，**不要复制**，只保留路线标签和帧序号。
- Markdown：一张表，一行一个候选：编号、来源路线、xTB 相对能（或按路线）、SP 相对能、Opt 状态和虚频数、qh_G 相对值、布居、缺失层、备注；表上方写参考、能量基准和警告；表下方列出 `unmatched_attempts`。

## 不允许

- 不重新计算布居、不做 Boltzmann 加权、不选代表构象、不判断覆盖是否足够。
- 不跟随清单以外的路径；不读 study 外的文件；拒绝符号链接（复用 `study.local_path`）。
- 不改已有 Attempt、dedup 输出或 study.md。
- 测试不用研究数据。

## 测试

- 用合成小分子（例如正丁烷或乙二醇，2–3 条路线、5–8 个候选）构造：dedup `--source` 输出、几个 SP Attempt、几个 Opt Attempt 和一张 ag-thermo 表。
- 覆盖：
  - 正常匹配，各层能量和参考正确。
  - `per_source_not_comparable` 时 `xtb_relative_kcal` 全为 null，`warnings` 有提示。
  - 未匹配、匹配多个候选、同层多个 Attempt（`ambiguous`）。
  - SP 非正常结束或 route 含 freq：写进 `notes`，该层视为缺失。
  - thermo 表中多余的行进入 `unmatched_attempts`；布居值与表中逐位相同。
  - XYZ 被替换（哈希不符）：拒绝。
  - 输出已存在：拒绝；`--out` 不在 merged 同目录或不在 analyses/ 内：拒绝。
  - 输出里没有绝对路径（扫描 JSON 和 Markdown）。
  - 对生成的清单运行 `ag review manifest`，引用的 merged、XYZ、thermo 都被收录。
- 按附录 A 写一个 JSON Schema 风格的字段检查测试，保证输出与格式说明一致（T54 照这份格式开发）。
- `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`；暂存精确文件后运行敏感扫描与 `git diff --cached --check`。

## 真实环境验证

- 不连集群。合并后，在 HSS 的 K4 审阅中实际使用：HSS 会话在计算机上对给体或 M0 生成清单，负责人把 Markdown 表转给监督方。结果是否可用记在 PR 评论里，不写研究数据。

## 停止条件

- 必须修改 `coverage.py`、`dedup.py`、`thermo.py`。
- 附录 A 的格式在实现中需要改字段：先在 PR 里提出，等监督方确认（T54 在同时开发）。
- 匹配规则需要对齐或改编号才能工作。

## 合并前审阅与交付

- 需要监督方审阅：是（新格式，前端依赖）。
- 修改 AGENTS.md：无。
- PR 描述第一行：`Task: T53`。
- 合并只由负责人操作。

---

## 附录 A：`ag-ensemble/1` 格式（T53 与 T54 共用）

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
