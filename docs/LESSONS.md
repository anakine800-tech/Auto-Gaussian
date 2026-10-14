# 开发与现场经验

每条最多五行：现象、原因、修复 PR、以后的写法。新经验追加这里，每周清理时合并重复条目。
只保留可复用的结论和公开 PR 链接；现场原始记录留在仓库外。工程修复不等于科学验收。
以下区分现场故障、审阅发现和风险预防；没有查到根因或专门修复 PR 时明确写出，不补造结论。

## PBS 残留作业
现象：程序结束，PBS 仍显示 R，旧 status 无法让结果进入可取回状态。
原因：调度器记录寿命与程序寿命不同，单靠 R/C 判断不够。
修复：[#212](https://github.com/anakine800-tech/Auto-Gaussian/pull/212) 加开始/退出回执、输出观察及残留标记；[#214](https://github.com/anakine800-tech/Auto-Gaussian/pull/214) 补取回提示。
以后：优先核对绑定的退出回执；残留不自动清理，只能人确认后 cancel 确切作业。

## Unknown Job Id 与两次观察
现象：Torque 的 `Unknown Job Id Error` / 返回码 153 被旧解析器拒绝；第一次观察还被误报 interrupted。
原因：真实错误方言未覆盖，且一次静态输出不能证明程序已经结束。
修复：[#213](https://github.com/anakine800-tech/Auto-Gaussian/pull/213) 识别该方言；[#214](https://github.com/anakine800-tech/Auto-Gaussian/pull/214) 增加 awaiting_second_observation。
以后：旧无回执作业需完成标记和至少相隔 60 秒的两次稳定观察，读标记后再 stat；PBS 仍有 R/C 时另查会话进程，SSH 255 不算作业消失。

## freq 段报几何未优化
现象：优化收敛且虚频为零，频率段却出现 `Non-Optimized Parameters` 或收敛项 NO。
原因：只看优化阶段的表，会把频率阶段几何判据遗漏。
修复：[#214](https://github.com/anakine800-tech/Auto-Gaussian/pull/214) 按段解析 freq_step_converged，并补 Opt/Freq 与诊断卡片。
以后：独立检查频率段四项阈值，缺失记未知；从最终几何提出同方法的新优化 Attempt，不能沿用未通过判据的热修正。

## SSH 255 与只读重试
现象：连接中断或超时使查询失败，提交响应也可能丢失。
原因：传输失败不能说明调度器未接收请求；重发写操作可能重复计算。
修复：[#209](https://github.com/anakine800-tech/Auto-Gaussian/pull/209) 限只读传输等 15 秒重试一次；[#212](https://github.com/anakine800-tech/Auto-Gaussian/pull/212) 脱敏并保留首次失败证据。
以后：submit/cancel 及其内部读取均不自动重试；提交结果未知只读核对，不把重试成功抹成“从未出错”。

## CREST 返回 0，却没有构象集合
现象：T20 报告 CREST 退出码为 0，但未生成可审阅的构象集合。
原因：返回码只证明进程报告成功；本次所查已合并 PR 未给出该现场缺失集合的具体根因，不能猜测参数或版本原因。
修复依据：[#208](https://github.com/anakine800-tech/Auto-Gaussian/pull/208) 的 crest-screen 已要求正常终止、非零 n_conformers 和能量/构象数量对应；未查到该事故的专门修复 PR。
以后：同时核对声明输出、完整 XYZ 帧和能量数量；缺集合就报告科学结果不完整，不因 sacct COMPLETED 或返回码 0 接受，也不自动重跑。

## squeue 补空格与作业名截断
现象：用户名带填充空格时解析失败，长作业名被截断后无法关联 Attempt。
原因：默认列宽和未逐列去空白的解析不匹配真实输出。
修复：[#232](https://github.com/anakine800-tech/Auto-Gaussian/pull/232) 使用明确的 squeue/sacct 列宽并逐列 strip。
以后：样例虚构身份但保留填充/截断形态；严格比较完整作业名和属主，不放宽成前缀匹配。

## 本机多个集群的作业号混淆
现象：monitor 把 Slurm 记录交给 PBS 作业号校验器；跨集群同号可能错误关联。
原因：先扫 status 再判断集群，会使用错误解析器，也让其他集群的坏记录阻断当前扫描。
修复：[#229](https://github.com/anakine800-tech/Auto-Gaussian/pull/229) 引入提交绑定；[#235](https://github.com/anakine800-tech/Auto-Gaussian/pull/235) 统一 local_record，先按 manifest 过滤。
以后：按 manifest 选集群/调度器，再核对 submission/status；裸作业号只按 default PBS 解释，错误要指明 Attempt。

## 平台 env.sh 的副作用
现象：加载平台 Gaussian 环境后 scratch 被改到安装目录，还会向 ag 根外共享文件追加记录。
原因：env.sh 同时执行平台记账和目录设置，不只是声明运行变量。
修复：[#234](https://github.com/anakine800-tech/Auto-Gaussian/pull/234) 用固定 scnet-a03 模板设置必要变量，禁止与 module 初始化混用。
以后：审阅环境脚本的全部副作用；scratch 保持在新 Attempt 内，不直接 source 未审阅的平台脚本。

## Slurm 自动重排队
现象/风险：调度器 requeue 可让同一 Attempt 再次运行和收费；T16 将其列为防范场景，所查 PR 未记载实际重复收费事故。
原因：本地只调用一次 sbatch，不能阻止调度器自动重新执行。
修复：[#229](https://github.com/anakine800-tech/Auto-Gaussian/pull/229) 脚本固定 `--no-requeue`，复用单次运行 guard。
以后：渲染测试保留 no-requeue 和单次执行断言；UNKNOWN 预留不释放，不新增自动重提或重排队入口。

## 远端 Python 版本兼容
现象：[#230](https://github.com/anakine800-tech/Auto-Gaussian/pull/230) 审阅发现 chk 助手使用 Python 3.7 才有的 `text=True`，不能在目标最低版本 3.6 运行。
原因：按本机 Python 编写远端脚本，没有检查远端 API 下限；这是审阅发现，不冒充已发生的现场崩溃。
修复：#230 改为读 bytes 后 decode，并检查 Python/描述符环境；[#232](https://github.com/anakine800-tech/Auto-Gaussian/pull/232) 把不使用 chk 时的缺环境改为警告。
以后：固定脚本同时检查语法和 API 的最低版本；真正使用父 chk 时，环境不满足仍在提交前拒绝。

## 提交者邮箱泄露本机标识
现象：T20 指出 Git 提交者邮箱会泄露本机标识；文件 diff 干净仍不能保证提交元数据安全。
原因：Git 可继承本机邮箱；作者和提交者字段独立，不能只查一个。
修复/核查：[#224](https://github.com/anakine800-tech/Auto-Gaussian/pull/224) 核查所有登记 worktree 的生效邮箱及提交身份均为 noreply；该 PR 未修改邮箱或重写历史。
以后：提交前本机核对 author/committer 的 noreply 身份，PR 不贴真实邮箱、主机标识或核查路径；不能声称该核查已清除历史泄漏。

## 本机 main 未同步
现象：PR 已合并，但本机 Skills 和 ag 仍停留在旧版本，前端也可能从旧检出启动。
原因：合并只更新远端 main；本机检出、软链接目标和运行环境不会自动快进。
修复：T24 补充合并后同步要求；本机同步操作另有记录，不把文档修改当作部署完成。
以后：每次合并后后端和前端 main 均 `git pull --ff-only`；真实计算只用后端 main 的 `.venv/bin/ag`，前端从固定目录运行。

## rcfc 的坐标系错配
现象：L3 用父 TS 的 Standard 坐标读取力常数时，双向 IRC 均首点校正失败；正确 Input 坐标的 RCFC 与独立 CalcFC 部分轨迹高度吻合并越过首点，随后仍有校正失败。
原因：输入坐标与父作业 Input 框架的 Cartesian 力常数/模式错配；副本哈希、相同起点能量及对齐 RMSD 不能证明取向一致，不宣称这是所有失败的唯一根因。
修复：[#240](https://github.com/anakine800-tech/Auto-Gaussian/pull/240)（待审阅）导出 final_input.xyz 与实际取向，在 prepare 读取父力常数时按固定原子顺序检查 1e-4 Å 容差；已有几何文件只沿用相同字节，不覆盖。
以后：RCFC/ReadFC 用 final_input.xyz，或预先在父 TS 加 nosymm；取向正确后再逐级审阅 StepSize、MaxCycle、CalcAll/ReCalc。L3-C/D 结论待补，部分轨迹不等于双向完成和端点验证。
