# AI 路线图（2026-10-18）

本页只维护现状、下一步和验收标准。算法与论文见 [核心设计](certified-day-game-design.md)，开发入口见 [交接说明](codex-handoff.md)，历史实验见 [归档](archive/README.md)。

## 当前状态

- 实战主线：公平粒子红方＋三牌联合黑方；矩阵／witness、终猜联合概率、三牌接口与replay可用。开眼模式明确标注，实验结果不自动切换默认AI。
- 后续AI基线默认使用BTX（有最终猜测）；FS没有终猜，作为支线策略和离线内核样本保留。
- 离线内核：FS完整域／日末树、无损缓存及混合策略逐阶段验收，专题报告保存测量与反例。完整压力根仍有未闭合的界，公平信息集迁移尚未完成。

## 主线实施顺序

T0.1–T0.3已验收，T0.4进行中；每阶段验证、提交。

| 阶段 | 交付与验收重点 |
| --- | --- |
| T0.1 精确基准 ✓ | [完整合法域／日末能力树](exact-day-baseline.md)，独立穷举核对。 |
| T0.2 无损压缩 ✓ | [状态键／缓存](exact-day-cache.md)、[局部效果／观察边](exact-day-local-programs.md)，资源与信息保真。 |
| T0.3 混合策略 ✓ | [精确LP／Double Oracle](exact-day-mixed-strategies.md)、完整域最优回应与L/U/gap；未知保留区间。 |
| T0.4 公平迁移（进行中） | [后验桥](public-posterior-day.md)、[兼容历史](compatible-history-day.md)、[原生信息集树](information-set-day.md)及[全域回应](information-set-responses.md)已实现；[常量子树压缩](constant-subtree-compression.md)已验收，公开FS根10秒档完成压缩前后对照，完整根域仍受缺失质量与黑方回应覆盖限制。 |
| T1 续局价值 | [独立日末估值接口](continuation-value-interface.md)已建立，随机rollout基线、CLI接入和自对弈校准烟测完成。BTX01 5局全输：当日存活Brier 1.000，随机rollout 0.306；BTX01 `random`剧作家3局全赢：0.000／0.175；BTX06 1局：1.000／0.268；FS01 20局：0.879／0.308。Brier受胜负构成影响，样本小且随机策略有偏，不能据此选估值器。实际整局估值器、终猜概率叶值和配对验证待做。一次求解冻结效用及更新模型。对比烟测见 [BTX AI 对比](btx-ai-comparison-2026-10-23.md)。 |
| T2 有限跨日 | [两日搜索设计](two-day-search-design.md)已写；状态返回模拟器已确认存在（引擎转移`Game.transition`/`clone`），已新增`advance_to_day_boundary`保留日末状态（`tests/test_day_game_transition.py`）。下一步：日边界转移接口、候选黑列/红计划、2日滚动宏动作搜索、观察分支与信念更新。 |
| T3 跨轮回 | 失败后重置棋盘并保留合法知识；真实整局终结置0/1，验证风险／信息取舍。 |

最终目标为整局获胜概率；当日存活保留独立基准，不硬抬信息技能使用率。近似叶值仅支持给定模型内的结论。

## 后续方向

- 内核共享给实战黑方，建模红方公开知识／近似信念，评测混合策略及终猜信息隐藏；后验、witness、跨维关联和病毒历史查询独立回归。
- 覆盖全部已录入FS／BTX标准、Easy及BTX-41，再从MC简单剧本逐步扩展；MZ动态身份及加号规则集专门验收。
- 完整整局信息集树、独立三／四人红方、强化学习及高预算平衡评测延后。[前端／联机](web-and-lan-roadmap.md)另管，当前保持局域网；旧HS／AH、OF、UP主和仙人不在范围。

## 验收纪律

1. 公平AI只读授权观察；黑牌先提交，揭牌后能力才响应红牌。证据独立于行动预算，内部真值不进入界面／SSE。
2. 保留资源所有者、时点、析取与完整matcher。未采到不等于never，启发式不作安全证明；所有候选在共同世界／攻击集评价。
3. 策略对照默认4进程、seed0–9、固定工作量，标准／Easy和留出剧本分报；性能空闲串行测。见 [实验方法](ai-experiment-protocol.md)。
4. 主指标整局胜率，同时记录存活、终猜、重复失败、信息、资源及耗时；报告horizon、效用版本、覆盖与认证范围。保留用户附件，`references/`继续忽略。

规则集扩展见 [AI调优指南](ai-tuning-guide.md)、[witness审计](witness-coverage-audit.md)和 [候选清单](witness-candidate-backlog.md)。历史记录不作为当前待办。
