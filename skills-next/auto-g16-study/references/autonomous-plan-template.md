# 自主计划字段模板

供负责人审阅不可变计划；不是新合同、配置生成器或提交授权。T184 基础字段与 T186 的 `submission_policy` 已在固定四源组合核对，来源和验证边界见[离线演练](autonomous-offline-walkthrough.md)。本模板不写本机放行规则，也不提供可直接启用的真实配置。

## 基础正文

以下 JSON 是字段示例。占位符须换成已审阅内容；`valid_until` 是故意过期的示例值，创建时改成负责人指定的 UTC Unix 秒。方法内容来自[现行方法表](acceptance-methods.md)和本 study 已签方案，不在此定义默认方法。

```json
{
  "goal": "[非研究试点或研究，二选一] <目标量、完成条件和适用边界>",
  "comparison_groups": ["<比较组一>", "<比较组二>"],
  "method_policy": "<各阶段方法、依据、温度、标准态、浓度及比较口径>",
  "mechanism_scope": "<已确认机理范围；纯性质任务明确无机理扩展>",
  "system_rules": {
    "main": "<主体系判定；各类作业预估小时及依据>",
    "small": "<小体系判定；各类作业预估小时及依据>"
  },
  "estimated_hours": 2,
  "attempt_limit": 10,
  "valid_until": 1
}
```

| 字段 | 实际约束与填写口径 |
| --- | --- |
| `goal`、`method_policy`、`mechanism_scope` | 非空文本；目标写边界，不枚举所有未来构象/对象 |
| `comparison_groups` | 非空字符串列表；保证比较组定义足以审阅 |
| `system_rules` | 仅 `main`、`small` 两个非空文本键；分类理由不能由资源档位倒推 |
| `estimated_hours` | 单个正的有限数；是整体耗时预估，不是 walltime 或逐作业映射 |
| `attempt_limit` | 正整数；动作组合按本轮实际提交消费，prepare 与旧意图计数不另扣；90% 暂停，不因新 wake、修订计划或接管清零 |
| `valid_until` | 晚于计划创建时间的 Unix UTC 秒；写明对应的人类可读时间供审阅 |

当前没有独立的试点/研究标志、逐作业类型耗时字段。上面的标志及分类耗时只能作为已确认文本保存，不声称 CLI 已结构化核验；不要添加 `study_type`、`job_estimates` 等未知键。需确定性消费这些信息时应补正式接口，不能自建解析协议。

`plan` 自动保存 `id`、`created_at`、`versions`、`spec`，输入只给 `spec` 正文。`versions` 的 `ag_version`、完整 `git_commit`、`dirty`、`rdkit`、`goodvibes` 来自实际干净运行环境，不能手填历史版本。确认时展示返回的完整计划与 SHA-256，再逐字记录负责人确认；CLI 不验证发言身份。修改计划另存新版并重新确认，旧签字不迁移。`begin` 创建授权 round，`start` 只开 wake；不能每次补构象都改计划或开启新额度。

## 提交边界：submission_policy

固定组合允许在上述正文加入一个 `submission_policy` 对象，精确字段如下。缺该对象的旧计划可读，但不能据此自主提交。本节形状已通过实际 plan 命令；示例哈希只用于隔离解析测试，不是获准路由。

```json
{
  "templates": ["xtb"],
  "clusters": {
    "default": {
      "nodes": [],
      "max_committed_cores": 8,
      "max_queued_cores": 8,
      "max_jobs": 1
    }
  },
  "max_cores_per_job": 8,
  "max_walltime": "00:30:00",
  "methods": {
    "xtb": [{"parameters": {"--gfn": "2"}}]
  },
  "routing_sha256": "<正式路由身份的64位SHA-256；不是手写或示例哈希>",
  "allow_relaxed": false
}
```

这是合成字段形状示例，不选择真实集群、节点或资源；入口键只使用配置入口标识。`nodes: []` 仅表示不具名提交，不是任意具名节点；具名 PBS 名单须在私有计划中逐一列明，不进公开示例。各上限为正整数，排队核数不得大于总核数；上限也不能扩大本机配置或统一额度。

`methods` 键与 `templates` 一致，每项是非空且不重复的完整方法列表。Gaussian/CP 方法项只含：

| 方法项字段 | 值的来源 |
| --- | --- |
| `method`、`basis`、`basis_function_type` | 受支持的规范化闭壳层方法、基组及基函数类型 |
| `dispersion`、`solvent_model`、`solvent`、`integration_grid` | 完整方法口径；缺省也须使用实际解析器的规范值，不靠文字同义词匹配 |
| `opt_convergence` | `normal` / `tight` / `verytight` 中已审阅的下限；实际最终任务仍不得放宽已签标准 |
| `scf_convergence` | 8 至 12 的整数下限 |

非 Gaussian 方法项为 `parameters` 映射，键值均为字符串；xTB 显式 GFN2，CREST 显式 GFN2/GFN-FF，Multiwfn 显式分析与网格，均受已审阅模板白名单限制。具体输入与科学边界继续查对应卡片；本模板不扩大 Gen/ECP、金属或开壳层能力。

规则还需绑定 study 身份、round、计划哈希、路由身份、有效期与 Attempt 上限，但这些是本机规则字段，不要塞入计划的 `submission_policy`。规则只能收窄计划，不能换路由、加方法/节点、延长期限、增额度或擅开 `allow_relaxed`。后者为 true 也只允许受控例外，不证明方法已核验。

新增对象、来源、拟动作理由与待人决定事项通过正式 update 写到动态状态。其输入精确包含 `summary`（字符串）、`pending`（非空事项字符串列表，可为空）及 `objects`（对象 ID 到动态内容的映射），三项整体替换，先保留未完成旧事项。`objects` 自由文本不替代提交归属、停止证明、消费记录或科学签字。首次路由哈希提取仍有[具体 CLI 缺口](autonomous-offline-walkthrough.md#接口核验与缺口)，不能自行调用内部 Python 函数填补操作入口。
