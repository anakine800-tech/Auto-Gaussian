# T224 严格 Gaussian 力常数读取的来源核验

## 分支与目标

从最新 `origin/main` 建独立工作树与 `codex/t224-strict-force-constant-source` 分支。先读 AGENTS.md、本任务单、docs/DEVELOPING.md 和 docs/LESSONS.md。

普通严格 Gaussian 请求 Opt=ReadFC 或 RCFC，使用全新的输出 chk 且没有父 chk 时仍可通过校验。放宽路径已有来源检查。

## 允许改动的路径

- ag/src/ag/gaussian_input.py、ag/src/ag/attempt.py、ag/src/ag/parent_chk.py：严格输入关键词识别、来源绑定和已有取向检查。
- ag/src/ag/autonomy_policy.py、ag/src/ag/parent_chk_report.py：只处理冻结重验和历史复核必要的兼容。
- ag/tests/test_gaussian_input.py、ag/tests/test_gaussian_sections.py、ag/tests/test_parent_chk.py、ag/tests/test_rcfc_frame.py、ag/tests/test_relaxed_attempt.py、ag/tests/test_autonomy_policy.py、ag/tests/test_core.py：针对来源路径的回归。
- ag/README.md：严格力常数读取用法。
- `docs/redesign-tasks/T224-strict-force-constant-source.md`：本单及实施、验证摘要。

## 验收标准

1. 通过严格 prepare 验证缺父 chk、只写全新 %chk、仅文字声明但无有效来源均拒绝；提示指向已有父 chk 声明机制。
2. 现行严格范围内识别 ReadFC、RCFC 和已识别的 ReadCartesianFC 写法，覆盖已有相应 Opt/IRC 路径和大小写，避免把 CalcFC、RecalcFC 或标题文本误拦。
3. 合法父来源仍核验归属、绑定和取向，错误父来源/坐标取向应拒绝；不凭文件存在证明 Hessian 科学适用。已有放宽 Link1 来源检查及别名边界保持。
4. 针对既有 Attempt 分别核对历史阅读与发起新提交时的资格；不改父子文件或已绑定字节。

## 验证与交付

- 先用合成数据重现问题、运行定向回归，再于首次推送前执行 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`。使用本工作树源码与现行隔离机制。
- 精确暂存本单文件，运行仓库的暂存敏感扫描和 `git diff --cached --check`，核对提交身份。PR 第一行 `Task: T224`，列出测试结果、跳过原因、现场证据覆盖范围及真实阻塞。监督按实际 head 复审。

## 真实环境验证

首选在本地 prepare 阶段封住缺来源输入，使用隔离父子样例验证。本单如触及实际跨 Attempt 读取或提交路径，在受审 head 上按开发手册做合并前非研究父子验证；列父子来源、资源、哈希、一次性命令与停止条件，提交由负责人亲手确认。

## 协作顺序与停止条件

与 T222、T223 分支独立；在前两项后核对共同严格入口及兼容性。 越界、同一问题两次修复仍失败、真实环境异常时依 AGENTS.md 停止并报告。研究数据、真实连接和原始输出仅留私有位置。

## 实施与离线验证（2026-11-25）

修改前在临时水分子 study 运行四例严格 prepare。无 chk 的 Opt=ReadFC、仅有输出 chk 的混合大小写 Opt=(TS,RCFC)、跨行 IRC=(ReadCartesianFC,Forward) 都错误地创建了 Attempt，即使只有普通父子关系。仅写 %oldchk=parent.chk 的第四例被拒绝，报错缺少 --parent-chk 的用法提示。

严格 prepare 在分配编号前把已解析的 route 和已绑定的附件交给原取向检查。TS 草稿和取向检查共用原有三个完整关键词；标题和 RecalcFC 不参与匹配。新提交在 verified_files 中从冻结输入重新核对，先解析真实父声明，再核验取向。人工确认后的字节复查同样走此入口。历史报告继续按原字节读取，可报告绑定缺失。已有永久提交声明的 Attempt 仍可为 status/回执核对读取冻结字节，原一次性声明禁止再次提交。改动未扩展放宽路径的别名。

## 合并前非研究父子验证方案（待负责人另行批准）

对象为受审 head 上的新非研究 study，用同一已核准入口，父、子各一个严格 Gaussian Attempt。建议两份均用 mini 档，每份 4 核、输入内存 1 GB、walltime 00:10:00；执行前核实该入口实际档位的核数、总内存和账号合并余量，写入私有验证记录。首次点击前固定实际 head、入口、目录、父 Attempt ID、完整 route、输入及 bundle SHA-256。子 ID 和哈希需待父频率计算取回后据实绑定。

父输入 water.gjf 如下（UTF-8、LF，末行 H 坐标后两个 LF），SHA-256 为 `e5593f781cbb8f937c54cd8da3d6e86caa71ae27378ba0a3d5802e448986f4ed`。

```text
%nprocshared=4
%mem=1GB
%chk=water.chk
# HF/STO-3G Opt Freq NoSymm

Water validation

0 1
O 0 0 0
H 0.95 0 0
H -0.24 0.92 0

```

1. 用受审版本在独立验证 study 执行一次 `ag prepare --study <study> --cluster <cluster> --template gaussian --tier mini --walltime 00:10:00 --label parent --method-basis '兜底方法：水分子流程验证' --input water.gjf`。核对父摘要后执行一次 `ag submit <parent>`，负责人亲手点击。用 `ag status <parent>` 观察至结束，`ag fetch <parent>` 一次。核实精确作业绑定、正常结束的频率段和 final_input.xyz。
2. 子输入 child.gjf 使用同样的资源行及 0 1，写 %oldchk=parent.chk 与 %chk=child.chk、route `# HF/STO-3G Opt=ReadFC NoSymm`，按原序照录父 final_input.xyz 原子行。执行一次 `ag prepare --study <study> --cluster <cluster> --template gaussian --tier mini --walltime 00:10:00 --label child --method-basis '兜底方法：水分子流程验证' --input child.gjf --parent <parent> --relation opt_from --parent-chk <parent>:water.chk`。留存子输入及 bundle 的 SHA-256、父子 ID、父输入与 final_input.xyz 的哈希。
3. 核对确认摘要中的父 chk 名、大小与哈希及子 bundle 后执行一次人工确认的 `ag submit <child>`（摘要在此命令的点击前显示）。用 `ag status <child>` 观察至结束，`ag fetch <child>` 一次。比对既有复制 journal 中已核验的源/目标大小及 SHA-256，核对两份 manifest 与授权字节，审阅子日志是否确有读取所声明力常数并正常结束；若日志未能证实读取，应保留该证据缺口。
4. 入口、资源、来源、坐标、哈希任一不符，或出现 SSH 错误、UNKNOWN、作业异常时立即停止并保留现场。每个 Attempt 最多提交一次，保留所有父子文件和提交声明。以上为待执行步骤，现场验证与监督对齐由监督对话协调。
