# T176：本地 xTB Hessian 导入及 G0 分析来源

## 分支与目标

- 分支 `codex/t176-xtb-hessian-import`；基于最新 main（规划基线 c1a0d084fd5f53d1fb4ab15dd3c57c12ad447a8f），一个任务一个 PR，首行 `Task: T176`。
- 先读 AGENTS.md、本单、docs/DEVELOPING.md、docs/LESSONS.md，再读 T163、docs/research/xtb-hessian-import.md、T162 和现行 G0 实现。
- T163 仅完成规格。本单实现只消费本地文件的有限适配器，使完整且可核验的 xTB v6.7.1 普通非线性分子 Hessian 能成为 G0 诊断来源。它不构成 DFT 提交前置条件或科学结论。
- 防止的具体事故：把未加权 Hessian 当成位移、把 g98.out 质量加权向量按 Gaussian 位移使用、跨几何框架或错误质量转换、盲删负曲率、通过声明文件替换真实来源。

## 允许改动的路径

- `ag/src/ag/xtb_hessian.py`（新建）：有限格式解析、数学转换、来源读取与独占 analyses 写入、CLI 注册；不建通用来源框架。
- `ag/src/ag/cli.py`：仅注册本地导入入口。
- `ag/src/ag/g0.py`、`ag/src/ag/g0_modes.py`、`ag/src/ag/g0_mapping.py`：显式 analyses 来源及 T162 映射适配。
- `ag/tests/test_xtb_hessian.py`（新建）、`ag/tests/test_g0.py`、`ag/tests/test_g0_modes.py`、`ag/tests/test_g0_mapping.py`：上述行为与兼容回归。
- `ag/tests/fixtures/xtb_hessian_v671_water/`：仅经来源核对、脱敏审阅的非研究水分子格式样例；真实样例尚待协调方交付，不能用合成文件冒充。
- `docs/g0.md`、`docs/research/xtb-hessian-import.md`：实际接口、支持限制和示例。
- `docs/redesign-tasks/T176-xtb-hessian-import.md`、`docs/redesign-tasks/open-tasks.txt`：仅自己的任务条目。

## 要做的

1. 增加 `ag import-xtb-hessian --study <study> --source <local-source.json> --out analyses/<new-directory>`。复用现有安全本地读取/路径与独占创建做法。来源 JSON 仅描述文件，不执行其中的命令、联网或调用计算程序。保留输入原始字节及哈希绑定，原文件和原 Attempt 不变。
2. 输入绑定程序版本/构建、原始 hessian、同次频率框架几何及其原文件/定位、原子序、有效质量、Hessian 缩放、生成路径和正常结束/驻点证据。区分请求质量、打印回显与最终有效质量。未知信息明确保留；缺少数值转换必需项时不能生成可用模式。构建声明与记录一致性不等于独立证明化学正确性。
3. 第一版只支持经过 T163 源码核对的 v6.7.1 普通非周期、非线性无约束 Hessian。明确拒绝 hessian.out、冻结/SPH/偏置/未知版本、格式歧义、缺配套文件、维数/单位/哈希不符、非有限值。不要通过文件名或手填版本绕过格式/来源校验。实际可支持构建范围须与取得样例一致。
4. 按固定源码常数处理 H、质量加权、符号频率、缩放及去质量权重后 Cartesian 归一。保留完整有符号谱；用真实几何刚体子空间和有依据的精度边界判断外部模式，不能直接删除最小六个本征值，也不能抹掉微小负内部模式。刚体空间不能可靠分离时返回 `external_modes_unresolved`，不得伪装成功。
5. 新增显式 `ag g0 ... --candidate <id> --modes-analysis analyses/<new-directory>/analysis.json`，与 `--modes-attempt` 互斥，仅单候选；批量自动来源保持当前 Gaussian 行为。用明确的 analysis 目标描述符，不伪造 `target.attempt`。完整保留候选→来源 1-based 双射、候选/声明/分析原始字节绑定、重复元素警告和 invalid/binding mismatch/unverified 语义。声明不能选择实际来源或执行文件。
6. 在来源几何框架计算 Bq；只重映射原子索引，不旋转或重排来源向量来迎合候选几何。没有映射只给未核实状态；驻点不足不能显示已确认驻点。
7. 新目录独占发布；失败不留下可被 G0 读为成功的半成品。读取时核对记录及原始源绑定，拒绝被改写的模式或来源。复用现有机制，不增加注册台账、全局准入或依赖。

## 不允许

- 不改模板、remote、submit、fetch、status、事实/台账、研究数据、生产配置、版本号或 CHANGELOG；不增加依赖，不修改 AGENTS.md 或冻结目录。
- 不运行 xTB/Gaussian，不连接集群，不生成真实样例。本单可并行完成实现及合成回归，真实水样例由单独获准的私有验证流程提供。
- 不把一次水样例推广为全部版本/同位素/约束模式均已支持；不把数值/格式验收称科学验收。

## 测试

- 合成矩阵验证布局、维数、对称性、单位、质量/缩放、带符号谱、去质量权重、刚体秩、软内部负模式与简并子空间；用打印精度及边界扰动验证容差，不能单凭一次水数据调参。
- 完整真实非研究水包到位后，核对重建谱与同次 xTB 输出精度、几何/质量来源、六个刚体方向及三条内部振动。没有完整包时 PR 保持 draft 并说明解析验收阻塞。
- 数值转换必需信息未知、已知异常结束、来源矛盾或损坏时，不发布可用模式。方法、溶剂或正常结束证据未核实但数学来源完整且不矛盾时，保留明确警示的数值诊断；驻点未知或非驻点沿用现有诊断提示，不冒充科学验收。第 3 项的配套文件要求指必需的数学/格式/来源绑定输入，不将未核实的科学信息一概升级为拒绝条件。
- 拒绝路径越界、符号链接、覆盖；非自反映射 [2,3,1]、重复元素、候选/来源变更、Bq 旋转不变性及 Gaussian/批量零记录回归。
- 开发中跑针对性测试，推送前用已具备依赖的 Python 且确认 ag.__file__ 属于本工作树，本地一次 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`；其后以最终 head CI 为准。记录完整 head、命令、环境和实际统计。
- 精确暂存，敏感信息扫描、diff --check、有效私有词表与 noreply 身份检查；实际原始运行路径等只留私有目录。

## 真实环境验证

纯本地分析工具，无远程/提交/状态/取回变动，不需要新增集群操作。真实格式包只读导入验收；生成样例不属于本单授权。本单不部署。

## 停止条件与交付

- 遵守 AGENTS.md；范围外改动、同一问题两次修复未解决、来源证据不足/不一致及时报告协调方。不要自行扩展支持范围来绕过缺样例。
- 交付代码、有限接口文档、真实格式与合成验收分别记述、来源限制。PR 绑定实际 head 接受独立审阅并处理评论，CI 通过后交协调方合并。本批用户已允许协调方在审阅与验证通过后合并；执行会话不自行合并或发版。

## 执行记录（2026-10-29）

- 基线与只读 GitHub main 核对为 `c1a0d084fd5f53d1fb4ab15dd3c57c12ad447a8f`；独立分支 `codex/t176-xtb-hessian-import`，审阅版任务原文先复制入库。
- 实现本地来源读取、固定 writer 解析、默认有效质量/缩放来源核对、完整带符号谱、按几何和打印精度辨识刚体子空间；不可靠时保留 unresolved 数学诊断。G0 使用 analysis 描述符、单候选显式选择和独立映射，批量来源仍为原 Gaussian 行为。
- 构建范围限定为已有配套样例的 conda-forge osx-64 `6.7.1 gfortran_h7141999_5` 普通 GFN2 CLI 路径；保留五个实际补丁。仅默认有效质量和 Hessian scale=1 的来源已纳入；数值内核另以合成质量/缩放检验通式。未把打印质量覆盖回显当作最终有效质量。
- 仅只读消费协调方另获授权生成的非研究水包；本会话未运行 xTB/Gaussian、未连接计算平台。私有本地导入得到三条内部波数约 1538.898353、3642.665507、3651.164333 cm⁻¹，与同次 g98 的四位输出匹配；原始样例未改，原路径和运行身份不入库。
- 已完成的相关回归：358 passed（16.81 s）；随后补充未知结束语义、声明字节绑定、拒绝 shell 文本和异常执行回执的回归，新模块 77 passed（1.05 s）。合成 writer 文本明确不是真实样例。
- 真实包独立格式/数值审阅已通过；随后协调方对 13 个脱敏 fixture 文件独立敏感/数据审阅通过，确认六份数值文件逐字保留、stdout 仅两处身份/执行路径修改，允许暂存推送。原始→脱敏字节关系见 fixture provenance。真实 fixture 已实际导入并核对三条内部频率和六维外部子空间。
- 全量本地一次：HEAD 基线 `c1a0d084fd5f53d1fb4ab15dd3c57c12ad447a8f` 加当时未提交 T176 工作树；`PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，6848 passed、26 skipped、13 failed（405.96 s）。Python 3.11.15 / NumPy 2.4.6 / pytest 9.1.1，已核对 ag.__file__ 为本工作树。25 个 Linux 方言/进程检查由 Linux CI 覆盖，1 项私有日志未启用。
- 上述 13 个失败均为 test_smoke 的动态扩展列表精确断言；CLI 改用既有 route/capacity 相同的独立本地注册方式，未改范围外测试。修复后 smoke + xTB + G0/模式/映射定向回归 391 passed（40.36 s），包含真实 fixture 导入、原字节不变、双射、共同旋转 Bq 和批量兼容。全量不重复，最终 head 由 CI 验证。
- 暂存前 12 文件的通用/有效私有词表扫描、独立未暂存 fixture 13 文件扫描及 noreply author/committer 核查均通过；最终暂存集合另作统一扫描。
- 当前阻塞（审阅）：最终 head 的独立代码审阅与 CI。PR 保持 draft，不自行合并、部署或发版；没有新增现场执行。

- 最后补充输入/频率原子顺序矛盾和严格布尔字段回归；新 xTB 模块 80 passed（3.29 s）。26 文件统一暂存通用/私有词表扫描为 0 errors。真实 Fortran 文件保留原始行尾填充，fixture 内局部 `.gitattributes` 只关闭四份原始 writer 文件的对应空白检查；不改写已审数值字节。
