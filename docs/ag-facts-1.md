# ag-facts/1：Gaussian 解析与重新解析

`facts.json` 记录本地已取回输出中的事实，`schema` 为 `ag-facts/1`。
`normal` 只说明终止证据完整，不代表优化、频率、TS/IRC 或科学验收通过。
本页补充现行解析规则；字段缺失或为 `null` 不等于零或通过。

## route 与子任务

`job_sections` 按日志顺序记录 `index`、`start_line`、`end_line`（均从 1 开始，
两端包含）、`route`、`termination`、`start_kind` 和 `internal_step`。
route 必须是两条虚线包围、以 `#` 开头的完整块；正文中的 `# OF POINTS`
等不是 route。每行只去掉 Gaussian 打印的行首一个空格，直接拼接、不插入空格，
保留原有词间空格，因此 `Fre` / `q` 和 `Op` / `t` 能正确还原。
首段、显式 Link1 及内部步骤使用相同规则。顶层 `route` 来自第一段。

未知类型、异常步骤序号或边界仍记录在 `parser_warning` 中。
警告不直接决定顶层终止；字段来源仍由 `fact_sources` 指向具体段，
未知尾段不得借用之前的频率事实。`freq_step_converged` 等收敛判据不变。

## 顶层 termination

Gaussian 顶层 `termination = normal` 必须同时满足：

- 至少有一个子任务；每个子任务都有对应的正常结束标记，且本段正常结束。
- 全日志 `Normal termination of Gaussian` 次数等于子任务数。
- 全日志没有 `Error termination`（现有其他异常终止识别同样保留）。

只有多余终止行的尾段不算完成的子任务。缺标记、次数不一致、截断或未结束尾段
仍为 `incomplete`；错误终止优先为 `error`。有完整终止证据但类型未知的子任务
可以得到顶层 `normal`，并保留 `parser_warning`；依赖类型的事实仍须独立核对。
已验证的不完整取回记录继续将 `normal` 降为 `incomplete`，不改变原有规则。

新增可选字段：

```json
{"parser": {"ag_version": "4.2.2", "rules": "route-join-v1"}}
```

`ag_version` 是生成这份 Gaussian facts 的 ag 包版本；`rules` 标识解析规则。
旧 facts 可以没有此字段。原有 `ag_provenance` 继续记录解析器 checkout 的提交号与
dirty 状态，两者不能代替日志哈希、科学审阅或签字。

## 本地重新解析

```sh
ag facts <Attempt> --reparse --dry-run --out <study外的新文件.json>
ag facts <Attempt> --reparse
```

只允许 `fetched` Attempt，读取 `outputs/` 的本地日志，不创建远程连接。
必须已有可读的 ag-facts/1 JSON 对象；符号链接、路径越界、缺日志、坏 JSON
或非有限数值均拒绝。不会改日志、几何、状态或任何引用旧哈希的记录。

先由人审阅 dry-run。`--out` 必须是 study 外、尚不存在的 `.json` 文件，父目录须存在。
预览文件是新版 facts；标准输出是 JSON 报告，包含 `old_sha256`、`new_sha256`、
`differences`、`references_to_old_sha256` 和 `dry_run`。study 内不创建锁或临时文件，
所有原文件字节和 mtime 保持不变。`--dry-run` 和 `--out` 必须一起使用。

`differences` 用 JSON Pointer 逐字段定位（数组逐元素）；每项包含 `path`、
`change`（`added` / `removed` / `changed`）及适用的 `old` / `new` 值。
不把缺失值与 `null`、布尔与数字混同；解析器来源元数据的变化也如实报告。

正式执行先在临时文件校验新版，再以独占创建方式复制旧版原始字节到
`facts-history/<UTC时间戳>-<旧SHA-256前12位>.json`，核对完整 SHA-256 并同步归档，
最后原子替换 `facts.json`。已存在的归档即使内容相同也拒绝覆盖。
发布失败时旧 facts 仍在，已完成且校验过的归档保留，未完成的暂存副本清理。
报告另含相对 study 的 `archive` 路径。

引用扫描仅检查 study 内 `.md` / `.json` / `.csv` 文本中的完整 64 位旧哈希，
输出排序后的相对文件名；短哈希或更长十六进制字符串的子串不算匹配。
扫描不修改文件，也不自动判断签字有效性。主会话在 study.md 记录 Attempt、原因、
旧/新哈希前 12 位；负责人重新确认受影响的已签内容，旧签字不自动继承。

普通 `ag facts` 的相同内容不写入行为，以及原 `--refresh` 的归档兼容行为保持。
`--refresh` 与 `--reparse` 互斥。T99 的解析错误处理流程使用 `--reparse`。

## thermo / profile 的段来源

顶层 `route` 保留首段含义，不代表频率段口径。thermo / profile 通过
`fact_sources.n_imag` 选择 `job_sections` 中的 Freq 段，并核对频率、收敛与热校正
字段来自同一段。GoodVibes 只接收这段的频率、能量、质量、转动和对称性数据；
内部段缺少启动 banner 时仅补入已核对的日志级程序版本，计算选项和公式不变。

`frequency_source` 和 `electronic_energy_source` 记录 Attempt、段号、原日志行范围、
完整 route 和 protocol。无 SPC 时电子能取 Freq 段；显式 SPC 时按其
`fact_sources.energies.scf` 指向的段取值，仍执行原配对检查。不会自动使用同一日志
尾随 SP 的能量替换频率电子能。配对使用 Freq 段的实际几何。

同一 Attempt 的 Opt/Freq 方法、基组、基函数类型、溶剂模型、溶剂或色散不一致，
列出差异并拒绝；积分网格仍仅警告，不作为口径等价推断。T82 的保守 protocol
解析保持不变：`SCRF=Check` 等缺少显式口径的 Freq 段不能借用 Opt route，
R/U 前缀不自动等同。旧版 facts 缺少段来源时需要重新生成；多段 thermo 缓存
缺少与当前 facts 一致的来源记录时需要重新运行 thermo。单段 Freq 的数值不变。
