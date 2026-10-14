# T34：xTB 正常结束判定读取调度器输出

## 目标与事故

xTB 的正常结束标记可能写到 stderr；PBS 合并输出保存于 job.pbs.out，Slurm 保存于 job.slurm.err。只读 xtb.out 会把完成误记 incomplete；finished run 或退出码不能替代正常标记。

## 允许改动的路径

- ag/templates/xtb.toml：普通与 scan 输出增加 job.pbs.out。
- ag/src/ag/_parse_outputs.py、ag/src/ag/facts.py：读取对应调度器输出、记录标记来源与缺失，错误优先。
- ag/tests/test_facts.py、ag/tests/test_scan.py：合成回归与输出清单断言。
- 本任务单。

## 实现要求

只有 xtb.out 或对应调度器输出包含 normal termination of xtb，且没有程序/调度器错误，才能 normal；finished run 单独不足。调度器 walltime、kill 等错误优先于正常标记。记录每个正常标记所在文件，缺调度器输出如实记录，不能靠回执推断。按 manifest.scheduler 区分 PBS 与 Slurm；Slurm 已声明 job.slurm.err，保留。

不修改 xtb.pbs、远程命令或 AGENTS.md。仅检查 CREST 是否同样遗漏正常标记并报告，不改 CREST。

## 验证与交付

合成测试：标记仅调度器、标记在 xtb.out、错误覆盖正常、缺文件且无标记 incomplete、PBS/Slurm 都覆盖。普通及 scan 输出清单验证；全量 ag/tests 与 skills-next 回归、敏感扫描、diff 检查。

T32 已合并；分支基于最新 main。CI 通过后 PR，不合并。真实验证（包括重新 fetch 和现有 facts 的人工刷新）待合并后另行授权；本任务无远端操作。

## CREST 静态核查

crest.pbs 将 stdout 重定向到 crest.out，parse_crest / parse_crest_mdopt 已在该文件寻找 CREST terminated normally.。未发现本任务所述的 xTB stderr 标记漏取链路；未修改 CREST，也未进行现场运行，不以静态检查保证所有版本行为。
