# T217A：链路不稳时的自主运行规则

## 授权与目标

负责人授权独立工作树、并行开发及一个 Draft PR；分支 `codex/t217a-link-aware-autonomy`，不合并、不部署、不运行真实验证。基线 T215；合并前须与含 T216 的 main 等价整合。负责人本单决定优先于旧文档中的冲突规则。

监控证据区分 relay 链路中断、单入口故障、全部入口失败和证据不足，避免共享链路故障误触发连续 SSH 暂停，或由故障误改投至不相关入口。缺失、损坏、过期不是成功；新鲜度保留三倍采样间隔。

## 允许路径

- `ag/src/ag/config.py`、`clusters.py`、`monitor.py`、`autonomy.py`、`autonomy_policy.py`、`autonomy_submission.py`、`_autonomy_store.py`、`route.py`、`submit.py`、`attempt.py`、`cli.py`；必要的小型纯逻辑模块 `ag/src/ag/link_health.py`。
- 相关 `ag/tests/test_*`；`ag/config.example.toml` 或现有配置示例对应片段。
- `AGENTS.md` 冲突规则的最小同步、`docs/DEVELOPING.md`、`ag/README.md`、`skills-next/auto-g16-study/references/autonomous-run.md`、`docs/LESSONS.md`、本单。

只改实际必要路径。不改 status/submission/remote 模板（T217B）、fetch/chk 或前端（T217C）。

## 行为与验收

1. 本机每入口可选 relay 分组，未配置为独立入口。唤醒开始读取最近 monitor，全部 relay 失败且至少一个独立入口成功判链路中断；部分 relay 失败沿用单集群处理；全部入口失败判本机断网。记录各入口年龄与分组至日志和只读摘要，不用旧成功推断恢复。
2. 链路中断拒绝 relay prepare/submit；独立路由既有 SCNet 类 CREST 可继续，禁止因中断改投。该唤醒内补检查不增加连续两次 SSH 暂停计数；其余暂停、租约、版本、资源、不可重提保护保持。
3. 本机补检查默认间隔 30 分钟、最多 2 次；目前本机 automation 只证实 recurring cron/heartbeat，无已验证 once 接口。采用同次唤醒内有界复测，不延长 60 分钟期限，不为凑第二次越过截止。次数为上限。
4. 不把未观测 running 改为 UNKNOWN，不重传原 Attempt；保留每对象每轮两次 failed_presubmit 上限，不新增 15 分钟门槛。
5. 通过现有只读 API 交付正常、链路断、全部断、证据不足例子和各入口 age/分组。前端不访问服务器或重算许可。

## 验证与交付

仅合成传输、临时目录、隔离 HOME：覆盖分类、证据新鲜度、次数上限、租约截止、SSH 计数、独立入口继续及 relay 拒绝；运行必要定向回归，新 head CI 全量，不重复本地全量。失败证据保留，同一问题两次修复仍失败则停止报告。
真实环境验证：本单明确不执行；不访问真实配置/研究 study/集群，不制造真实断网。离线结果不表示现场通过或自主启用。
交付 Draft PR、最小生产 diff、完整相关生产文件、定向/CI 结果；送审包不包含测试源码。明确列出自主提交计数影响点。

## 当前阻塞

科学审阅：待监督方审阅。环境：未执行真实验证（本单明确排除）。已在含 T216 的 main `09366724` 上完成变基；新 head CI 在交付前核对。

## 实现与离线证据

- `config` 保存 relay_group 和本机补检查设置；local-only 仅透传分类元数据，无连接凭据。`clusters` 返回当前缓存分类；自主 status 返回最近记录与补检查安排。
- prepare/submit 保持原路由，relay 证据失败/未知及全部入口失败拒绝，原本独立入口继续。SSH 豁免仅影响连续唤醒暂停；真实消费、声明、对象失败上限和派发后 UNKNOWN 不变。
- 定向：分类/配置/发现 121 项通过；自主状态含补检查 206 项通过；新增动作边界 3 项通过；相关 driver 8 项和路由 64 项首轮通过；卡片加链路 542 项通过。全量交新 head CI，本机不重复全量。
- T216 变基只在自主子命令注册发生冲突，保留 audit-reservations 并追加 link-recheck；相关组合 85 项通过。
- 首轮发现 CLI 配置调用兼容失败，改为保留 local-only 和最小入口元数据后回归通过；失败原始证据保留在本机交付区。另一次 pytest 临时目录清理警告不影响 exit 0，未据此访问或清理真实数据。
- 负责人本单已授权 AGENTS.md 冲突规则的最小同步；本 PR 仅追加链路中断例外，不启用自主运行。

## 协调审阅修正

协调发现初版已消费后的链路拒绝误分类为 object，可绕过对象 presubmit 两次和同 wake 上限。
修正为 LinkDeferred / failure_kind=link：消费前仅等待，消费后真实 failed_presubmit 纳入既有
对象上限及下一 wake 约束，实际消费/声明保留，科学补救名额不消耗。保留初版 CI，修正另跑
消费后、上传后及 dispatch 前翻转的完整后继测试和新 head CI。UNKNOWN 语义不改。
修正定向：自治计数/SSH/UNKNOWN 34 项通过，完整 driver 翻转和后继约束 5 项通过；
后者每个已消费场景完整核对两个失败 Attempt、三个 wake、同 wake 缓存恢复拒绝及两次后交人。
