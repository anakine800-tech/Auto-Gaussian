# T50：CREST/xTB 模板固定 BLAS 线程数，消除 OpenBLAS 警告刷屏

## 分支与目标

- 分支：`codex/t50-xtb-crest-thread-env`；基于 v4.1.0 之后的 main，一张任务单一个 PR。
- **防的事故（2026-10-15 真实发生）：** SCNet 上 V2（17 个原子的 CREST）的 crest.out 里有约 159 万行 OpenBLAS/OpenMP 警告，文件约 194 MB。xTB 用 OpenMP 并行，又调用了按 pthread 编译的 OpenBLAS，嵌套并行时 OpenBLAS 会反复报警。HSS 的 M1 有 84 个原子，运行时间长得多，日志可能更大。后果是取回慢、本地和集群都多占空间，也让真正的错误信息淹没在警告里。
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
  - crest.out 里不再有 OpenBLAS 警告（或只剩个位数行），文件大小降到 MB 量级以下；
  - 构象数、相对能量与 V2 一致（相对能量差小于 0.01 kcal/mol）；
  - 墙钟时间不明显变长（超过 V2 的 1.5 倍就停下报告）。
- 结果写进 PR 描述，不写主机和路径。验证结束后删除临时 worktree。

## 停止条件

- 加了变量后警告仍然存在：停下报告，不要试别的变量组合。
- 结果或耗时明显变化。
- 需要改动 Gaussian 模板或安全逻辑。

## 合并前审阅与交付

- 需要监督方审阅：是（模板属于硬内核第 7 条的范围）。
- PR 描述第一行：`Task: T50`。
- 合并只由负责人操作。HSS 剩余 3 个 M1 的 CREST 最好在 T50 合并之后再提交。

## 实现选择与依据

- `OPENBLAS_NUM_THREADS=1`：按 [CREST 官方 README](https://github.com/crest-lab/crest/blob/master/README.md#option-2-conda) 的说明，将 OpenBLAS 线程数固定为 1，避免并发/嵌套部分的警告。
- `OMP_MAX_ACTIVE_LEVELS=1`：按 [xTB 官方并行设置](https://xtb-docs.readthedocs.io/en/latest/setup.html#parallelisation) 禁用嵌套 OpenMP；原有 `OMP_NUM_THREADS=$cores` 和 CREST `-T $cores` 不变。
- 不新增 `MKL_NUM_THREADS=1`：xTB 文档允许 MKL 独立设置为分配核数，并未要求固定为 1。此次故障针对 OpenBLAS，强制串行化 MKL 可能影响其他构建的性能。
- 完整脚本基线来自 v4.1.0 后 main 的 `36b645e`；覆盖 xTB/CREST 的 PBS、Slurm，以及 Gaussian PBS、Slurm 和 SCNet A.03。移除两行新增 export 后校验完整脚本 SHA-256，Gaussian 直接校验原始字节哈希。
- 真实环境验证尚未执行；合并前仍需负责人授权并确认提交，以及监督方审阅。README/交接文档按任务单删除 T50 已知问题条目，不代表真实验收通过。
