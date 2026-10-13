# 验收与兜底方法

先使用文献 Skill 查找直接先例；未找到时才声明“兜底方法”，不能编 DOI。下表来自当前改造方案第 5.5 节，不是针对所有化学体系的精度保证。

| 用途 | 方法 | 使用边界 |
|---|---|---|
| 流程验收 | B3LYP-D3(BJ)/6-31G(d)，气相 Opt+Freq，不做高精度单点 | 只证明流程；Gaussian route 示例 `#p B3LYP/6-31G(d) EmpiricalDispersion=GD3BJ Opt Freq` |
| 研究但无先例 | B3LYP-D3(BJ)/def2-SVP Opt+Freq；单点 B3LYP-D3(BJ)/def2-TZVP 或 ωB97X-D/def2-TZVP | 溶液相加入 SMD，写明溶剂；这两种单点方案需明确择一，不能跨构象混用 |
| 构象初筛 | CREST GFN2-xTB，溶液相加入 ALPB | xTB 相对能量 3 kcal/mol 内去重；研究最多 20 个、验收最多 10 个进入 DFT，截断后说明覆盖局限 |
| 热化学 | GoodVibes 4.3.0；Grimme qRRHO，截止 100 cm⁻¹，298.15 K，1 mol/L | 用 `ag thermo`；记录实际采用的熵 / 焓处理。气相验收也按该统一标准态比较时注明，不能据此声称溶液模型成立 |

资源与科学方法分别选择：simple 8 核 / 12 GB、general 22 核 / 50 GB、complex 44 核 / 120 GB。Gaussian `%nprocshared` 等于档位核数；`%mem` 不超过档位内存的 85%，建议分别用 10GB、42GB、100GB。walltime 在具体卡片中按任务建议，再结合既有耗时调整。所有作业合计不超过配置核数上限（当前 44）。

首版只处理主族闭壳层单分子。不能将这张表延伸为金属、开壳层、激发态、TS/IRC 或双分子结合搜索的执行依据。
