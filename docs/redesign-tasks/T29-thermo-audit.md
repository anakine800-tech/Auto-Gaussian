# T29：热化学配对校验与审计输出

分支：`codex/t29-thermo-audit`；依赖：当前 main；依据：负责人本次 T29 指令。

## 目标与事故

防止同分子不同构象因原子数、电荷、多重度相同而被错误 SP/Freq 配对；让热化学分项和统计权重可审阅，避免标准态重复修正及简并度混用。

## 允许改动的路径

- `ag/src/ag/thermo.py`
- `ag/tests/test_thermo.py`、`ag/tests/test_profile.py`（仅补齐 thermo 集成测试的 SP 输入证据）
- `skills-next/auto-g16-recipes/cards/thermo.md`
- 本任务单

不改 AGENTS.md、其他工具、依赖或远程执行路径。

## 验收标准

1. manifest 绑定的 SP 输入与频率最终几何元素序列完全一致；固定原子顺序 Kabsch RMSD ≤ 1e-3 Å。输出 RMSD、两边几何 SHA-256；禁止原子重排。
2. 同温度、同浓度报告 RRHO 和 qRRHO H/S/G；单列 SP 替换、低频 G 差、1 atm → 1 M 标准态修正。非 1 M 时单列剩余浓度修正，避免重复计入。
3. 每行分别给构象简并度、实际旋转对称数及来源；反应路径数只提示另记。
4. Markdown 显示 qh_H、分解与配对证据；卡片说明工具成功不等于配对正确及 SMD H/S 的解释限制。
5. 正丁烷已有 qh_G、布居、系综 G 数值不变；错配拒绝、同几何不同取向通过，并覆盖证据缺失与原子顺序。
6. ag 单元测试、Skills 测试与敏感信息扫描通过，CI 通过后提 PR，不合并。

## 真实环境验证

纯本地确定性分析；使用已脱敏水/正丁烷 fixture 及合成输入，不连接集群，不新增真实计算。

## PR

第一行 `Task: T29`；记录测试、CI、兼容性和实际阻塞。合并由人执行。
