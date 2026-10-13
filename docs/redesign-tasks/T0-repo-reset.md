# T0：仓库重置与新 CI

分支：`codex/redesign-t0-reset`　位置：本地或云端　依赖：无　预计：半天以内

## 目标

冻结旧代码，合入新规则、方案和任务单，建立只服务于新代码的轻量 CI。这是其余任务的前提，越快合并越好。

## 必读

本任务单附带的文件：`AGENTS.md`（新）、`docs/REDESIGN-PLAN.md`、`docs/redesign-tasks/T0`～`T5`。由人提供，原样放入仓库对应路径。

## 允许改动的路径

- `AGENTS.md`（整体替换）
- `docs/REDESIGN-PLAN.md`、`docs/redesign-tasks/`（新增）
- `ag/`（只建骨架，见步骤 4）
- `skills-next/README.md`（新增）
- `.github/workflows/ag-tests.yml`（新增）
- `.github/workflows/offline-tests.yml`（只改触发条件）
- `.gitignore`（如需忽略 `ag/` 的构建产物）

## 不允许

- 修改或删除任何其他旧文件（包括 `OWNER_DECISIONS.md`、`docs/v3/`、`config/`、`scripts/`、`auto_g16/`、旧 `skills/`、旧测试）。旧文件的归档在 T6 统一做。
- 修改分支保护（由人在 GitHub 网页上操作）。

## 步骤

1. 从最新 `main` 拉分支。**在任何改动之前**，对当前 `main` 的 HEAD 打附注标签 `v3-frozen`（说明：“Freeze before ag redesign, 2026-10”），并推送这个标签。本任务明确授权推送这一个标签。
2. 用新文件整体替换 `AGENTS.md`；加入方案和全部任务单。
3. 新增 `skills-next/README.md`：一句话说明这里是新 Skills，部署方式见方案 5.1。
4. 建 `ag/` 骨架：
   - `ag/pyproject.toml`：项目名 `ag`，`requires-python = ">=3.11"`，命令入口 `ag = "ag.cli:main"`，可选依赖组 `test = ["pytest"]`、`chem = ["cclib", "goodvibes==4.3.0", "numpy"]`（版本按当前可安装的稳定版本锁定小版本）。
   - `ag/src/ag/__init__.py`（`__version__ = "0.1.0"`）、`ag/src/ag/cli.py`（argparse，只有 `--version`，并预留 `register` 挂载点：依次尝试导入 `ag.facts`、`ag.thermo`、`ag.dedup`、`ag.cluster`、`ag.graph` 等模块的 `register(subparsers)`，模块不存在时跳过）。
   - `ag/tests/test_smoke.py`：能导入、`ag --version` 输出版本。
   - `ag/README.md`：三行说明，指向方案第 4 节。
5. 新增 `.github/workflows/ag-tests.yml`：
   - 触发：`pull_request`、推送到 `main`、`workflow_dispatch`。
   - 一个 job，**job id 和 name 都叫 `ag-tests`**（它将成为唯一的必选检查）。
   - Python 3.11；`pip install -e "ag[test,chem]"` 和 `rdkit`；运行 `pytest ag/tests`；若 `skills-next/` 下存在任何 `test_*.py`，再运行 `pytest skills-next`。
   - 一个敏感信息扫描步骤：对本次 PR 改动的文件检查私钥头（`-----BEGIN ... PRIVATE KEY-----`、OpenSSH 私钥头）、IPv4 地址、真实用户目录路径（正则 `/(home|Users)/[A-Za-z0-9_.-]+`），命中即失败。占位符写法如 `/home/<名字>`、`<ag_root>` 不会命中。用几行 shell 或一个不超过 60 行的 Python 脚本实现，放在 `ag/tools/scan_sensitive.py`。
6. 修改 `.github/workflows/offline-tests.yml`：只把 `on:` 改为仅 `workflow_dispatch`，文件其余内容不动。旧测试仍可手动运行。
7. 开 PR。

## 验收标准

- tag `v3-frozen` 存在于远程，指向重置前的 `main` HEAD。
- 新 `ag-tests` 检查在 PR 上运行并通过。
- PR 的改动只涉及上面允许的路径。
- `pip install -e ag` 后 `ag --version` 可用。

## 停止条件

- 推送标签失败或标签已存在且指向不同提交。
- 需要改动允许范围以外的文件才能让 CI 通过。

## PR 要求

PR 描述第一行 `Task: T0`。描述中写明：标签名和它指向的提交短哈希；`ag-tests` 的运行结果；提醒人：合并前需要在分支保护中把必选检查改为 `ag-tests`（人有操作清单）。
