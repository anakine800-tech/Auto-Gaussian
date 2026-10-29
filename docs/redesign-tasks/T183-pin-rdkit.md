# T183：固定开发与 CI 的 RDKit 版本

## 分支与目标

- 分支：`codex/t183-pin-rdkit`，基于最新 main，一单一 PR。
- 对应 V4.8 W11 的依赖版本固定；自主计划记录和运行期版本检查由运行状态工单负责。
- 问题：CI 与 README 使用无版本的 RDKit 安装，两台机器可能产生不同成键/去重行为。
- 核查时运行环境的 RDKit 为 `2026.3.3`，GoodVibes 为 `4.3.0`。优先固定同一 RDKit 发行版，需验证 Python 3.11 和 Linux/macOS 的包可用性；不顺便升级。

## 允许改动的路径

- `.github/workflows/ag-tests.yml`：RDKit 安装精确版本。
- `README.md`、`ag/README.md`：对应安装说明及复现边界。
- `docs/redesign-tasks/T183-pin-rdkit.md`：本单。

## 要做的

1. CI、README 所有现行新架构 RDKit 安装示例采用相同精确版本，注明版本固定并不代表不同硬件数值逐位一致。
2. 核对官方发行/包信息及本地可用环境；兼容性不足时报告具体证据，不擅自换版本。
3. 保留 GoodVibes 的现有版本、其他依赖与算法。不要修改运行环境或共享虚拟环境的 editable 安装。

## 不允许

不更新锁文件以外的无关依赖、不改算法、不改真实 study/配置、不部署、不运行量化或集群命令；不引入新的依赖管理层。

## 测试

- 在自己的虚拟环境核对依赖版本及 `ag.__file__` 指向；推送前一次 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，之后以当前 head CI 为准。
- 确认 CI Linux 安装成功，记录测试的解释器和实际版本。没有本机其他平台证据不得称全部平台已实测。
- 精确暂存、敏感扫描、`git diff --cached --check`；Git 身份使用 noreply。

## 真实环境验证

依赖与本地计算库版本固定，仅离线验证；不改变远端作业路径，无须集群验证。

## 停止条件

范围外改动、版本兼容证据不足、同一问题两次未解决则报告。

## 合并前审阅与交付

PR 首行 `Task: T183`。与 T182 都改 README：T182 先合并，本单 rebase 后核对保留双方改动并做受影响验证。由协调会话审阅最终 head、CI 并按负责人本次授权合并；本单不自行合并。

## 依赖与兼容性核对（2026-10-29）

- 开发基线：`4fce3cf7305bd57eb31525e54bb3edcc70b71986`。
- [RDKit 官方安装文档](https://www.rdkit.org/docs/Install.html#cross-platform-using-pip)指向 PyPI 的 `rdkit` 包；[2026.3.3 文件列表](https://pypi.org/project/rdkit/2026.3.3/#files)及其[发行元数据](https://pypi.org/pypi/rdkit/2026.3.3/json)列出未撤回的 CPython 3.11 wheel：Linux glibc 2.28+（x86-64、ARM64）、macOS 11+（ARM64）。
- 该版 PyPI 无 macOS Intel wheel。本机 Python 3.11.15 / macOS x86-64 已有 conda 提供的 RDKit `2026.3.3`；独立 worktree `.venv` 通过 `--system-site-packages` 只读复用，不能将此作为全新 Intel pip 安装成功的证据。
- 本工作树独立 editable 安装后核对 `ag.__file__` 指向本工作树的 `ag/src/ag/__init__.py`，`pip check` 通过。实际版本：ag `4.7.0`、RDKit 包 `2026.3.3`（运行时字符串 `2026.03.3`）、GoodVibes `4.3.0`、NumPy `2.4.6`、cclib `1.8.1`、pytest `9.1.1`。
- 仅固定现行 CI 与安装示例的 RDKit 要求；GoodVibes 和其他依赖声明、算法不变。离线测试与 Linux CI 结果记录在 PR；ARM64 仅核对官方包信息，未实测。
