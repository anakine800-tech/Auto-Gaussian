# R3 附件：首次选择、版本轴与可实现的私有 Q 结构

**精确结构候选，未获 Owner 冻结；不是真实资格或 production 权限。** 本文与 [R3 接口补丁](publisher-pilot-candidate-r3-interface-delta.md)共同回应独立 R2 审阅 P1-1/P2-1/P2-2；没有读取或依照未经审阅的 prototype 定义合同。

## A. 首次创建与持久重放是不同入口

**首次创建：** 保留现有 `_prepare_completion_rendering_material(current_profile, resolved_profile)` 的历史默认，只生成 material `/1`，profile 中出现 Q 也不自动升级。拟增加私有 `_prepare_publisher_pilot_rendering_material(current_profile, resolved_profile)`，其唯一分支是 material `/2`，要求精确 Q bytes 与 profile identity 闭合；此纯 builder 不判断人工资格、不产生授权。只有显式选用该新 builder 才构造新材料。现有 snapshot 私有 material 参数接收哪个完整闭合版本就选择对应内建分支；没有新的公开 qualified/production bool、环境开关或按 executable path 自动升级。

**重放：** 只由持久 scheduler 的固定头与唯一 data line 读取 material schema，匹配下表完整 tuple 后选择内建 source，重建 B/script/snapshot/receipt expected identity。不读 current Q 决定版本，不按 receipt 自报 source hash 选源码；未知/错配/降级拒绝。创建和重放共用同一 tuple 表，但首次创建不读取尚不存在的 artifact。

| 使用路径 | adapter | scheduler | material | B | receipt schema | ProgramTransportStore | completion proof | 行为 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 既有 strict xTB | 历史 v1 replay / v2 默认 | 原 strict `/1` | 无 | 无 | 不使用 completion receipt | `/1` | 原 strict proof `/1` | 原合法行为不变，不要求 Q；v1 不变成可新建。 |
| 现有合法 synthetic receipt v3 | v3 | `/2` | `/1` | `/2` | `auto-g16-v31-program-completion/1` | `/2` | receipt completion `/2` | **完整原离线执行、collection、assessment、transition、合法replay/proof 路径保持，不要求真实 Q 或 pilot 附件。** |
| 原 C2/C3 `/1` store 中的 receipt 历史 | v3 | 原持久值 | 原持久值 | 原持久值 | 同上 `/1` | `/1` | 不获 C4 completion/proof | raw-readable；C4 collect/reduction/replay-completion/promotion 拒绝。store `/1` 不能误读为 receipt schema `/1`。 |
| 未资格化的旧真实 receipt v3 | v3 | `/2` | `/1` | `/2` | 同上 `/1` | `/2` 也不能补资格 | 无生产可接受 proof | 生产 construction/evaluation 禁止不变；后来安装 Q 不能追溯升级。 |
| 新 production pilot 候选 | v3 | `/3` | `/2` | `/3` | 同上 `/1`，不增加 host 字段 | `/2` | receipt completion `/2` | Q/固定安装附件/三批准/actual-host guard 接口齐全并经后续真实 Gate 才有资格；当前全部 hard stops 保留。 |

旧 source 固定 14181 bytes/SHA `58167de5436ec2d5ae9ef89dde458f386cdc2860f4f00a41c81c0a390f782333`；新分支使用另一个内建 source，hash 待新 source 冻结，不能覆盖旧常量。历史 synthetic v3 的 source/identity reconstruction 与合法 completion 不检查真实 Q。新增资格检查**仅针对新生产 effects/生产 completion 接受**；新分支的测试替身仅存在离线 harness，不因合成 Q 满足语法获得 production driver。

## B. 精确结构记法及全局边界

以下每个对象仅允许列出的键；所有键必需，除明确写明以外不允许 null。对象外键、重复 JSON 键、NaN/Inf/float、bool冒充integer、无效 UTF-8/BOM、超界/非 canonical bytes 均拒绝。固定结构版本未知也拒绝。`NOT_ACQUIRED` 仅可出现在**无效的制包模板/报告**，不得作为有效 Q 字段值。

- `H`：64 个小写十六进制 SHA-256；`G`：40 个小写 Git object ID；`S`：1–256 个 UTF-8 字节，无 NUL/CR/LF/首尾空白；`U`：canonical 小写 UUID 文本。
- `I`：精确非负整数 ≤ 2^63−1；`P`：精确正整数 ≤ 2^63−1。`T`：固定 27 字符 UTC `YYYY-MM-DDTHH:MM:SS.ffffffZ`，真实日历有效。
- `Path`：绝对 POSIX 路径，UTF-8 ≤4096 bytes，无 NUL/CR/LF、`.`/`..`、内部空组件及非根尾斜杠；不 resolve symlink 为可接受别名。
- `Digest={sha256:H,size_bytes:P}`；`Node={device:I,inode:P}`；`File={path:Path,sha256:H,size_bytes:P}`；`Window={started_at:T,finished_at:T}`，start≤finish。
- 单 Q 信封 canonical 文件 ≤1 MiB；JSON 嵌套 ≤16；host 数 1–32；单 chain ≤128 节点，必须覆盖 `/` 到所声明 path 的所有词法组件。更大规模不截断，明确不受首 pilot 支持。新 material `/2` canonical JSON ≤5 MiB，Q base64 解码 ≤1 MiB、其他两个 manifest 各≤1 MiB；旧 material `/1` 原3 MiB限制不变。base64 必须 canonical padded RFC4648。
- 字符串数组按 UTF-8 字节序排序且唯一；未另声明的数组保留规范顺序，不允许自行重排。所有 set equality 必须完全相等，不能用 subset 放行。

## C. Q 信封和逐层 payload

`Q={payload:Payload,payload_sha256:H}`。payload_sha256 使用当前 Execution `semantic_sha256` 对不可变 typed mapping/list 投影计算；hash不在其自身preimage内。信封普通文件 SHA/size 用于 profile/runtime 和摄入；不把两个 hash 混用。

`Payload={schema,contract_sha256,scope,implementation,profile_basis_sha256,runtime,execution_domain,hosts,observation_window,evidence_manifest_sha256,controller_probe}`：

| 字段 | 闭合定义 |
| --- | --- |
| `schema` | 固定 `auto-g16-v31-publisher-qualification/1`。 |
| `contract_sha256` | H，未来 exact 受审规范包的 hash；包清单固定本接口文档+本附件的文件hash，不含其自身hash或Q。 |
| `scope` | `{backend,program_kind,adapter_id,adapter_contract_version,completion_mode,operations}`；依次固定 `legacy_rtwin_pbs`、`xtb`、`auto-g16-v31-xtb`、整数3、`receipt-on-absence-v1`；operations固定数组 `["optimize","single-point"]`。 |
| `implementation` | `{commit:G,tree:G,wrapper_source:Digest,probe_source:Digest}`；必须与已审部署源及内建新source/probe精确匹配，不能据该字段选择/执行任意代码。 |
| `profile_basis_sha256` | H；完整 resolved `identity_payload` 去掉派生 effective_config_sha256，且仅从runtime_identities排除固定 `v31-publisher-qualification-v1.json` 后的 `semantic_sha256`。其他值包括先选定的新 profile revision 全保留。 |
| `runtime` | `{deployment_manifest:Digest,server_python:File,xtb:File,xtb_runtime_data_manifest:Digest}`；manifest必须是当前闭合manifest-v3；Python等于其trust root、xTB等于spec invocation和profile identity、data等于profile规范manifest。 |
| `execution_domain` | `{target_identity_sha256:H,remote_user:S,remote_root:Path,queue:S,eligible_host_keys:[H],scheduler_scope_evidence:Digest}`；hostkeys排序唯一，等于hosts集合；target hash=`semantic_sha256(resolved_profile.target_identity)`；user/root/queue分别精确等于profile及snapshot资源。无隐式queue/null或通配主机。 |
| `hosts` | 1–32 个下述 Host，按host_key排序唯一。 |
| `observation_window` | Window；包含每个Host的observed_window，均由可信采集原始记录核对，不由Q自述证明。 |
| `evidence_manifest_sha256` | H；完整资格原始证据清单。所有下述 evidence digest 必须按精确原字节能在该受信清单中定位并一致。 |
| `controller_probe` | 下述 Probe，case_id固定P08；只需一份，测试的是固定来源摄入/编排，不冒称各计算节点运行Controller。 |

`Host={host_key,machine_id_sha256,boot_id,kernel_release,architecture,namespaces,locations,observed_window,identity_evidence,probes}`：

- `machine_id_sha256:H`：实际节点 `/etc/machine-id` 原始 bytes SHA，读取点与信任来自认证节点采集；`boot_id:U`：`/proc/sys/kernel/random/boot_id` 的UUID，允许输入原文件单LF但Q存无LFcanonical值。`host_key=semantic_sha256({machine_id_sha256})`；同一key不能出现两项，不把hostname环境变量当身份。
- `kernel_release:S, architecture:S`：与实际节点 uname 采集一致；`namespaces={mount:Node,pid:Node}`：受信Linux procfs `/proc/self/ns/mnt` 和 `/proc/self/ns/pid` 指向的kernel namespace身份。只对这两个固定kernel入口取得所指对象身份，不扩大一般no-follow允许范围。队列实际namespace无法以已授权方式观察时不合格，不能编造预期值。
- `locations`：固定顺序四项 Location，role分别 `workspace-root,server-python,xtb,xtb-data-root`。`Location={role,path,parent_chain,object,mount,evidence}`；path:Path，parent_chain:[Node]从根到path父目录，object:Node为该path本体，evidence:Digest。工作root等于profile.remote_root；Python/xTB path等于runtime对应File；data-root等于profile.xtb_data_path。
- `mount={mount_id:P,device_major:I,device_minor:I,root:Path,mount_point:Path,filesystem_type:S,source:S,mount_options:[S],super_options:[S]}`：选自该真实namespace的 `/proc/self/mountinfo` 中覆盖Location的唯一最深挂载点；options各最多64项、排序唯一。逐项比较，不能只比f_type或设备号。source字段为mountinfo已解码单个来源字段，长度≤4096 bytes且无NUL/CR/LF，可不是绝对路径。该项特例覆盖S的256-byte上限。
- `observed_window:Window, identity_evidence:Digest, probes:[Probe]`；probes固定七项P01–P07按case_id顺序。它们在该host的实际root/mount/namespace及runtime身份下取得；相同名字的登录节点记录不可复用为计算节点身份。

实际 wrapper 在launch/publication两边各采集上述machine/boot/kernel/architecture/namespaces/locations与runtime files，必须精确匹配Q中唯一Host。workspace-root的Q身份不替代fresh Attempt本身：Attempt后缀另按原snapshot workspace+完整no-follow链校验。Q mismatch最多形成拒绝/未知，不能构造rc或成功receipt。

## D. 固定强制 probe inventory

`Probe={case_id,outcome,evidence,observed_window}`；case_id为下列枚举，outcome固定 `PASS`，evidence:Digest，observed_window:Window且在所属host/window内；P08在总window内。Q是全部案例确定成功后的qualification候选；失败/未知/跳过原记录留在外部清单，不能用缺行/null/改枚举生成有效Q。

| case_id | 每一列的子条件均须有证据，不是任选其一 |
| --- | --- |
| P01 | actual父链no-follow正常；父链/文件symlink、replacement、same-byte新inode拒绝；保留原对象，无越界读写或删除。 |
| P02 | launch marker/log/pending/final预存在均拒绝；并发publisher至多一个launch和一个publication winner；无覆盖。 |
| P03 | Linux subreaper设置并读回；真实adopted child/grandchild；waitpid回收全部后代后才允许出版；direct child status不被后代状态替代。 |
| P04 | launch失败、nonzero、signal、wait失败、后代存活/超时、wrapper死亡；分别检查原定FAILED/UNKNOWN/无receipt语义，不能凭基础设施异常伪造program rc；自有进程按packet回收。 |
| P05 | actual mount descriptor-relative atomic link；已有final EEXIST；link前/后崩溃；pending身份漂移、log close/fsync/hash失败；零覆盖/删除及原证据保留。 |
| P06 | manifest-bound Python精确path/hash/size及 `-I -S -B`；`/proc/self/fd` executable语义；xTB/data身份对照；前后runtime替换拒绝。只用固定惰性child验证launch语义，不实际执行xTB。 |
| P07 | 新source host guard正常匹配；未知/重复host、错boot/namespace/mount/root/runtime；启动前拒绝零child，publication前拒绝零可接受receipt；未信名单不能放行。 |
| P08 | 受信部署expected与Q/confirmation附件一致；缺Owner原件、未信自签附件、错路径/物理身份/哈希、错三批准、调用顺序和非PLANNED重启均拒绝；首次资格失败零execute/claim/external effect；唯一execution owner惰性组合。 |

原始 packet 必须列每个子向量的有限输入/命令、解释器、host/namespace/mount、最大自有进程/时长/文件清单和终止回收动作；这些是执行前 Gate 的具体值，不是上述schema/清单尚未定义。Q只绑定其source/evidence，不执行其中命令。此处1MiB、32 hosts等是待审解析边界，不是已授权probe规模。

## E. 一次 pilot 确认附件与两个窗口

`confirmer_evidence.publisher_pilot` 仅含 R3 接口列出的10个身份/引用字段及 `pilot_window`，共11键。payload/file/清单/安装/Owner/LiveGate hash均H，qualification_size_bytes:P且≤1MiB，qualification_path:Path；qualification_parent_chain:[Node]覆盖root至父目录；qualification_file_identity=`{device:I,inode:P}`，另与size/hash同时检查；pilot_window:Window。外层 `confirmer_evidence` 保留既有其他证据键，不把整份通用 Approval mapping 强行收窄。

**观察窗口**说明真实资格证据何时取得；**pilot_window**是人批准允许此次新生产动作和评估的时间范围，不能互相替代。要求Q总观察finished_at≤pilot started_at，效果/新生产评估时可信当前UTC处在pilot窗口；窗口外或时钟可信性不明停止，不自动续租。窗口长度没有由解析器替人选择的默认值；实际起止须由Owner明确填写并绑定本次Confirmation/LiveGate。旧synthetic路径与历史raw/identity读取不受这个新窗口约束。中断/过期不删除既有状态或自动qdel，后续按原Gate另行核对。

## F. 最小入口/信任/失败表（P1 回应索引）

| owner/入口 | 输入与独立来源 | 检查时点 | 失败效果 |
| --- | --- | --- | --- |
| qualification reviewer/Owner与deployment操作者 | 原始probe、exact Q、人工接受；create-new固定部署expected附件及真实文件/三库身份 | 安装与明确人类确认之前 | 不安装有效资格、不自行生成APPROVED。 |
| `_run_first_publisher_pilot` | 固定部署包；从已绑定ApprovalStore加载三批准；不接受caller替换数据库或confirmed ID | 准备前与最终execute前 | 资格/附件/validator失败：零execute、零claim、零外部effect。 |
| `_RTWinProgramEffectDriver.__init__/_authority` | 固定部署expected原件 + current Confirmation附件 + Q/profile/material；复用既有store/confirmation对象，不信单份Q自述 | constructor、每个实际effect与生产评估边界 | preclaim失败零claim/effect；claim后漂移停止后续效果并保留先前claim/receipt，不能声称事后仍零claim。 |
| `execute_once` | 刚经validator确认的snapshot ID及exact私有port | 唯一新claim入口 | 现有WINNER/REPLAY/UNKNOWN语义不变，不由新script创建第二owner。 |

以上是对独立 R2 报告 1 P1 + 2 P2 的候选修复；是否关闭由独立复核判定。当前 auto_g16/冻结合同/CI/production hard stops 均未修改。
