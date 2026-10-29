# Counterpoise（BSSE）相互作用能诊断

## 1. 适用范围

仅主族闭壳层 RC、离子对及 TS 的双片段相互作用能诊断，按 [complex](complex.md) 的体系与参考态约定。
只做单点；不以 CP 单点验证驻点、虚频或 IRC，不修正主线 ΔG‡、ΔΔG‡。

诊断量；未进入 thermo/profile；不构成已校正剖面。

## 2. 前置条件

- 结构、原子映射、总电荷及两个片段的电荷/多重度经负责人审阅，整体与各片段均为单重态。
- 每个原子恰属一个片段；片段电荷相加等于总电荷。跨片段共价键及 topology 的 uncertain 接触均拒绝。
- 成键后的物种不做 CP（例如某研究课题的成键后物种）；TS 若发生跨片段成键或不确定接触也不绕过校验。
- 方法/基组见 [acceptance-methods.md](../../auto-g16-study/references/acceptance-methods.md)。以几何层级为主；BSSE >1 kcal/mol 时，在最终 SP 层级补算检查收敛。这是使用规则，不是自动重提触发条件。
- 溶剂限制：**G16 A.03 实测拒绝，T105 第 0 节**。原文 `No SCRF with counterpoise/fragments.`；prepare 拒绝任何含 SCRF 的 CP route。

## 3. 输入模板

下列 Link0 数值、档位和 walltime 仅为示例，须按所选入口与已审阅资源替换。`%nprocshared`、`%mem` 可省略，由新 prepare 按实际档位补齐；显式核数须匹配档位，内存仍检查不超过调度内存的 85%。

输入为普通、未加片段标签的 Cartesian GJF 和四列 CSV；prepare 根据 CSV 生成片段标签和三组电荷/多重度。
手动加标签或把完整片段电荷行直接放入源 GJF 会被拒绝，避免 CSV 与手写标签不一致。

```text
%nprocshared=4
%mem=8GB
#p <方法/基组> SP Counterpoise=2

<诊断对象与几何来源>

<overall_charge> 1
<按 study 映射排列的坐标>

```

水二聚体的片段文件示意（只演示映射，几何须另行审阅）：

```csv
fragment,atoms,charge,multiplicity
water-a,1-3,0,1
water-b,4-6,0,1
```

逗号分隔的非连续编号需用 CSV 引号，如 `"1-3,7"`。NH₄⁺···H₂O 应分别指定 +1/1 与 0/1，整体 +1/1。
提交输入将生成 `元素(Fragment=1)` / `元素(Fragment=2)`，CSV 与 GJF 都计入 bundle 哈希。

```text
ag prepare --study <study_id> --cluster default --template gaussian-cp --input <cp.gjf> --fragments <fragments.csv> --tier mini --walltime 00:30:00 --label cp --card counterpoise --method-basis <已审阅方法依据或兜底声明>
ag status <cp_attempt>
ag fetch <cp_attempt>
ag facts <cp_attempt> --study <study_dir>
ag cp-report <cp_attempt> --study <study_dir> --out analyses/cp.json
ag cp-report <cp_attempt> --study <study_dir> --solvent-sp <ordinary_solvent_sp_attempt> --out analyses/cp-solvent.json
ag cp-report <cp_attempt> --study <study_dir> --solvent-sp <complex_smd_attempt> --solvent-fragment-sp 1:<fragment_1_smd_attempt> --solvent-fragment-sp 2:<fragment_2_smd_attempt> --out analyses/cp-smd.json
ag cp-report <cp_attempt> --study <study_dir> --asm analyses/asm.json --out analyses/cp-asm.json
```

prepare 不等于授权提交。保存完整摘要，手动模式提交前由负责人核对；按 [Study 流程](../../auto-g16-study/SKILL.md)取得对应模式的提交授权。
`--solvent-sp` 使用普通 gaussian 模板、同原子序/几何、同方法/基组（含色散及基函数类型）；固定映射刚性对齐 RMSD ≤0.001 Å。
可用重复的 `--solvent-fragment-sp <index>:<attempt_id>` 接入本 study 已有的片段 1、2 单点；不按片段名称猜配。
新片段模式只接受正常结束的 SMD ordinary SP：片段只含 CP CSV 指定的真实原子，在复合物几何下使用自身基组，电子态取对应片段声明。
按全体系号升序抽取并保留到片段局部号的映射；输入/输出都需固定行序 proper Kabsch 匹配，不反射、不交换原子、不用优化后的孤立片段。
复合物、片段与气相 CP 的方法/基组/基函数类型/色散须一致；三个 SMD 的溶剂及实际打印参数须一致。报告纯本地，不补建/提交计算。

## 4. 资源建议

水二聚体和 NH₄⁺···H₂O 流程验证的资源示例为 mini：4 核、10 GB、30 分钟，Gaussian `%mem=8GB`；该示例每作业最多申请 2 核时，不是所有入口的通用默认或上限。实际档位、核数及调度内存取所选入口配置，保存值以 manifest 为准，核时按实际核数与 walltime 重算；详见[资源表达](../../auto-g16-study/references/acceptance-methods.md#资源表达)。
CP 包含复合物及两片段在两套基组下的多个单点，较普通 SP 更贵；研究体系据已观察耗时另估，不照搬小分子上限。
default 与 scnet 沿用普通 Gaussian 的资源和入口规则；scnet-test 的 allowed_templates 不允许 Gaussian 类任务时即拒绝，不切换入口绕过。

## 5. 提交前检查清单

- 整体及两个片段身份、原子数、分子式、电荷/多重度与摘要一致，原子无漏标/重复，跨片段无 bonded/uncertain 接触。
- route 只有 Counterpoise=2 单点，不含 SCRF、Opt/Freq/IRC/Scan、Guess=Read 或自定义 Gen/ECP/IOp。
- 结构与立体化学警告、方法依据、完整 route、入口、资源、walltime、远程目录、CSV/GJF/bundle 哈希均已保存，手动模式提交前展示。
- 同一 Attempt 仅提交一次；手动提交沿用 [Study 流程](../../auto-g16-study/SKILL.md)，自主模式仅按 [AGENTS 自主运行规则](../../../AGENTS.md#自主运行)启用及核验。未合并代码的真实验证仍须单独获批。

## 6. 结果判据清单

- 正常终止，复合物及两个片段的 DCBS/MCBS 能量、汇总与行号可唯一对应；格式未知、缺项或加和不符即停止。
- 对照未校正/校正复合物能量、BSSE（Hartree/kcal/mol）、未校正/校正相互作用能及各片段能量，核对每项来源文件/哈希/行号。
- 溶剂相结果 = 溶剂相相互作用能 + 气相 BSSE；假设 BSSE 基本不受溶剂影响。
- 两个有效片段齐全时，核对 E_AB(SMD) − E_A(SMD) − E_B(SMD) 及再加 BSSE(gas) 的近似值、全部操作数来源和原子映射。SMD 的 SCF Done 已含非静电项，不重复加 CDS。
- 零个/一个片段时显示已知能量，逐一列出缺失项，相互作用能仍未知。不用气相片段替代；“复合物能量 + 气相 BSSE”始终不是相互作用能，也不是计算出的结合自由能。
- ASM 形变能仅并列查看，不拼成新的结合能结论；所有数据均不进入 thermo/profile，不能声称得到已校正的自由能剖面。
- BSSE >1 kcal/mol 的对象按最终 SP 层级补算后比较；在 study 保留诊断量、层级敏感性及剩余误差，不把量级检查称为文献对标。

## 7. 常见失败与处理

SCRF 在 prepare 被拒绝：改为气相 CP，并把普通溶剂 SP 留给报告叠加；不修改校验、不绕过模板。
片段/电荷/拓扑被拒绝：先人工审阅映射或体系是否适合拆分，不靠移动原子躲过阈值。
真实环境异常按 [失败诊断](failure-diagnosis.md)及上述 AGENTS 模式规则处理；输出格式不能唯一识别或能量加和异常时停止并交人核对，保留日志，不用新 Attempt 绕过证据问题。
输出报告已存在时使用新的文件名；已有 facts 变化须先审阅差异，再按 facts 的显式刷新流程处理。

## 8. 常见坑

知识衔接：[GKB-0521：超分子相互作用能和 BSSE](../../auto-g16-gaussian-learning-library/references/advanced-properties.md)。

- 气相 BSSE 不是溶剂化自由能，也不是零点能或热校正。
- 校正后的复合物电子能不等于相互作用能；缺溶剂片段能量时不能用气相值补齐。
- 不同几何或不同方法/基组的 BSSE 不混用；同元素原子交换也不能靠重排对齐。
- 对称/近对称原子的换序可能无法由几何阈值区分；配对通过不证明全部同元素原子的化学身份，仍须审阅原始映射。
- 半径规则只用于拒绝有疑义的拆分，不替代成键化学判断。
- 真实验证日志齐全前，离线合成夹具通过不表示已完成现场验收。
