# BTX AI 对比烟测（2026-10-23）

这些是开发诊断，不是棋力认证；样本小，默认 AI 未切换。

## 配置

- 剧本：BTX01、BTX06 标准版。
- 黑方：`joint_mastermind`，回复模型分别为 `public` 和 `belief`。
- 红方：`particle_ensemble`，日末 horizon。
- 预算：24 节点、深度 6、双方每步 1 秒软上限。
- 8 进程并发，各 5 个种子。

## 黑方回复模型

| 剧本 | 回复模型 | 主人公胜局 |
| --- | --- | --- |
| BTX01 | public | 0/5 |
| BTX01 | belief | 0/5 |
| BTX06 | public | 0/5 |
| BTX06 | belief | 0/5 |

两组黑方都全胜，当前公平红方在这个预算下没有区分出回复模型差异。信念采样版没有表现出更强棋力，暂不切换默认黑方。

## 主人公 horizon

BTX01、`optimized` 剧作家、`particle_ensemble` 红方、种子 0–9：

| horizon | 主人公胜局 |
| --- | --- |
| day | 3/10 |
| loop | 2/10 |

day 不差于 loop，和“专注当日存活已经够用”的判断一致；样本小，不能据此证明统计显著。

## T1 终猜信息

BTX01、单局、20 个日边界、终猜信息节点上限 2000：

- 当前最佳整套身份概率均值约 0.0089。
- 对局最终终猜角色正确率 25%（4 个角色对 1 个），整套全对为否。
- 整套概率和单角色正确率口径不同，不能直接比较；校准已改为同时记录“整套是否全对”。

## 结论

- 当前黑方联合搜索在低预算下已经压过公平粒子红方，回复模型不是瓶颈。
- 红方 horizon 用 day 即可，长 horizon 没有收益。
- 想继续提升棋力，需要在红方行动规划或跨日信息集上做新设计（T2 或更强信息集搜索），已经超出现有 T1 接口的范围。

## 数据

原始 JSON 在忽略目录 `references/ai-calibration/2026-10-21/`：

- `t1-btx01-calibration-5games.json`
- `t1-btx06-calibration-1game.json`
- `t1-selfplay-calibration-20g1r.json`
- `btx_horizon_compare` 运行输出
- `btx_reply_model_compare` 运行输出
