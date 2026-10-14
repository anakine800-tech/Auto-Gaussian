# IRC 本地事实与端点比对

`ag facts ATTEMPT --study STUDY --json` 对 Gaussian IRC 新增 `irc` 对象：

| 字段 | 含义 |
|---|---|
| `direction` | `forward` / `reverse` / `both` / `unknown`，来自 route 或打印的路径方向 |
| `point_count` | 已报告的唯一 `(path, point)` 数；不计 TS 点 0、试探 SCF 或未完成校正步 |
| `max_points` | 日志或 route 中的上限；缺失为 `null`，不猜默认值 |
| `reached_max_points` | 达到上限；上限与到达标记均缺失时为 `null` |
| `corrector_failed` | 是否出现明确校正器失败；单次 `Delta-x Convergence NOT Met` 不是最终失败 |
| `path_complete_reported` | 是否打印对应方向的完成标记；不代表到达极小值 |
| `energies` | 按日志顺序，每个路径点的 `path`、`point`、`energy_hartree`；缺失能量为 `null` |
| `energy_kind` | 当前为 `scf`：路径点前最后一次 SCF 能量，Hartree；不是相关能、自由能或势垒 |
| `end_geometry` | 有可读的已报告路径点几何时为 `irc_end.xyz`；否则 `null` |

`irc_end.xyz` 优先取路径点后的 `CURRENT STRUCTURE`，否则取该点前的完整 orientation；不取后续失败校正器的试探结构。多方向日志只导出最后报告的路径点，并附警告；工作流应分别使用 forward/reverse Attempt。多个 Link1 中取最后一个 IRC 步；后续 Opt 的几何不会污染 IRC 末点。现有 `final.xyz` 仍由通用 cclib 解析产生。

末点文件不存在时使用独占创建；已存在的普通文件若与本次解析结果逐字节相同，则直接沿用，并继续重新生成 `facts.json` / `final.xyz`。内容不同时报错“irc_end.xyz 与当前日志解析结果不一致，需人工核对”，保留所有既有产物，不更新 facts 或 final。符号链接及非普通文件仍拒绝沿用。这既允许重复提取事实，也避免替换已供后续优化或人工审阅使用的几何；命令不会自行清理末点。

## 比对命令

```sh
ag irc-compare --ts demo-001-ts \
  --forward demo-002-forward --reverse demo-003-reverse \
  --reactant reactant.xyz --product demo-005-product-opt \
  --study demo --out comparison.json --json
```

`--ts`、`--forward`、`--reverse` 接受已有 `facts.json` 的 Attempt ID 或目录；两个目标也可用单帧 XYZ。再优化后的 forward/reverse Attempt 使用 `final_geometry`，IRC Attempt 使用 `irc.end_geometry` 并标注“未再优化”。普通 XYZ 不声明已再优化。ID 在当前 study 的 `attempts/` 下解析，或使用 `--study`；也可通过本地配置的 `local.studies_root` 查找唯一 ID。不会连接服务器或自动调用 `facts`。

`--out` 必填，始终写 JSON 报告；`--json` 控制终端是否输出完整 JSON。既有目标文件/链接均报错，并使用独占创建防止检查后发生覆盖。命令只创建指定报告，不创建目录、不更新 Attempt、日志、facts 或其他产物。退出 0 表示报告生成成功；科学结构结果应读 `status`，不能把退出 0 当作“匹配”。

报告包含四种端点—目标配对、最合适的正向/对调对应关系、每端“匹配 / 不匹配 / 无法确定”、差异键及双方距离、质子归属、立体中心、反应物→产物成断键/键级变化。对应关系并列时保留两种，不随意定向。已知电荷、多重度或元素序列与 TS 不同会写入 `input_issues`。

逐行原子编号就是本命令采用的映射：不重排原子，同元素原子交换仍须人核对。复用 `ag.geometry` 的有限数 XYZ 读取、图和立体工具；不以整体 RMSD 作为身份判据，碎片平移或旋转本身不会导致不匹配。XYZ 缺少电荷时沿用 TS 电荷推键，并保留这一假设；缺少 TS 电荷、推键失败或立体中心无法指派时不能确认匹配。

为防 IRC 延长键被单一截止距离误判为已断裂，距离在共价半径和的 1.2–1.5 倍之间作为歧义区，小于 0.6 倍作为过近接触。两侧推断图都确认的 1–3 非键接触除外；存在于任一侧的候选键仍保留歧义。阈值是保守几何启发式，不是键级或离子对的科学定义。无歧义的连接冲突可报“不匹配”，有歧义且无确定冲突时报“无法确定”，并保留距离供人审阅。

“匹配”只表示当前结构证据一致，不代表双向 IRC 已验证。MaxPoints、校正器、路径完成、TS 单虚频及振动方向、端点 Opt+Freq 与人工审阅仍需结合判断。本任务不新增远程命令，不运行计算，不签署 study。

## 来源与离线验证

仅改写归档脚本的纯逻辑思路：`archive/skills/auto-g16-ts-irc/scripts/ts_irc.py` 的 `audit_irc_endpoint_provenance` / `propose_endpoint_components`；`archive/skills/auto-g16-main-group-open-shell/scripts/open_shell_ts_irc.py` 的 `build_irc_acceptance`。不导入旧模块，不沿用旧合同、执行器或审阅流程。

合成水 IRC 日志覆盖正常完成、MaxPoints、校正器失败、截断、LQA CURRENT STRUCTURE、双路径和 Link1。合成小分子端点覆盖正向/对调、连接不符、拉长键、质子转移、立体翻转和碎片平移；CLI 检查必填输出、拒绝覆盖、仅创建报告、未知数据不补造。测试位于 `ag/tests/test_irc.py`，可运行 `python -m pytest ag/tests`。
