# T164：父 checkpoint 的频率来源与力常数证据报告

版本：v1，2026-10-28。目标仓库：Auto-Gaussian。类型：纯本地实现单。覆盖 H5。

## 分支与目标

- 分支：codex/t164-parent-chk-evidence-report；一个任务单、一个分支、一个 PR；PR 第一行：Task: T164。
- 基于开工时最新 main；已核查基线 e24a5bd1d9045e3b783d8ef25f02e430ad4dc3c5。先读 AGENTS.md → 本单，再读 docs/DEVELOPING.md、docs/LESSONS.md 的 RCFC 事故、parent_chk.py 和历史依据 T46。
- 目标：将当前分散的父作业频率证据、坐标取向检查依据和 checkpoint 关联记录汇总为可审阅的本地报告，明确缺口，减少仅凭已有坐标便假定 RCFC 可用的误用。
- 事故依据：既有记录曾把中断优化的 chk 用于 RCFC，但缺少可用 Freq Cartesian 力常数；当前 validate_force_constant_frame 只检查坐标框架，不能证明 chk 内部记录可用。
- 三件事分别报告：日志中的频率执行事实、checkpoint 身份/字节关联证据、科学适用性。前两项即使齐全，也不能自动得出第三项通过。
- 并行：可与资源、CREST、G0、CP 开发并行。本单新建独立报告模块；cli.py 只加一项注册，整合时按块保留其它任务注册。不依赖 T162 的新映射格式。

## 允许改动的路径

- ag/src/ag/parent_chk_report.py（新建）：本地报告、局部来源读取和确定性检查。
- ag/src/ag/cli.py：只注册新增命令，不改 prepare/submit 参数和行为。
- ag/tests/test_parent_chk_report.py（新建）：本单合成测试。
- docs/parent-chk-report.md（新建）：使用说明、字段含义和证明边界，不建立“schema 合同”。
- README.md：只加命令入口；docs/redesign-tasks/T164-parent-chk-evidence-report.md、docs/redesign-tasks/open-tasks.txt。
- docs/LESSONS.md：仅追加本单可证实经验。
- 现有 parent_chk.py、mode_review.py、catalog.py、_parse_outputs.py 等只复用公开函数或只读查阅，不修改；如果局部复用必须调整其行为，停下列出最小范围变化。T166 负责 TS 卡最终链接与措辞整合。

## 要做的

1. 新增纯本地命令，建议形式如下（本单定义的新入口，实施后核对实际 help）：
       ag parent-chk-report <parent_attempt> --study <study> [--child <child_attempt>] --out analyses/<new-report>.json
   同时独占输出同名 Markdown；解析和显示不加载远端凭据，不创建 Transport，不调用 Gaussian/formchk 或其他子进程。
2. 父对象只接受精确的本 study Gaussian Attempt。可选子对象只用于核对已有 parent_chk 绑定和显式坐标，不改变子对象状态；明确显示其引用是否确实指向该父 Attempt。
3. 报告本地存在的输入、manifest、日志、facts、最终输入取向几何等来源，逐项给文件哈希、段/行或 JSON Pointer。复用已有来源核验习惯；不调用 ag facts --refresh，不修改任何原文件。
4. 频率事实分为：找到正常结束的适用频率段、未找到、段歧义/不完整、源不可核验。只从已经核验的实际日志段陈述执行事实，不能从 route 含 Freq 或顶层 termination=normal 推断。列明所用段与原始字节哈希；多段无法唯一归属时保留歧义，不猜。
5. 子输入声明 RCFC/ReadFC 时，报告父频率几何、父保存的 input orientation、子显式坐标之间能核对的关系；沿用现有固定原子序和坐标框架的含义，不引入新的自动旋转或同元素重排。不能承诺固定行比较能检出所有同元素交换；几何对称、相同位置或缺少身份来源而无法判定时，明确身份未知。坐标相同不等于原子化学身份已证明。不调用提交准入函数以免附带远端操作。
6. checkpoint 身份单独列出：
   - 父输入绑定的 %chk 文件名及其已核验输入来源；
   - 子 manifest 中的 parent_chk 关系；
   - 本地已有复制日志/记录中能确认的源/目标大小及哈希（如果存在），并保留该记录自己的来源。先核对真实记录字段再实现，不猜记录文件名。
   - 没有 checkpoint 字节检查证据时写“内部力常数未核验”。存在正常 Freq、坐标吻合、输入哈希吻合或历史复制记录，均不能改写成“当前 chk 内肯定有可用力常数”。
7. 本单不解析 chk 二进制、不新增 fchk 导入、不执行 formchk；不能从未读取的二进制内容给出数值结论。即使未来有此类来源，也不在本单自动支持。
8. 输出实际方法/基组、电荷、多重度和几何来源差异作为审阅事实；是否选择 RCFC、ReadFC、CalcFC 或另算 Freq 留给现行卡片与人。不得生成替代 route、改输入或授权提交。
9. 报告完成与科学可用性分开：来源完整读取并生成报告时命令成功，即使其中有“未知/未找到”；损坏哈希、越界、符号链接、结构无效等完整性错误返回非零且不发布半份报告。明确 CLI 退出码，不把 unknown silently 改成通过。
10. 旧记录按可取得证据列示缺项；不补写历史 manifest/journal，不回填哈希，不重新签字。

## 不允许

- 不修改 prepare、submit、父 chk 复制操作、确认、状态机、旧 Attempt 或 evidence。
- 不增加全局提交禁止条件，不把本报告变成新的必签层级。
- 不连接服务器，不下载 chk，不尝试真实计算或试运行 RCFC。
- 不改变频率解析和科学方法表，不做前端页面或发布工作。

## 测试

| 场景 | 预期 |
| --- | --- |
| 合成父作业正常 Freq，输入与子坐标吻合 | 频率事实和框架检查可核验；chk 内部可用性仍未核验 |
| 仅优化、中断优化、route 含 Freq 但尚未执行 | 不声称存在已完成 Freq 力常数 |
| Opt 正常而后续 Freq 失败/段歧义 | 精确记录频率事实；不沿用整体正常结论 |
| 正常 Freq 但子输入旋转、可判定的同元素换序或改变坐标 | 明确可判定的框架/序号差异；不自动修正；几何无法区分的身份关系保持未知 |
| 历史记录无复制哈希，或本地只有文件名关联 | 报缺口，不补造字节证据 |
| 有复制日志但父/子绑定不一致 | 明确关联错误，不能记为来源通过 |
| 输入/日志哈希损坏、链接、越界、输出已存在 | 非零，不覆盖，不发布部分报告 |
| 构造 Transport/子进程被测试替身禁止 | 报告仍可工作，调用次数为零 |

开发阶段运行本单测试；推送前一次：
    PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs

记录跳过原因；随后以 CI 为准。按开发手册扫描精确暂存文件和有效私有词表，运行 git diff --cached --check，人工检查 PR/提交身份。未做的检查如实列出。

## 真实环境验证

不需要新增远程验证或计算，本单只读本地证据。使用合成非研究目录覆盖成功、缺失和矛盾；可只读核对已有脱敏验证材料，禁止把本地报告当作二进制 checkpoint 验证或科学签字。如果实现必须触及远程/复制/提交，本单停止，不能将验证挪到合并后。

## 停止条件

必须读取或转换二进制 chk 才能达成当前目标；必须修改共享解析器或提交行为；无法区分频率事实与 chk 内容证明；范围越界；同一问题修两次未解决。真实环境意外按 AGENTS.md 停止报告。

## 合并前审阅与交付

- 必须监督方审阅，重点检查“正常 Freq 不等于当前 chk 可用”的反例及零副作用。
- PR 第一行 Task: T164，提供报告示例、来源分类、退出码、测试和明确限制。
- 不修改 AGENTS.md；处理绑定实际 head 的 ag-review 评论。T166 在本单完成后更新 TS 卡入口，避免同时改 TS 卡。
- 人工合并，不发版、不部署、不执行计算。

## 实施记录（2026-10-28）

- 新增 `ag parent-chk-report`，父/子使用精确 Gaussian Attempt ID，`--study` 使用本地目录；
  `--child` 可选，`--out` 成对独占输出 JSON/Markdown。CLI 仅增加独立注册块。
- 输入按 manifest/bundle 哈希核对；实际日志按已有分段器和模式读取函数处理，
  保留原始字节段哈希。已存 facts 是待核对声明，不借整体 normal 推断 Freq。
- 父频率取向、已存 Input/最终几何和每组子坐标按固定行逐原子距离比较；
  所有数值匹配均保留化学身份未知，不依赖新映射格式。
- 复制来源已对照 `submit.py` / `journal.py`：仅使用 `journal.jsonl` 中
  `copy_parent_chk` 的真实字段；历史 verified 不升级为当前二进制力常数证明。
- 没有调用父 chk 提交准入、Transport、配置加载、formchk 或子进程；
  不修改既有 Attempt、研究或证据，不新增提交门槛。
- 使用说明、字段与退出码见 `docs/parent-chk-report.md`；包含合成水分子简化示例。
- 真实环境验证：本单按工单无需新增现场验证，未连接服务器、未提交/取消作业。
  本地合成报告的正常 Freq、吻合坐标与历史复制记录并存时，内部力常数仍为未核验。
- 剩余依赖：独立监督审阅与 CI；T166 后续整合 TS 卡入口，本单不修改卡片。
- 最终验证：专项 59 项通过；专项加 smoke 合计 85 项通过。
  `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`：
  6033 通过、19 跳过（18 项 Linux GNU stat/procfs 方言，1 项私有日志未启用）。
- 暂存 6 个任务文件；通用扫描及有效私有词表扫描零命中，`git diff --cached --check`
  通过，author/committer 均核对为 GitHub noreply。未把开发者自查记作独立审阅。
