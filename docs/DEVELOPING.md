# 开发时查这份

本手册对应 `ag/` 与 `skills-next/` 新架构；操作示例中的尖括号均为占位符。
先读 [AGENTS.md](../AGENTS.md)、本次任务单和 [经验记录](LESSONS.md)；文档总入口见 [文档索引](README.md)，[改造方案](REDESIGN-PLAN.md) 只作历史参考。
当前代码是实现依据；遇到文档与实现不同，写明差异，不借文档修改扩大任务范围。

## 模块地图

以下均位于 `ag/src/ag/`，一个模块一行；模板在 `ag/templates/`，测试在 `ag/tests/`。

- `__init__.py`：包入口与 CLI 版本号。
- `cli.py`：参数解析、子命令挂载、配置选择与退出码。
- `config.py`：本机配置校验、集群选择及按 manifest 绑定目标。
- `clusters.py`：只读输出供前端发现的集群、档位和资源上限白名单字段；当前不发布预算余额。
- `study.py`：study 骨架、标识符和本地路径校验。
- `attempt.py`：prepare、不可变 manifest、输入哈希及统一的本地记录读取。
- `state.py`：允许的状态迁移和本地 status 原子更新。
- `journal.py`：追加本地动作记录。
- `locks.py`：提交串行锁和不可复用的独占声明。
- `autonomy.py`：本地计划/轮次/租约、暂停与恢复、实际提交消费、手动写入登记及最终发布保护。
- `autonomy_policy.py` / `autonomy_submission.py`：绑定计划的规则/方法核验、全机占用登记与提交/补救证据核对。
- `_autonomy_store.py`：autonomy 的描述符相对文件操作、短 OS 互斥、追加日志与原子状态；不修复旧日志。
- `confirm.py`：唯一的 macOS 人工点击确认入口。
- `submit.py`：批次核验、确认、上传、提交及不确定结果处理。
- `submission.py`：一次性提交绑定及确切作业身份交叉校验。
- `budget.py`：按入口记录本地 ag 核时预估、预留与结算，保留共享入口未观测核数的核对。
- `cancel.py`：确认后取消记录中的确切作业，取消声明也只能用一次。
- `status.py`：PBS/Slurm 观察、程序完成证据及 unknown 只读核对；保留不完整取回所需的 PBS 首次/最近不活跃观察。
- `fetch.py`：校验输出大小和哈希，以不覆盖方式发布到本地；显式不完整取回及绑定的独占记录。
- `monitor.py`：只读采样集群，在本地缓存最新快照和历史。
- `route.py`：原有档位建议与 T185 纯函数 `select_ladder`；可信运行记录适配及 T186 提交核验待集成。
- `capacity.py` / `node_targeting.py`：同节点精确容量判断与 PBS 具名资源切分、绑定及准入。
- `doctor.py`：只读检查连接、调度器、目录和程序环境。
- `remote.py`：全部固定远程命令、参数白名单及路径检查；独立的 incomplete_output_observation 在可进入的父目录内区分缺失与无法核实，复用 output_observation 只读操作类别。
- `transport.py`：SSH/scp、只读传输重试、脱敏及可注入的 Transport 接口。
- `pbs.py`：PBS 节点与容量解析，供提交和监控共用。
- `slurm.py`：Slurm 提交、队列和记账输出的严格解析。
- `render.py`：声明参数校验及 PBS/Slurm 程序脚本渲染。
- `gaussian_input.py`：Cartesian Gaussian、QST2/QST3 输入与资源校验。
- `gaussian_relaxed.py`：显式放宽 Gaussian 输入的分段资源、文件引用和附加段底线检查。
- `crest_input.py`：CREST 约束输入的受支持子集校验。
- `parent_chk.py`：父 chk 声明、父子关联与提交时来源检查。
- `parent_chk_remote.py`：以固定描述符安全读取和独占复制 chk 的远端脚本文本。
- `cards.py`：读取实际部署卡片并保存文本、提交号和 dirty 状态。
- `review.py`：生成审阅骨架，检查判据完整性及 facts 是否过期。
- `_review_manifest.py`：签字前独占生成 study 证据清单，绑定文件字节与 ag 提交号。
- `facts.py`：本地 facts/final.xyz 输出入口，仅提取事实。
- `mode_review.py`：基于正常结束的频率段导出正负模式位移、指定原子对距离及全对排名，方向由人审阅。
- `_parse_outputs.py`：Gaussian/cclib、xTB、CREST 输出解析。
- `_irc.py`：Gaussian IRC 方向、路径点和完成事实提取。
- `geometry.py`：XYZ、显式能量单位、成键/立体标识及 RMSD 共用工具。
- `dedup.py`：能量窗口和对称性去重，记录排除原因。
- `cluster.py`：代表构象选择及可选镜像简并度。
- `graph.py`：只读展示 parents/relation 谱系和缺失父节点。
- `irc_compare.py`：保留原子编号的 IRC 端点几何比较，不代替科学验收。
- `topology.py`：本地比较提交与最终几何，报告拓扑/立体差异或指定 TS 原子对距离，独占输出 JSON 与 Markdown。
- `fragments.py`：复用半径规则识别连通片段，在 study analyses 下独占导出报告与保留原子编号、原始坐标行的 XYZ，不推断电子态或身份。
- `thermo.py`：GoodVibes qRRHO、单点修正和显式简并度布居。
- `_profile_sources.py`：反应曲线的来源、物种、方法和审阅检查。
- `profile.py`：守恒反应自由能曲线、能垒和敏感性分析。

prepare 先选择入口，再用 `config.resolve_tier` 解析显式档位或该入口的可选 `resources.default_tier`，之后才做节点映射、资源检查和编号/目录分配。
省略档位且入口无默认值时明确报错；配置默认值必须是该入口已配置且合法的档位，不跨入口继承。
全部允许模板共用此入口；manifest 仍只保存实际 tier/cores/mem，verified_files 不调用默认解析，不为旧记录补字段。
clusters 的资源白名单仅在已配置时发布 default_tier；route 的原建议模式仍要求显式档位。
默认严格模式的 Gaussian prepare 在档位与 walltime 检查后依次补缺失的 `%nprocshared`、`%mem`，并在分配序号/目录前完成输入校验。
核数只取所选入口的最终档位，显式输入值不修正；内存仍按 R1 和 85% 上限处理。普通完整输入字节不变，CP 沿用原片段转换。
仅实际补齐时新增可选 `auto_nprocshared` 整数或 `auto_mem_gb`，摘要注明来源；二者都不是提交授权。
输入和 bundle 哈希绑定最终保存字节，源文件不变；verified_files 只核验，不补齐、不重写旧 manifest 或哈希，缺少可选说明的旧记录照常读取。

T185 的 `node_targeting.FRACTIONS` 末尾追加 `'1'`，整节点仍走既有档位、max_cores、精确总内存与两次准入核验，
不改变半/四分之一脚本字节或共享节点排队行为。按协调补充范围，`clusters.py` 的发现元数据复用同一 `FRACTIONS`，保留原顺序和默认 `1/2`。
`route.select_ladder` 与 `ladder_config_identity` 供后续 prepare/提交适配共用；不得为 T186 另写一套阶梯顺序。
函数只处理传入数据，要求 `study_key`、显示用 `study_id`、独立的 `round_id`（整个自主轮次）和 `run_id`（一次唤醒运行），输出 `ag-routing-ladder/1` 的身份、候选、原因、推荐及配置/快照/占用/唤醒证据哈希。
T186 可信适配须从全本机记录核对真实自主归属、全部活跃本地预留及提交绑定、运行事件和首次选格完整输入；T184 的意向计数不能当实际占用。
每条 placements 必须带 study_key、study_id 和 scheduler_job_name：核验 manifest 后 PBS 取 pbs_job_name，Slurm 取 attempt_id，用于真实调度快照身份比对。
study_key 是必填的 64 位小写 SHA-256，T186 须按安全校验后的本机绝对 study 目录生成并持久绑定目录身份；请求、placements、wakeups、batch.request 和本地去重一致使用 key，不允许缺失时回退到显示名 study_id。同名 study/Attempt 不跨来源合并，物理作业按确切调度身份去重，矛盾归属拒绝。纯算法不访问路径；实际目录绑定及全本机适配仍待 T186。
适配尚未完成时，`route --job-class main|small` 带 study/round/run/object/walltime 返回阻塞，不退回旧建议冒充已通过。
SCNet 类末级运行加排队最多 4 个、兜底排队最多 2 个，按全本机全部自主 study/round 的活跃记录合计，包含不同配置目录和 studies_root、旧轮活跃作业；非自主作业仍仅参与原有全部账号核数限制。批次放置数限定同一 round/run，逐轮 Attempt 预算和每次唤醒取消上限不变。
适配按共享账号及确切作业身份去重，未观测到的本地预留及 UNKNOWN 占用不得释放；不能核实则拒绝。T186 负责跨配置目录的共同注册与共同锁，并在共同锁内重新收集、核验和复算；现有配置目录内的 submit.lock 不够，换配置、study、round 或唤醒租约不能取得额外名额。
`batch_inputs` 保存首次选格的完整输入，用同一算法重放全部条件，不能仅凭原始空闲快照证明批次合格。
两份半节点位置在重放验证后，再以当前单节点剩余容量核对，避免首份读回导致第二份被误跳过，或外来占用后仍误放行。
快照未知按实际候选排序阻断：低优先失效不阻已核实的首选，高优先未知不能被跳过；小体系复用非 queue、入口顺序、已有占用、格序的排序，以最靠前的可能占用排名比较。所有原占用、共享账号及全局额度核验保持；评估来源本身的当前节点与比例仍须核实。
`select_ladder` 的可选 `evaluate_from` 只含 study_key/attempt_id/record_sha256，调用方先核验原 reservation；等价读取/共享别名去重后须唯一匹配原绑定且哈希一致，冲突或多个物理绑定仍拒绝，原 cell/节点/资源/配置由 T186 不可变 recommendation 绑定。不得用 `exclude_ownership` 移除来源占用；仅精确来源豁免同对象快捷拒绝，其他占用及同对象阻断保留。
评估候选须不同 cell 且按原 main/small 排序严格更优；默认调用及哈希不变。评估结果带 `evaluation_only=True` 和 `evaluate_from`；首个组合不启用取消、停止核验、后继或改投入口，不等待 T187。后续接入评估时，薄适配独立透传参数并在普通 reservation 消费时拒绝此类结果，T187 复用同一算法后另核验立即运行、从未运行且排队六小时、无 chk、归属租约及取消消费等条件。此扩展无新 CLI 参数或警告界面，不执行真实操作。
条件、能力过滤与真实验证缺口见 [CLI 说明](../ag/README.md#提交阶梯与整节点t185)；本单没有提交授权接线或现场验证证据。

### Gaussian 放宽输入的冻结与复核

为防止 Link1 后段绕过资源或文件检查，以及未核验方法被误当作已核验方法，
`prepare --template gaussian --relaxed-input` 使用独立校验器；默认路径与旧记录保持原样。
每一段必须显式提供 `%nprocshared` 和 `%mem`，核数匹配所选档位，内存遵守原 85% 上限；
放宽路径不继承、不猜测也不自动补齐资源。`--include-file` 可重复，附件只从显式参数收集，
主文件及直接引用的附件都在编号/目录分配前检查，随后 `verified_files` 对最终保存字节重验。
收集时逐级用目录描述符与 `O_NOFOLLOW` 打开路径，防止父目录在检查后被替换为链接；
读到的文件必须是普通文件，同 inode 别名拒绝。
解析只允许单层 include：主输入可直接引用多个显式附件，附件不能再引用附件。
最多 32 个附件、32 个 Link1 段，冻结输入与展开文本各最多 1 MiB。
附件只含数据片段，不能注入 Link0/route/Link1；未被引用的附件也拒绝。
GaussView 格式的 `Geom=Connectivity` 仅在显式坐标使原子数已知时接受，
Check/AllCheck 与 Connectivity 的组合明确拒绝。首个附加块须按顺序逐原子列行，
核验整数索引与有限数值键级；剩余尾段沿用原有数据语法，不代表 Gen/ECP、
ModRedundant 等完整科学分段顺序已获验证。
Opt 的 GEDIIS/NoTrust、SCF 的 NoIncFock/NoDIIS、IRC 的 GS2/CalcAll、
Freq 的 HPModes/SaveNormalModes 均纳入放宽语法；算法选择和力常数科学合理性不由这些检查证明。
[G16 输入顺序表](https://www.conflex.co.jp/gaussian_support/input.php) 是人工核对组合输入的依据，
不是当前尾段校验器已完整实现该顺序的声明；ReadFC/RCFC 用途见 [Opt 手册转载](https://www.conflex.co.jp/gaussian_support/opt.php)。

不再用 Units、EmpiricalDispersion/EM、Stable/Polar/Symmetry 的值白名单选择科学方案；
这不证明输入的算法名称、拼写或方法可用，方法口径仍未核验。纯 basename 中间的连续点
可以保留，父目录路径组件、路径分隔符、展开和别名检查不放宽。
Stable/Polar 的 Restart 继续拒绝；Polar 的 Raman/ROA 需读取旧力常数，DCSHG/Gamma
隐含频率读入，WorkerPerturbations 涉及 Linda 资源模型，也拒绝。这些危险选项的非空前缀
一并拒绝，防止 Gaussian 的最短唯一缩写绕过完整拼写检查；不扩为所有科学值的白名单。
依据为 Gaussian 经销方的 G16 手册转载：[Stable](https://www.conflex.co.jp/gaussian_support/stable.php)、
[Polar](https://www.conflex.co.jp/gaussian_support/polar.php)、[Symmetry](https://www.conflex.co.jp/gaussian_support/symmetry.php)
及[输入缩写规则](https://www.conflex.co.jp/gaussian_support/input.php)。语义核查不等于目标程序实测。

唯一的 manifest 放宽标记为 `input_validation`，准确字段是 `mode: "relaxed"`、
`skipped_checks: [...]`、`method_verified: false`。输入包中的 `input-validation.json`
另绑定该标记、主输入名称和附件记录，随 bundle SHA-256 冻结；标记、跳过项或包文件不一致即拒绝，
不能因为严格解析恰好成功而消除标记。输入、附件、脚本与 sidecar 都保留各自的字节哈希。
提交审计共用 `attempt.prepared_bundle(files)`，不要对新包直接比较 `bundle(files)` 的记录顺序：
旧记录仍按名称排序，放宽包按已哈希 sidecar 将主输入排首，其余按名称排序，摘要计算仍用规范名称顺序。
verified_files 直接复用 prepared_bundle 的 sidecar 结构核验与首位主输入身份，不重复解析同一 sidecar 或再检查同一后缀。
这是为兼容现有输出选择器而保留的主文件身份；经过 `verified_files` 核验后可用
`attempt.program_input_name(manifest)` 读取 Gaussian 主输入，不能按后缀从附件中猜选。
摘要展示完整各段 route、资源、几何/电子态来源或未知，并提醒 scan-peak 不可用、profile 可能不支持。
缺失的几何、电荷或多重度不伪造；既有科学解析和验收边界不变。

`skipped_checks` 总含 `scientific_method`；依据实际输入另列
`general_basis_semantics`、`ecp_semantics`、`scrf_read_semantics`、`nbo_section_semantics`、
`modredundant_semantics`、`coordinate_unit_semantics`、`checkpoint_geometry_science`、
`link1_scientific_consistency`、`additional_section_semantics` 中的适用项。
这些名称说明未核验的科学语义，不表示资源、模板、路径或授权检查被跳过。
本次不新增标记字段或 skipped_checks 名称；力常数的科学适用性仍由总是存在的
`scientific_method` 未核验状态表达，连接表使用既有附加段标记，不使旧已接受输入的标记漂移。

Geom=Check/AllCheck、Opt=ReadFC/RCFC 只能使用同 Attempt 的可追溯 chk 来源，
或现有专用父 chk 机制。放宽力常数检查证明的是来源与文件归属，不证明 Hessian 是否存在、
方法是否适用或原子/坐标取向匹配；不得称为通过严格路径的 `validate_force_constant_frame`。
本轮只开放 Opt 下的 ReadFC/RCFC，ReadCartesianFC 别名仍在拒绝集合内。
严格路径原有取向核验保留，不能为减少验证对象而改父 chk 读取或复制机制。
当前父 chk 机制要求父 Attempt 只有一个程序输入，放宽包含 sidecar，因此放宽 Attempt
不能作为该机制的父来源；严格父 Attempt 可以被放宽子 Attempt 显式声明。
旧 `approval.policies` / `--policy` 不绑定本轮计划和方法例外，因此拒绝带放宽标记的 Attempt；
一次性批准与人工对话框继续使用现有字节核验、摘要和单次提交流程，不添加授权回退。
T186 放宽接口已接入开发代码：计划和有效规则均须允许例外，`verified_files` 重验实际主输入、
sidecar 与附件；每个 Link1 段仍核验获批收敛下限，方法继续为未核验而非自动匹配。
Stable 的 relaxed 语法不作本轮扩展；自主 policy 已有的 Stable 拒绝保持原样。
这不启用自主运行；最终组合验证、敏感审阅、非研究试点和负责人显式启用仍未被文档替代，
不能仅凭配置中的 `allow_relaxed` 获得权限。非研究合并前验证及实际阻塞记录在
[T188](redesign-tasks/T188-relaxed-gaussian-input.md)，离线通过不代替该验证。

## 自主运行的实现边界

[AGENTS 自主运行规则](../AGENTS.md#自主运行)是唯一规则正文；T182 统一文档，T184 实现 `ag autonomy` 的本地计划、租约、暂停、日志和意图计数。手动计算入口仍保留下文流程：`approval.authorize` 的旧长期规则只核对 study、模板、集群、核数和 walltime；`submit.submit` 拒绝具名 PBS 的长期规则；`cancel.cancel` 仍调用 Mac 人工确认。旧 `--policy` 不能据新文档获得自主权限，单独的 autonomy 本地记录也不能授权这些入口。T186 的独立自主参数已接入开发实现，细节与尚未完成的验证见下节。

下节 T186 实现已在动作前核验计划哈希及版本、有效期与实际消费、方法口径、节点与路由选择、唯一运行锁和状态，并保留逐 Attempt 摘要、授权来源、输入字节和上传后哈希核对。具名 PBS 仅放行有效规则中列出的节点；本版关闭自主取消、取消停止证明和改投，取消来源须先显式人工解除；提交批准参数不能用于现有人工 cancel。后端观察发布保护已接入，前端运行中拒绝写操作的接入仍须由对应工单核验。

放宽输入的受控例外同样以 [AGENTS](../AGENTS.md#自主运行)为准；T188 组合保存跳过检查及方法口径未核验的事实，仍须逐次提醒。不能把可提交当作科学支持，也不能把本单文档当作启用开关。

启动前逐项核对相关工具实现、敏感路径的合并前验证、非研究试点及本轮显式启用；缺任何一项都不能运行自主计算。本地状态工具的合成验证不代替这些证据。90% 实际提交阈值已接入；本次审阅补齐提交路径派发前 SSH 跨唤醒和对象拒绝，跨唤醒快照过期、其他全局运行条件及现场验证仍待完成。开发会话的真实意外仍按 AGENTS 第 5 节立即停止；自主运行的暂停、补救和科学待确认事项按其专节，不把开发授权当运行授权。


### T186 绑定计划的提交接线（开发验证中，未启用）

`approval.autonomous_policies.<name>` 与旧 `approval.policies.<name>` 分开。
自主 prepare/submit 使用 `--autonomous-policy`，并同时要求 `--run`、`--token`、
`--plan-sha256`、`--object-id`、`--job-class`；缺项或核验失败不回退聊天批准或弹框。
旧 `--policy` 只选择手动规则，具名 PBS 的手动规则禁令保持不变。一个自主提交调用
只处理一个 Attempt/对象；连续调用的部分成功仍由每个独立归属和真实消费核对。
注释示例在 `ag/config.clusters.example.toml`；没有创建或启用真实规则。

自主规则字段为 schema、study_id、study_key、round_id、plan_sha256、routing_sha256、
templates、clusters、max_cores_per_job、max_walltime、max_attempts、quote、set_at、
expires_at、methods、allow_relaxed。各 cluster 明列 nodes、max_committed_cores、
max_queued_cores、max_jobs。`nodes=[]` 只接受未具名目标，非空只接受精确节点。
study_key 取安全绝对 study 路径的 SHA-256，共同登记另绑定 device/inode；同名 study
或不同配置根不能重置额度。全部字段参与规则哈希，未知/模糊字段和矛盾限额拒绝。

计划可选 `spec.submission_policy` 保存 templates、clusters、max_cores_per_job、
max_walltime、methods、routing_sha256、allow_relaxed；规则须一致或更窄，方法和
网格来自同一完整计划记录，不跨记录拼接较宽条件。Attempt 上限和有效期复用
`spec.attempt_limit` / `valid_until`。旧文本计划可回放，但不具备自主提交资格。

首次配置使用 `ag route --config-identity --json` 取得精确 `routing_sha256`，再把它
填入计划及规则。该入口仅调用 T185 的 `ladder_config_identity`，在任何计划、规则、
租约或监控读取之前执行；不依赖 study，不输出账号、主机、路径或入口名称，不查询
远端，不创建 registry、锁或 monitor 文件。只输出哈希；配置改变后须重新取得身份。
`--template`、`--tier`、`--study`、`--walltime` 及自主上下文等选择参数不得与其混用，
无须伪造模板/档位。缺少 T185 同一算法时明确报错，不复制算法或采用另一种摘要。

普通 Gaussian 从冻结文件核对方法、基组/类型、色散、溶剂、积分网格及 Opt/Freq/SCF
收敛下限。允许已核验的算法/循环数和输出选项变化，不把完整 route 字节相等当约束。
CREST/xTB/Multiwfn 使用各自受支持参数，gaussian-cp 保留专用片段限制。T188 组合时，
仅其正式 `verified_files`、主输入和不可变 input_validation 标记能启用放宽例外；
规则和计划均须允许，保存跳过清单并标“方法口径未核验”。每个 Link1 段仍核对
收敛下限，不能用放宽输入绕过最终 Opt/Freq 要求；这不扩大科学支持范围。

提交固定按配置提交锁 → 全机登记锁 → study 状态锁核验并消费，长网络 IO 在锁外。
全机登记位于标准本机配置根的 autonomy-studies/autonomy-reservations，独立
`autonomy-submit.lock` 不被手动提交的长网络过程占用。全机扫描交叉核对目录登记、
不可变 reservation、claim、摘要、submission/status、journal 以及 T184 消费；
缺失或截断不是零，未经人工解除的 UNKNOWN 保留额度。非零自主调度响应也保持 UNKNOWN，不能只凭
错误前缀断定从未提交；只有已记录的 dispatch 前 abort 证明未提交，且不退回历史计数。

`state.submissions` 按当前 round 汇总实际消费；规则改名、换配置、计划修订和唤醒
不清零。prepare 不消费提交次数；Attempt 上限及 90% 阈值只使用提交消费记录，
已经消费后在 dispatch 前中止的记录保留。准备应随用随备，不预先准备整批。
原始选择的请求、快照、placements、wakeups 和时间均持久化，再由 T185
同一算法重算。SCNet4/兜底排队2按全机所有 study/轮次核对，手动/非 ag 作业仍计
账号核心总数。CREST/xTB 复用旧路由顺序并叠加可信占用；不另建高斯阶梯。
只读 route CLI 使用同一绑定上下文，拒绝时不创建等待记录或修改状态。

prepare 的最终分配、远端建目录、复制父 chk、每次上传、最终 dispatch 都重新核验。
到 90% 原子记录暂停，已消费但未 dispatch 的成员保留 abort。dispatch 之前保存
不可逆边界；暂停不能撤回已发请求。晚到确切响应可补原作业绑定，但不恢复动作资格、
不倒退已观察到的 running/finished/fetched 状态，也不能重新提交同一 Attempt。

普通 PBS/Slurm 提交和 status/fetch 使用现行正式接口，不依赖 T187、Slurm 版本探针、
原始实例或绑定提交构造器。旧实验 probe/reroute 归属拒绝用于新动作；UNKNOWN 仍须
通过确切原作业证据只读找回，或按下述显式人工路径解除；不能自动释放或重提旧 Attempt。

`start --observe-only` 可观察到期计划，版本/哈希/60 分钟动作及 90 分钟接管限制保留，
禁止新 prepare/submit/resume/count。status/snapshot/fetch 的观察参数为 `--run`、
`--token`、`--plan-sha256`。网络与解析在锁外，最终状态/快照/输出/facts/journal 发布
在短事务内再次核对 owner。Slurm 结算先在配置锁内复核并发布预算，再单独复核并发布
状态；两者之间失锁不回滚先前合法结算。没有自主轮次的普通手动调用保留原行为。

手动 prepare/submit/fetch、独立 facts/refresh/reparse，以及会发布本地证据的
CLI status/snapshot 使用 writer 登记，
running 或有效 lease 时拒绝；
paused 且无有效 lease 方可写。90 分钟接管记录原租约，旧 token 不可用。
专属 writer flock 跨实际操作，但不长持全机/study 锁。崩溃登记通过
`ag autonomy manual-writers --study '<STUDY>'` 查看；只有没有活动 flock 的完整登记
能由 `release-writer --writer-id '<ID>' --quote '<逐字确认>'` 独占解除。
这不删除旧记录、不恢复自主、不更改作业/UNKNOWN/预算，不替代人工取消确认。facts 外部 dry-run 不写 study，仍可读取预览。

同对象同 canonical 失败最多两次补救，必须由前次实际消费及已结束失败证据推导；
`--failure-class` 只是可选断言，不能省略或改名绕过。TS 正常结束但零虚频或方向不符
由 `ag autonomy scientific-review` 保存来源绑定的理由，标待人确认；方向判断必须
有对应 mode-review 及位移文件，代码只检查来源，不替代科学判断。完整输出及正式
Slurm 不完整失败取回可在已实现范围内作补救来源；PBS 诊断性不完整取回不自行证明失败。
没有退出回执的 PBS interrupted 可使用正式不完整取回所绑定的确切作业、两次相隔
至少 300 秒的稳定非活动观察和最终核验作为来源；仅精确 ag-start 作业/时间与首张非活动观察
时间证明已达到冻结 walltime 时归为 walltime，否则归 interrupted。

资源核算与失败补救分别核验。历史手动终态不作本地在途预留；审计缺失留警告，
账号调度器清单中的实际作业照常统计。自主归属仍严格审计；自主终态只有相邻两张
完整、成功、新鲜监控快照都缺少确切作业号和唯一名时才释放本地资源占用；
两张均须晚于进入终态的证据，并以 `account_sha256` 匹配归属和当前账号。
旧快照缺少账号指纹时保留占用，不能在换账号后沿用同名入口的空清单。
`previous.json` 保存完整前驱，失败/控制快照也轮换，不能跨过失败拼成两张成功。
此核算结论不证明可再次提交旧 Attempt，也不解除 UNKNOWN。
Slurm 的两次提交核数检查也按同一严格证据重新核算：只从临时 ledger 副本排除
匹配 root/study/cluster/account/bundle 的已释放预留，实际核时账本、消费和声明不变。
当前账号清单中的实际作业仍计核，不把资源释放当作退回核时额度。

取消来源须先由负责人显式执行本地命令：

```sh
ag autonomy resolve-attempt --study '<STUDY>' --attempt '<ATTEMPT>' --quote '<负责人逐字解除原话>'
```

该命令只读取已核实的本地证据、追加人审决定及哈希。取消须有上述两张缺席快照；
UNKNOWN 须由正式 status 成功按唯一作业名查询无匹配，并通过已有固定只读命令
确认 ag-start 不存在，观察账号指纹须匹配不可变归属；本地账号展开在查询前后也须一致。
观察须在实际消费后且不超过 600 秒。后一次失败或含糊观察
会使旧负面证据失效。解除不写旧 status/claim、不退回真实消费、不自动 resume，
也不授权提交；新 Attempt 仍须逐项核验计划、规则、owner、资源及字节。
历史人审决定保留；后继准备还需当前同类新鲜证据，发现新作业/回执不能沿用旧缺席。
取消后归 interrupted 的新补救受科学两次上限；UNKNOWN 人工解除不伪称从未派发。

对象的补救来源不可用、科学次数耗尽、facts 冲突或 placement 变化只记录该对象
“需要你看”；身份/哈希、配置/规则/计划/版本、UNKNOWN 和 90% 预算问题仍全局暂停。
派发前 SSH 失败独立记录，同一唤醒同一失败不重复计数；首次禁止依赖该失败证据
继续动作，连续两次唤醒失败才全局暂停。同对象每轮实际派发前失败上限为 2，
达到后该分支交人，不占科学补救两次额度，也不退回实际 Attempt 总预算。
未派发的科学补救后继保留原科学来源，不能通过 presubmit 链清零科学次数。

本版不提供自主取消、停止证明或改投入口，也不接受 `--reroute-source`。
需要这些动作时，对应分支交人处理；唯一 owner 使用现有 `ag autonomy update` 的
`summary/pending/objects` 记录“需要你看”，保留其他对象，并在 summary 第一行提醒
负责人在 Mac 上亲手确认取消。自主卡片不调用取消命令。已证明结束失败的新 Attempt
补救仍按前述两次上限处理；不能把本次删减理解为删除普通失败谱系。

`autonomy_submission.audit` 继续只读审计旧手动证据；`autonomy status` 本身不扫描
全机 reservation，不能把其意图数或未做全局交叉检查的 JSON 当作提交许可。
跨唤醒快照过期和其他全局运行条件仍按后续入口范围核对。手动 cancel 的每次本地
声明、journal 和状态发布共用配置锁 → 全机锁 → study 锁；Mac 弹框和网络在短锁外。
状态观察以最初读取的 status 为发布基线，拒绝慢查询覆盖后来取消/完成状态；
取消晚到也保留更新的完成或不确定状态。验证按
[T186 工单](redesign-tasks/T186-plan-bound-submission.md)留存：本地只跑受影响流程，
全量交 CI，真实验证前对最终组合另跑一次；不做 AST 比对。旧含 T187 组合仅为历史证据。
首轮审阅回应只交绑定新 head 的增量 diff、逐项答复、红绿证据及修订的未执行真实验证
草稿，不再重复整份源码包。T188 放宽语法现已补齐 Opt GEDIIS/NoTrust、SCF NoIncFock/NoDIIS、
IRC GS2/CalcAll、Freq HPModes/SaveNormalModes 八项；最终组合回归与真实验证仍须分别留证，
语法接入不等于现场通过。监督审阅、真实试点及显式启用完成前不能运行自主计算。

## 提交流程：规范顺序

本节描述当前手动模式的 CLI 行为；自主模式的启用条件见上节。

规范顺序与当前 `submit.submit` 实现一致，参见已合并 [#209](https://github.com/anakine800-tech/Auto-Gaussian/pull/209)、[#224](https://github.com/anakine800-tech/Auto-Gaussian/pull/224)：
锁内校验输入和集群 → 核对显式批准记录/规则 → 核数及 Slurm 台账预检 → 打印摘要（无显式授权时 Mac 确认）→ 整批再校验字节和授权 → 独占消费批准 → 逐个 Attempt：声明 → Slurm 核时预留 → submitting → 独占存档本 Attempt 摘要 → 复查占用 → 建目录 → 上传并逐文件核对大小/SHA-256 → qsub/sbatch → submission.json → submitted。
这里“声明”指以 `O_EXCL` 创建 `.submit-claim`；有声明就不能再次提交该 Attempt。
声明放在确认之后，是为了让人在弹窗取消时 Attempt 仍保持 prepared、没有声明，之后可正常提交，不因取消而消耗一次提交机会。

核数统计包含该用户在目标集群的全部作业，不能只统计 ag 作业；还要计入已提交但尚未读回的占用。
PBS 和 Slurm 的单作业上限均为正整数 max_cores；运行加排队（含挂起）总上限均为 max_committed_cores，不再限制为单作业的四倍。
可选 max_queued_cores 在提交前和确认后限制排队、挂起和尚未读回的预留；同集群入口取已配置限额的最小值。scheduler_max_running_cores 仅记录调度器应实施的运行限额，ag 不设置或验证该配置。
普通提交不读取节点；显式具名 PBS 提交在确认后、批准/声明消费前，以及上传核验后、qsub 前各复查一次节点。
具名候选、prepare 和实时复查共用 node_targeting.admission；正常占用及具名排队不再拒绝，按总 slots 映射档位。
容量提示复用 T156 evaluate_node 和精确内存字节；分配内存未知只影响提示，身份、总规格和一致性仍必需。
候选保留 status 显示，节点及各比例选项增量返回 selectable/selectable_reason，选项的 capacity 附原容量结果。
每项声明后仍复查全部本人作业，Slurm 另计本地尚未读回的预留。ag 不限制运行中的核数。
Slurm 台账在远程写入前预留核数 × walltime，按结束证据结算，unknown 不释放。
`budget_core_hours` 不再作核时额度拦截，配置了该字段仍须是正的有限数；台账记录本地 ag 的预估、预留与结算，不代表平台余额，也不包含外部网页作业的消费。
这不取消核数、排队限额或台账完整性检查；缺失/损坏的台账及提交绑定仍拒绝，不能按零预留处理。
父 chk 若已声明，在新目录中先专用复制并核对来源/目标哈希，再上传其他输入；不改变父文件。
上传使用确认后核验过的字节快照；脚本、输入和附件都不能在确认后被悄悄替换。

负责人明确批准后，`ag approve --study <S> --attempt <ID> [--attempt <ID> ...] --quote '<逐字原话>' --hours 24`
在 study 的 `approvals/<批准ID>.json` 独占保存 prepared Attempt 的身份、bundle SHA-256、集群、核数和原话。
有效期从写入时起算，必须大于零且不超过 24 小时；此命令纯本地，不发起 SSH。
会话负责核对原话来自本 study 当前会话中的负责人；CLI 保存原话，不能验证其发言身份或替代人的批准。
`ag submit <ID> ... --approval <批准ID>` 整批核对；任何成员不匹配、损坏、过期或已使用都拒绝，不回退弹框。
核数预检、打印摘要和字节复核之后，再次核对有效期和记录内容，以 `O_EXCL` 创建 `.used` 标记；标记写入/落盘失败禁止远程写入。
记录本体不改；一个批准可覆盖多个 Attempt，但只消费一次，提交其中一部分也会消耗整条批准。中断或后续检查失败不恢复批准，也不重试提交。
摘要只在该 Attempt 已声明后独占创建，存档失败走 failed_presubmit 且禁止远程写入；后续未声明成员不预写摘要。批次中途停止后，仍为 prepared 且没有 `.submit-claim` 的剩余成员须重新取得批准，或改由负责人点击 Mac 对话框，之后才能提交；已有声明的成员不能重提。

长期规则仅在负责人明确指示后写入本机配置的 `approval.policies.<name>`；study、模板、集群均为明确名单，无通配符。
使用 `ag submit <ID> ... --policy <name>` 显式选择，核对核数和 walltime 上限；规则不匹配直接拒绝。
`ag doctor` 的 CLI 输出包含 `approval_policies` 及适用范围。未给 `--approval` 或 `--policy` 时仍走 Mac 对话框，即使配置了匹配的规则也不自动选用。
两参数互斥，取消不接受它们；`ag cancel` 始终由人点击 Mac 确认。具体配置见 `ag/config.clusters.example.toml`。
三种提交方式受具体入口与验证对象的更窄要求约束：具名 PBS 不接受长期规则，只接受绑定节点的显式批准或 Mac 对话框；特定验证要求亲手点击时仍须点击。不能用一般提交概述扩大验证授权。

每个实际获授权的提交在 Attempt 中独占保存 `submission-summary.json`（原始摘要、授权来源和 manifest 哈希），journal 追加 `submit_authorization`。
`submission.json.authorization` 记录 `method`（`approval` / `policy` / `dialog`）、`approval_id` / `policy_name`、`quote`、`rule_sha256`；
批准模式另记 `record_sha256`。规则/记录哈希基于排序键、紧凑 UTF-8 JSON；dialog 无原话或规则哈希，相关字段为 null。
摘要和 journal 在作业号获取前保存；响应不确定后由只读 status 找回唯一作业时，核对摘要绑定后将原授权写入 submission.json，不重新授权。
两次核数检查、排队上限、共享入口预留和 `.submit-claim` 均保留。

## 状态速查

完整允许迁移见 `state.TRANSITIONS`；状态描述执行证据，不能替代科学审阅。

| 状态 | 含义与下一步 |
| --- | --- |
| prepared | 本地准备完成；可请求人工确认提交。 |
| submitting | 已消耗单次声明，正在提交；中断后保留声明并人工核对，不手改回 prepared。 |
| submitted | 已取得并绑定作业号，尚无运行或完成证据。 |
| running | 调度器报告运行；继续只读观察。 |
| awaiting_second_observation | 首次证据不足；按 next_observation_at 等待第二次观察，至少相隔 60 秒。 |
| stalled | PBS 仍运行而声明输出至少 60 秒未变化；需结合进程/日志判断，不自动取消。 |
| interrupted | 无充分完成证据，且作业不活跃或报告异常；PBS 满足五分钟稳定、不活跃且无回执的两次观察后，可显式 fetch --incomplete。 |
| finished | 程序退出回执、旧 PBS 完成证据或 Slurm 终态已确认；检查退出码，再 fetch/解析/审阅。 |
| fetched | 声明输出已取回校验；仍需 facts 和科学审阅。 |
| cancelled | 已发出经确认的取消；不据此断言程序科学失败或调度记录已经消失。 |
| failed_presubmit | 确定未提交成功，如提交前失败或 PBS 明确拒绝；该 Attempt 已消耗，不能再提交。 |
| unknown | 提交/状态证据不确定；仅只读核对，不能把无记录当作未运行。 |

unknown 经唯一、匹配的作业证据可回到已知状态；找不到或歧义时保持 unknown，交给人决定。
手动模式对 failed_presubmit 或计算失败提出新 Attempt，经人确认；已启用自主模式只按 [AGENTS](../AGENTS.md#自主运行)判断是否允许有界补救。哈希不符、状态损坏或 UNKNOWN 不按普通失败补救；任何模式都不删除声明、不重用目录、不重提原 Attempt。
PBS 有退出回执时可 finished 并取回，即使队列仍显示 R（调度器残留）；清理只走确认后的 cancel。
旧 PBS 无回执时：完成标记 + 两次输出稳定；队列仍有 R/C 记录时还需会话进程证据，读取标记后再复核输出。
Slurm 从 squeue 消失仅触发 sacct 核对；终态中非零退出/信号以及 FAILED、TIMEOUT 等都不是科学成功。

`fetch --incomplete` 不新增状态，也不把 interrupted/finished/cancelled 改成 fetched。
PBS 的 `incomplete_observations` 只补充证据，不改变已有 60 秒观察规则或核心状态判定；输出变化、回执出现或重新入队都会清空/重置这组证据。
Slurm 取回前后均只读核对 squeue 无此作业及 sacct 终态（TIMEOUT、CANCELLED、FAILED、OUT_OF_MEMORY、NODE_FAIL、COMPLETED）；COMPLETED 仅在缺声明输出时适用。
本地 cancelled 可显式不完整取回，但须核验 `.cancel-claim`、匹配确切作业号的 `cancel/succeeded` journal，以及 manifest/submission/status 绑定；单独改状态标签不能放行。
取消请求成功不等于调度器已停止。取回前后仍独立核对结束证据：PBS 要有至少相隔 300 秒的不活跃、无退出回执、输出稳定的两次 status 观察，并实时核对确切作业不存在或为 C；Slurm 要有 squeue 无该作业及身份匹配的唯一受支持 sacct 终态。存在退出回执时改走普通 status/fetch；COMPLETED 且输出齐全也走普通 fetch。
独占记录绑定 manifest SHA-256、集群/作业身份、存在输出哈希、确认缺失项、结束证据和 ag 版本；记录与本地字节不符时 facts/父 chk 均拒绝。
已有不完整取回记录拒绝普通 fetch、重复 --incomplete 和 --add-missing，两个显式选项互斥；缺失文件不能被后续补放后静默升级成正常结果。
失败保留 `.partial`，验证全部通过后独占发布；本地发布失败仅撤回本次已创建的链接，暂存字节仍保留。远端无写入。
并发取回锁位于 `outputs/.partial/.fetch-incomplete.lock`，不放在 Attempt 根目录；签字清单不收集该暂存锁。
调度器 walltime 匹配仅设置 `error_hint` 和来源，不改变日志解析的 termination；有效不完整取回记录才将 normal 降为 incomplete，日志本身的 error 保留。

## 集群绑定：读哪个记录

- `manifest.json`：prepare 后不改；记录目标 cluster/scheduler、相对远程目录、输入哈希、方法、父关联和可选卡片快照，不保存连接凭据。
- `submission.json`：提交后独占写入；绑定 Attempt、集群限定作业号和 manifest 原始字节的 SHA-256；与 status 交叉核验后才能取消或关联。
- `attempt.local_record`：函数，不是新文件；先读 manifest 并过滤集群，再按该调度器读取 status/submission，返回 manifest、状态和原始作业号。

扫描 monitor、预算、list/status 等时复用 local_record/local_records；别先用 PBS 解析器读取所有 status。
旧无 cluster 的 manifest 按 default PBS 解释；无前缀作业号仅属于 default PBS；有前缀也必须与 manifest 一致。
其他集群的 status 不参与当前扫描；本集群缺失/损坏绑定须报出具体 Attempt，不能静默跳过或用可变 status 代替。
核对案例见 [#229](https://github.com/anakine800-tech/Auto-Gaussian/pull/229)、[#235](https://github.com/anakine800-tech/Auto-Gaussian/pull/235)。

## 怎么加功能

### 本地命令

在 `ag/src/ag/` 写确定性模块；参考 dedup 的 `register(subparsers)` 并在 `cli.py` 挂载。
纯文件工具不加载远端凭据、不创建 Transport；只需 studies_root 时用现有 local_only 配置路径。
参数、JSON、错误及已有输出不覆盖都用合成数据测试；科学判据优先写卡片，不再建工作流框架。

`ag autonomy` 的实际命令、字段和恢复步骤见 [autonomy 使用说明](../ag/README.md#本地自主运行记录autonomy)。
它只在已有 study 的 `autonomy/` 写入，计划创建与负责人确认分开；版本取实际干净 ag 提交和已安装依赖。
计划字节不覆盖，动态对象写状态/日志；`begin --plan --quote` 明确创建授权轮次，`start` 只创建该轮内的一次唤醒租约。
`finish` 只关闭唤醒并保留轮次状态；`end --round '<ROUND_ID>' --reason '<原因>'` 才结束授权轮次，
其中轮次 ID 取 `begin` 输出的 `state.current_round`，必须在锁内核对并记入日志，避免迟到请求关闭新轮。
结束后 `start` 拒绝，须显式 `begin` 新轮次；无租约的 `end` 也不能省略 `--round`。
`totals` 保存全历史，`rounds` 保存逐轮计数，`runs` 保存逐次唤醒计数。计划修订、再次唤醒及接管不重置本轮预算；
`attempt_limit` 按当前轮次计数检查，新轮预算只能由显式 `begin` 创建，历史不清空。
`begin` 也保留暂停标志；新轮可取得暂停状态下的唤醒租约，但仍须显式 `resume` 才能恢复动作。
为了防止进程崩溃丢计数或旧进程恢复后继续写入，每次短操作在固定 `store.lock` 的 OS 互斥内
重放并校验日志、状态、计划及当前租约，先落盘追加事件再原子发布快照。
状态只落后于完整日志时才允许显式恢复；截断、未知状态、部分日志或哈希错误均拒绝，不能重置计数。
60 分钟到点即失去本次唤醒的动作资格，90 分钟后才能显式接管或用无令牌 `recover` 关闭过期租约；
恢复只关闭过期唤醒并保留轮次状态；恢复与接管保留证据且不会清除暂停，旧令牌不能操作新租约。

`action_guard(...)` 的锁只包短本地动作边界，不包网络或完整运行；`check(...)` 的返回值不能缓存为授权。
暂停由任何会话发布，仅与短操作串行，发布后的新动作检查拒绝；当前持有者仍可在原期限内观察、取回和整理。
T186 的 submission_guard 在 prepare/submit 边界重查，并按不可变声明/归属核对实际消费；
本地意图计数不是执行证据。可核验的版本/计划失效会在短事务中记录暂停；
不能在 `action_guard` 内嵌套调用再次获取锁的 `pause()`。本版自主取消及改投关闭，需要时记录“需要你看”。
验证只用临时合成 study、模拟时钟及真实本地子进程；不读取研究数据、不改共享运行环境、不连接集群。

### 远程命令

先说明具体要防或解决的事故，在 `remote.py` 增加固定 Command，参数经白名单和路径检查；不接受 shell 文本。
只读操作同步加入 `transport.READ_OPERATIONS`；写操作不进入该集合，不获得自动重试。
**白名单测试必须同步更新**：参考 `test_core.py::test_remote_allowlist_and_paths`、`test_slurm.py` 和相应功能测试，断言完整命令、操作集合及坏参数拒绝。
覆盖链接替换、越界、SSH 255 和响应丢失；远端助手兼容目标 Python，不能拿本机版本替代。

AGENTS.md 第 7 条的例外只覆盖 ag 暂无对应命令时、限定在单个 Attempt 范围内且逐次展示完整命令并获负责人明确同意的临时只读查看，不是开发捷径；仍须遵守该条的命令白名单、路径限制、输出处理和 study.md 记录要求。出现重复需要时，应开工单做成 ag 的正式只读命令，经监督方审阅并在合并前完成真实验证；正式命令可用后，立即停用对应的例外用法。

### 程序模板

新增受审阅的 `ag/templates/` 程序体和 `.toml` 参数/输出声明，并同步 render、prepare/CLI、配置校验及 facts 解析入口。
不是只把文件放进目录：`render.declaration` 的程序白名单也须显式更新。
复用 `_guard.sh`，私有 scratch、独占回执、只执行一次；不随意 source 平台环境脚本。
CREST 可选 `programs.crest.executable` 独立绝对路径，doctor 与模板使用同一解析函数；省略时继续使用 xTB 安装根的 bin/crest 并保持原渲染字节。
用假程序检查成功/非零退出、输出和回执；保持既有 PBS 渲染结果逐字节不变，不重写旧 prepared bundle。

### 调度器

沿 config、固定 remote 命令、纯解析、render、submit/status/cancel/doctor/monitor、预算和 submission 绑定逐处接入。
按集群选 Transport；核对属主、完整作业名和确切作业号；全用户占用含数组与非 ag 作业。
测试提交响应丢失、队列读回延迟、终态/缺失记账、跨集群同号、预算预留与取消目标；Slurm 保留 `--no-requeue`。
不要新增通用调度抽象来预留未知需求；参照 [T16](redesign-tasks/T16-slurm.md) 的具体接入点。

### 卡片

放在 `skills-next/auto-g16-recipes/cards/`，同步 Skill 索引和 `skills-next/tests/test_skill_format.py` 的卡片清单。
固定八个二级小节（保留编号）：
1. 适用范围
2. 前置条件
3. 输入模板
4. 资源建议
5. 提交前检查清单
6. 结果判据清单
7. 常见失败与处理
8. 常见坑

每卡最多 **285 行**，“常见坑”最多 **10 条**；超限先合并或删除，不随最长卡片重新抬高上限。
TS 拆分后总入口及各阶段卡均遵守此上限，不再保留 ts 的 400 行例外；入口保留现有锚点和可直接提取的第 6 节清单，旧 Attempt 快照不改。
为防止已实现工具仍被卡片写成缺功能、复制的方法骨架继续漂移，CI 的
`skills-next/tests/test_card_consistency.py` 从实际 CLI 注册核对子命令和选项。
“待 Tn”只能引用 `docs/redesign-tasks/open-tasks.txt` 中的任务，完成时同 PR 移除记录与标记。
方法/基组只在 `acceptance-methods.md` 定义；骨架使用占位符，具体 route 仅限逐例标明的“流程验收示例”，且组合仍须在方法表中。

第 6 节写可逐项审阅的判据；只有显式 `prepare --card <名称>` 才保存卡片文本、Git 提交号和 dirty 状态。来源优先为本机部署的 recipes，未部署时才用当前检出的卡片；须核对实际来源。
无快照的 manifest（包括未传 --card 的新 Attempt）须在 `review init --card <名称>` 指定审阅卡片，来源只保存在 review.md，不补写 manifest；已有快照不能被 --card 替换，review check 使用保存的判据，不追着最新版改旧 Attempt。见 [#228](https://github.com/anakine800-tech/Auto-Gaussian/pull/228)。

## 测试与敏感信息

### 开发机分工与合并前真实验证

负责人 2026-10-16 决定：开发机可以连接集群，所有开发任务（包括合并前真实验证）都在开发机完成；计算机只负责研究 A 计算。此决定取代历史经验中“开发会话不连接集群”的分工描述。
T62 的远程观察改动虽通过离线测试，真实运行却出现 unreadable 并由 T65 回退；为避免再次将未验证的执行或证据路径带入研究，涉及**证据清单、远程命令、提交、状态、取回**的改动，工单必须写明真实验证对象和步骤，并在**合并前完成**。验证在开发机上使用非研究 study（L1、L2 或专门的验证 study）；涉及提交由负责人亲手点击确认，研究 A 只做观察，不作为验证对象。纯文档、纯本地分析工具不受此限。结果记录执行版本、范围和实际结论；遇到意外按 AGENTS.md 停止报告。

工单应区分三类证据，不把缺授权或缺对象改写成“合并后补”：

| 改动/目的 | 时机与证据 |
| --- | --- |
| 远程或上述证据路径改动 | 合并前：列出非研究对象、确切执行提交、固定命令/次数、预期结果、授权范围与停止条件；未获授权或缺样例记待验证，不能据离线通过宣称完成。 |
| 纯文档、纯本地分析工具 | 合并前离线验收：文档做相关 Skills 测试及语义/链接核对；本地工具做合成回归。不因任务类型创建无意义的远程验证。 |
| 发布后安装、构建、服务与配置验收 | 在具体部署授权和维护窗口内按 [运维文档](OPERATIONS.md) 执行；不能替代该代码合并前必需的真实验证。 |

自主开发、旧的一次性命令授权、PR 合并都不授权新的现场操作。更窄的验证对象、命令和人工点击要求优先。

### 测试范围

负责人 2026-10-16 决定：开发中只跑相关测试；推送前本地跑一次后端全量 `pytest ag/tests skills-next`，之后以 CI 为准。纯文档改动本地只跑 `skills-next`，其余交给 CI。
前端首次开 PR 和合并前跑全部浏览器测试；复测只跑受影响部分加构建，前提是 rebase 没有带进其他前端改动。跨页面的完整集成回归只在发版前做一次。测试通过不能代替合并前的真实验证。

### 本地证据与签字

`parse_facts` 只返回内存中的事实和几何文本；thermo/profile/review check 不生成或改写 facts.json。
`ag facts` 比较新旧解析内容时排除 `ag_provenance`；解析内容相同则保留旧文件原始字节和 mtime，
不归档、不补写缺失的 provenance，升级提交号不会使既有证据失效。只有解析内容不同时才列出差异并拒绝；
人工核对后用 `ag facts <id> --refresh`，先保留原始字节为 `facts.<SHA-256前12位>.json`，再原子写入新版。
已有几何仍不得覆盖。新 facts 的 `ag_provenance` 记录解析器 checkout 的提交号与 dirty 状态；
review 快照绑定该来源，不能用当前 HEAD 或 Skills 提交号代替。旧记录缺版本时明确报告未知。

签字前运行 `ag review manifest --study <dir>`；它无需配置或网络，独占创建
`analyses/review-manifest-<UTC时间>.json`。清单包含 study.md、全部 facts.json/review.md，
以及从 study/review 和已引用分析文件递归发现的 analyses/ 输出，记录相对路径、字节数和 SHA-256。
文档用 Markdown 链接、反引号路径或显式 `analyses/文件名`；分析 JSON 支持相对文件路径，
包括 profile 的 `thermo` 引用。含空格路径用 Markdown 尖括号链接或反引号；二进制输出只哈希不解析。
普通引用的 `missing` / `escapes_study` 进入 `unresolved_references`，退出码 4 且不写清单；签字人逐项核对后可显式 `--accept-unresolved`，清单保存完整列表与确认时间，每次重跑重新收集。
study 内存在的 analyses 外显式引用（`outside_analyses`）及无 analyses 同名文件的裸名（`unqualified_name`）只列信息，不新增收录，不需该参数。
study 内符号链接、歧义、非法显式路径、空分析目录、收集期间哈希变化，以及 JSON 专用指针 `thermo` / `frozen_evidence` 的缺失或越界仍是硬错误，接受参数不能绕过。
远程 URL 不下载。未被引用的分析输出不纳入清单，因此签字前先在 study.md/review.md 写全依据；分类细节见 [review manifest](../ag/README.md#签字证据清单review-manifest)。生成清单不是科学签字；向人展示清单后，
将清单路径和命令返回的清单 SHA-256 一起记入签字记录。旧清单保留，每次签字生成新的清单。

新测试只用合成配置、合成小分子和假 Transport/假 ag，不读取真实配置、研究数据或连接集群。
从现场问题改写脱敏样例时，虚构身份和值，但保留空格、截断、换行、列宽、返回码和缺字段的真实形态。
既有经审阅的小分子 fixture 留作回归，不把原始现场日志、chk 或私有研究 fixture 加入提交。
PBS 兼容性要比较渲染字节或固定哈希，不能只比较脚本语义；本任务没有模板变化。
从仓库根目录、已具备项目依赖的 Python 环境运行：

```sh
PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs
git diff --check
# 逐个暂存本任务文件后：
python scripts/scan_public.py --staged --terms-file ~/.config/auto-gaussian/sensitive-terms.txt
git diff --cached --check
```

不要设置私有日志 fixture 环境变量。macOS 跳过的 Linux 方言检查由 Linux CI 补足，报告跳过原因。
扫描器只覆盖部分常见模式；还要人工检查 diff、PR 正文和提交元数据中的主机、用户名、作业号、凭据及绝对路径。
提交前在本机核对 author/committer 都使用 GitHub noreply 邮箱；不要把身份检查的原始输出贴到 PR。
真实验证按上文在合并前完成，单独记录执行版本、范围和结果；离线通过不等于实际提交或科学验收。

## 角色与审批

三方分工：负责人做决定、合并、科学签字和计算授权；监督方（Claude）写任务单、审阅 PR 并留评论，也可以提交文档 PR；执行方（Codex）按任务单开发，真实环境操作须经负责人授权。

| 事项 | 由谁决定 | 说明 |
| --- | --- | --- |
| 合并任何 PR | 负责人 | Codex 和监督方都不合并、不直接推 main |
| 修改 AGENTS.md | 负责人明确批准 | 在 PR 中写明批准记录 |
| 修改方法表（方法、基组、窗口、热化学设置） | 负责人确认 | 在 acceptance-methods.md 写明确认日期 |
| 涉及 remote、submit、cancel、status、fetch 的代码 | 监督方审阅通过后再合并 | 新增远程命令须写明防的是哪个事故 |
| 卡片与 Skills 修改 | 监督方审阅 | 卡片一致性测试必须通过 |
| 真实计算的提交 | 负责人批准；ag 逐项核对 | 手动模式保留一次性批准记录、显式长期规则或 Mac 人工点击；自主模式须满足 [AGENTS](../AGENTS.md#自主运行)启用前提，旧规则不赋权；具体对象的更窄限制仍有效 |
| 真实计算的取消 | 手动模式由负责人在 Mac 上亲手点击 | 当前 cancel 不接受提交批准参数；未来自主例外仅按 [AGENTS](../AGENTS.md#自主运行)实现并验证，其他取消仍不得代点或绕过 |
| 科学签字（机理假设、结构、代表构象集合、最终结果） | 负责人 | 签字前先生成证据清单 |
| 计算平台与软件许可的科研用途认定 | 负责人 | 记入 study.md |
| 创建 tag 和 release | 负责人在 GitHub 网页操作 | 版本号与 CHANGELOG 先经 PR 合并 |

监督方审阅评论的首行为 `<!-- ag-review head=<短哈希> -->`，正文写“通过”或逐条列出需要修改的项；只发评论，不推送他人分支、不合并、不改 Issue、不碰集群。PR 更新后按新的 head 重新审阅。

## PR 与发布

一张任务单、一个 `codex/<任务名>` 分支、一个 PR；描述第一行写 `Task: Tn`，模板见 [TEMPLATE.md](redesign-tasks/TEMPLATE.md)。
只写改了什么、验证结果和实际阻塞（结构/提交/解析/科学审阅/环境）；不另造规章、合同或指标体系。
监督方评论首行是 `<!-- ag-review head=... -->`；用 `gh pr view <编号> --comments` 读取，逐条修改并回复。
涉及 `remote`、`submit`、`cancel`、`status` 或 `AGENTS.md` 的改动，合并前等监督方审阅；AGENTS.md 修改还需负责人明确批准。
有冲突在本地 fetch 后 rebase 到最新 main，检查差异并重跑受影响测试；不用网页编辑器解决冲突。
合并只由人操作；Codex 不合并、不直接推 main、不修改分支保护。

发布任务同步 `ag/pyproject.toml` 与 `ag/src/ag/__init__.py` 的版本号，并在新架构 `CHANGELOG.md` 写变更、兼容性和验证。
版本取发布任务指定值，核对包元数据与 `ag --version` 一致；若尚无新架构 CHANGELOG，在发布任务中创建，不改 `archive/CHANGELOG.md`。
版本/CHANGELOG 经 PR 审阅、测试、人工合并后，由人在 GitHub 网页创建对应 tag 和 release；文档 PR 不顺带发版。

## 合并后同步本机运行版本

合并不会自动部署，也不要求每次合并立即更新运行检出。目标选择、安装来源、版本核验和回退统一见 [部署目标与授权适用表](OPERATIONS.md#部署目标与授权适用表)；常规发布按确切 tag，开发机采用已审阅合并提交的长期口径仍是待确认建议。
已有具体更新授权只覆盖所列机器、前后端提交和操作。授权使用 main 检出时，先核对分支、干净工作区及确切目标；只有快进结果等于该目标时才执行 `git pull --ff-only`。目标漂移、分叉或本地改动时停止，不强制重置。
后端在获准运行检出的 `.venv` 中维护依赖；日常真实计算只调用该检出的 `.venv/bin/ag`，核对完整 HEAD、包版本和 Python 导入位置。清除临时 `PYTHONPATH`，不能用开发 worktree 或 PATH 中的旧 ag 代替运行版本。
用未合并代码做真实验证，必须在工单写明对象和步骤并取得批准，在开发机的临时 worktree 使用非研究 study，合并前完成；验证证据留在仓库外，worktree 不再需要时归档。计算机只负责研究 A 计算，研究 A 不作为开发验证对象。
Skills 软链接指向获准运行检出的 `skills-next`，核对实际解析目标与 Git 来源；部署后核对链接不改变旧 Attempt 快照。
前端从本机约定的固定运行检出目录构建和运行，停止旧实例后从该目录重启，
核对其调用的后端也是上述 `.venv/bin/ag`；不从临时 worktree 启动日常前端。
固定目录的具体值只记在本机配置，不写进公开仓库；同步检出不授权提交或取消计算。

## 公开仓库检查（T116）

当前文件的审计发现研究与环境信息会进入工单和夹具，因此 CI 对全部 Git 跟踪文件运行
`python scripts/scan_public.py`，提交前检查暂存 blob，不让未暂存的安全副本遮住待提交内容。
通用模式涵盖 IP、个人目录、非 noreply 邮箱、私钥头及常见令牌前缀；不打印命中原文。
`archive/` 已纳入相同的失败规则；任何未豁免的通用命中均拒绝检查。
确认为合成例子、公共资料或语法误报时，可在同一行写 `# scan-public: allow 原因`；空原因拒绝。
通用扫描仅检查 UTF-8 文本；二进制文件计数并跳过，不能识别研究身份、图像中的信息或所有凭据格式，仍须人工检查。

合并后在开发机与研究用计算机的每个后端检出启用一次：

```sh
git config core.hooksPath .githooks
python scripts/scan_public.py --terms-file ~/.config/auto-gaussian/sensitive-terms.txt
```

本地词表 `~/.config/auto-gaussian/sensitive-terms.txt` 每行一个正则表达式（普通词可直接写），
空行和以 `#` 开头的注释跳过；特殊字符需要按正则规则转义。不存在时提示并跳过词表，
通用检查仍运行；无效正则拒绝检查。词表命中不接受行豁免，`archive/` 与其他目录相同。
词表内容由负责人和 Codex 在本机维护，不进入仓库、工单、PR、评论或提交说明。
`SCAN_PUBLIC_TERMS_FILE` 仅供使用临时词表验证 hook；日常不设置该变量。
前端使用前端仓库自带的 `.githooks` 和扫描器；在前端检出执行
`git config core.hooksPath .githooks`，再运行上述全量词表检查。
研究用计算机同步后同样启用；只在合并后 PR 评论记录命中数量，不公开命中内容。
