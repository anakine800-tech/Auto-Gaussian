# T30：解析波函数稳定性结果

分支：`codex/t30-wavefunction-stability`；依据：负责人本次 T30 指令。
依赖：#240、#242 均已合并，分支包含两者。

## 目标与范围

提取 Gaussian Stable 的诊断原文，防止把正常终止或旧作业的稳定性结论当作当前波函数稳定的证据。
允许改动：
- `ag/src/ag/_parse_outputs.py`：稳定性事实提取。
- `ag/tests/test_stability.py`：合成日志、facts CLI、prepare 与既有拒绝条件回归。
- 本任务单：验收与字段语义说明。

## 验收与输出

1. 仅当 route 含 `stable` 或日志出现 `The wavefunction …` 诊断行时，Gaussian facts 新增两个稳定性字段；普通作业不写入，防止无信息的字段扩展改变已签字 facts 的哈希。新增字符串 `wavefunction_stability`：`stable`、`internal_instability`、`rhf_to_uhf` 或 `unknown`。
2. `wavefunction_stability_line` 保存对应原文行（保留空白，去除换行符）；无诊断行时为 null。未知/截断诊断保留原文且值为 `unknown`。
3. 当前 Gaussian 作业内多次诊断取最后一条；新 route、Link1 或新 Gaussian 作业开始时清除旧结论，避免跨作业误用。该字段表示最后打印的诊断，需与独立的 `termination` 一起审阅；正常终止本身不证明稳定。
4. prepare 已接受 `stable` 和 `stable=opt`，用合成输入核对 manifest、输入字节及重新校验；不更改输入校验器，不放宽资源、路径、外部程序、Link1、坐标和父 chk 限制。
5. Stable=Opt 在本工作流仅作为诊断作业；Gaussian 可能在该作业内改变电子态，是否采用新电子态由人决定。ag 不自动修复、重提或接受结果，不改研究状态、卡片或执行路径。

## 验证与交付

- 普通 Opt/Freq/SP 的 facts 键集合与 main 完全相同；Stable 无诊断仍为 unknown/null，非 Stable route 的诊断仍保留。
- 新测试只用合成日志片段和水输入；覆盖三类诊断、未知/缺失/截断、多次诊断、作业边界、错误/不完整终止、facts JSON 持久化及 prepare。
- `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，暂存精确文件后敏感信息扫描及 diff 检查。
- 真实环境验证：不需要；不连接集群、不运行 Gaussian，不将解析测试当作科学验收。
- CI：推送任务分支后手动触发现有 ag-tests，成功后提 PR；PR 第一行 `Task: T30`。
- 读取并处理监督方评论；等待 T32（分析命令不得改写 facts.json）合并后再 rebase；合并仅由人执行。
- 停止条件沿用 AGENTS.md：范围外修改、同一问题修两次仍失败、真实环境意外；实际阻塞写入 PR。
