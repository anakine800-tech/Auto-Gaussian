# 父 checkpoint 的本地证据报告

`ag parent-chk-report` 汇总父 Attempt 的频率执行事实、输入取向、子输入坐标与
checkpoint 关联。它解决“有坐标或 route 写了 Freq，就假定 RCFC 可用”的误读。
报告完成不等于科学可用；**内部力常数始终未核验**。

```sh
ag parent-chk-report '<PARENT_ATTEMPT>' --study '<STUDY_DIR>' \
  --child '<CHILD_ATTEMPT>' --out analyses/parent-check.json --json
```

- `--study` 是现存本地 study 目录；不按 study 名查本机配置，不加载远端凭据。
- 父、子参数只接受该 study 下的精确 Gaussian Attempt ID；不接受路径、前缀或自动匹配。
- `--child` 可省略。提供时只核对已有绑定和显式坐标，不改变 Attempt。
- `--out` 必须是 study `analyses/` 下的新 `.json`，父目录须已存在，同时独占创建同名 `.md`。
  任一文件已存在都不覆盖。路径越界、符号链接、非普通源文件均拒绝。
- 不生成 facts，不 refresh，不读取 chk/fchk，不运行 Gaussian/formchk、Transport、SSH 或任何子进程。
  不改输入、manifest、journal、status、提交行为或既有证据。

## 三类结论

| 字段 | 含义 |
| --- | --- |
| `frequency` | 本次读取的原始日志字节、分段范围和实际振动块；执行事实不借用已存 facts 的整体正常结论 |
| `checkpoint` | 父输入 `%chk`、子 manifest `parent_chk`、既有复制 journal 的历史关联；`internal_force_constants` 恒为 `unverified` |
| `scientific_suitability` | 恒为 `requires_human_review`；是否选 RCFC、ReadFC、CalcFC 或另算 Freq 由现行卡片和人决定 |

`frequency.status` 有四种取值：

| 值 | 界限 |
| --- | --- |
| `normal_frequency_found` | 唯一无分段歧义、正常结束的实际振动频率块；复用现有模式读取与模式数检查。这里只说明日志中的执行事实 |
| `not_found` | 未找到实际完成的振动频率块；仅优化、仅有 Freq route 都不构成证据 |
| `ambiguous_or_incomplete` | 段边界不明、多个实际频率段、频率段异常/中断、后续待完成 Freq、模式/坐标缺项或不可核验 |
| `source_unverifiable` | 缺少与父输入同名的本地日志；即使 facts 写 normal 或 final_input.xyz 存在也不能补成已完成 Freq |

Opt+Freq 内部步骤按已有 Gaussian 分段器读取。正常 Opt 加失败 Freq 不会得到正常频率结论。
多段频率不自动挑最后一段。单原子仅打印热化学、缺位移向量、未支持的模式打印格式，
保守列为不完整或未找到；不为本报告扩展共享解析器。

## 来源与完整性

`parent` / `child` 的全部准备输入按 manifest 的大小、SHA-256 和 bundle 哈希核对，
再用现有纯本地 Gaussian 输入校验器读取显式结构、电荷、多重度和 route。
不调用父 chk 提交准入函数。`manifest_method_basis` 是准备时声明；实际日志打印的方法、
基组、电荷、多重度保存在 `frequency.sections[].printed`，附各自的行号，不从其他段补齐。

`sources` 列出读过的输入、manifest、日志、可选 facts、几何和 journal 等文件，
使用 study 相对路径、文件字节数和 SHA-256；缺失项明确列出。
具体事实另带行号、段号或 JSON Pointer。段哈希取原始字节，包括 CRLF，
不以归一化文本代替。来源在发布前重读，阻止把两次不同版本混成一份报告。

原始日志限于父输入同名的 `outputs/<input-stem>.log`，不从快照或其他 Attempt 借用。
普通 fetch 的历史 journal 没有输出哈希；本报告此时只记录本次本地字节哈希，
不能证明它们与历史远程字节一致。已有 `fetch-add-missing-*.json` 或
`fetch-incomplete-*.json` 时，核对记录的 Attempt 及日志大小/哈希；
不完整取回另核对 manifest 哈希、集群/调度器、complete 和 missing 声明。
这不重新认证调度器终态或作业身份，也不把不完整取回升级成科学成功。
若记录存在而日志哈希不符，命令失败，不生成报告。

`saved.facts` 保留已存声明和指针，不将它作为实际执行依据。
`sections_match_log=false` 表示缓存段信息与当前日志不同，留给人核对，不回填或 refresh。
`final_input.xyz` / `final.xyz` 各自记录当前字节哈希、与日志同取向坐标吻合的段，以及
已存 `fact_sources` 的段号是否与坐标相符；缺少来源声明保持未知。
几何来源不明时仍可报告两个现存文件的数值关系，但这种数值吻合不能确认其来源。

## 固定行坐标与原子身份

`frame_comparisons` 分别列出频率段的 Input 坐标、频率振动打印取向、
父保存的 Input/最终几何和每组子显式坐标的关系。频率 Standard 坐标与 Input 坐标可能不同。
沿用已有父 chk 检查的固定行元素序列和每个原子位移 ≤ `1e-4 Å`，
不旋转、不平移、不对同元素重排，也不用整体 RMSD 稀释局部差异。
非默认 Units 的子坐标不作 Å 比较；父 NoSymm 下的 `final.xyz` 也只展示数值关系，
不在此重新执行或改变提交准入。

`matched` 只表示所列坐标的固定行数值吻合；`different` 列出能观察到的行差异。
二者的 `atom_identity` 均保持未知：可检测的同元素换行会造成坐标差异，
但无法承诺检出所有交换。几何对称、相同位置、缺少身份来源时不能证明化学身份。
报告不依赖 T162 的新映射格式。

## checkpoint 关联

`checkpoint.binding` 核对子 manifest 的父 ID、源文件名、目标 `parent.chk`、集群和 parents，
并核对父输入中经过哈希校验的 `%chk`。关联不符标为 `mismatch`。

复制证据来自实际已有的 study `journal.jsonl`，只读 `action=copy_parent_chk` 且涉及
所选子 Attempt 的行。现行 `detail` 字段为 `source_attempt`、`source_name`、
`target_attempt`、`target_name`、`size`、`sha256`。
`result=verified` 表示复制流程当时核对源与目标都等于这组大小和哈希；不是分别存了两组字段。
只有字段完整且父子绑定一致，才标为 `historically_verified`。
缺字段、只有 started/failed、源目标不符、多个不同哈希均明确列出；不补写旧记录。
历史 journal 自身只有本次读取的哈希，不是不可篡改的远程证明。

无论频率、几何、输入哈希或历史复制证据怎样组合，都不能推断当前 chk 内有可用力常数。
本工具不打开 checkpoint 二进制，不支持 fchk 导入，不给出来自未读二进制的数值结论。

## 退出码与示例

| 退出码 | 含义 |
| --- | --- |
| `0` | 来源读取和报告生成完成；允许未知、未找到、框架不符、绑定不符等审阅结论，不能据此自动提交 |
| `1` | 内容/路径/结构/哈希无效，或输出已存在；不发布半份报告 |
| `2` | I/O、必需字段缺失或本地化学依赖不可用；参数语法错误也由 argparse 返回 2 |

输出文件以独占创建方式成对写入；发生写入失败时只撤回本次创建的文件，已有文件不动。
报告 JSON 的简化合成水分子示例（省略来源明细）：

```json
{
  "report_status": "complete",
  "frequency": {"status": "normal_frequency_found", "selected_section": 1, "mode_count": 3},
  "checkpoint": {
    "binding": {"status": "matched"},
    "copies": {"status": "not_found"},
    "internal_force_constants": "unverified"
  },
  "scientific_suitability": "requires_human_review"
}
```

报告是本地研究材料，应留在 study；不要把真实研究输入、日志、结构或报告提交公开仓库。
