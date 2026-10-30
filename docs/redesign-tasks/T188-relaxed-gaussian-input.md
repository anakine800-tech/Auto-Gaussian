# T188：Gaussian 受控放宽输入

## 分支与目标

- `codex/t188-relaxed-gaussian-input`，一单一 PR；来源 V4.8 W7 后端。
- 从最新 main 的干净隔离工作树开始。可先实现独立输入校验和 prepare/verified_files 回归；提交规则与 T186 协调，待最终接口接入后才可完成集成，不能复制其未合并代码进入本 PR。
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
2. 按 W7 支持 Gen/GenECP、SCRF=Read、NBO 附加段，TS 与 ModRedundant，Link1，Geom=Check/AllCheck，以及扫描超出原白名单（多于两个坐标、更多步数、通配符、笛卡尔冻结、Units、多种附加段）。这些是放宽输入接受范围，不等于解析器、科学方法或 profile 已支持。
3. 每个 Link1 段均需核验资源、Link0 文件名和 External；不能只检查第一段。资源的实际有效值必须与所选档位及现有内存规则一致；若采用继承或补齐必须明确记录并在最终字节上重验，不能猜测未写明的资源。
4. 只运行既有审阅模板，不放宽 shell 或模板参数。各段 Link0 文件仅普通 basename、不得目录、绝对路径、父目录、链接、环境变量展开；命令型 External 的大小写、括号、换行写法均不能绕过。不能让附加段的文件指定或间接输入逃离本 Attempt，也不得让输入覆盖已上传的脚本/清单或只读父 chk。无法证明满足这些底线的写法先拒绝并报告，不执行探测。
5. @include 只接受已显式收集进输入包且按最终字节绑定哈希的普通文件。递归引用、别名、环、缺失文件和嵌入危险指令必须有界检查；不从任意路径隐式收集文件。主文件和附件同样执行底线检查。只有安全可核实的输入能进入目录分配，源文件不改。
6. Geom=Check/AllCheck 只能依赖同 Attempt 已证明来源的 chk 或既有专用父 chk 机制；不得凭文件名读取其它 Attempt。对无显式几何/电荷/多重度的段，不伪造 science 字段，不用虚拟水结构骗过旧校验；摘要显示来源或未知以及完整各段 route。
7. 与 T186 约定一个不可变的放宽标记、确切跳过检查清单和方法口径“未核验”字段；prepare 与 verified_files 共用同一校验器及附件清单。提交摘要逐次显示该标记、跳过项、完整输入/资源/哈希、scan-peak 不可用和 profile 可能不支持的事实。已放宽输入不得因解析恰好成功而自动变回“已核验”。
8. 自主提交仅在计划与有效规则均明确允许时使用方法例外；仍核验有效期、次数、节点/路由、持锁和所有输入字节。普通输入不受影响。T186 未合并前不得只凭 allow_relaxed 字段放行；集成可以在临时组合检出测试，PR 保留待集成。
9. scan-peak 从冻结 manifest 拒绝放宽来源，避免旧白名单之外的扫描被误解释；不扩大 thermo/profile/facts 的科学接受条件。前端标记由 T197 单独做，本单给出实际字段和合成示例。

## 离线验收

每类放宽输入有最小合成接受用例；每条底线有拒绝用例，覆盖第二/第三 Link1 段、空段/重复资源、资源继承与不匹配、大小写/换行 External、附件递归/缺失/环/越界/链接、危险文件名、包文件被替换、冻结标记/跳过清单被篡改、父 chk 与 Geom=AllCheck、旧严格输入不变。分别验证 prepare、verified_files 和提交前复核，失败不产生远程动作。

本地只跑受影响相关测试；全量 ag/Skills 交给 CI，并在真实验证前对最终源码组合统一运行一次，不做 AST 比对。
敏感扫描用私有词表、精确暂存、noreply 身份及当前 head CI。不要用仅接受异常的测试冒充该类语法可用。

## 真实环境验证（敏感，合并前必需）

当前仅授权开发与离线测试，不连接集群、不修改真实配置、不提交或取消。整理非研究小分子矩阵：上述每类放宽至少一个独立 Attempt，固定单次 prepare/submit，status/fetch 观察次数执行前列明。可让一个安全输入覆盖数个语法类别，但必须明确对应；底线拒绝只在本地执行，绝不将危险输入送上服务器。

交最终提交 SHA、对象/电荷/多重度/方法/完整 route/资源、输入和 bundle 哈希、精确命令和次数、预期与停止条件，由协调方汇总 T185/T186 最终组合后请负责人批准实际执行并亲手确认。取消/改投接口不阻塞此验证。任何真实 UNKNOWN、哈希不符、SSH 错误或异常结束立即停，不重新提交。真实验证缺失不得合并。

## 交付

PR 首行 `Task: T188`；说明最终字段、允许及仍拒绝的语法、方法未核验和工具限制、底线矩阵、兼容性和真实验证缺口。敏感生产路径在 T185/T186 后交 Claude 审阅一次定稿，之后只复核回应意见的改动；审阅意见未处理完不得合并，协调方的独立合并授权不覆盖本 PR。开发对话不合并、不发布或部署。范围外、同问题两次未解决或底线语义不清时向协调方报告，独立工作继续。

## 合并前验证准备清单（未执行）

本节是供协调方审阅的非研究小分子矩阵，当前未连接集群，未 prepare 真实 study，
未提交或取消计算。输入语法接受和计算正常结束分别验收；不以任一项证明科学方法正确、
TS 成立或 profile 可以采用结果。危险拒绝输入只在本地合成回归中使用。

以下每行是独立 Attempt；R06 内含三个 Link1 段。每段均显式给出资源，
`%nprocshared` 必须等于获批档位核数，`%mem` 为不超过该档位内存 85% 的明确整数及单位。
候选 walltime 为 `00:30:00`，最终入口、档位、核数、内存与时限须由协调方按目标配置
确定后保存到精确输入；本表没有假定任何真实入口容量。方法均为流程验收兜底方案，
不作为研究方法先例。所有列出的 route 都是完整候选 route，附加段亦须在执行前
成为完整输入字节并通过最终校验器。

| 项目 | 对象；电荷/多重度 | 完整候选 route（依输入顺序） | 附加段或来源；覆盖类别 |
| --- | --- | --- | --- |
| R01 | 水；0/1 | `# HF/Gen SP` | H/O 的 STO-3G 基组块，`****` 分隔；Gen。 |
| R02 | 氯化氢；0/1 | `# HF/GenECP SP` | H 用 STO-3G，Cl 用 LANL2DZ 基组及 ECP 块；GenECP。 |
| R03 | 水；0/1 | `# HF/STO-3G SP SCRF=(PCM,Solvent=Water,Read)` | `eps=78.3553`、`epsinf=1.7778`；覆盖已命名溶剂参数，不声称两个参数构成完整 Generic 溶剂。 |
| R04 | 水；0/1 | `# HF/STO-3G SP Pop=NBORead` | `$NBO BNDIDX $END`；NBO 附加段。 |
| R05 | 平面氨反转初猜；0/1 | `# HF/STO-3G Opt=(TS,CalcFC,ModRedundant) NoSymm` | `B 1 2 F`，固定一条 N–H；TS 与 ModRedundant。只验收执行链路，TS 科学判定另需频率与方向审阅。 |
| R06 | 水；首段0/1，第二段显式0/1，第三段电子态来自前段 chk | 1. `# HF/STO-3G SP`；2. `# HF/STO-3G SP Geom=Check Guess=Read`；3. `# HF/STO-3G SP Geom=AllCheck Guess=Read` | 三段显式 `%chk=water.chk`；后段只用本 Attempt 前段来源。第二段有标题/电子态，无几何；第三段不写标题/电子态/几何。覆盖 Link1、Check、AllCheck。 |
| R07 | 金字塔氨；0/1 | `# HF/STO-3G Opt=ModRedundant NoSymm` | 三条 N–H 各 `S 2 0.010`，保留弯曲自由度；多于两个扫描坐标。 |
| R08 | 水；0/1 | `# HF/STO-3G Opt=ModRedundant NoSymm` | `B 1 2 S 51 0.001`，其余内部坐标仍可优化；超出原 50 步白名单。 |
| R09 | 甲烷；两个显式几何段均0/1 | 两段均为 `# HF/STO-3G Opt=ModRedundant NoSymm` | 第一段 `B 1 * F`；第二段 `X 1 B` 后 `X 1 F`，分别使用不同 chk；通配符与笛卡尔冻结。 |
| R10 | 水；0/1 | `# HF/Gen Opt=ModRedundant NoSymm Units=AU SCRF=(PCM,Solvent=Water,Read) Pop=NBORead` | 正确换算为 AU 的坐标；尾段顺序 ModRedundant → Gen → 普通 SCRF Read → NBO。 |
| R11 | 水；0/1 | `# HF/Gen SP` | 嵌套 `basis.inc` → `hydrogen.inc` / `oxygen.inc`；仅本地打包覆盖，Gaussian 嵌套语义未证明，真实调用为零，保留 HOLD。 |
| R11-flat | 水；0/1 | `# HF/Gen SP` | 主输入直接引用 `hydrogen.inc`、`oxygen.inc`；可替代直接 include 覆盖，不能算递归语义通过。 |
| P00 | 水；0/1 | `# HF/STO-3G SP` | 独立严格输入，`%chk=water.chk`，作为 P01 的专用父 chk 来源。 |
| P01 | 水；电子态/几何拟来自 P00，输入不重复写 | `# HF/STO-3G SP Geom=AllCheck Guess=Read` | 真实父尚未完成、chk 哈希未知，HOLD；条件具备后以 `--parent`、`--relation`、`--parent-chk` 绑定 P00，父文件只读。 |

R01–R10、R11-flat、P01 使用 `--relaxed-input`；P00 保持严格模式以覆盖兼容与父来源。
R11-flat 的两个附件全部通过重复的 `--include-file` 显式收集，不按引用隐式打开文件。
最多 12 个可审阅候选加条件解锁后的 P01；嵌套 R11 不进入真实执行列表。
多段与组合输入还需针对最终 Gaussian 版本复核附加段顺序；若最终校验器不能证明安全，
本地拒绝并记录具体缺口，不把该行标成接受，也不发往服务器探测。

### 固定命令、次数与验收

执行前替换并审阅下列全部占位符，保存每一行的实际命令；本表不是执行授权。
`<INCLUDE_ARGS>` 仅用于 R11-flat，展开为两个 `--include-file`；`<PARENT_ARGS>` 仅用于 P01，
展开为 P00 的确切 `--parent`、经审阅的 `--relation` 与 `--parent-chk`。
P00 完成、核验来源并取回后才能准备 P01，不能用尚未完成的父作业。

```sh
ag prepare --study '<STUDY>' --template gaussian --input '<INPUT.gjf>' --relaxed-input \
  --cluster '<CLUSTER>' --tier '<TIER>' --walltime '00:30:00' --label '<LABEL>' \
  --method-basis '兜底方法：非研究小分子语法验证；科学方法未核验' <INCLUDE_ARGS> <PARENT_ARGS> --json
ag submit '<ATTEMPT_ID>' --json
ag status '<ATTEMPT_ID>' --json
ag fetch '<ATTEMPT_ID>' --no-facts --json
```

P00 的 prepare 删除 `--relaxed-input` 和两个附加参数组。每行 prepare **一次**、submit
**最多一次**；提交前展示完整摘要并由负责人亲手点击 Mac 对话框。status 最多 **六次**，
候选观察时点为提交后第 1、5、10、20、30、40 分钟，提前确认结束即可停止后续观察。
只有状态与正常程序退出证据满足时才 fetch **一次**；未结束就不 fetch。
第六次仍排队或运行则保留状态并报告，需要新增观察授权，不自动增加轮数、改投或取消。
本矩阵不调用 snapshot、facts、refresh、cancel，不以解析器的偶然成功扩展科学边界。

预期检查：prepare 保存真实输入字节及放宽标记，摘要逐段完整；提交前再次核对 bundle，
上传后大小和哈希一致；status/fetch 保持确切 Attempt/集群绑定；程序正常结束且无越界文件
或输入包改写。R06 核对三段均执行到预定阶段，P01 核对专用 chk 来源检查与复制哈希。
任何 UNKNOWN、哈希不符、SSH 错误、异常结束或非预期文件操作立即停止整组并报告，
不重新提交、不删除声明，也不清理服务器。

### 执行前尚须补齐的审阅材料

- 最终代码完整 SHA，以及它与集成代码、实际执行环境的一致性；当前不得用开发中 HEAD 代替。
- 各行最终主输入与附件全文、完整各段 route、明确的对象/电子态/几何来源、立体化学提示和方法依据。
- 真实配置解析出的入口、档位、核数、内存、walltime、远程目录，以及本地和账号合并容量核验。
- 各行输入、附件、sidecar、脚本和 bundle SHA-256；父 chk 的来源、目标名、大小和哈希在专用流程中核验。
- 替换占位符后的精确命令、固定次数、负责人授权及人工确认安排。
- T186 提交规则集成、T185/T186 最终组合与 Claude 敏感代码审阅；T188 在 T185/T186 后送审，不等待取消/改投接口。真实验证缺失仍禁止合并。

当前实际阻塞属于**提交/环境**：集成接口与最终执行清单尚待协调，未获真实执行授权；
不存在真实成功或失败结论。输入和 bundle 哈希依赖最终配置和独占 Attempt 身份，
当前不填造哈希，也不把本地合成样例的哈希冒充待执行对象。
