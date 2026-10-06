# Anti Freq 尾段标记：精确修订提案 r2（待 Owner 接受）

## 实际问题与处置

anti 736.master 已成功收集；现有 r2 合同 `docs/v3/proposals/gaussian-successor-frequency.md:61` 明确规定“纯 Freq 不可有 Opt/stationary marker”。现安装 ScientificValidation 如实执行该规则，正式联合 authority 拒绝。不能在运行中删字段、改日志、临时移除 guard 或绕过原生验收。

本提案只处理真实单段 Freq 输出的尾段标记兼容性。接受本提案不是接受 anti 科学结论，也不授权 gauche 提交。中性解析入库独立保留全部标记和拒绝证据，既有 Opt 集合保持原修订。

## 精确证据

- 实际源码 commit `3b9df8c2f287b6a289328711ce2eb52fba2c6dc1`，tree `7116d5d039c9031e5a01fc7f11db21ba8cf0e8bf`。
- anti Freq Attempt `40bc176d-9425-4763-abb1-9d4940679dd0`；输入 SHA-256 `f600b8e5425fc7bb0ff8ecb90bcc6f3c2ec23e4b0c9423b6b086d902de3304a2`。
- 收集日志 SHA-256 `2e04a0f0c5e618dfa711e45a8f8987afa8d70785ae3350589a7e2bb373aec992`，89753 bytes。
- 第85–86行 route 为批准的纯 Freq；第1222行 archive job type 为 Freq；只有一个 Input orientation 和一次 SCF。
- 第1080行 Link716结束，随后 Link103尾段；第1152–1153行两个标记，字节区间分别 [72094,72119)、[72119,72150)；均在全部36模式之后、唯一正常终止之前。
- 原生来源回放、Opt authority、Freq输入与Opt几何逐原子六位坐标、plan lineage、方法及输出电荷/多重度/SCF/basis均通过。36模式、0负频、最低122.9897 cm^-1。详见同目录 `acceptance-blocker.json`。
- 这些事实说明本例与“Freq必无上述文字”的合同假设不兼容；本提案不据此泛化所有 Gaussian Freq 输出，也不把尾段标记当作独立 Opt 优化证据。

## 拟替换的规则

原第61行中“纯 Freq 不可有 Opt/stationary marker”替换为：

Freq 的原始 marker 与 source span 必须完整保留。marker 缺失的现有受支持路径保持原规则。marker 存在时，仅允许以下全部条件成立的狭窄尾段形式；任何条件缺失、矛盾、重复或不能归属都拒绝产生 positive authority：

1. 同一已关闭来源链、唯一 job_section、唯一正常终止、无错误终止；输入仍精确匹配批准的纯 Freq route，输出唯一 route echo 和唯一 archive job type 独立确认同一 Freq 任务；不得接受 Opt/Freq、Link1、多任务或拼接输出。
2. 恰好一组完整 Input orientation、一次已验证方法的 SCF；几何与原 Opt/批准 Freq 输入逐项一致；不允许从多几何或多 SCF 中选取有利部分。
3. 所有已解析有限、连续模式来自同一几何和同一 job_section；两个标记各恰好一次且顺序紧邻，所有原生 spans 完整归属、无重叠冲突，并位于最后频率块之后、正常终止之前。
4. 尾段形式固定为 `g16-a03-freq-l716-l103/1`（只支持输出明确标识的 Gaussian 16 A.03）：最后频率块之后依次出现完整 Link716 退出、Link103 进入、唯一 `Step number 1 out of a maximum of 2`、相邻且各唯一的两项完成 marker、Link103 退出及 Link9999 进入；所有匹配限定在 parser 的唯一 job_section 内，不扫描输入回显或 archive 充当执行证据。该段禁止另一轮 Step、SCF、几何、频率或作业入口；尾段外也不得另有完成 marker。route echo 必须精确为批准路线，archive 必须是唯一同作业 Freq 记录；未知、重复或截断结构拒绝。不使用标记本身证明 Opt 通过，不把尾段 New X 预测值替代已算频率的输入几何。
5. 原 Opt 的正向几何 authority、相同 Project/不同 Attempt、精确 plan/member/原子映射/立体化学/方法、所有原生结构审计与去重、0负频条件全部保留。任何负频仍为 NOT_MINIMUM；未知尾段结构仍拒绝。

组合 owner 从已验证日志闭合 route/archive/尾段来源，ScientificValidation 仍只消费事实及严格关闭的补充证据；不得让调用者提供未重放的布尔豁免。`tail_evidence` 闭字段为 `schema, form, source_artifact, job_section, route_echo_span, archive_span, tail_span, optimization_completed_span, stationary_point_span`；schema 固定 `v31-gaussian-freq-tail-evidence/1`，form 固定 `g16-a03-freq-l716-l103/1`。所有 span 绑定同一原始 artifact，并沿用 parser 原生span形状。Conformer 从重新验证的原始日志构造并完整重放比对，SV 不读取日志、不接受调用者布尔豁免。

合法尾段不能覆盖既有分类：来源/方法/几何/尾段身份冲突优先边界拒绝；正常来源下不完整 capture/parse/终止仍 INCOMPLETE；35模式仍 INCOMPLETE，37模式仍 UNSUPPORTED，完整36模式中任何负频仍 NOT_MINIMUM，只有全部既有正向条件满足才能 VALIDATED_TWO_STAGE_MINIMUM。不得为满足尾段规则而把缺失模式补成36。

## 版本与证据保存

新分支固定 authority schema/domain `v31-conformer-successor-two-stage-minimum-authority/2` 和 policy `v31-successor-two-stage-minimum/2`。旧 /1 按原禁止 marker 规则重放，不自动升级；新消费显式选择 /2。Result source/parsed `/2` 与 parser 1.2.0 不变。新 authority 的 frequency 新增闭字段 `tail_evidence`：无 marker 为 null；有 marker 为上述完整、从原始日志重新构造的证据。集合及查询按 authority schema 分派，未知版本拒绝。既有 /1 authority、历史集合和原始解析 /2 不得覆盖或偷偷重解释；若实施发现需扩大合同范围，返回补充方案。

## 最小离线验证

- 真实 anti bytes 的来源重放与尾段正例；新政策下继续完整结构/方法审计及原生集合修订，不仅测试 marker 放行。
- 反例：错输入/route/archive、Opt+Freq、第二 job/Link1、marker早于频率/重复/逆序/错span、几何冲突、第二SCF/第二轮、截断、异常终止、35/37模式、负频、伪造自洽解析及调用者伪造豁免。
- 额外反例：回显伪造 Link103/marker、尾段span指向其他artifact、正确marker但错误Link退出、/1历史重放自动采用/2。
- 无 marker 旧正例、旧 /1 记录和原生只读导入、不可覆盖发布、集合/query历史回放回归。
- 真实输出只作为本地受限证据，不提交 Gaussian 原始输出/checkpoint/数据库。测试使用可审阅的最小脱敏模拟，真实捕获另做精确哈希离线重放。

## 请求范围

接受此精确提案后，仅授权隔离分支内合同落盘、最小实现、离线验证和独立只读审阅（最多2轮、15分钟，超过再报告）；不改化学参数、不连接服务器、不重新提交 anti、不启动 gauche。通过后冻结源码并评估实际加载与安装绑定影响，按既有授权边界准备需要的精确安装候选。新验证器尚未合格前，anti正式最低点验收与集合升级保持阻塞。
