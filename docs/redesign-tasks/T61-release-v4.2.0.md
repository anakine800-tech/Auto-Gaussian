# T61：发布 v4.2.0（版本号、CHANGELOG、交接文档）

## 分支与目标

- 分支：`codex/t61-release-v4.2.0`；基于最新 main，一张任务单一个 PR。开发机做。纯文档和版本号，不改功能。
- **开工条件：** #274（T58）、#276（T52）已合并。T62、T63 **不进**这个版本（它们合并后进下一个版本）；如果开工时它们已经合并，就一并写进来，并在 PR 里说明。
- **目标：** 把 v4.1.0 之后合并的工作汇总成 v4.2.0，两台电脑能对齐到同一个版本号。
- 内容范围（以实际已合并的 PR 为准，逐个核对）：T49 #269、T49b #275、T50 #268、T51 #271、T52 #276、T53 #270、T58 #274、T59 #273、T60 #272。

## 允许改动的路径

- `ag/pyproject.toml`、`ag/src/ag/__init__.py`：版本号 4.1.0 → 4.2.0。
- `ag/tests/test_smoke.py`：只改断言里的版本号。
- `CHANGELOG.md`：新增 v4.2.0 一节，放在 v4.1.0 之上。
- `README.md`：标题版本号；“配合前端 v4.2.0 使用”；版本历史一行。
- `docs/handoff-v4.md`：标题和第一段改为 v4.2.0；“已知问题与后续工作”按实际状态更新（删掉已修复的 T49、T50 条目，补上 T51 的“ag 不限制运行中核数”说明、T49b 后仍存在的 L3 越界链接已知问题）。
- `docs/redesign-tasks/T61-release-v4.2.0.md`：本任务单。

## 要做的

1. **CHANGELOG v4.2.0**，按类别分组，每条写清改了什么、对使用者的影响，附 PR 链接：
   - **提交与资源：** T51 核数上限改为运行加排队（`max_committed_cores`，最多 4 × `max_cores`），删除严格模式和提交时的 `pbsnodes`；ag 不限制运行中核数；SSH 本地日志。**升级提示：** 本机配置需要按新含义检查 `max_cores`（单作业）和 `max_committed_cores`（运行加排队）。
   - **取回与解析：** T52 取回成功后自动运行 facts，绝不覆盖已有 facts.json（`--no-facts` 可关闭）。
   - **模板：** T50 CREST/xTB 固定 `OPENBLAS_NUM_THREADS=1`、`OMP_MAX_ACTIVE_LEVELS=1`。
   - **证据清单：** T49、T49b 中文路径、目录引用、Attempt 相对文件名、study 快照引用的解析。
   - **分析：** T53 `ag ensemble`。
   - **Skills 与文档：** T58 kinetics 卡片、S8、F4、Gaussian 报错速查；T59 开题包模板；T60 文献整理脚本。
   - 写一句：真实环境验证的结果见各 PR 评论；发布不等于科学验收。
2. 版本号和 README、handoff 按上面的路径修改。
3. 全量测试：`PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`；敏感扫描与 `git diff --cached --check`。

## 不允许

- 不改任何功能代码、模板和卡片。
- CHANGELOG 和 handoff 不写研究内容、本机路径和主机信息。

## 合并后（负责人）

- GitHub 上在合并提交上建 tag `v4.2.0`，release 正文用 CHANGELOG 的 v4.2.0 一节；前端 T57 合并后同样建 `v4.2.0`。
- 两台电脑 `git pull --ff-only`，确认 `ag --version` 为 4.2.0；前端同步并重新构建。

## 停止条件

- 发现有已列入的 PR 实际没有合并，或合并后有未处理的审阅意见。
- 需要改功能代码。

## 合并前审阅与交付

- 需要监督方审阅：是。
- PR 描述第一行：`Task: T61`。
