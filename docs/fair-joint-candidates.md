# 公平多世界联合候选（2026-10-16）

## 首阶段范围

`ParticleEnsembleProtagonistAgent(candidate_policy="joint_threat")` 复用共享 `JointActionSpace`，从完整轻量三牌空间选出候选，再沿用原公平AI的共同世界真实引擎评价。默认仍 `legacy`，没有更换大厅AI、角色后验、witness、暗牌分布、技能续演、终猜或最终评分策略。

这个阶段单独测量候选生成。原有 `dark_card_policy="sampled"|"adversarial_guard"` 独立配置：前者每个后验抽样只有原暗牌，后者附带既有有限攻击分支。尚未迁移开眼的完整单因素覆盖／候选条件化反例搜索，后续分开消融。

## 身份质量与暗牌覆盖

新增 `HypothesisThreatRanker`：

1. 每个原始后验抽样为一组，默认各占 `1/N`；也支持显式有限非负质量并归一化。重复抽样保留原有质量，暂不合并它们的暗牌攻击并集。
2. 组内全部场景必须具有同一初始剧本／当事人与当前身份，复用 `JointThreatRanker(state_policy="worst")`。该组的轻量安全指标要求全部已测攻击风险为0，状态分取最低值。
3. 同一三牌在所有组上计算，再按原组质量聚合安全、危险度及状态分。额外攻击数量不改变身份／当事人质量；不同身份也不会全部取最坏。
4. 这些只是候选排序指标。引擎评价继续使用原始后验抽样，每个抽样在自己的暗牌／技能分支内取最差，再跨抽样聚合。绝不把各世界分别选择的最优牌平均成一个不可执行方案。

轻量安全性、后验概率和实际胜率分别解释。分支不更新witness、角色矩阵、终猜概率或采样RNG；公平入口只收合法视图、授权私密答案与自己采样的假设。

## 边界与成本

- 完整轻量枚举保留席位、限次资源与已出牌前缀；实际只提交尚未出牌的席位。BTX高不安／非标准区域等未证明等价时显式回退原候选，记录原因，不假设未知病毒不存在。
- 原候选及其准备项先生成以供回退；新路径成功后以联合短名单替换候选池，旧的单独撤离保留计数清零。信息／防守奖励及最终实际评分不变。
- `node_limit` 仍限制昂贵候选评价数，不等于全部枚举数。完整轻量枚举是原子阶段，软墙钟可能超限；暂不切换默认。需要先测质量，再按投影数量优化成本。
- trace新增 `candidate_policy`、`joint_candidate_diagnostics`，记录是否启用、回退、原后验抽样组数、质量、暗牌覆盖数、枚举和投影次数。组数不等于唯一身份表数；压力场景数不能当后验样本数。

## 验证与运行

组件验证显式3:1质量、攻击重复／不均衡数量不改变质量、组内混合身份拒绝、空组／非法质量拒绝。公开接口覆盖完整／部分提交、角色计数仍为原粒子数、输入不变；高不安回退的候选和决策与legacy一致。专项34项及CLI／报告相关69项已通过。

首个FS01 seed0完整烟测，两版均行动胜、均先输1轮；旧约13.6秒、新约20.6秒，并发诊断计时，不作正式速度或棋力提升结论。

```powershell
python -X utf8 -m benchmarks.ai_self_play --protagonists particle_ensemble --protagonist-candidate-policy joint_threat --dark-card-policy adversarial_guard --strategy joint --games 1
python -X utf8 -m benchmarks.ai_matrix_validation --scenario official-fs-01-first-script --scenario official-btx-04-young-womens-battlefield --comparison guard_joint_candidates --mastermind-nodes 4 --protagonist-nodes 4 --worlds 4 --workers 4 --output references/ai-calibration/fair-joint-new.json
```

`guard_joint_candidates` 比较相同攻击集下的legacy／联合候选；`matrix_joint_candidates` 比较相同单暗牌抽样下的两者。默认seed0–9，支持任务ID续跑，双方固定工作量。首个40局报告 `references/ai-calibration/2026-10-16/fair-joint-candidates-10seeds.json`；评测期间冻结生产Python，完整报告后再分析同种子差异。

## 完整结果与下一缺口

源码 `7cbbc3ad…`，完整 **890项通过（225.886秒）**；日志 `references/fair-joint-candidate-regression-20261016.txt`。默认legacy路径与Git `0826ea2` 的旧benchmark／旧公平策略做四组完整对照，47根／663命令的决策、replay、技能、失败、终猜及最终信念相同；报告 `verify_fair_joint_baseline.json` 含Git文件SHA。

两个剧本各seed0–9，两策略40局全部完成；黑方联合候选4，红方候选4、原后验抽样4、相同adversarial_guard攻击集，固定工作量：

| 剧本 | legacy候选 | 联合候选 |
| --- | ---: | ---: |
| FS01 | 6/10 | 7/10 |
| BTX04 | 0/10 | 3/10 |
| 总红胜 | 6/20 | 10/20 |

6组改善、2组退化，配对p=.289；样本／剧本限定，不能称统计显著或普遍优势。442根／6508命令的回放、公开硬证据与矩阵真值全部审计通过。新策略159根使用联合空间、57根显式回退；保留默认legacy。长任务的60秒faulthandler堆栈为诊断输出，40局均正常终止，没有任务失败。

FS01 seed9退化根已定位到第2轮第4天。选牌为女学生禁止密谋、城市／医院无效填充；4个原身份样本都确定女学生关键人物、巫女杀人狂。既有guard分支在每个样本均无失败；逐槽合法单牌覆盖则在每个样本各找到1个失败——移动男学生离开，让女学生与巫女单独相处。不能把这次漏防归因于身份矩阵未确定或需要硬调角色概率。

同一批角色／当事人、相同权重、额外攻击不进后验，补入边缘覆盖后重新联合排序，得到4个方案，均通过其全部扩展场景的真实引擎／既有技能路线。该反事实不保证全联合暗牌完备；实际对局指令和replay与原报告完全一致，诊断未改变游戏。原始审计 `audit_fair_marginal_gap.json`，脚本同名 `.py` 在2026-10-16忽略目录。

下一阶段新增独立暗牌覆盖策略：保留原攻击模板并补全合法单因素分支，物理暗牌签名去重，原后验组质量不变。先为移走旁人的致命分支加正式回归，再与本版在相同联合候选下消融；后续再迁移候选条件化联合反例。FS01另一个退化seed6的谋杀失败需单独审计，不由seed9归因外推。
