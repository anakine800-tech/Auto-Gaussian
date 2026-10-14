# T33：scan-peak 只选局部极大

## 分支与目标

- 分支：`codex/t33-scan-local-maxima`，基于最新 main。
- 防止已发生的错误：分离方向高能边界附近的内部点被选为 TS 初猜，遗漏势阱内较低的局部峰。
- 依据：负责人 T33 要求；只修改本地确定性选点及使用说明。

## 允许改动的路径

- `ag/src/ag/scan_peak.py`：严格局部极大、候选列表及指定点导出。
- `ag/tests/test_scan.py`：合成曲线和 CLI 回归。
- `skills-next/auto-g16-recipes/cards/ts.md`：扫描初猜使用与科学边界。
- `skills-next/auto-g16-recipes/cards/reaction-plan.md`：扫描策略说明。
- `docs/redesign-tasks/T33-scan-local-maxima.md`：本任务单。

## 要做的

1. 只选内部严格局部极大；候选及左右紧邻点均须收敛且有能量。
2. 全列局部极大的序号、实际坐标值、Hartree 能量和相对能；相对能以全部已收敛扫描点最低能为零，单位 kcal/mol。
3. 默认导出最高局部峰；`--point` 用原扫描的 1-based 序号指定其他局部峰，非候选拒绝。
4. 无局部极大拒绝导出，提示范围或坐标不合适；不回退全局最高点，保留范围、收敛和跳变警告。
5. 更新 TS 和扫描相关卡片：scan-peak 只给初猜；气相离子–分子反应的全局最高点常常不是 TS。

## 不允许

不改 AGENTS.md、冻结目录、解析器或远程操作；不提交真实研究数据，不提交/取消计算，不合并。

## 测试

- 合成高能边界/第 2 点与较低第 9 点局部峰，必须选第 9 点。
- 单调、平台、邻点未收敛/缺能量拒绝；双峰全列、默认最高和指定另一峰；非法指定不产生文件。
- 保留范围、未收敛、能量/RMSD 跳变及输出哈希/不覆盖回归。
- `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`；提交前敏感扫描和 diff 检查。

## 真实环境验证

不需要；使用合成曲线验证本地行为，离线通过不等于科学验收。

## 停止条件与交付

遵循 AGENTS.md 的停止条件。CI 通过后创建 PR，首行 `Task: T33`；报告实际阻塞。
读取监督方评论并逐条处理；合并由人操作。
