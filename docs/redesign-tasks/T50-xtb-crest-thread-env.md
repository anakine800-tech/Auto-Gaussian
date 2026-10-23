# T50：CREST/xTB 模板固定 BLAS 线程数，消除 OpenBLAS 警告刷屏

## 分支与目标

- 分支：`codex/t50-xtb-crest-thread-env`；基于 v4.1.0 之后的 main，一张任务单一个 PR。
- **防的事故（2026-10-15 真实发生）：** SCNet 上 V2（17 个原子的 CREST）的 job.slurm.err 里有约 159 万行 OpenBLAS/OpenMP 警告，文件约 194 MB。xTB 用 OpenMP 并行，又调用了按 pthread 编译的 OpenBLAS，嵌套并行时 OpenBLAS 会反复报警。某研究物种规模较大，运行时间长得多，日志可能更大。后果是取回慢、本地和集群都多占空间，也让真正的错误信息淹没在警告里。
- **目标：** 在 `crest.pbs` 和 `xtb.pbs` 两个模板里固定设置 `OPENBLAS_NUM_THREADS=1`（是否同时加 `MKL_NUM_THREADS=1` 和 `OMP_MAX_ACTIVE_LEVELS=1`，由 Codex 查 xTB/CREST 官方文档后提出并说明依据），让并行只交给 OpenMP（`OMP_NUM_THREADS=$cores` 保持不变）。

## 允许改动的路径

- `ag/templates/crest.pbs`、`ag/templates/xtb.pbs`：只新增固定值的 `export` 行。
- `ag/tests/` 下模板渲染相关的测试（断言完整的脚本文本）。
- `docs/LESSONS.md`：新增一条。
- `README.md`、`docs/handoff-v4.md`：只在“已知问题”中删除 T50 这一条。
- `docs/redesign-tasks/T50-xtb-crest-thread-env.md`：本任务单。

## 要做的

1. 两个模板各加固定的环境变量行，取值写死，**不新增任何配置项、参数或开关**（硬内核第 7 条：模板参数只接受白名单取值）。
2. Gaussian 模板和 `gaussian-scnet-a03.sh` 不动。
3. 在 PR 里引用 xTB/CREST 官方文档对线程环境变量的建议，说明每个变量的作用。

## 不允许

- 不改模板中的路径检查、回执、noclobber 等安全逻辑。
- 不新增可配置项，不让 LLM 或用户传入任意环境变量。

## 测试

- 渲染测试：两个模板渲染出的脚本文本包含新的 `export` 行，其余内容逐字节不变；Gaussian 模板的渲染结果不变。
- `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`；敏感扫描和 `git diff --cached --check`。

## 真实环境验证（合并前，在开发机上，由负责人确认提交）

- 用 T50 分支的临时 worktree（按 DEVELOPING 的例外流程），在 SCNet 上重跑一次 V2 体系（质子化正丁胺，`--chrg 1 --alpb ch2cl2`，8 核）：
  - 核对 `crest.out` 和 `job.slurm.err` 的 OpenBLAS 警告行数及精确字节数；警告不再出现（或只剩个位数行），日志低于 MB 量级。原 V2 的约 194 MB 警告日志实际是 stderr，非 crest.out；
  - 按下述修订后的结构与能量判据比较两次构象集合；
  - 墙钟时间不明显变长（超过 V2 的 1.5 倍就停下报告）。
- 结果写进 PR 描述，不写主机和路径。验证结束后删除临时 worktree。

### 验收口径修订（2026-10-15，负责人转达监督方批准）

CREST 采样有随机性，原“构象数一致、相对能差 < 0.01 kcal/mol”标准作废，改为：

1. 两次运行的最低构象为同一结构：重原子对齐后 RMSD ≤ 0.125 Å，绝对总能量差 ≤ 0.1 kcal/mol。
2. T50 的每个构象都能在 V2 中找到对应：重原子 RMSD ≤ 0.125 Å，相对能差 ≤ 0.2 kcal/mol。
3. V2 多出的构象，相对能 ≥ 1.5 kcal/mol，或与某个已匹配构象近乎重复，均可接受；若有 < 1 kcal/mol 的低能构象在 T50 中找不到，停下报告。未落入上述接受条件的情况列出证据交监督方判断，不自行降低阈值。

复用仓库 `ag.geometry` 的 XYZ、重原子投影和 RMSD 工具；保持输入原子顺序，允许对称等价映射，不另写对齐算法；镜像仅按下述批准的补充核对范围使用。先核对分子身份及原子序列，再计算全部配对；不能只按能量排序配对。PR 描述列出逐构象配对、RMSD、相对能差，以及最低构象总能量差。

V2 的 `crest_conformers.xyz` 由负责人提供，仅作临时比较数据，不写入任何 study，比较后删除本次创建的临时坐标副本，不操作原 V2 study。XYZ 注释的绝对总能量与 `crest.energies` 的相对能必须区分，缺少总能量时报告缺失，不用相对零点代替。

V2 的 1 h 与 T50 的 4 h 为调度资源时限，按批准意见不影响本次 CREST 正常完成的比较，保留披露。实测墙钟时间 664.285 s 对 108.129 s，约为原来的 1/6，满足“不明显变长”。

### 镜像补充核对（2026-10-16，负责人转达监督方批准）

本体系无手性，允许把镜像扭转构象作为对应。仅对 V2 2 ↔ T50 2、V2 5 ↔ T50 5 复算，调用已有 `ag.geometry.best_rms(..., mirror=True)`，同时报告 `mirror=False` 的 RMSD 和原子顺序固定的 C1–C2–C3–C4、C2–C3–C4–N5 二面角。工具没有镜像选项时停止，不另写算法。

两对镜像 RMSD 均 ≤ 0.125 Å、相对能差均 ≤ 0.2 kcal/mol，则与其余已通过项合并，验收通过；否则维持停止。PR 配对表注明“镜像匹配，体系无手性”。手性体系（如研究 A）不做镜像合并，不改变其已签能量口径。

补充核对结果：两对镜像 RMSD 分别 0.002397、0.002736 Å，相对能差 0.000753、0.002290 kcal/mol，关键二面角符号相反。两对均通过；其余四对、最低构象、V2 额外高能构象及日志/耗时项沿用已完成结果，T50 满足获批验收标准，待监督方复核。V2 临时坐标用后删除，不写入任何 study。

## 停止条件

- 加了变量后警告仍然存在：停下报告，不要试别的变量组合。
- 修订后的结构/能量判据不满足，或墙钟时间超过 V2 的 1.5 倍。
- 需要改动 Gaussian 模板或安全逻辑。

## 合并前审阅与交付

- 需要监督方审阅：是（模板属于硬内核第 7 条的范围）。
- PR 描述第一行：`Task: T50`。
- 合并只由负责人操作。研究 study 剩余的 CREST 最好在 T50 合并之后再提交。

## 实现选择与依据

- `OPENBLAS_NUM_THREADS=1`：按 [CREST 官方 README](https://github.com/crest-lab/crest/blob/master/README.md#option-2-conda) 的说明，将 OpenBLAS 线程数固定为 1，避免并发/嵌套部分的警告。
- `OMP_MAX_ACTIVE_LEVELS=1`：按 [xTB 官方并行设置](https://xtb-docs.readthedocs.io/en/latest/setup.html#parallelisation) 禁用嵌套 OpenMP；原有 `OMP_NUM_THREADS=$cores` 和 CREST `-T $cores` 不变。
- 不新增 `MKL_NUM_THREADS=1`：xTB 文档允许 MKL 独立设置为分配核数，并未要求固定为 1。此次故障针对 OpenBLAS，强制串行化 MKL 可能影响其他构建的性能。
- 完整脚本基线来自 v4.1.0 后 main 的 `36b645e`；覆盖 xTB/CREST 的 PBS、Slurm，以及 Gaussian PBS、Slurm 和 SCNet A.03。移除两行新增 export 后校验完整脚本 SHA-256，Gaussian 直接校验原始字节哈希。
- 已由负责人点击确认完成单次真实运行：T50 stdout 37,091 字节、stderr 0 字节，OpenBLAS 警告为 0；V2/T50 分别 7/6 构象。按修订和镜像补充口径，结构与能量对应已通过；这是 T50 技术验收，不代表研究构象空间已穷尽。README/交接文档删除已知问题条目不代表验收通过，合并前仍需监督方复核。

## 版本记录

- T116 脱敏：研究标识、编号与环境字面量改为泛称；原工单结构和结论不变。
