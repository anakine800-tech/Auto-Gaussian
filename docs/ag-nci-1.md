# ag-nci/1：Multiwfn 非共价相互作用报告

`ag nci-report <Attempt 或其目录> --out analyses/<新文件>.json` 仅解析本地完整取回的
Multiwfn Attempt；ID 从本机 studies_root 查找，也可指定 `--study <本地 study 目录>`。
不创建 Transport，不修改 facts，不覆盖已有报告。未正常退出、错误版本/线程数、
缺文件、非有限数、格式不符、原子/片段映射或加和不符均报错；不接受不完整 fetch。

结果仅为相互作用的可视化与半定量分析，不是能量分解。IGM 使用前分子密度，
IGMH 使用 Hirshfeld 分区的实际波函数；原子对 δG 指数不能当作 kcal/mol。
多片段原子对指数之和也不等同于多片段 δg_inter cube 的空间积分。

## 输入及固定版本

仅 default PBS；`programs.multiwfn` 为可执行文件绝对路径或 `~/` 路径，允许空格，
禁止 shell 特殊字符与 `..`。兼容 `[programs.multiwfn] root = "<安装目录>"`，
此时执行该目录中的 `Multiwfn`。实际值只保存在本机配置，不进仓库。

固定 **2026.10.1 Linux noGUI**。菜单来自官方同版本手册 §§3.23.5、3.23.6、
4.20.10、4.20.11；命令行与设置文件见 §§2.2–2.4，Linux 栈建议见 §2.1.2。
按同版本官方源码 `visweak.f90` 核对 `atmdg.txt` 的完整字段与末行总和；
`Multiwfn.f90` 确认 `q` 为无文本结束语的正常 STOP。
官方资料入口：[Multiwfn](http://sobereva.com/multiwfn/)。

CSV 列固定 `fragment,atoms`，2–4 个片段按行编号，各原子恰好属于一个片段，覆盖全体系：

```csv
fragment,atoms
first,"1-3,7"
second,4-6
```

原子编号从 1 开始，必须与输入/父 Gaussian 的原子顺序一致；片段定义由人审核。
IGM 输入为 1–50 帧 XYZ，帧间原子数和元素顺序一致；XYZ 不含电荷/多重度，
确认摘要将这两项记为未提供，不能从坐标推断。IGMH 只接受正常结束的 Gaussian 父 Attempt，
复用其 chk，先取回父日志以核对正常结束、原子数、方法和几何预览。
IGMH 不接收单独 `--input`，实际几何从父 chk 读取；默认使用几何 Opt 层级波函数，
若显式选择单点父 Attempt，其实际 route 和来源会展示，是否适用由人审阅。

```text
ag prepare --study <id> --template multiwfn --analysis igm --grid medium --fragments <fragments.csv> --input <frames.xyz> --tier mini --walltime 00:30:00 --label igm --method-basis <已审阅依据>
ag prepare --study <id> --template multiwfn --analysis igmh --grid medium --fragments <fragments.csv> --parent <parent-id> --relation nci_from --parent-chk <parent-id>:<name.chk> --tier simple --walltime 01:00:00 --label igmh --method-basis <已审阅依据>
ag fetch <nci-attempt> --no-facts
ag nci-report <nci-attempt> --out analyses/<新报告>.json
```

`--no-facts` 跳过不适用于 Multiwfn 的通用 facts 解析；数据取回的大小/哈希检查照常执行。
普通 `fetch` 仍能取回数据，但自动 facts 会提示不支持此模板；随后使用 `nci-report`。

## 运行与文件

父 chk 沿用现有 `ag submit` 专用复制：人工确认后、qsub 前在新 Attempt 中独占创建，
复制前后核对来源与目标 SHA-256；不移动到计算节点内重新复制，不改变提交确认流程。
PBS 作业内 `formchk parent.chk parent.fchk` 使用 Gaussian 相同环境，随后运行固定菜单。
手册 §3.23.5 印刷页 306 明确：超过两个片段时，选项 6 必须选择两个片段；
`atmdg.txt` 和 `IBSIW.txt` 只含该对的定量指数。§3.23.6 印刷页 308 说明 IGMH 用法相同。
同版本 `visweak.f90` 的选项 6 分支还确认这两个固定文件采用覆盖方式打开。
因此，一份全片段 cube 可以覆盖全体系，但一份原生贡献表不能覆盖全部片段对。
为保存每对指数且不覆盖远端文件，每帧、每对片段独立新建子目录、启动一次 Multiwfn；全部片段都传给每次调用，
只改变请求的定量片段对。这样可取得 3–4 片段全部配对，避免原生 `atmdg.txt` 覆盖。
原生 cube 每次计算；每帧只取回第一对调用生成的两份全片段 cube，其他副本留远程。

菜单是六份固定模板（igm/igmh × low/medium/high），仅替换已核对的整数原子范围和
片段对编号，末尾固定 `0,0,q`。不接受用户菜单。格点对应如下：

| 档位 | cube 标称点数 | IGM Becke 积分 | IGMH Becke 积分 |
| --- | ---: | --- | --- |
| low | 125,000 | 30 × 110 | 40 × 170 |
| medium | 512,000 | 40 × 170 | 60 × 302 |
| high | 1,728,000 | 60 × 302 | 75 × 434 |

IGMH 避开该版本已弃用的 Becke 选项 1。cube 档位为固定总点数，实际网格间距随体系尺寸变化，
不能把 `high` 解释为对任意大体系都收敛。两个 cube 的取回估算约为 3.5/14.3/48.4 MB/帧，
50 帧 high 约 2.42 GB，另加文本表和日志；确认摘要显示一致的估算，非硬容量上限。

线程使用 `-nt <申请核数>`；`-set ../multiwfn-settings.ini` 指向 prepare 哈希绑定的
独立设置文件，仅含 `nthreads`。指定已有输入参数避免 Multiwfn 写入 `lastfile`；
不读取家目录设置，不依赖 `Multiwfnpath`。`OMP_STACKSIZE=1000M`；
`ulimit -s unlimited` 失败记警告后继续。每次程序退出 0 且原生文件存在后由模板输出
`AG_NCI_NORMAL_EXIT`，全作业成功输出 `AG_NCI_COMPLETE`，不是伪造 Multiwfn 原生结束语。
报告还检查原生版本行、线程数、完整数值表及 cube 的格点数量，不能仅凭退出码接受半成品。

输出名单只从 manifest 的 `science.n_frames`（必须存在且为整数 1–50）与片段数展开。
不读远程目录列表，不默认一帧。取回文件：

- `multiwfn.out`、`job.pbs.out`；
- 每帧 `frame-001-dg_inter.cub`、`frame-001-sl2r.cub`；
- 每对 `frame-001-pair-01-02.out`、`frame-001-pair-01-02-atmdg.txt`、`frame-001-pair-01-02-IBSIW.txt`。

帧三位补零，片段两位补零；high 同样取回两份 cube。
`parent.chk`、`parent.fchk`、工作子目录不取回、不删除。文件通过不覆盖的硬链接发布为根目录固定名称，
复用现有 status/fetch 大小、SHA-256、符号链接和路径检查。
Multiwfn 的输出观察使用固定只读循环，文件名仍全部来自 manifest 和模板声明；
不枚举远程目录，逐文件返回格式不变。路径祖先检查也按原顺序循环，避免深路径产生二次增长。
配置本身没有路径长度上限；测试覆盖 Linux 4095 字节可用路径、80 字符 ID、50 帧/4 片段。
若异常长的配置仍使观察命令达到 64 KiB，该分支明确报错，不把超长命令交给 SSH。
旧模板生成的观察命令保持逐字不变。

## JSON 字段

| 字段 | 内容 |
| --- | --- |
| `schema` | 固定 `ag-nci/1` |
| `attempt_id` | 本 Attempt ID |
| `multiwfn_version` | 每个标准输出中一致的 `2026.10.1` |
| `analysis` / `grid` | `igm`/`igmh`；`low`/`medium`/`high` |
| `fragments` | CSV 行顺序的名称、原子编号数组及元素数量 |
| `frames` | 按 1 开始的帧号排列 |
| `frames[].fragment_pairs` | 每一对片段的完整原子表、原子对表和 `total_delta_g` |
| `fragment_pairs[].atoms` | `atom`、`element`、`fragment`、`delta_g`、`percent` |
| `fragment_pairs[].atom_pairs` | `atoms[2]`、`elements[2]`、`fragments[2]`、`delta_g`、`percent` |
| `frames[].fragment_totals` | 每片段对其他片段的成对指数之和；全片段相加会把每对算两次 |
| `frames[].cube_grid` | 网格尺寸、原点/轴向量（Bohr）及 cube 原子行（核电荷与坐标） |
| `units` | δG 为原子单位，百分数为 `%` |
| `parent` | IGM 为 null；IGMH 记录父 ID、方法、几何预览和父 manifest/日志哈希 |
| `provenance.manifest_sha256` | 当前不可变 manifest 原始字节哈希 |
| `provenance.inputs` | 所有上传输入的文件名、字节数、SHA-256（含 CSV、菜单、脚本、设置文件） |
| `provenance.outputs` | 所有取回的声明输出的名称及 SHA-256，包括未解析的 IBSIW 文本 |
| `provenance.remote_inputs` | IGMH 的 chk/fchk SHA-256，从已取回标准输出读取；明确未在本地取回 |
| `notice` / `summary_note` | 半定量限制与片段加和口径 |

`atmdg.txt` 本来省略严格为零的原子对；报告保留其非零行，并要求两个片段的全部原子行和末行总和。
核对加和时容许原生 `f12.6` 格式的逐行舍入误差；不从排序自动给出化学结论。
缺失/非有限的百分数或零总和无法形成可靠贡献百分比，报告拒绝，交给人审阅。

本功能未提供图形渲染、前端或 SCNet 支持。合并前必须完成任务单指定的非研究 RTwin
最小 IGM、三帧 IGM 及新 Gaussian 父 chk 的 IGMH 验证；离线合成测试不构成真实运行或科学验收。
