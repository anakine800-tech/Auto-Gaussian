# T231 后端 v4.8.1 补丁发布

## 目标与范围

以已合并的 `d2750ba28752269be4b5758cc594f140c4565d39` 为功能基线，与 T232 前端同号发布。更新 `ag/pyproject.toml`、`ag/src/ag/__init__.py` 和 `ag/tests/test_smoke.py` 的产品版本，整理 `CHANGELOG.md`、`README.md`、`ag/README.md`、`docs/README.md`、`docs/OPERATIONS.md`、`docs/handoff-v4.md` 中的当前版本、安装、配对与导航，并维护本工单。分支 `codex/t231-release-v4.8.1-backend`，一个 PR，首行 `Task: T231`。

## 验收

- 安装包元数据、导入的 `ag.__version__`、CLI、测试断言以及前端配对均为 4.8.1。发行物从同一提交构建；完整源码含 `ag/templates/` 和 `skills-next/`。
- 发布说明涵盖 v4.8.0 后本仓已合并的 Gaussian 严格输入校验、共享 PBS 节点准入、预留核算与目录恢复和许可变更。共享节点按本机策略和原申请核数判断，证据不足时仍会拒绝。保留 v4.8.0 及更早发行的许可分界、既往验收与部署日期。现场验收引用公开记录。
- 核查当前入口的版本和链接、wheel/sdist 元数据、CLI、全量后端与 Skills 测试、私有词表及公开扫描和 diff。核对当前 PR 的 CI 与独立审阅后交协调方与前端配对发布。

## 真实环境验证

本单只变更产品版本、既有断言和文档。共享节点现场结果可查 [部署验收](https://github.com/anakine800-tech/Auto-Gaussian/issues/405)。版本发布与机器升级分别记录。

## 发布核对记录

- 已按功能基线核对已合并改动，以及 2026-11-25 的开发机非研究验收。发布说明保留 v4.8.0 的历史 tag、部署与授权记录，并单列本版许可。
- 本工单的 PR 记录精确提交、从该提交构建的 wheel/sdist 元数据与安装验证、完整源码清单核对、后端和 Skills 测试及扫描结果。现场机器使用的版本按各自的部署记录核验。
