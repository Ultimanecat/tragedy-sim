# AI 实验方法：并发配对、固定种子与反例审计

## 默认流程

1. 小样本用于找 bug、验证合法行动／horizon／信息边界；明确标为烟测，不以一两个 seed 排棋力。
2. 新算法或一组简单 witness／奖励改动通过正确性测试后，跑同源码的旧／新对照。常规固定种子 **0–9**，每个剧本每个算法 10 局；固定规则集、剧本版本／难度、对手和预算，保持特性开关单独消融。
3. 整局对弈默认 **4 个独立进程并发**。先核验串行／并行固定工作量下的决策摘要、完整 replay、胜负完全一致，再考虑 8 个进程。不同进程各自维护 RNG、缓存和游戏；不并发操作一局的三张牌，也不共享 AI 实例。
4. 常规回归默认固定工作量，避免机器竞争改变搜索深度。秒级／分钟级限时棋力与响应速度另跑，记录并发宽度及实际节点／世界×路线评价数；严格用时校准用 `--workers 1 --no-fixed-work`，空闲机器运行。固定种子不保证限时轨迹严格重复。
5. 出现明显配对差异后，从同 seed 的改善和退化中抽取代表局，检查每轮失败原因、终猜前知识、witness／联合概率变化、危险组合、候选覆盖和同世界评分。先解释共同根，再扩大到 30–50 seed 或留出剧本确认；不按某次真值和剧本编号调先验。
6. 每个验证完成的阶段更新路线图、提交并推送。报告保留原始失败反例；未完成的配对和不同源码不混成最终胜率。

10 局仍是每局 10 个百分点，不足以稳定区分小差异。报告每剧本的胜率／Wilson 95% 区间、改善／退化／双方同胜负，以及完整配对的探索性二项检验；检验未作多重比较校正，不自动判定普遍更强。标准／Easy 共用秘密，单独列出结果，不作独立剧本数。

## 调度与恢复

`benchmarks.ai_matrix_validation` 默认 0–9、最多 4 workers、固定工作量。一个任务由 **剧本＋seed＋算法变体** 标识，完成顺序可不同；只由主进程按规范任务顺序保存汇总，每次完成即原子更新。正常任务失败后停止启动新任务，保存已完成结果并等待已启动任务结束。

`--max-jobs` 限制本次新启动的局数，`--resume` 只补未完成任务；不能把结果数量当作连续完成前缀。续跑校验源码指纹、剧本内容／字典顺序、算法预算、唯一任务 ID 和 replay 审计。固定工作量可调整 worker 数续跑；限时实验的 worker 数属于资源配置，变更需新报告。schema 2 不自动迁移旧报告，旧结果保留不覆盖。

记录每个任务的 worker PID、含审计墙钟／CPU 时间、worker 生命周期峰值内存和每次调用总墙钟。并发时每局耗时有竞争，不能拿它宣称单线程加速；比较整个任务批次吞吐量。缓存冷热、进程启动、异构核心和其它应用都会影响加速比。

初次真实验收：FS01，seed 0／3，矩阵／分区各两局，黑 4 节点、红 2 候选、4 世界、depth 4。串行与 4 个不同 worker PID 的并行对照，四局完整决策摘要／replay／胜负逐一相等。批次总墙钟 **28.37→9.18 秒（约 3.1 倍）**，单 worker 峰值约 42 MiB。报告 `parallel-equivalence-workers1.json`／`parallel-equivalence-workers4.json` 在 2026-10-14 忽略目录；这是小批次吞吐测量，不外推为任意剧本严格四倍加速。

并发／非前缀续跑／失败后排空／配对统计专项 17 项通过，完整后端 **815 项通过（192.483 秒）**；日志 `references/parallel-evaluation-regression-20261014.txt` 被忽略。

```powershell
# 默认六剧本×10 seed×两个算法＝120 局，固定工作量，并发 4
python -X utf8 -m benchmarks.ai_matrix_validation --comparison matrix_partition --output references/paired-new.json
# 分阶段调度；第二次从未完成的任务续跑
python -X utf8 -m benchmarks.ai_matrix_validation --comparison matrix_partition --max-jobs 8 --output references/paired-stage.json
python -X utf8 -m benchmarks.ai_matrix_validation --comparison matrix_partition --max-jobs 8 --resume --output references/paired-stage.json
# 定点烟测／严格串行限时对照需显式指定
python -X utf8 -m benchmarks.ai_matrix_validation --scenario official-fs-01-first-script --seed 0 --workers 1 --no-fixed-work --output references/timed-new.json
```

其它旧 CLI 仍可作定点诊断；常规配对统一使用支持默认并发／固定种子的评测器，避免在多个旧入口重复维护调度。原始报告／完整 replay 放在忽略的 `references/`，开发信念／真值／Trace 不进入玩家 API、SSE 或公开回放。

## 指标与归因

身份边际误差、完整身份表终猜概率、危险世界覆盖和整局胜率分别测量。人工压力状态的 TV 改善不能当作实际对弈身份误差改善；ESS 接近批次大小也不证明有限行动世界已覆盖罕见攻击。记录初始身份、当前身份和信息来源，不把终局公开答案算入终猜前推理。

对死亡／失败依次检查：引擎真实结算 → 真值硬兼容 → 身份×事件当事人×暗牌危险组合 → 重建及黑方续演 → 防御候选 → 共同世界评分 → 跨日与跨轮回信息价值。当前 FS01 反例是身份分布相同、杀手×纵移组合遗漏；BTX Easy 反例是轨迹少了一条巫女亲友公开事实。详见 [抽样诊断](exact-partition-role-sampling.md)。

新暗牌优化先与有限合法枚举作对照，再测对弈。若以敌对牌面作为安全压力测试，不将这些样本计入普通后验；若混入概率估计，必须定义提议密度及校正。保持历史牌型作为软先验，黑方始终可以选择低历史权重的致命攻击。

当前 [防守审计](dark-attack-defense-audit.md) 有完整 504 合法暗牌的共同根参照和 40 局／10 seed 对照。额外攻击评价增加真实 rollout 数；相同候选上限和世界数不等于相同计算预算。下一轮单独测相同墙钟、候选覆盖和评分场景消融，并用开眼暗牌区分角色推断问题与防守问题。
