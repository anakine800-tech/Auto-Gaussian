# T149：监控重试请求可追踪与配置重读优化

版本：v1.0，2026-10-27。开发机做。后端一个分支、一个 PR，首行 `Task: T149`。本单不部署、不提交计算。

## 1. 分支与目标

- 分支：`codex/t149-monitor-retry-reload`。
- 开工重新 fetch 的 main：`830ce69e69ff3559bbc72ab603fe3a7ed3e8eb43`，即 T148 PR #347 的实际合并提交；T148 实现 HEAD 为 `41794ee8fafc0fe3bc3460dce96f30316ad46503`。原共同基线 `020475a81bf0354ecc5c25941ace2fd584969bbf` 仅作来源记录。
- B04：请求登记后遇暂停、入口移除、配置变化或重启，不能静默消失；B05：减少主循环每约两秒完整解析未变化配置的开销。
- 负责人决定 X1：按监督推荐范围准备 T148–T150。X2 原话：“本批同时完成前端反馈：三张后端工单之外，再准备一张独立前端配套工单”。配套为 T151；本单生产结果，T151 展示结果。
- 默认做法（已告知负责人）：旧 CLI 响应兼容；新追踪显式开启；控制状态和真实采样时间分开。配置优化只在 monitor 生命周期内缓存。
- 新检查/记录防的事故：静默丢请求；把旧目标请求带到更改后的连接；同秒点击误对应；用假快照结束前端等待；改变四字段响应令旧前端直接报错。
- 资料（共同基线）：`ag/src/ag/monitor.py:416` Sampling、`:533` retry、`:574` WatchControl、`:614` 附近 begin、`:678` 附近 run_clusters、`:740` reload_config；`ag/src/ag/cli.py:18`、`:140`；`ag/src/ag/config.py:49`；T127 和 T148。

## 2. 允许改动的路径

- `ag/src/ag/monitor.py`：请求/状态、重读缓存、必要的小型局部函数。
- `ag/src/ag/cli.py`：显式 --track 参数与组合校验。
- `ag/tests/test_monitor_resilience.py`、`ag/tests/test_resources_monitor.py`、`ag/tests/test_monitor.py`：状态、重读、旧调用兼容。
- `README.md`、`docs/OPERATIONS.md`、`docs/LESSONS.md`：本单字段、请求未执行原因、恢复口径，不改部署顺序。
- `docs/redesign-tasks/T149-monitor-retry-reload.md`、`docs/redesign-tasks/open-tasks.txt`：本单归档与自身标记。

不改 config.py 的校验规则、transport、远程模板、提交链路、前端、版本号或冻结目录。不重写 T148 已合并的解析逻辑。

## 3. 要做的

### T149 / T151 共用字段约定（两单文字必须保持一致）

这是本批拟新增的本机控制数据，不是现有字段。沿用既有锁、缓存目录与读取保护，不另建队列服务或数据库。

1. 新监控在根部 `watch.json` 发布 `retry_tracking_version: 1`；其 `entries[入口].source` 明确为 `legacy` 或 `named`，指向该入口实际控制文件布局。根目录始终是已核对的本机 study 根；不接受任意路径。
2. 默认 `ag monitor --retry <ENTRY> [--auth-fixed] --json` 仍只返回既有四键 `entry/result/reason/requested_at`，退出码和原枚举不变。旧前端对四键作严格检查，不得直接加字段。
3. 本单新增显式 `--track`，只允许与 `--retry`、`--json` 同用。启用时额外返回 `request_id`：受理结果为 32 位小写十六进制随机标识，refused 为 null。不改变认证确认、只读或提交权限。
4. `queued` 分配新标识；`already_queued` 返回原待处理请求标识；`in_progress` 返回所合并的当前采样标识。同一轮被多个客户端合并时标识相同；不拿秒级时间戳当标识。默认未追踪调用也走同一处理逻辑。
5. 每入口在原 `retry-request.json` 同级保存一个 `retry-status.json`，只保留最近一次受理请求的状态，不创建额外子目录。字段：
   - `version: 1`、`entry: string`、`request_id: string`、`requested_at: UTC ISO`；
   - `state: "queued" | "running" | "finished" | "discarded"`；
   - `reason: null | "auth_confirmation_required" | "entry_removed" | "config_changed" | "monitor_restarted"`；
   - `finished_at: UTC ISO | null`、`sampled_at: UTC ISO | null`、`ok: boolean | null`。
6. queued/running：后三项为 null，reason 为 null。finished：真实采样及快照发布完成后写入，finished_at、sampled_at 非空、ok 为本轮真实布尔值、reason 为 null。discarded：未执行该请求，finished_at 非空，sampled_at/ok 为 null，reason 必须为上述具体原因；不是作业取消。
7. 状态原子发布，在现有 `watch.lock` 下与登记/领取串行处理。未采样不得更新 `latest.json.sampled_at`、`last_ok_at`、`ok`，不得往采样 history 添加假轮次。正常定时采样不覆盖上一条追踪终态；收到新请求可以替换最近状态。
8. 新前端仅在同一已核对根下、心跳新鲜且来源唯一的版本 1 标记存在时使用 --track。旧标记缺失则使用原命令；未知/损坏版本不能宣称支持。若调用失败，不再次换命令登记请求。标记只能表示能力；真正是否运行、能否受理由 ag 原有检查决定。
9. 前端 `GET /api/monitor` 的每个 ClusterRow 增加可选 `retry_tracking_supported: boolean`、`retry_status: object | null`、`retry_status_error: string | null`。数据来自同一 name/source 的本地控制文件，绝不混入保存的 ag-monitor/1 快照；即使还没有快照或入口已移除，已有控制结果仍可展示。
10. 已知字段严格验证；未知附加键忽略。未知版本、非法枚举、身份不符、损坏/越界/符号链接控制文件仅影响请求状态，不能清空正常监控快照。单文件读取上限复用现有 2 MiB 保护。
11. UI 以 name + source + request_id 对应终态。不同标识、被覆盖的结果、控制文件暂缺或超时都不能表示成功；不能凭另一次新快照时间判断被追踪请求完成。旧四字段响应才沿用旧快照时间兜底，并明确不能精确确认该请求。

### 3.1 请求处理

- queued 只在请求文件和可追踪状态成功持久化后返回。继续使用现有 O_EXCL/O_NOFOLLOW、控制锁与原子发布；失败不伪报 queued，不自动重发。
- 领取时先检查当前状态，再决定运行或丢弃；不能先删除请求后静默返回。discarded 状态先成功持久化，再清除本地请求文件；发布失败则停止并保留待核对文件。
- 请求登记后转入认证/主机密钥暂停，且请求无 auth_fixed：discarded/auth_confirmation_required。不能自动提升原请求的授权。
- 入口删除：在丢失旧 entry/cache 定位前写 discarded/entry_removed，再走原 mark_removed。入口的实际配置改变：先使旧待处理请求 discarded/config_changed，再按既有规则重建 transport/调度；共享额度元数据变化按原 comparable 规则处理，不误当成本入口连接变化。
- 监控重启：有效的 queued/running 遗留结果写 discarded/monitor_restarted，绝不重新执行；仍保留原 T127 的重新开始自动采样口径。遗留旧请求无追踪标识时沿用原启动清理摘要，不捏造曾经返回过的标识。
- 对正在采样时合并的请求，用同一真实采样结果完成状态；只有 publish 成功后才能 finished。异常退出或写盘失败不能伪造采样成功。
- 只保留每入口最近状态；若新请求已替换旧结果，调用方只能说明旧结果无法确认。无需历史队列、后台服务或自动重试。
- 请求原因只写固定枚举；控制文件不记录 SSH 原文、主机、用户、作业、研究对象或批准信息。

### 3.2 配置重读

- 只优化单个 run_clusters 调用的内存状态；不全局缓存，不影响其他 CLI 命令和 submit 的配置读取。
- 每次循环仍检查配置文件元数据。以设备/文件身份、大小、mtime_ns、ctime_ns 识别变化；变化即重新 load_config。另以 monotonic 时间至多每 30 秒强制完整重读一次，覆盖元数据未变化的写入。
- 成功加载前后文件元数据不同，不把本次加载标记成稳定缓存；保留最近有效配置并在下一轮重试，给原有配置重读警告。
- 读/stat/解析失败保留最近有效配置和警告；恢复后正确清除警告。缓存不得让错误被永久记住；修复后不要求重启。
- 无 _config_path 的内存调用仍不读文件。单集群、多集群、自定义文件路径、增删入口、修改间隔、同群限额更新保持原语义。
- 保留至多约两秒的本地唤醒、每 30 秒心跳、串行 SSH、手动请求取下一空闲时刻、退避/暂停规则。30 秒兜底不承诺正在执行慢查询时能中断它。
- 不引入文件监听依赖、新配置项、跨进程缓存或定时 SSH。若处理变化必须迁移 studies_root/控制根，停止报告，不顺带实现跨根迁移。

## 4. 不允许

不通过删除暂停、重启监控或换连接消除故障；不自动重试 SSH；不把拒绝/丢弃算成功采样；不改变一般失败退避、Mac 确认、节点或提交额度；不改真实配置、常驻服务、研究状态。T151 前端实现另一个 PR，不塞进本单。其他遗留和版本发布不在范围内。

## 5. 测试

| 场景 | 预期 |
|---|---|
| 旧 CLI 默认四字段与退出码；新 --track 参数组合 | 旧调用逐项兼容，错误组合不登记、不 SSH |
| 连点 queued/already_queued；采样中 in_progress | 稳定标识、只采样一次、合并原结果 |
| 同秒两个依次完成的请求、其他入口/其他定时快照 | 标识不混淆，不误完成 |
| 登记后暂停 / 入口移除 / 本入口配置变化 | 可读取对应 discarded 原因，无额外 SSH，无假快照 |
| 重启时 queued/running、旧无标识请求 | 不重放；新格式有原因，旧格式保留原清理摘要 |
| 无监控、坏心跳、未知入口、缺锁、符号链接 | 原拒绝行为，不创建多余缓存或请求 |
| 状态写失败、请求删除失败、采样/快照发布失败 | 不伪报终态、不自动重试，不出现第二次执行 |
| 终态保留后正常定时采样；后续新请求 | 定时采样不覆盖终态；新请求可替换最近状态 |
| 未变化配置反复本地唤醒 | 不每两秒 load_config；30 秒兜底重读可测 |
| 原地编辑、原子替换、相同大小、元数据变化 | 下一循环识别，变更成功后更新缓存 |
| 元数据保持不变、加载中变化、坏配置再恢复 | 兜底/不缓存不稳定读取；保留有效配置并恢复 |
| 单/多入口、自定义配置、共享额度、配置增删 | 原语义与 T148 保持，警告不吞失 |
| 空闲循环只有请求丢弃、没有采样 | 状态可读；必要的匿名控制摘要及时输出，不伪造采样 history |

使用假时钟、假 Transport、本地临时控制文件，检验调用次数与状态，不运行几分钟的真实睡眠。推送前一次 `PYTHONPATH=ag/src python -m pytest ag/tests skills-next -q -rs`，之后以 CI 为准。

暂存精确文件后执行 `python scripts/scan_public.py --staged --terms-file <PRIVATE_TERMS_FILE>`、`git diff --cached --check`，人工核查公开内容与 noreply 身份。

## 6. 真实环境验证

无需新增 SSH 或真实计算。本单只修改本机控制与重读，不改远程命令、提交/状态/取回入口。使用独立临时目录、合成配置、假 Transport 和假时钟，走真实本地锁、请求、状态文件及 run_clusters 循环；验证一次请求对应一次采样，默认 CLI 和追踪 CLI 都有覆盖。

当前 CLI 只读取默认配置，不能发明 --config 或通过修改 HOME/正式配置隔离测试。测试通过已有 Python API/可注入对象与 CLI 的配置替身装配，不写常驻包装脚本，不启动第二个真实 watch。

正式服务现场观察由后续部署单安排；PR 明确“未新增现场查询”。如必须改远程或提交/状态/取回入口，停止重新确定范围与合并前真实验证，不能视为本单已授权。

## 7. 停止条件

需要更改远程命令/认证策略；必须迁移控制根；需要范围外文件或新的通用队列框架；与 T151 字段不一致；同一问题两次仍未解决；现场意外。记录实际阻塞。

## 8. 合并前审阅与交付

逐行审阅锁内顺序、磁盘失败路径、旧默认响应兼容和配置缓存失效；PR 给准确 HEAD、字段样例（合成）、每个原因的测试覆盖、真实验证状态和扫描结论。读取并处理监督评论，负责人合并。

T148 先合并；T149 再合并；T151 合并前按 T149 最终字段核对并同步两张工单。任何共享字段调整须两边一致，不创建新的独立格式合同文档。T150 共享文档最后 rebase。

## 9. 版本记录

- v1.0：负责人选择本批同时补前端反馈，增加与 T151 的最小追踪接口；保留旧默认四字段协议。

## 10. 实现与验收记录

本单只实现本地控制与重读。共用字段块与 T151 v1.0 逐字一致，没有修改共用字段；前端实现和配套验收仍由 T151 完成。
本单在 open-tasks.txt 原本没有待办行，不新增已实现项，也不修改其他任务标记。准确最终 HEAD、全量测试和 CI 结果在 PR 描述记录，避免文件自引用提交号。

| 验收项 | 可复现证据（全部为合成离线测试） |
| --- | --- |
| 默认四键、退出码、--track 组合 | test_cli_tracking_shape_and_refusal；test_track_combinations_fail_before_config_or_io；test_cli_request_through_real_watch_loop |
| 连点与并发、采样中合并、同秒不同请求 | test_concurrent_clients_share_one_id；test_tracking_merges_real_sample_and_preserves_terminal；test_two_finished_requests_in_same_second_are_distinct |
| 认证/主机指纹暂停后丢弃、不提升旧请求授权 | test_queued_then_paused_has_reason_without_authorization_upgrade |
| 入口移除、本入口变化、共享额度不误判 | test_reload_discard_precedes_rebuild_and_preserves_real_history（removed/connection/interval/peer_cap） |
| queued/running 重启不重放、已移除入口、旧请求 | test_restart_discards_tracked_state_without_replay；test_restart_covers_removed_entry_from_previous_watch；test_startup_cleanup_untracked_records_has_no_invented_id |
| 缺监控/坏心跳/缺锁/未知入口/来源错配 | test_retry_without_live_monitor_leaves_files_unchanged；test_unknown_retry_entry_never_creates_cache；test_source_marker_follows_actual_layout_and_mismatch_refuses |
| 状态发布、请求持久化或删除失败 | test_status_publish_failure_never_acknowledges_or_reexecutes；test_atomic_status_failure_preserves_old_bytes；test_request_persistence_failure_has_no_queued_response；test_request_unlink_failure_preserves_claim_and_cannot_execute_twice |
| 采样、latest/history 发布失败不伪报完成 | test_run_failure_leaves_running_status_without_second_sample |
| 正常采样不覆盖终态、新请求替换、其他入口隔离 | test_tracking_merges_real_sample_and_preserves_terminal；test_other_entry_sample_cannot_finish_queued_request |
| 损坏、未知版本、符号链接、2 MiB、附加键 | test_invalid_status_cannot_be_merged_or_claimed；test_status_read_failure_keeps_snapshot_and_request；test_track_cannot_claim_unknown_or_old_capability；test_unknown_extra_status_fields_are_ignored_not_republished |
| 两秒唤醒、30 秒兜底、仅单次调用缓存 | test_reload_cache_wakeup_count_and_thirty_second_fallback；test_reload_cache_fallback_catches_metadata_preserving_change |
| 原地/等长编辑、原子替换、全部五项元数据 | test_reload_cache_detects_file_identity_and_metadata；test_reload_cache_checks_each_signature_field |
| 读取/stat/解析/不稳定读取失败及恢复 | test_reload_failure_retains_config_and_recovers_without_metadata_change；既有 test_reload_add_remove_invalid_and_recover |
| 单/多入口、自定义配置、无路径配置 | 既有 test_single_reload_custom_file_and_timeout_then_recovery；test_selected_custom_config_preserves_binding_on_reload；test_in_memory_reload_never_reads_file |
| 空闲丢弃摘要、无假 history、根变化停止 | test_reload_discard_precedes_rebuild_and_preserves_real_history；test_removed_marker_never_appends_sampling_history；test_changed_control_root_stops_before_migration_or_second_sample |

状态只保留已知字段，未知附加字段不复制到下一次写入。运行中断后 running 的 monitor_restarted 表示没有可确认的发布完成结果，不能推断远端从未被查询。
移除入口只更新本地移除标记；已有有效快照的 sampled_at/last_ok_at/ok 保留，缺失或坏快照的标记 sampled_at 为 null，没有新采样 history。
真实验证边界：以配置替身装配 CLI，假 Transport、假时钟走真实本地锁、原子请求/状态文件和 run_clusters；**未新增现场查询**。未启动第二个真实 watch、未修改正式配置或常驻服务、未部署、未提交计算。正式服务现场兼容由后续部署单验证；离线通过不替代该验收。
