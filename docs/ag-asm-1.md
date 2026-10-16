# ag-asm/1：畸变–相互作用分析

`ag asm` 是纯本地电子能汇总工具。片段、原子映射、电荷、多重度和弛豫参照由人指定，
不推断化学身份、不准备或提交计算、不判断哪一项决定选择性。
只读取现有文件，不刷新 facts。JSON 与 Markdown 独占创建；任一输出已存在就拒绝整个输出。

## 从 Attempt 拆出片段

```sh
ag asm split water-pair --study '<STUDY_DIR>' --geometry input \
  --atoms 5,1,3 --name first --out analyses/first.xyz
```

`--geometry` 必须显式指定：`input` 读取 manifest 绑定的 Cartesian Gaussian 输入，
核对输入哈希；`final` 读取 Attempt 的 `final_input.xyz`，不回退到 Standard 取向。
原子编号从 1 开始，支持逗号与范围（如 `1-40,52`）；重复、越界、倒序范围和空项报错。
按编号升序输出，不对齐、不平移、不旋转。XYZ 注释记录来源 Attempt、几何类别、
片段名和 `original_atoms=1,3,5`，不填片段电荷或多重度。
负责人用导出的几何照常准备片段单点，并自行指定电荷、多重度与同一方法口径。

## 定义文件

定义文件和输出位于当前 study 的 `analyses/` 下。文件参数相对 study 根目录，
也可用该 study 内的绝对路径；输出引用始终为 study 相对路径。
`--study` 接受目录，省略时用当前目录；split 传绝对 Attempt 目录时可推断其 study。
定义中的 Attempt 使用本 study 的 ID 或绝对 Attempt 目录。拒绝越界和所有路径层级的符号链接。

```json
{
  "schema": "ag-asm-definition/1",
  "systems": [
    {
      "label": "TS-A",
      "complex_attempt": "ts-a-sp",
      "complex_geometry": "input",
      "fragments": [
        {"name": "first", "atoms": "1,3,5", "charge": 0, "multiplicity": 1,
         "attempt": "ts-a-first-sp", "reference_attempt": "first-relaxed"},
        {"name": "second", "atoms": "2,4,6", "charge": 0, "multiplicity": 1,
         "attempt": "ts-a-second-sp"}
      ]
    }
  ],
  "comparisons": []
}
```

`systems` 非空，label 唯一；每个 system 的片段名唯一且片段非空。
`complex_geometry` 只接受 `input` 或 `final`。`reference_attempt` 可省略，
部分片段有参照也可汇总；`comparisons` 可省略或为空。
比较两个已定义的 system 时填 `{"a": "TS-A", "b": "TS-B"}`，差值方向固定为 **b − a**。

```sh
ag asm summary --study '<STUDY_DIR>' --definition analyses/asm-definition.json \
  --out analyses/asm.json
```

校验分别防止未配平的片段能量、坐标串用、电子态或方法混用造成假能量分解：

- 片段原子互不重叠且恰好覆盖复合物，片段电荷之和等于复合物电荷；全部为单重态。
- 片段输入按升序 `original_atoms` 对应复合物子集，逐原子元素相同、坐标欧氏距离 ≤ `1e-4` Å。
  不允许通过旋转对齐或重排掩盖原子映射差异。
- 所用 facts 均为正常结束的 Gaussian、Hartree 单位、有限 `energies.scf`；
  与 profile 的电子能字段相同，不读取 G、ZPE 或热校正列。
- 用 `_profile_sources.protocol()` 核对所有系统、片段和参照的方法、基组、色散、
  溶剂模型与溶剂，程序版本须相同。自定义或无法确定的口径按原解析器规则拒绝。
- `input` 能量限一个不改变几何的作业段，拒绝 Opt/IRC/Scan 的末次能量配起始输入。
  `final` 必须有 `final_input.xyz`；能量与最终几何来源段一致，或是已识别的
  Opt+Freq 内部频率续段；仅该续段允许 `SCRF=Check` 继承首段显式溶剂口径，
  并统一 Gaussian 自动添加的 restricted 方法前缀（如 B3LYP → RB3LYP）。
  无关 Link1、缺失分段证据或来源方法不同直接报错，
  不把末次 SCF 默认为任意几何的能量。旧 facts 缺来源信息时需先核对并按正常流程更新 facts。
- 弛豫参照用 facts 的 `final_geometry` 核对元素组成、电荷与多重度；原子顺序可不同。
  参照结构是否为适用的弛豫构象仍由人审阅，程序不会由组成相同推断物种身份。
- comparison 的片段名集合相同，同名片段的元素组成、电荷、多重度相同。

错误说明 system / fragment；发布前复核所有读入文件字节，收集期间变化则不写报告。

## 输出字段与公式

顶层 `schema="ag-asm/1"`，另有 `ag_version`、`units`、`hartree_to_kcal_mol`、
`geometry_tolerance_angstrom`、`definition`、`sources`、`systems`、`comparisons`、`notice`。
`definition` 和 `sources` 用 `{ "path": "study相对路径", "sha256": "64位十六进制" }`。
`sources` 包含定义文件及全部实际读取的 facts、输入 manifest、Gaussian 输入或最终 XYZ。
每个能量值均为 `{ "hartree": 原值, "kcal_mol": 换算值 }`，换算常数来自现有 geometry 模块，
当前为 `627.5094740631`；JSON 不截断 Hartree 精度，Markdown 显示 12 位小数。

每个 system 包含：

| 字段 | 含义 |
| --- | --- |
| `label`, `complex` | 人工标签、复合物来源与绝对电子能 |
| `fragments` | 片段名、升序 `original_atoms`、来源、电子能、可选参照及畸变能 |
| `E_int` | `E_complex − Σ E_frag@complex` |
| `E_dist_total` | 全部片段都有参照时的 `Σ E_dist`，否则 null |
| `delta_E` | 全部片段都有参照时的 `E_dist_total + E_int`，否则 null |

每个来源记录 `attempt`、`geometry`、`facts` 路径/哈希、`energy`、`elements` 元素计数、
`charge`、`multiplicity`、`protocol` 和 `program_version`。
片段的 `reference` 是参照来源记录或 null；`E_dist = E_frag@complex − E_frag,ref`，
没有参照时为 null。`geometry=reference` 指参照 facts 所指定的最终几何，仅用于组成核对。

每个 comparison 包含 `a`、`b`、`direction="b - a"`、`ddE_complex`、`ddE_int`、
`fragments: [{name, ddE_dist}]` 和 `sum_residual_hartree`。
`ddE_dist` **直接用两侧同名片段在复合物几何下的电子能相减**，不需要参照，
也不减去两侧不同的参照能量。
核对 `ddE_complex = ddE_int + Σ ddE_dist`，绝对残差必须 `< 1e-8` Hartree。
Markdown 每个 system 一张表、每个 comparison 一张表；缺参照项用破折号表示，末尾列来源哈希。

固定附注：

> 电子能，不含零点能和热校正；未做基组重叠误差校正；溶剂模型与复合物一致；只描述能量分解，不判断选择性来源。

## 签字证据的间接绑定

先在 `study.md` 或 `review.md` 中链接本次输出的 **JSON 和 Markdown**，再运行
`ag review manifest --study '<STUDY_DIR>'`。
清单直接收录这两份报告及其定义文件，`facts.json` 仍照常直接收录。
Attempt 内的几何、输入与 manifest 只列为 analyses 外引用，不由证据清单直接收录。
这些文件通过已收录 JSON 中的 `sources[].path` 与 `sources[].sha256` **间接绑定**：
核对时逐项重新计算当前文件的 SHA-256，与报告里的值比较。
几何文件变动会导致复算不一致；仅重新生成证据清单不会自动检查 asm 保存的几何哈希，
不能把清单生成成功解释为这些间接来源仍未改变。

这是负责人在 T76 v2 确认的范围；本任务不修改证据清单实现。
以后若需直接收录 Attempt 几何，应另开工单，并复扫全部已签 study。
