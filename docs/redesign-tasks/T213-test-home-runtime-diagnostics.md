# T213：测试 HOME 保护的时区数据与失败报告兼容

## 已发生的问题与起点

冻结候选 `258c5a444bdf70caa332440536d3625ca19f2c98` 的本地最终组合在 1346 项通过后
退出 3。定向诊断确认 `test_pbs_scheduler_timezone_config_and_migration` 三个参数因
解释器发行的 `share/zoneinfo/Asia/Shanghai` 被 HOME 保护误拦而失败；默认 pytest
报告随后把 `<frozen genericpath>` 当作磁盘路径，触发 INTERNALERROR 并遮蔽原始失败。
T211 已合并，本单从 main `64307e9cab561b556dd222340b9ffac4d5030ffb` 独立修复；
不修改已冻结 T212 分支，也不将该问题归因为已证实的 T212 生产缺陷。

## 允许范围

- `_test_home_isolation.py`、`_test_home_pytest.py`（仅必要诊断兼容）。
- `ag/tests/test_home_isolation.py`、`ag/tests/test_clusters.py`（仅确需的合成回归）。
- `docs/DEVELOPING.md`、`docs/LESSONS.md` 与本任务单。

不改生产代码、其他测试、冻结目录、CI 配置、真实配置或研究目录。需要越界或同一
问题两次修复仍未解决时先报告。本单只修复已发生的问题，不扩展为通用安全沙箱。

## 验收

- 仅对 prefix/base_prefix 下的标准时区发行数据追加只读范围；不按任意
  `PYTHONTZPATH`、`TZDIR` 或其他用户环境变量放行用户数据，原写拒绝与临时 HOME 保留。
- 虚拟源码在实际磁盘查询前按无源码处理；不扩大普通路径 metadata/open 白名单，
  不吞掉原始 `HomeAccessError`。会话结束恢复诊断适配。
- 用临时模拟 HOME 验证两个解释器前缀的时区数据可读不可写，私有覆盖、相邻数据及
  链接越界仍拒绝；真实 zoneinfo 读取与三个原失败参数均通过。
- 实际 pytest 子进程用默认 traceback 触发带 frozen-frame 的模拟 HOME 违规，
  报告原始失败并 exit 1，无 INTERNALERROR，哨兵字节与目录不变。
- 保留 descriptor、子进程、吞错、能力身份和临时 HOME 隔离回归；不关闭保护、不扩大
  skip、不降低断言。只跑本地定向测试，不跑本地全量或 AST 比对；全量交当前 head CI。

## 边界与交付

完全离线，不连接集群、不执行真实 study/doctor/monitor/计算/部署，不探测或清理真实
自主登记。原全量 exit 3 和三个定向失败的私有证据保持原样；新的最终源码组合由协调
统一验证，旧失败不能改记为通过。原复现环境为 Python 3.11.15、pytest 9.1.1、
RDKit 2026.3.3；环境位置、完整命令、源文件哈希和原始日志仅放私有复现包。

公开扫描、精确暂存后创建 PR，首行 `Task: T213`。交付冻结 SHA、精确增量、
定向结果、当前 head CI、支持边界与私有证据位置；开发会话不合并，无真实运行授权。
