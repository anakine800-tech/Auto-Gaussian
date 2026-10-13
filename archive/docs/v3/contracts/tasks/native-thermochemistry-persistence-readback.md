# Auto-G16 原生热化学第三包合同 r2（待准确边界冻结）

任务：`NATIVE-THERMO-ADAPTATION-03 / PERSISTENCE-AND-READBACK`。
分类：feature development，OWNER-GUIDED、non-BUS、L2。
基线：main `23da24c4ec240dc65a0c2333780af9b6ea5f193a`，tree `fc2e42c0bb95d6d54cb475199ffbeacf6cddd257`。
分支：`codex/native-thermo-readback`，独立 linked worktree；开发 preflight 通过。

Owner 已要求冻结第三包合同、实现保存与回放、随后接入原生页面并安排安装和浏览器验收。这些开发步骤保留授权，不再请求同一一般开发许可。本文把此前未定义的持久化格式、写入语义和可信摘要来源具体化；状态为 `PROPOSED_FOR_EXACT_CONTRACT_DECISION`，不能把本文自行写成已获 Owner 接受的决定。准确边界接受后继续离线实现、验证及独立审阅。真实材料操作、发布/合并、安装切换和科学验收按各自准确范围另行绑定。

## 1. 结果、范围与复用

保存第二包产生的 exact tuple `(ConformerEnsemble, ThermodynamicEnsemble)`，在新进程中恢复相同不可变对象及完整身份；保存与重读都不调用 GoodVibes，也不重新计算 raw RRHO、qRRHO、布居、分区函数或整体自由能。

沿用第二包已冻结的全部支持域和来源要求：两个完整、顺序固定的 canonical n-butane 成员、相同 profile、Opt/Freq minimum authority `/2`、parser `1.2.0`、相同方法与完整显式参数、有限且非穷尽采样范围。本文不扩大分子、方法、成员数或科学用途。

复用两个现有公共模型、`FreqReadout` 完整来源重放、来源 facts helper、纯资格派生函数及可信启动的 `_PublisherFileBinding` / `_PinnedPublisherFile`。不新增科学记录类，不改 Core/Transport SQLite schema，不将热化学产物伪装成新的 Gaussian Result，不接通 legacy `final_integration`。

一个文件包含一对完整对象，杜绝分别保存/读取两个版本再拼接。它是未安装的本地不可变候选材料，不能仅因文件存在就成为原生查询来源或 ScientificAcceptance。

## 2. 闭字段文件格式

版本 `auto-g16-native-thermochemistry-pair/1`，UTF-8 canonical JSON；编码为 `ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")`，无 BOM、无结尾换行。文件上限 16 MiB。

顶层字段恰为：

- `schema`：上述版本。
- `request`：第二包 `_normalize_request` 返回的完整规范化 request，转为既有 plain JSON 形状；不补默认值。
- `qualified_conformer_ensemble`：闭字段 `{conformer_ensemble_id, payload_sha256, payload}`，payload 为该 exact ConformerEnsemble 的完整 `_identity_payload()`。
- `thermodynamic_ensemble`：闭字段 `{thermodynamic_ensemble_id, payload_sha256, payload}`，payload 为该 exact ThermodynamicEnsemble 的完整 `_identity_payload()`。

不另增 pair 科学 ID、数据库记录、时间戳或审批 token。整个文件的 SHA-256 是外部物理 binding 的 `sha256`；它与两个模型自己的 payload hash 不混用。source/profile/有限采样说明由完整 request、qualified audit 和 thermo provenance 保留，无需另造摘要对象。

request 必须与 qualified 的最后一条 `native_thermochemistry_eligibility` audit 中的 request payload、ID/hash 完全一致。两个模型先验证自己的 canonical 身份再编码；解码时拒绝重复 JSON 键、非有限数值、未知/额外/缺少字段、非规范 UTF-8/JSON 字节及超限文件。

request 解码须先验证 `source_member_ids` 和 `member_policies` 均为 JSON array，仅将这两处列表分别恢复为 tuple，再调用既有 `_normalize_request`。规范化后的完整 plain request 必须与文件原值逐项相等，并保持整体 canonical 字节一致；不接受字符串代列表、隐式成员排序、数值/布尔转换或其他自动修复。

按模型现有字段白名单恢复对象，不把任意字典透传给 `_create`。特别明确把 `source_member_ids` 恢复为 tuple；嵌套容器沿用现有 freeze 规则。重建后逐项比较 plain 完整 identity payload 和两个 ID/hash，不能让工厂静默忽略字段、重设 schema_version 或改变布尔/整数类型后仍接受原文。

## 3. 可信摘要及保存入口

新增私有 owning module `auto_g16/conformer/thermochemistry_readonly.py`，不加入公共 `__init__` 导出。拟固定接口：

```python
encode_native_thermodynamic_pair(pair) -> bytes
save_native_thermodynamic_pair(
    readout, *, pair, expected_sha256, destination
) -> _PublisherFileBinding
NativeThermodynamicReadout(readout=..., artifact=...).read() -> tuple
load_native_thermodynamic_readout(content: bytes, digest: str)
```

`pair` 必须为 exact tuple、长度 2、成员必须为两个 exact 模型类；`readout` 必须为 exact FreqReadout。编码器只做确定性编码及局部身份/形状验证，不授予保存或计算真实性。

`expected_sha256` 是可信本地调用方在保存前独立固定的文件摘要：从工程验收已接受的计算证据中取得完整两对象，用本节编码器离线确定字节，再在准确保存方案中绑定其摘要、source/request 身份和目的地。这里的证据接受不等于 ScientificAcceptance 或扩大科学用途。现有私有验收文件不得自动当作新格式的已注册产物；可以准备显式转换方案，逐项核对完整对象后再取得保存许可，无需重新计算。

保存函数重算来件文件摘要仅用于与外部预期摘要比较，不能把自己的计算值提升为外部预期。HTTP/查询参数不得同时选择来件、路径和所谓可信摘要。自洽模型 ID/hash 不能证明数值由 GoodVibes 产生；数值真实性来自此前独立接受且固定的计算证据。可信启动配置及其批准范围属于信任边界，修改该配置不是数据文件本身的篡改测试，也不能静默重新登记改变后的 hash。

`destination` 是新私有 frozen `_NativeThermoDestination`，闭字段为 `path` 和 `directory_chain`。path 是受审本地现有目录的规范绝对路径；directory_chain 是从 `/` 到该目录（含目录本身）的每一级 `(st_dev, st_ino)` exact tuple。不允许请求参数/环境变量选择目的地，不创建目录，不自动选 latest，不扫描目录。叶名唯一确定为 `native-thermochemistry-<expected_sha256>.json`。

## 4. 写入和失败语义

保存获取既有 `_OPT_READ_LOCK` 一次，沿用 30 秒等待，完整来源重放并执行第 5 节关联验证。验证失败、摘要不符或已有目标应在写字节前失败。所有来源 pins、只读连接、snapshot、receipt context 与锁保持到写入及退出验证结束。

目的地逐段 `O_RDONLY | O_NOFOLLOW | O_DIRECTORY` 打开、核对配置中的名字与 fd 身份并保留 descriptors。通过最终目录 fd，以 `O_RDWR | O_CREAT | O_EXCL | O_NOFOLLOW`（以及平台支持的 `O_CLOEXEC`）创建唯一叶名，权限 0600；禁止 `O_TRUNC`、replace、覆盖、删除或自动重试。已有任何文件/目录/symlink 都拒绝，即使内容相同。打开后确认 regular file 和同一物理身份，处理短写，fsync 文件及父目录，通过同一 retained fd rewind 后读回完整字节/hash，再核对目录和叶名的物理身份；不能重开叶路径代替该验证。

这是“成对封装、排他创建、完成后才可注册”，不是声称断电原子替换：短写、异常、同步失败或写后来源退出失败可能留下不完整或未接受文件。保留该文件和错误证据；不返回成功 binding、不登记、不重试、不清理，也不自动把已写入当作成功。

只有写入、读回、目录身份以及全部来源退出检查成功，且资源释放成功后，才返回 detached `_PublisherFileBinding`。该 binding 包含准确 path、parent_chain、file_identity、sha256、size_bytes；它仍不自动修改 startup registry。初始化异常、BaseException 和关闭异常都必须释放已打开资源并整体失败，不返回部分对象或 success binding。

## 5. 只读回放和成对关联验证

`NativeThermodynamicReadout` 只由可信本地启动构造，成员为 exact FreqReadout 和 exact `_PublisherFileBinding`。`read()` 无外部路径/参数；固定文件 pin、既有读锁与完整来源上下文保持到验证结束，所有退出检查通过后返回 detached exact tuple。读取缺依赖 GoodVibes 的 core 环境也应成功；不导入 `goodvibes` 或加载其 kernels。

`load_native_thermodynamic_readout` 解码另一闭字段启动格式：`{schema, frequency_registration, artifact}`，schema 为 `auto-g16-native-thermochemistry-readout-registration/1`；后两项沿用现有 `_PublisherFileBinding` 的五字段 plain 形状。文档 cap 1 MiB，外部 digest 固定文档字节；duplicate keys/未知字段拒绝。仅 pin 指定的 frequency registration 文件并将其准确字节及绑定 digest 交给现有 `load_freq_readout`，不搜索其他来源。随后构造 owning reader。启动格式不通过 HTTP 传入，不自动生成/安装。

保存与重读共享以下纯关联验证；不调用旧 compute builder、不调用 `_finish_thermodynamic_ensemble` 或 legacy final integration 来重新求数值：

1. 在 `_replayed_frequency` 内重新取得完整 profile、原始 refined 及 Opt/Freq 输入；调用 `_native_input_facts_from_replay` 验证来源 facts。
2. 用完整保存 request 调用既有 `_normalize_request` 和 `_qualify_ensemble`，纯重建 expected qualified；与保存 qualified 的完整 payload、ID/hash 逐项相等。这是来源资格核验，不是热化学重算。
3. thermo 的 conformer ID/hash/revision 必须等于 qualified；`source_member_ids`、member observations 的数目和顺序必须等于全部 canonical eligible，不能接受子集、重复或跨成员拼接。
4. 每个 observation 的 minimum authority、native source/result、thermo facts、request ID/hash、source/profile binding 逐项等于本次完整来源 facts 和 request；method ID/binding、温度、标准态、degeneracy/rationale、inclusion status 与第二包生成规则完全相同。
5. 复用 `_policy_identity`、`_implementation_binding` 和 `_standard_state_binding` 的纯语义，验证 thermo policy、实现身份、低频政策、标准态与单位/常数绑定。准确采用基线内核已校验的 `GAS_CONSTANT=8.3144621`、`J_TO_AU=4.184 * 627.509541 * 1000.0`，以及既有 `_service._POPULATION_TOLERANCE=1e-12`。允许使用上述相同表达式核对单位绑定及标准态，不加载 GoodVibes、不引入另一套可选常数、不重新计算热化学或分区结果。通过兼容测试约束这些核验值与基线生成行为一致，旧内核文件不改。
6. 数值字段保持原样，只做 exact 类型、finite、闭字段/单位与范围检查：禁止 bool 代数值、布居必须位于 [0,1]，既有 normalization status/tolerance 字段形状和常量必须合法；不重新生成 raw/qRRHO、布居、整体 G，也不把保存值回灌计算器充当独立 oracle。
7. fixed file hash/pin 失败、source/request/profile 漂移、全部成员来源不闭合或任一退出检查失败，整体拒绝并释放全部资源。不能返回历史值兜底、空成功值或部分集合。

共享实现允许对 `_native_service.py` 机械抽取“方法/成员 provenance/政策关联期望”纯 helper，旧 builder 和新 reader 使用同一份字段规则；不改变旧 builder 输出或 numerical helper。以完整 payload/ID golden 验证提取前后等价。

## 6. 允许路径与兼容性

第三包新增 `auto_g16/conformer/thermochemistry_readonly.py` 和 `tests/v31/conformer/test_thermochemistry_readonly.py`。允许限定修改 `auto_g16/thermochemistry/_native_service.py` 的纯 helper 提取，及 `tests/v31/thermochemistry/test_core.py` / `tests/v31/conformer/test_successor_freq.py` 的相邻兼容测试或合成 fixture 复用。

治理改动限本合同、Owner 真正接受后记录的 `OWNER_DECISIONS.md`、现有 `config/context-map.toml` / `config/validation-selection.json` 的准确路径登记。不得降低 selector、新增 full owner、改 required contexts。

禁止改变模型/schema_version、公共导出、Core/Transport 存储、Result/parser、FreqReadout 历史返回值、旧 reader/legacy final_integration 支持域、GoodVibes 内核/常数/依赖、真实源库、HTTP/UI 或已安装运行环境。

## 7. 离线验收与准确本地证据

| 检查 | 必须证明 |
| --- | --- |
| 成对 round trip | 合成完整 native 来源生成一对对象；独立固定 canonical 字节摘要；save 后 fresh process 读取的两个完整 payload/ID/hash 与原对象一致 |
| 零重算 | save/read/load 在 GoodVibes 导入拒绝、kernel loader/functional kernel/aggregate builder 调用即失败的环境中仍完成；包括新进程 |
| 成员与参数 | 缺/重复/乱序成员，另一 qualified/thermo、request/profile/方法/T/标准态/cutoff/scale/简并度任一拼接均拒绝 |
| 字节与信任锚 | 篡改 artifact、重算内部模型 hash、改文件/父目录身份均被固定外部 binding 拒绝；错误 expected digest 在创建前失败；外部“预期 hash”不会从来件自动填充 |
| 格式闭合 | duplicate key、额外/缺少字段、非法 schema、BOM/非 canonical bytes、非有限数值、bool/int 混淆、mutable/list 恢复错误、超限均拒绝 |
| 来源生命周期 | 读取期间仍持有锁/pins/四个快照；原库/材料/parsed revision 修改或替换、末端退出失败、并发 busy 均整体失败；成功与异常资源全部关闭 |
| 排他写入 | 现有普通文件/目录/symlink、目录替换、叶名竞争、短写、fsync/关闭失败、写后来源漂移：无覆盖，无成功 binding，无自动重试/删除；残留文件保留且未注册 |
| 历史兼容 | 旧 compute 与 reader 完整身份/输出不变，原来只读入口不获取写权限；已保存 tuple 不被修改 |

preflight → focused/affected → 静态与 CI/Python contract → 冻结候选 L2 独立审查 → selector 指定完整证据/远端 CI；不为不变字节重复 full。所有实现测试使用合成材料和显式新建测试目的地，真实数据不得进入 Git。

本包写文件及 filesystem/SQLite 生命周期是生产可达行为。合并分类时必须准备准确本地 native 验收：使用已接受计算证据转换得到的固定 pair、受审新目的地、一次保存、fresh-process 零重算读取、源库与资源退出核对及失败残留策略。先给出完整路径/hash/调用次数/上限再执行；上一包 300 秒真实计算窗口已经消费，不能重用，也无需因此再调用 GoodVibes。真实保存/注册尚未发生。

## 8. 后续原生页面与安装安排

Owner 的页面目标保留在下一包 `NATIVE-THERMO-ADAPTATION-04 / READONLY-PROJECTION`：在第三包 owning reader 完成后绑定 query DTO、HTTP 边界与前端精确基线，建立独立 worktree/PR。不得直接把 native provenance 塞入 legacy final_integration 或覆写当前 Gaussian-reported thermochemistry 字段。

页面应分别展示：Gaussian 原始报告值、保存的 raw RRHO/treated qRRHO、成员 treated G 和布居、整体 treated G、单位、T/标准态/cutoff/scaling/degeneracy、有限采样说明及来源/结果身份。读失败显示明确 unavailable，不显示 0、成功空表或触发计算。列表与详情相同 owning reader，GET 不提供计算/保存动作、不接受磁盘路径。

前端是另一仓库；基线、实际 loader、启动配置和安装包必须另行核对，不能改共享目录中的未跟踪本地文件或用旧源码替换较新安装。先准备隔离合成浏览器预览、静态资源/DTO/兼容性证据和可回退安装 diff，再绑定准确安装及真实只读浏览器验收窗口。当前合同不授予部署、真实 startup 注册或新科学计算权限。

## 9. 待 Owner 冻结的三个具体决定

1. 采用单个 canonical JSON pair artifact 和既有两个模型；不增加 Core 数据库 schema。
2. 保存已有 exact tuple，独立可信摘要在调用前固定；保存/重读均零 GoodVibes 和零热化学重算，数值真实性继承自已接受计算证据。
3. 采用排他创建、完成后才返回可注册 binding；失败残留保留且不自动重试，第三包只实现 owning 保存/回放，页面按第 8 节随后接入。

接受这些准确边界后，已有开发授权继续覆盖离线实现、验证和独立审阅，不再次索取相同授权。发布、合并、真实材料保存/登记和安装仍按准确产物准备具体交接。
