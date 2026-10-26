# T144：v4.6.1 后端与前端同号补丁发布

版本：v3，2026-10-27。T142、T143 已审阅通过并合并；负责人已授权准备两个同号发布 PR。本单仅版本、文档与发布验证，不含部署。

## 依赖与范围

- 后端包含已合并的 T141 Gaussian-only 兼容及 T142 可选六档、显式 PBS 高内存及每入口 walltime 硬上限；前端包含已合并的 T143 PBS 节点明细、多入口响应式布局及可选资源字段显示。
- 两仓任务编号 T144；各仓一个独立分支 `codex/t144-release-v4.6.1`、一个 PR。PR 首行分别 `Task: T144`、`Task: T144 (frontend)`。
- 开始实施前重新确认 T142/T143 的准确审阅 head、merged 状态、实际合并提交、CI 及两仓 main 干净。核对 `git log v4.6.0..main --first-parent` 实际增量；发现额外未确认改动先列出差异。
- 已核对后端 main `43f248cef263dceb8754efe2ce1e46dc420c4d57` 与前端 main `5e960aedddc0482dc8155e5de1e2615b1395d499`。相对 v4.6.0 分别仅增加 #342/#343 与 #42；T142 审阅 head 为 `120156e652ca453b38b9bba845dadf049d95c938`，T143 审阅 head 为 `b16ca3de4ddbc34b93847689be49494b7e5efcd5`。
- 两仓同号 4.6.1；不借发版追加功能、依赖升级、模板或研究格式变化。

## 允许路径

后端：
- `ag/pyproject.toml`、`ag/src/ag/__init__.py`、`ag/tests/test_smoke.py`：只修改版本及版本断言。
- `CHANGELOG.md`、`README.md`、`docs/handoff-v4.md`：本次版本、兼容性、实际 PR/验证和已知问题。
- `docs/OPERATIONS.md`：适用版本及高内存/Gaussian-only 配置回退提醒，保留通用部署步骤和停止条件；观察时长仍由私有部署消息指定。
- 本任务单、`docs/redesign-tasks/open-tasks.txt`：核实后清理已完成历史记录、登记本单。保留历史任务单与研究待办。

前端：
- `pyproject.toml`、`web/package.json`；`web/pnpm-lock.yaml` 只在含本包版本时同步。
- `CHANGELOG.md`、`README.md`：版本、配合版本、Release status、历史和本次已验证变化。
- 本任务单、`docs/redesign-tasks/open-tasks.txt`。
- 现有 runtime `__version__` 遗留仍按项目约定列为已知问题，不顺带改功能代码。

需要范围外修改时先报告。以前各版 CHANGELOG 原文不改，不全局替换历史版本号。

## 发布说明

- 后端：Gaussian-only 入口必须显式白名单；缺软件不填假路径；原完整配置兼容。PBS 高内存必须逐入口显式授权，默认 120 GB 保留，最高 200 GB；max/ultra 两档可选；可选 max_walltime 在 prepare/submit 前硬拒绝超限，审批不能豁免。授权字段不等于硬件或调度器许可。
- 前端：PBS 节点状态与已分配 slots 分开展示；未知和非实时数据明确标识；复用现有快照，无新增远程查询；ag-monitor/1 只增可选字段；四卡与五卡响应式、四/六档、可选单作业时限和既有排队上限，以及 Slurm/作业详情回归。
- 升级前备份。回退到 4.6.0 前恢复与旧版兼容的入口配置：旧版不能加载缺 xTB 的 Gaussian-only 新入口，旧版不理解新增档位或 max_walltime，已识别的四档 PBS 内存仍受120 GB限制；完整恢复旧配置，不依赖旧版忽略字段。
- 不增加 study/catalog 迁移，不为发版执行真实研究操作或未经审批的作业。
- 发布、部署、监控显示、实际计算与长期认证是不同验证结果；本发布不宣称新增服务器已部署。

## 验证

- 后端全量 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，准确发版 head 的 CI。
- 前端离线 Python 测试、全量 Playwright、构建；发版时做一次跨页面集成回归。用合成数据验证四/五卡、PBS free 仍有分配、未知/失败/过期、响应式、键盘/可访问名称、四/六档与可选时限字段、操作模式兼容及 Slurm/作业页面。
- 两仓有效本机词表全量/暂存扫描、diff 检查、noreply 身份与人工脱敏检查。
- 记录实际结果及跳过项，不把功能 PR 的测试结果当成新发版提交已测。

## 合并、发布与部署边界

两个发布 PR 均经监督方审阅，由负责人合并；负责人在各自确切合并提交上建立 v4.6.1 tag/release，不能直接使用之后的 main。Codex 不合并、不发版。

双 tag 核实后，开发机部署另按 OPERATIONS 和最新私有执行单进行；开发机所有必要验收完成前不得配置研究机。研究机仍须负责人批准维护窗口并独立验证。

公开工单、PR、发布说明不包含真实主机、账号、SSH 别名、队列、目录、资源池实值、路由实值、研究数据或原始记录。部署参数与原始证据仅在仓库外私有交接中保存。
