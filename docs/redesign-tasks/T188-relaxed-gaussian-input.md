# T188：Gaussian 受控放宽输入

## 分支与目标

- `codex/t188-relaxed-gaussian-input`，一单一 PR；来源 V4.8 W7 后端。
- 从最新 main 的干净隔离工作树开始。T186 放宽接口已随主线接入开发代码；本单复用其提交、归属和计数实现，最终组合验证与负责人显式启用仍须另行完成。
- 事故依据：现有科学语法白名单挡住合理的高级输入，但直接跳过校验会允许 Link1 隐藏超额资源、外部命令或越界文件；放宽标记丢失会把未核验方法冒充已核验方法。

## 允许改动的路径

- `ag/src/ag/gaussian_input.py`，可新增职责明确的 `gaussian_relaxed.py`：分段语法与不能放宽的检查。
- `ag/src/ag/attempt.py`、`cli.py`：显式 prepare 选项、输入包内附件、冻结标记、摘要及 verified_files 重验。
- `ag/src/ag/scan_peak.py`：读取不可变标记并明确拒绝放宽输入来源。
- `ag/src/ag/autonomy_policy.py`、`autonomy_submission.py`、`approval.py`、`submit.py`：仅与 T186 合作接入放宽规则、逐次提醒和禁止回退；不另写提交/计数/路由实现。
- `ag/tests/test_gaussian_input.py`、`test_gaussian_sections.py`、`test_core.py`、`test_scan_peak_ts_input.py`、`test_approval.py`、`test_autonomy_policy.py`；可新增 `test_gaussian_relaxed.py`、`test_relaxed_attempt.py`。
- `ag/README.md`、`docs/DEVELOPING.md`、`docs/redesign-tasks/T188-relaxed-gaussian-input.md`。

## 要做的

1. 默认行为与旧输入/manifest/bundle 字节保持兼容。只有显式选项允许放宽，适用于普通 Gaussian 模板；不默默解除 gaussian-cp 的专用科学边界或其它程序限制。
2. 按 W7 支持 Gen/GenECP、SCRF=Read、NBO 附加段，TS 与 ModRedundant，Link1，Geom=Check/AllCheck，以及扫描超出原白名单（多于两个坐标、更多步数、通配符、笛卡尔冻结、Units、多种附加段）。补齐有显式坐标的 GaussView 格式 Connectivity：首块按顺序逐原子列行、整数索引/有限键级，后续沿用旧尾段数据语法；Check/AllCheck+Connectivity 拒绝，不声称完整科学分段顺序已验证。另补 Opt GEDIIS/NoTrust、SCF NoIncFock/NoDIIS、IRC GS2/CalcAll、Freq HPModes/SaveNormalModes 八项。这些是输入接受范围，不等于科学方法或 profile 已支持；Stable 的 relaxed 语法及自主 policy 原有边界不扩展。
3. 每个 Link1 段均需核验资源、Link0 文件名和 External；不能只检查第一段。每段显式给出核数和内存，与所选档位及现有内存规则一致，不继承、不补齐或猜测未写明的资源。
4. 只运行既有审阅模板，不放宽 shell 或模板参数。各段 Link0 文件仅普通 basename、不得目录、绝对路径、父目录、链接、环境变量展开；命令型 External 的大小写、括号、换行写法均不能绕过。不能让附加段的文件指定或间接输入逃离本 Attempt，也不得让输入覆盖已上传的脚本/清单或只读父 chk。无法证明满足这些底线的写法先拒绝并报告，不执行探测。
5. @include 只接受主输入直接引用已显式收集、按最终字节绑定哈希的普通附件；只支持单层，附件再次引用即拒绝。别名、缺失文件、越界和嵌入危险指令必须检查；不从任意路径隐式收集文件。主文件和附件同样执行底线检查。只有安全可核实的输入能进入目录分配，源文件不改。
6. Geom=Check/AllCheck 及 Opt=ReadFC/RCFC 只能依赖同 Attempt 可追溯的 chk 或既有专用父 chk 机制；不得凭文件名读取其它 Attempt。本轮只开放 ReadFC/RCFC 两个词，ReadCartesianFC 别名仍拒绝。放宽力常数路径只证明来源，不声称 Hessian 存在、适用或坐标取向匹配，不代替严格路径原有取向检查。对无显式几何/电荷/多重度的段，不伪造 science 字段；摘要显示来源或未知以及完整各段 route。
7. 与 T186 约定一个不可变的放宽标记、确切跳过检查清单和方法口径“未核验”字段；prepare 与 verified_files 共用同一校验器及附件清单。提交摘要逐次显示该标记、跳过项、完整输入/资源/哈希、scan-peak 不可用和 profile 可能不支持的事实。已放宽输入不得因解析恰好成功而自动变回“已核验”。
8. 自主提交仅在计划与有效规则均明确允许时使用方法例外；仍核验有效期、次数、节点/路由、持锁、每段收敛下限和所有输入字节。普通输入不受影响。T186 接口已有实现，但不能只凭 allow_relaxed 字段或本单文档启用自主运行；最终组合证据和负责人显式启用仍是前提。
9. scan-peak 从冻结 manifest 拒绝放宽来源，避免旧白名单之外的扫描被误解释；不扩大 thermo/profile/facts 的科学接受条件。前端标记由 T197 单独做，本单给出实际字段和合成示例。

## 离线验收

每类放宽输入有最小合成接受用例；每条底线有拒绝用例，覆盖第二/第三 Link1 段、空段/重复资源、资源继承与不匹配、大小写/换行 External、单层附件及嵌套拒绝、缺失/越界/链接、危险文件名、包文件被替换、冻结标记/跳过清单被篡改、父 chk 与 Geom=AllCheck、力常数读取的有/无来源、Connectivity 单独与组合尾段、八项新选项以及旧严格输入不变。分别验证 prepare、verified_files 和提交前复核，失败不产生远程动作。

本地只跑受影响相关测试；全量 ag/Skills 交给 CI，并在真实验证前对最终源码组合统一运行一次，不做 AST 比对。
敏感扫描用私有词表、精确暂存、noreply 身份及当前 head CI。不要用仅接受异常的测试冒充该类语法可用。

## 真实环境验证（敏感，合并前必需）

当前仅授权开发与离线测试，不连接集群、不修改真实配置、不提交或取消。合并前按下列精简非研究矩阵准备 9 组、10 个 Attempt；每类语法保留离线覆盖，后置类别不冒充真实通过。固定单次 prepare/submit，status/fetch 观察次数执行前列明。一个输入可以覆盖数个类别，但须明确对应；底线拒绝只在本地执行，绝不发往服务器探测。

交最终提交 SHA、对象/电荷/多重度/方法/完整 route/资源、输入和 bundle 哈希、精确命令和次数、预期与停止条件，由协调方汇总 T185/T186 最终组合后请负责人批准实际执行并亲手确认。取消/改投接口不阻塞此验证。任何真实 UNKNOWN、哈希不符、SSH 错误或异常结束立即停，不重新提交。真实验证缺失不得合并。

## 交付

PR 首行 `Task: T188`；说明最终字段、允许及仍拒绝的语法、方法未核验和工具限制、底线矩阵、兼容性和真实验证缺口。敏感生产路径在 T185/T186 后交 Claude 审阅一次定稿，之后只复核回应意见的改动；审阅意见未处理完不得合并，协调方的独立合并授权不覆盖本 PR。开发对话不合并、不发布或部署。范围外、同问题两次未解决或底线语义不清时向协调方报告，独立工作继续。

## 合并前验证准备清单（未执行）

这是待负责人审阅的独立非研究矩阵：**9 组、10 个 Attempt**，没有真实 prepare、提交或结果。
每段均显式填写最终档位核数和不超过档位内存 85% 的 Gaussian 内存。
8 核、Gaussian 10 GB、30 分钟只保留为候选，合成档位 12 GB 不代表真实配置。
最终入口、档位、资源、walltime、代码 SHA、输入/bundle 哈希与执行授权全部待填。
输入接受、文件来源证明、程序正常结束、科学验收分别记录，不能互相替代。

### 精简矩阵

| 组 | 对象；电荷/多重度 | 候选完整 route | 预期观察与证据边界 |
|---|---|---|---|
| R01 | 水；0/1 | `# HF/Gen SP` | H/O 的 STO-3G 基组块被读取，SP 正常结束；Gen。 |
| R02 | 氯化氢；0/1 | `# HF/GenECP SP` | H/STO-3G、Cl/LANL2DZ 基组及 ECP 被读取；不证明生产 ECP 方法受支持。 |
| R05 | 平面氨；0/1 | `# HF/STO-3G Opt=(TS,CalcFC,ModRedundant) NoSymm` | `B 1 2 F` 约束被识别；仅启动不算整行通过，正常结束也不构成 TS 验收。 |
| R06 | 水；首/第二段显式0/1，第三段电子态来自前段 chk | 1. `# HF/STO-3G SP`；2. `# HF/STO-3G SP Geom=Check Guess=Read`；3. `# HF/STO-3G SP Geom=AllCheck Guess=Read` | 三个 Link1 正常结束，后段来源绑定本 Attempt 前段 `water.chk`；缺省字段保持缺省。 |
| R07 | 金字塔氨；0/1 | `# HF/STO-3G Opt=ModRedundant NoSymm` | 三条 N–H 各 `S 2 0.010`，保留弯曲自由度；读取三坐标并从输出核对实际点数和收敛，不推断耗时。 |
| R09 | 甲烷；两段均显式0/1 | 两段均为 `# HF/STO-3G Opt=ModRedundant NoSymm` | 独立几何/不同 chk：先 `B 1 * F`，后 `X 1 B` 与 `X 1 F`；分别核对通配符与笛卡尔冻结。 |
| R11-flat | 水；0/1 | `# HF/Gen SP` | 主输入直接引用 `hydrogen.inc`、`oxygen.inc`；只验单层附件，不代表递归通过。 |
| P00 → P01 | 平面 NH3；与 R05 同源几何，两者显式0/1、相同原子顺序/坐标 | P00 严格：`# HF/STO-3G Freq NoSymm`；P01 放宽：`# HF/STO-3G Opt=(TS,RCFC) NoSymm` | 两个独立 Attempt，目标为氨反转 TS 输入路径。P00 `%chk=ammonia.chk`；P01 `%oldchk=parent.chk`、`%chk=child.chk`。只证明来源/归属/复制哈希及读取执行，不保证 Gaussian TS 成功或 Hessian 科学适用。 |
| G01 | 合成水；0/1 | `# HF/STO-3G SP Geom=Connectivity` | GaussView 格式连接表：`1 2 1.0 3 1.0`、`2`、`3` 各一行；不声称真实从 GaussView 导出。 |

R01/R02/R05/R06/R07/R09/R11-flat/G01 与 P01 使用 `--relaxed-input`，P00 保持严格。
P00 必须独立：现有父 chk 机制要求一个程序输入，relaxed 包含 sidecar，不能借 R06 或其它
放宽 Attempt 充当父来源；不得为减少数量改该机制。P00/P01 改用与 R05 同源的平面 NH3
几何，但不继承 R05 的冻结约束；新的 Freq → TS/RCFC 候选另存，前水父子候选保留历史，
其离线结果不能转作本组证据。G01 已有离线 prepare 与 verified_files 结果；NH3 新候选
的纯校验/prepare 状态须按新归档记录，不能伪造 checkpoint 或父完成证据。最终真实输入/哈希仍待确认。
P01 必须等待真实 P00 完成、取回并核验关联后再 prepare；父 chk 的实际
大小/哈希由专用 submit 流程在人工确认前核验，不能预造值或用合成父记录。
放宽 P01 不要求调用严格路径的取向检查；这必须写成尚未科学核验，不能写成该检查已通过。
若 P00 频率负曲率不适于目标 TS 初猜、P01 收敛不适或异常终止，记录未通过/待人处理；
不追加 NoEigenTest、不自动补救。P01 即使正常结束，也不构成 TS 科学验收：
最终结构恰一个虚频、振动方向及 IRC 均未验收。

R03（SCRF Read）、R04（NBO）、R08（51 增量）、R10（Units 与组合附加段）后置，
本轮真实调用均为零；其离线覆盖不能冒充现场验证。八项新选项及 Connectivity/尾段组合
由离线回归覆盖，本精简矩阵不声称逐项现场通过。R11 嵌套 include **明确拒绝**，
不再保留为待真实探测项，真实调用为零。R11-flat 的两个附件均显式 `--include-file` 收集。

### 固定命令与次数

执行前保存全部占位符展开后的实际命令。拟串行顺序为 P00 → R01 → R02 → R05 → R06 →
R07 → R09 → R11-flat → G01 → 条件解锁后的 P01；任何停止条件出现即停后续列表。
只在新建的独立非研究 study 中执行一次 `ag init '<STUDY>' --json`。

```sh
ag prepare --study '<STUDY>' --template gaussian --input '<INPUT.gjf>' --relaxed-input \
  --cluster '<CLUSTER>' --tier '<TIER>' --walltime '<WALLTIME>' --label '<LABEL>' \
  --method-basis '兜底方法：非研究小分子流程验证；不是文献先例，科学方法未核验' <INCLUDE_ARGS> <PARENT_ARGS> --json
ag submit '<ATTEMPT_ID>' --json
ag status '<ATTEMPT_ID>' --json
ag fetch '<ATTEMPT_ID>' --no-facts --json
```

P00 仅删除 `--relaxed-input` 及两个附加参数组。其它普通行两组为空。
R11-flat 的 `<INCLUDE_ARGS>` 展开为两个确切附件路径的 `--include-file`。
P01 的 `<PARENT_ARGS>` 固定展开为
`--parent '<REAL_P00_ID>' --relation restart_from --parent-chk '<REAL_P00_ID>:ammonia.chk'`。
不用 `--policy` / `--approval` 代替本次逐 Attempt 的 Mac 人工确认。

| 动作 | 含 P01 的总上限（10 个 Attempt） | P01 未解锁时（9 个 Attempt） |
|---|---:|---:|
| init | 1 | 1 |
| prepare | 10（各一次） | 9 |
| submit | 10（各最多一次） | 9 |
| status | 60（各最多六次） | 54 |
| fetch | 10（各最多一次） | 9 |
| snapshot / monitor / 额外 SSH / facts / refresh / cancel / 改投 / 补救 | 0 | 0 |

status 候选时点为提交成功返回后第 1、5、10、20、30、40 分钟，确认结束即停止后续观察。
只在状态和正常退出证据满足时普通 fetch 一次，取回后本地检查 Gaussian 正常结束与矩阵特征。
六次后仍排队/运行即记未定并停止本轮；不追加观察、不自动取消/改投，不把墙钟等待当失败。
保留 `--no-facts`；本轮不把力常数科学验收变成本地 facts 的隐含额外动作。

### 验收、停止与尚缺材料

每个 relaxed 包保持 `input_validation` 的 `mode=relaxed`、实际 `skipped_checks`、
`method_verified=false`，sidecar、主输入、附件、脚本和 bundle 字节一致；摘要显示完整各段
route、对象/电子态/几何来源或未知、资源、方法依据、远程目录和输入哈希。
提交前复核，上传后核对大小与哈希；status/fetch 保持确切 Attempt/集群绑定。
P01 专门记录父 chk 来源、归属和复制前后哈希，科学适用性、取向与优化结果另列未验收。

任何 UNKNOWN、哈希/绑定不符、SSH 错误或未经核定的警告、异常结束、非预期文件操作、
负责人暂停或人工确认被拒绝均立即停止，保留现场，不重投、不删声明、不清理服务器。
已知抗量子 SSH 警告只有取得精确原文并核定后才可例外；当前没有可用原文，不猜测。
首版取消、停止核验、后继与改投入口关闭。需要取消时首行提醒负责人在 Mac 上人工确认，
本清单不执行取消。后置/拒绝项不能为了补齐表格而追加真实作业。

执行前仍须补齐：最终组合完整 SHA 和实际程序的一致性、最终输入/附件全文及哈希、真实
入口/档位/资源/walltime/目录、各 Attempt bundle、实际命令、有效授权及逐次人工确认。
T186 接口已有开发实现；最终组合证据、T185/T186 后的 T188 敏感审阅、合并前真实验证仍未
被本清单代替。当前阻塞为提交/环境：未定真实参数与授权，没有真实成功或失败结论。
