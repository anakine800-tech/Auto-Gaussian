# TS 初猜能力现状审计（T125）

审计日期：2026-10-24。后端基线：`8ab8b915944f5dda3a535fdb68d6e76ccd6e7561`（当次获取的 main，含 T119、T117、T123）。前端读取 T121 已合并 PR #34 的提交 `63236192d25ddc46ca30b4d5e1716b21a76fce4a`，不把其他开发分支或正在运行的前端当成该版本。下文代码行号均对应这些固定提交。

本单只审阅源码、现有测试和卡片，核对指定出版方条目；没有运行量化计算、连接计算服务器、读取私有 study 或修改代码、测试、卡片。源码能证明输入/输出和拒绝分支，不能证明真实体系的 TS 搜索成功率；需要实际计算才能确认的事项明确留给后续工单。

规格保存为 [ts-guess-plan-v1.md](ts-guess-plan-v1.md)。负责人在本次开发会话允许补充脱敏：除第 1.1 节泛称替换外，第 1.2 节具体数量改为泛称，并删除第 6 节两项未经一手核实的工具及 DOI 所在行；其他内容保留。规格的 P0 排期、对象单位和台账选择按 T125 的 A1–A4 执行；T125 本身按工单免做真实环境验证。未发现必须改变现行提交审批或 AGENTS.md 硬内核才能执行本审计的要求。

## 1. profile 的参考态与 T82 检查范围

**结论**

反应曲线先按 `G_state = Σ ν_s G_s` 组成完整状态，再相对定义中唯一的 `reference` 求差；每步另列 `G_TS−G_R`、`G_TS−G_P` 和反应自由能。选择性分支用经标准态处理的 TS 物种系综绝对 G 求对数权重，统一数值平移在比值中消去；没有把各自前体的局部能垒相加作为产物选择性的路径。

但“完全不比较局部垒”也不准确：非循环 `sensitivity` 会比较每步局部正向能垒的最大值，字段是 `highest_local_barrier_TS`，明确限定它不是动力学决速态；`step_decomposition` 也把各局部正/逆垒分别换算成 Eyring 数字。这些输出不能跨不同前体当成直接的产物通量比较。

当前实现包含 T82 及之后的一致性加固，覆盖层次如下：

| 层次 | 实际检查与边界 |
|---|---|
| 构象与电子态 | 同一物种内元素计数、电荷、多重度、虚频数一致；同分子式不证明同一物种，不判断快速互变。 |
| 方法 | 比较频率层及可选 SP 层的方法、基组、显式色散、基函数形式、溶剂模型和溶剂；各物种程序版本一致；SP 要全有或全无。非受支持 SCF 方法及不能可靠定义的自定义方法拒绝。积分网格仅记录和警告。 |
| 频率与来源 | 频率段收敛、完整模式数、正常结束、分段来源一致性；单原子仅豁免模式数。TS 还读人工写入的方向审阅两行，但不自动核实双向 IRC 或真实签字。 |
| SP 配对 | 直接 Attempt 路径复用固定原子行序的 Kabsch、RMSD ≤ 0.001 Å 与输入哈希配对，含 TS；缓存 thermo 路径保留其已有配对证据，不重新生成缓存。 |
| 温度/热修正 | 比较完整热化学 settings：温度、来源浓度、qRRHO 模型、截断、频率/ZPE 缩放、惯量/对称处理；显式请求温度不一致则拒绝，不能只改 RT。 |
| 标准态/计量 | 目标限定 1 M 或 1 atm，按每物种做来源浓度到目标的修正；显式自由溶剂另加浓度项。状态计量为正整数，逐态核对总元素和总电荷相对参考态守恒。不是对任意活度模型、浓度或自旋耦合的自动验证。 |

`selectivity` 的条目是单个 TS species 与 `paths`，不是可组合旁观物种的完整 state。它核对相互间组成和电荷，不要求选择性 TS 的组成等于曲线 reference 的组成。因此同组成 TS 可以在共同参考态适用时比较；不同显式溶剂数/不同化学计量通道不能直接塞入同一选择性定义，也不能把人对参考盆地和平衡的判断视作代码已经完成。

**代码位置**

- `ag/src/ag/profile.py:calculate_profile`（296–440）、`step_table`（71）、`selectivity_results`（194）、`selectivity_distribution`（167）、`sensitivity`（267）、`step_decomposition`（99）。
- `ag/src/ag/_profile_sources.py:protocol`（151）、`settings_checked`（199）、`section_source`（321）、`attempt_facts`（425）、`check_review`（462）、`load_species`（482）。
- `ag/src/ag/thermo.py:_frequency_evidence`（65）、`_pairing_evidence`（101）、`_ensemble_consistency`（223）；`ag/tests/test_profile_decomposition.py:test_selectivity_sign_order_and_lowest_conformer`；[T82](../redesign-tasks/T82-thermo-consistency.md) 区分原始任务与后续实现。

**对后续工单的影响**

T-X 应补清局部垒与共同参考下通量的区别，保留已有公式和数值检查；无需以“尚无共同参考态支持”为由重写 profile。不同计量分支或慢交换网络如确有需求，必须单列代码范围，不能用措辞修订掩盖当前接口限制。

## 2. ensemble / dedup 的计数与真实简并

**结论**

`ag ensemble` 是证据汇总器，不做 Boltzmann 求和。它读 dedup 的代表、来源成员及可选 thermo 表中的既有 population；多个 Attempt 匹配同一输入候选或同一候选对应多行 thermo 时标歧义、不挑值。它不检查不同初始候选最终是否优化到同一驻点。

`dedup` 会按分子图、立体标识、所选氢模式、对称等价映射 RMSD、可比能量差以及可选局部构象分箱合并结构。单来源/显式 lowest 合并还涉及能量窗；跨来源 geometry-only 不混比不同层级能量。重复次数保留为来源 members，不自动变成热力学权重。它是有阈值、顺序相关的结构筛选，不能保证 TS 部分成键几何的键推断正确，也不自动重跑于 DFT 最终结构。

实际求和在 `thermo.boltzmann` 和 profile：同一 Attempt 重复列入同一集合会拒绝，选择性内同名 TS species 重复也拒绝；但不同 Attempt 的相同最终几何仍可成为两行，同一 Attempt 被换名放入不同 species 也没有跨 species 的身份去重。若调用方不先整理，会重复计权。

真实简并已有位置：thermo 的显式 `--degeneracy`/`rows[].degeneracy`（带来源），profile 直接 Attempt 的 `degeneracy`，以及独立的等价反应路径数 `paths`；旋转对称数 σ 单列，不应再次乘入上述权重。`cluster --mirror` 还有代表的 `degeneracy`：在非已指定中心手性结构上、能差小且镜像更匹配时逐个增加。它依赖去重输入与映射判据，未证明每个计数都是唯一物理镜像态，也不是完整对称群/所有类型手性的判定器；不能直接把其成员数当真实简并导入 TS 统计。

**代码位置**

- `ag/src/ag/ensemble.py:_layer`（165）、`build`（263；325–378 为能量、thermo 关联）。
- `ag/src/ag/dedup.py:deduplicate`（93–226）；`ag/src/ag/geometry.py:best_rms`（241）及等价映射枚举；`ag/src/ag/cluster.py:select`（11–86）。
- `ag/src/ag/thermo.py:boltzmann`（21）、`calculate_thermo`（237）；`ag/src/ag/_profile_sources.py:load_species`（515、595–608）；`ag/src/ag/profile.py:selectivity_definitions`（130）。

**对后续工单的影响**

T-X 第 3 条主要补操作口径与来源审阅，现有权重字段可复用。自动 DFT 最终驻点去重、跨 species 重复诊断、镜像计数加固属于代码工作，须另定范围；T-B 不应把尝试次数或候选数量复用为 degeneracy。

## 3. xTB 扫描 → scan-peak → TS 输入的接通程度

**结论**

前两段已通：`ag prepare --template xtb` 支持单一 B/A/D 内坐标扫描，通过约束附件开启 `--verbose`，保存定义并声明扫描输出。取回后 facts 结合 `xtbscan.log` 几何/能量和 `xtb.out` 逐点收敛证据，输出 `scan.points[]` 和带哈希的 `scan_points.xyz`。收敛缺失为未知，不能由退出码替代。

`scan-peak` 校验 multi-XYZ 哈希，只从自身及两邻点都明确收敛的严格内部局部极大导出新 XYZ；一维默认选最高的合格局部峰，可显式选其他峰。已有全程相邻能差 >20 kcal/mol 或固定行序全原子对齐 RMSD >0.5 Å 的跳变提示，并注明仅为启发式。二维 Gaussian 仍须显式选 `--point i,j`。

断点在峰 XYZ 之后：Gaussian prepare 只收已写好的 `.gjf`，没有 scan-peak 直接产出 TS route/电荷多重度/资源完整输入的入口。卡片明确要求去掉 XYZ 前两行，将坐标显式写进 Gaussian 输入，移除扫描/冻结段。`--parent` / `--relation` 能人工登记父扫描，但扫描点号、文件哈希、选择理由和 `guess_origin` 不会自动成为候选台账。现有 stdout JSON 也不等于持久化来源记录。

**代码位置**

- `ag/src/ag/crest_input.py:validate`（6–86）；`ag/src/ag/attempt.py:prepare`（161–217）；`ag/templates/xtb.toml`、`xtb.pbs`。
- `ag/src/ag/_scan.py:_result`（137）、`parse_xtb_scan`（260）；`ag/src/ag/facts.py:parse_facts`（252–265）、`build_facts`（349）。
- `ag/src/ag/scan_peak.py:select_peak`（25）、`select_saddle`（86）、`run`（140）；`skills-next/auto-g16-recipes/cards/ts.md` 第 2 节，尤其 68–94、108–116 行。

**对后续工单的影响**

T-C 不需重建扫描执行/解析/选峰；若只补 XYZ → Gaussian 输入与来源是小单。规格另含沿程拓扑和构象连续性，完整 T-C 为中等规模，建议拆为衔接与沿程诊断两块，不降低已有选峰条件，也不让生成输入自动提交。

## 4. 独立优化端点的映射与 QST2 对齐

**结论**

没有找到“接收两份独立优化结果及人确认的原子映射，重排行序/取向并输出 QST2 输入”的工具。现有 QST2/QST3 输入校验逐组检查原子数、逐行元素序列、电荷和多重度。不同元素的顺序不一致会拒绝；同元素原子互换不改变元素序列，会通过这些检查，同时保留人工映射警告。

`_qst_displacements` 对前两组做固定行序、无反射的 Kabsch，仅给出最大的五个原子位移，既不找映射也不改写输入坐标。geometry/dedup 的等价映射用于同一分子图的 RMSD，不能直接代替成断键端点的反应原子映射；结构 Skill 的 TS 立体标签脚本读已给映射，不输出端点对齐后的 QST 文件。

**代码位置**

- `ag/src/ag/gaussian_input.py:_qst_structures`（70–92）、`_qst_displacements`（95–117）、`validate`（191–204）；`ag/src/ag/attempt.py:summary`（379–388）。
- 已查 `ag/src/ag/cli.py` 的命令挂载、`geometry.py`、`irc_compare.py`、`thermo.py:_pairing_evidence`、`skills-next/auto-g16-structures/scripts/ts_stereo_label.py` 及结构 Skill。它们是比较/标注入口，不是所需的 QST2 生成器。
- `ag/tests/test_gaussian_input.py:test_kabsch_removes_translation_and_proper_rotation`、`test_alignment_neither_reflects_nor_remaps_atoms`（105–129）明确保留这种边界。

**对后续工单的影响**

T-D 为中等规模本地工具：显式完整一一映射、元素/电子态检查、正规刚体对齐、映射及源文件哈希留存、QST2 输出。对称歧义应要求人补齐唯一映射/锚点；不能把已有 RMSD 的“最优”自动当反应映射。它生成的新取向不能顺带拿来读取旧 chk 的 Cartesian Hessian。

## 5. 父 chk 力常数与坐标框架

**结论**

Gaussian 程序模板不固定 TS/IRC route（`gaussian.toml` 无 route 参数）；route 来自已验证的 `.gjf`。卡片的父 Hessian 示例用 `RCFC`，TS 卡另允许有依据的 `ReadFC`，明确二者不无条件等价；也有 `CalcFC` 基线。

代码没有强制证明父 chk 来自完整 Freq 或实际包含可用力常数。`_parent` 核对 Gaussian 父 Attempt 的状态、同集群、提交绑定、输入哈希与 `%chk` 文件名；有合法不完整取回记录的 interrupted 父也存在通路。远端助手只核对/复制字节，不解析 Hessian。因而“父 Freq 已完成、Hessian 适用”现在是卡片与人工审阅要求，不能称作程序已强制保证。

取向核对在 `prepare` 调用 `validate_force_constant_frame`：当声明 `--parent-chk` 且 route 命中 RCFC/ReadFC/ReadCartesianFC 时，逐行元素及逐原子坐标与父 `final_input.xyz` 比较，容差 1e-4 Å，禁止借旋转/平移/RMSD 掩盖差异；父输入有 nosymm 时也接受 `final.xyz`。这是准备时检查；提交时继续核对不可变输入、父绑定与 chk 哈希，但没有再次调用此坐标框架函数。

**代码位置**

- `ag/templates/gaussian.toml`、`gaussian.pbs`；`ag/src/ag/attempt.py:prepare`（161–167）、`verify`（含父绑定和输入再校验）。
- `ag/src/ag/parent_chk.py:_parent`（9）、`validate_force_constant_frame`（58–104）、`resolve`（107）；`ag/src/ag/parent_chk_remote.py:SCRIPT/main`（31）。
- `skills-next/auto-g16-recipes/cards/ts.md`（153–160、197–214、250–255）；`irc.md`（56–86）。

**对后续工单的影响**

T-D 应与复用 chk 的坐标框架区分；T-X 保留父 Freq/取向警告。若要把“存在频率力常数”变成确定性检查，需单独允许父 chk/证据路径改动，并按工单安排真实验证；本审计没有读取任何 chk 来证明其内容。

## 6. facts / manifest 中的候选来源可复用程度

**结论**

有可引用的来源基础，没有完整的候选来源字段。manifest 有不可变 `parents[{attempt_id, relation}]`、输入文件哈希和 `bundle_sha256`、`science`、可选 `parent_chk`、卡片文本及提交来源。它能表达已建 Attempt 的谱系，不能覆盖尚未建 Attempt 的手工候选、变换参数、目标/暂定/已验证通道、失败尝试与文献位置。

facts 的 `fact_sources` 是日志事实所在的作业段，`ag_provenance` 是解析器版本；扫描字段有逐点几何哈希。这些均不是候选来源，不应改义。`cards.snapshot` 保存的是实际部署卡片，不是候选生成证明。无需因此另建一套 facts/manifest schema：按 A2，在现有 catalog 追加通道与候选事件，引用已有身份/哈希；兼容性按第 8 问处理，旧 manifest 和 facts 保持原字节。

**代码位置**

- `ag/src/ag/attempt.py:prepare`（220–273）、`read_manifest`、`verify`；`ag/src/ag/facts.py:parse_facts`（190）、`ag_provenance`（282）、`build_facts`（349）。
- `ag/src/ag/cards.py:snapshot`（38）；`ag/src/ag/catalog.py:OBJECT_FIELDS`、`replay`、`plan`；[ag-catalog/1](../ag-catalog-1.md)。

**对后续工单的影响**

T-B 可复用 catalog 追加写、哈希链、锁、派生视图和来源引用，不改事实字段含义、不回填旧输入文件。候选与 Attempt 是可关联但不同的记录；把“未找到”与“未尝试”区分，必须保存真实尝试及其结果。

## 7. 扫描逐点几何能否直接交给 topology

**结论**

不能直接从 CLI 把 multi-XYZ 喂给 `ag topology` 做沿程比较。当前入口读单个 Attempt 的 manifest、facts、提交几何和一帧最终几何，比较“提交 → 最终”；没有轨迹参数或相邻扫描点迭代入口。

底层 `compare_minimum`、成键半径/不确定接触和片段工具可复用为诊断原语，但沿扫描几何常是受约束非驻点，不能直接套用“极小点身份已变”结论。当前 TS 模式只有在 route 与 `n_imag=1` 对应时报告人工指定原子对距离，不判连接；扫描点通常不具备这一频率条件。`scan-peak` 已有全程 RMSD/能差跳变，不能把它称作逐点拓扑审计，也不能认为拓扑未变就没有构象跳变。

**代码位置**

- `ag/src/ag/topology.py:compare_minimum`（168）、`analyze`（204–280）、`run`（317）、`register`（341）。
- `ag/src/ag/_scan.py:_result`、`_result_2d` 的 `geometry_frame`；`ag/src/ag/facts.py:parse_facts` 的逐点几何导出；`ag/src/ag/scan_peak.py:select_peak`（64–79）、`select_saddle`（108–133）。
- `ag/src/ag/irc_review.py:_continuity`（184）是 IRC 证据分析，不能直接把扫描点冒充 IRC 点。

**对后续工单的影响**

T-C 沿程诊断需要真实的本地代码衔接：按点号/几何帧映射和收敛状态处理缺点，比较相邻点与人工声明反应坐标，保留不确定连接、构象描述符及连续性警告。不为每点虚构 Attempt/facts，不改已保存证据，也不把扫描中预期的成断键一概当失败。

## 8. catalog 新事件的兼容性（A2）

**结论**

工单关于后端的判断成立，关于 T121 前端“同样回放未知 op”的前提需更正：

| 读取方 | 给它新日志时的真实行为 |
|---|---|
| 本基线 ag | `read_journal` 要求每行 `ag-catalog/1` 并调用 `replay`；未知 op 抛错后包装成 `Catalog journal damaged`。show、suggest、写操作均受影响；不会自动只读展示已知前缀。 |
| T121 的 Python 读取器 | 读取 state 和 journal 原始字节，校验 state schema、完整 journal SHA-256、对象及报告类别；不逐行解析/回放 journal 的 op。若仍给合法 state/1 且哈希正确，单纯新增未知 op 不触发其错误。 |
| T121 的页面 | `catalogObjects` 只消费 state/1 的已知对象字段。新候选/通道字段可能不显示；state schema 不支持、状态值/报告类别不支持或哈希不匹配时，警告并回退为未登记。它不是未知 op 的自动兼容读者。 |

因此不能声称“加两种事件后老前后端自然只读、明确提示”。旧前端可能继续显示旧字段而遗漏新语义；旧 ag 不能忽略未知事件继续写入派生状态。

建议优先遵守 A2，沿用 catalog/1 日志与现有事件含义，采用协调升级：先交付认识两种新事件的后端和前端读者、明确支持版本；升级所有实际读取入口后才在新版本写第一条扩展事件。新增字段读旧事件时缺失视为未知；旧 object 的完整元数据更新不能抹去新期望字段。旧工具回退的实际限制须写在升级说明中，不能靠未知字段让已发布旧代码产生它没有的提示。

若要求混用任意旧版时也能可靠拒绝误读，就需要另议版本边界：例如在同一 catalog 格式家族升版本，并使派生 state 也使用旧前端会拒绝的版本值；新读者支持原 /1 前缀和明确的升级边界，旧事件字节/序号/哈希不重写。此方案需监督方确认 A2 是否允许版本号升级，不能由本审计擅自决定。只升日志版本而保留兼容 state/1，仍挡不住上述旧前端。

已有日志在没有新写入时保持可读。协调升级方案只追加，不迁移旧行；一旦追加新 op，旧 ag 就不可再用于该日志。绝不能删除新行、重算旧链或改写已有事件含义来“恢复兼容”。

**代码位置**

- 后端 `ag/src/ag/catalog.py:read_journal`（77–98）、`replay`（101–151）、`change`（322）、`show`（370）、`suggest`（388）。
- T121 [autog_frontend/studies.py:catalog](https://github.com/anakine800-tech/Auto-Gaussian-Frontend/blob/63236192d25ddc46ca30b4d5e1716b21a76fce4a/autog_frontend/studies.py#L223)（223–264）。
- T121 [web/src/catalog-data.ts:catalogObjects](https://github.com/anakine800-tech/Auto-Gaussian-Frontend/blob/63236192d25ddc46ca30b4d5e1716b21a76fce4a/web/src/catalog-data.ts#L37)（37–47）；[PR #34](https://github.com/anakine800-tech/Auto-Gaussian-Frontend/pull/34) 已合并，审计按固定 head 读取。

**对后续工单的影响**

T-B 是跨后端事件、派生视图和前端消费的工作，须在写新事件前排定读取升级与旧日志回归。它不能只加两条 `elif`，也不能以静默跳过未知 op 处理兼容。

## 9. 对象级期望组成、电荷、多重度（A3）

**结论**

工单“目前没有多重度字段”不符合当前 main：`OBJECT_FIELDS` 已有 nullable 正整数 `multiplicity`，CLI 已有 `--multiplicity`，object 事件和 state 也保存它。目前缺的是期望元素组成和电荷；现有 multiplicity 是登记元数据，member/adopt 并未拿它与成员 manifest 核对。

`object --update` 是追加完整元数据事件；未指定的可选字段沿用旧值，不是删除或覆盖历史行。可以扩展同一对象的期望值并保留此语义，但需区分未提供、未知与有效值（电荷 0 必须是有效值），解释旧 multiplicity 何时成为已确认期望，不能把旧元数据自动升级为科学签字。旧更新事件回放时缺少新字段应保留既有值，禁止意外清空。修改期望后，已有成员须报告不一致/待核对，不回写它们的 manifest 或撤销既有历史事件。

可从现有 manifest 的 `science.n_atoms`、`science.charge`、`science.multiplicity` 和显式 `science.geometry` 取得核对值。普通单结构 manifest 通常没有独立元素计数字段，需解析几何再计数；QST 各组在 `science.structures[]`，含 elements/geometry；xTB/CREST 的 science 由输入 XYZ 和 chrg/uhf 参数生成。应按声明输入哈希核验来源并逐项比较，缺字段不能用默认 0/1 代替。单看元素组成仍无法确认同元素原子顺序，A3 也不能代替 T-D 的映射。

**代码位置**

- `ag/src/ag/catalog.py:OBJECT_FIELDS`（28）、`replay`（105–117）、`plan`（218–268）、`register`（479）；[ag-catalog/1 对象事件](../ag-catalog-1.md)。
- `ag/src/ag/attempt.py:prepare`（161–213、249–253）；`ag/src/ag/gaussian_input.py:_qst_structures`（70）、`validate`（197–222）；`ag/src/ag/coverage.py:input_geometry` 体现从输入取几何的现有做法。

**对后续工单的影响**

T-B 先完成对象期望字段与更新/回放兼容；T-E 读取该对象的已确认期望，按对象判输入完整性。不能按 study 统一组成，也不新增第二个相互矛盾的 multiplicity 字段。仅有组成、电荷、多重度仍不满足“原子顺序一致”的全部证据，候选还需映射来源。

## 10. T-X 第 1–3 条：哪些只改口径、哪些要代码

**结论**

| 条款 | 当前实际做法 | 所需工作 |
|---|---|---|
| 共同参考态 | 曲线与选择性已经使用共同数值口径；卡片要求公共零点、守恒、快交换及浓度审阅。局部垒另列。 | 明确跨前体比较与审阅条件主要是卡片/报告措辞。自动支持不同计量通道或显式前体动力学权重则需代码，现接口没有。 |
| 三数报告 | 主结果有系综 ΔΔG‡，还有 `lowest_conformer`，但后者对每个 TS species 各取最低构象后，仍按多个 channels 与 paths 求和；不一定是“每个产物只取一个最低 TS”。没有两者之差字段/三数并列。 | 先定义“最低 TS”是否保留路径简并；严格按每分支一个最低 TS 的要求输出并求差，需要修改 `selectivity_results`/Markdown 及回归。不能把已有 lowest_conformer 直接改标签冒充。若先人工报告，可从已有逐构象 G 重算，明确不是自动输出。 |
| 简并因子 | d、σ、paths 已分列；profile 卡明写“采样次数不是物理简并度”，kinetics 要先跨家族去重。 | 补真实对称简并依据、DFT 后再次去重及不得按重复次数计权，主要是卡片。自动查重/计数检查另属代码，见第 2 问。 |

即便一个产物只有一个 TS species，已有 `lowest_conformer` 仍保留 paths；多 species 时尤其不能当成单最低 TS 比较。本审计不改变已经存在的输出字段意义。

**代码位置**

- `ag/src/ag/profile.py:selectivity_results`（194–245；两个 evaluate 共用同一 products）、`markdown`（518 起）；`ag/tests/test_profile_decomposition.py:test_selectivity_sign_order_and_lowest_conformer`（180）、多通道/paths 用例（209 起）。
- `skills-next/auto-g16-recipes/cards/profile.md`（79–83、119–130、143–160、199–203、235–236）；`kinetics.md`（109–146、179–185、199–201）。

**对后续工单的影响**

T-X 的“纯文档”定位只能覆盖口径修订；自动三数输出必须交给另列的代码范围，建议独立小单，不在 T125 或纯卡片单顺手改。公共参考、去重与快速平衡是三个不同条件，不能用任一检查代替其余两项。

## 11. T-X 第 4–9 条与现有卡片逐项核对

**结论**

完整检查了 ts、irc、profile、kinetics 四张现行卡片，另核对 crest-screen 的约束/候选边界。以下区分直接表述冲突、未覆盖和已经一致；未找到的原方案句子不会凭空报告为现行卡片错误。

| 条款 | 核对位置与现状 | 冲突/缺口及后续处理 |
|---|---|---|
| 4 覆盖状态词表 | `ts.md:118–141` 要求有限覆盖与保留失败；`profile.md:12,168–173,212–220`、`kinetics.md:181–183` 保留覆盖限制。四卡未找到“系综已收敛”的完备性承诺。 | 未发现需要直接替换的该句；缺少“待确认通道”“低置信度排除”统一词表和预算内稳定表述。写入卡片并由 T-B 存通道状态；现 catalog candidate/adopted/retired 是对象采用状态，不能改义为通道覆盖。 |
| 5 IRC 政策 | `ts.md:246,274` 泛化要求双向 IRC；`profile.md:18,30`、`kinetics.md:22–25` 将其作为已验证路径条件；`irc.md:86,104–132` 已要求端点独立 Opt+Freq 和身份确认。未找到按“全局权重”筛 IRC 的条文。 | 选择哪些候选优先做 IRC 的分支内重要性/结构新颖性策略缺失，TS 卡的无条件后续措辞需细化。可调整排程，但被跳过的候选仍未验证；“已验证”仍须双向完成并识别极小点，不能削弱 AGENTS.md。端点要求已一致，应保留。 |
| 6 泄漏不证明快速互变 | 四卡没有“通道泄漏证明快速互变”句；`profile.md:131–134` 和 `kinetics.md:109–114` 已要求独立的快交换/动力学依据。 | 无直接反向表述；补约束、偏置低层采样不能证明 Curtin–Hammett 条件。原方案 L3 的措辞不在这四卡，不能假称已删。 |
| 7 刚性变换冲突 | 四卡没有“所有模板变换冲突即可排除通道”的规则；`ts.md:139–141` 明写失败搜索不等于机理不存在。 | 无直接冲突；补只说明该模板/变换失败，并在台账保存失败类型，不自动设通道排除。 |
| 8 低层端点塌缩 | `ts.md:74–87,131,139–141,257` 保留改用其他策略及失败记录；未写低层失败等于排除通道。 | 补“停止该条低层路线”的限定。DFT TS 验收仍需一个正确虚频；不得把对最终 TS 的判据错误套成 xTB 初猜准入门槛。 |
| 9 TS 后分岔 | `profile.md:175–176,218` 已说 IRC 不是真实动力学、不能凭单条 IRC 排除分支；`irc.md:132` 要端点识别后才赋化学标签；`ts.md:244–245` 仍要求身份/通道审阅。 | 卡片科学边界基本一致，但数据模型缺“产物分支未唯一确定/简单 TS 能垒比不适用”。profile 的 products 强制给 TS 归属且拒绝一 TS 重复跨产物；不应通过重复填同一 TS 来表达分岔。未定归属先留在 T-B 候选，不送简单选择性求和。 |

**代码位置**

上表的文件均位于 `skills-next/auto-g16-recipes/cards/`。对应机器边界：`ag/src/ag/catalog.py:replay`；`ag/src/ag/profile.py:selectivity_definitions`（130–164）；`ag/src/ag/irc_review.py:review`（284）按两个方向记录证据，缺项/工具通过不等于科学验收。

**对后续工单的影响**

T-X 可独立完成术语、排程和结论边界；T-B 承接覆盖与未定归属字段，T-E 保留软诊断失败。无需在本期引入轨迹计算。若监督方打算让“未做 IRC”也取得已验证标签，那将与现行规则冲突，须先裁定；本报告只建议排程变化，不建议这种放宽。

## 12. Laplaza 等文献核对（A5）

**结论**

已从 ACS 出版方页面核对，题名、作者、期刊卷页和 DOI 对应一致：

- 题名：*Overcoming the Pitfalls of Computing Reaction Selectivity from Ensembles of Transition States*。
- 作者：Ruben Laplaza；Matthew D. Wodrich；Clemence Corminboeuf（按出版方页面拼写）。
- *The Journal of Physical Chemistry Letters* **2024**, **15** (29), 7363–7370。
- DOI：**10.1021/acs.jpclett.4c01657**；线上发表日期 2024-07-11。

访问 doi.org 和 ACS DOI URL 的直接抓取返回 403；随后出版方域名检索返回了同一 ACS 条目的完整可读内容，含上述作者、题名、卷期页码和 DOI，故本次核对依据是出版方条目，并非从记忆或第三方聚合站补全。未核对论文计算结果的可复现性，也不把论文表现当作本项目验证。

**代码位置 / 一手来源**

本项无代码位置。来源为 [ACS 文章条目](https://pubs.acs.org/doi/10.1021/acs.jpclett.4c01657)，核对日期 2026-10-24；另可由 [ACS 15(29) 目录](https://pubs.acs.org/toc/jpclcd/15/29) 定位。该核对只解决规格第 6 节的书目信息。

**对后续工单的影响**

T-X 可引用这一已经核实的条目支持去重、分类和选择性处理的讨论；实际统计模型仍由本 study 的科学依据决定。本单未查询或写入被禁止的两项未核实外部工具信息。

## 拆单建议、顺序与交付边界

| 规格项 | 规模 | 建议范围/拆分 | 主要相交文件或接口 |
|---|---|---|---|
| T-B | 大 | 先完成 catalog 读者兼容、对象期望值、通道/候选事件；再接 T121 计算链展示。后端与前端分 PR，先读后写，仍沿用 catalog。 | `catalog.py`、`docs/ag-catalog-1.md`；前端 `studies.py`、`catalog-data.ts`、`chains-view.tsx`。 |
| T-C | 中 | 输入/来源衔接为小块；沿程拓扑与构象连续性另为中块。已有 scan/facts/峰选择不重写。 | `scan_peak.py`、`topology.py`、`_scan.py`；候选写入调用 T-B，TS 卡与 T-X 相交。 |
| T-D | 中 | 单独的本地端点映射/正规对齐及 QST2 输入导出；先做好歧义与相同元素交换夹具。 | `gaussian_input.py`、几何工具、新本地入口；T-B 来源；与 T-C 共用输入输出边界但不预建通用框架。 |
| T-E | 大 | 建议拆本地对象完整性/几何/通道诊断与模式诊断。已有 Gaussian `mode-review` 可复用距离导数；没有完整 G0 排序，也没有 xTB Hessian 模板白名单。需要 xTB Hessian 时另列程序/解析/真实验证范围，默认不算。 | `catalog.py` 期望值、`topology.py`、`mode_review.py`/`_parse_outputs.py`；若扩程序才涉及模板/prepare，不在纯诊断单夹带。 |
| T-X | 小（纯文档）；另加小型代码项 | 四卡与报告措辞单独修订；严格“最低 TS/系综/差值”的自动三数报告另拆代码工作。两者同批审阅，不能假定当前 lowest_conformer 已满足。 | TS/IRC/profile/kinetics 卡片；代码项涉及 `profile.py` 与对应测试，自动驻点去重另定范围。 |

建议次序：先由监督方确认本审计与版本策略；按 A1 等 v4.5.0 发布后启动其余 P0。T-B 的字段/读取边界先定并完成读者支持，T-C/T-D/T-E 再写候选来源；T-C 沿程诊断与 T-E 共用 topology 的修改应先后合入，避免两套判据。T-C/T-D 的 Gaussian 输入导出若都需调整 `gaussian_input.py`，先落最小公共接口再接第二种来源；不为了并行提前引入抽象。T-X 对 TS 卡的编辑排在 C/D/E 功能边界确定后；profile 三数代码项可与几何工作独立推进，但其输出措辞最后与 T-X 一起审阅。

T-E 可借用 `mode_review.displace` 已有的逐距离有符号导数（相当于距离内坐标的 Bq），但现在只选一个显式模式，没有目标成断键符号集合、所有相关负模式汇总、角度投影或 G0 优先级。不能因已有位移图就把完整 T-E 判为小单。刚体对齐、镜像去重与 Hessian 框架核对也应各保留自己的语义。

**当前阻塞**：科学审阅——待监督方确认 12 项结论、兼容性方案和 C 批粒度；不是计算、SSH 或数据解析故障。此处仅建议，不分配新编号、不创建后续工单、不变更任何计算/提交策略。源码审计不替代后续工单各自要求的非研究 study 验证。

验证记录见 [T125 工单](../redesign-tasks/T125-ts-guess-audit.md) 的实施记录；本报告和规格不包含私有研究对象或环境标识。
