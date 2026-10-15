# Codex 会话交接（2026-10-15）

先执行 `git status --short --branch`、`git log -8 --oneline`，以当前源码和 [AI 路线图](future-roadmap.md)为准。本页保留当前实现、验证证据和易错信息；历史实验进入专题报告，不按旧报告的“下一步”开展工作。

## 最新状态

新增开眼实验 `dark_state_policy=mean|worst`（默认 mean）：身份内对暗牌取最低状态分，同时用于轻量候选排序和真实续演；当前存活排序及限次成本保持。worst 排序器拒绝混合身份／剧本。完整879项通过，四剧本16局均审计通过，最终两版8/8，轮回失败2→0：BTX04 seed1/6由各先输一轮改为首轮胜。更强黑方16预算、BTX04／06各10 seed共40局已启动，报告 `references/ai-calibration/2026-10-16/dark-state-btx-10seeds-black16.json`，须读取progress确认完成；进程工具session88968，源码指纹fa420597…，评测期间不修改Python。另已修复病毒变身后开眼暗牌样本遗失当前身份；公平 helper 不复制私密身份。公平主线未切换，未来需先身份内评价暗牌、再按后验聚合身份。见 [保守状态估值](dark-state-defense.md)。

最新实验 `future_incident_policy=legacy|impact`（默认 legacy，公平内部 helper 未切换），共享既有事件影响权重计算未封顶的未来不安成本，解决已达临界后的额外防守代价低估；临时工运行时当事人也统一解析。完整 875 项通过，四剧本两种子16局均审计通过，最终两版均8/8；BTX06 seed6从先输两轮变首轮胜。BTX04 Day2平均状态分让关键人物吃密谋+2，下一步身份内暗牌最坏状态值，而非继续靠样本次数稀释风险；见 [未来事件成本](future-incident-defense.md)。

最新阶段见 [开眼技能执行](oracle-skill-execution.md)：明确零值降计数、角色相关杀人／复活、私密技能上下文、真实接受／拒绝后的目标估值、已知无病毒高不安不变量。公共技能基线影响双方续演，公平 helper 明确 `script_aware_rollout=False` 不读私密属性。可用 public/script 技能消融，额外转换次数独立统计；完整 873 项通过。BTX06 seed1/6 四局均最终行动胜，但 script seed6 先输两轮。下一步未来致命事件超额不安成本／防线准备，未证明总体棋力提升。

地点效果压缩及增量排序已实现：`tactical_dark_key` 仅合并轻量计算，保留实体成员及限次消耗，真实探测不改牌。`JointThreatRanker.add_worlds` 复用旧前缀，保留有序值统一求和。共同根 504→143 组、排序投影 438915→93837，三种配置的三牌与 4 个引擎反例顺序相同；源 `79f43e05…` 在 FS01／BTX06 seed 0／6 两策略共 8 局，843 命令、完整 replay、决策 SHA、技能及失败原因与原源完全一致。专项 43 项／完整 **865 项通过（227.567 秒）**；之后做事件截止时间／可达性规划，勿把加速当棋力提升。

当前阶段：`defense_counterexamples.py` 实现候选条件化暗牌攻击分离，开眼可选 `joint_counterexample`，暗牌最多 8 轮／16 探测，只有引擎确认的当日失败加入共同场景，再统一复评。明牌分支沿用 `joint_threat`，默认／公平未迁移；不修改信念。共同 FS01 根在 504 合法暗牌×3 定式技能路线全存活，3 轮原型曾退化到 462/504，保留不完备标记和独立穷举验收。专项 57 项／完整 861 项通过；同源 40 局全部审计通过，FS01 两版均 10/10、BTX06 均 5/10，没有胜率提升。下一步用户提出的地点无效牌压缩，及重复投影增量复用；详见 [反例搜索报告](counterexample-defense.md)。

公共技能基线修正已完成代码／专项 98 项／8 局回放审计／最终完整 **856 项通过（251.598 秒）**：正向不安／密谋技能不自动获得解锁奖励，面对可选跳过也不无条件发动。负向计数和正向友好保留，合法空间／随机策略不变。该基线被开眼、公平模拟、黑方近似回应共享；不要称全生产行为未变，出牌候选默认仍保留原配置。源 `e5538b74…` 的 bug 样本两开眼 seed 4 行动胜、seed 9 终猜，没有继续提高样本胜率，下一步联合反例／事件截止时间规划。

防御准备误分类修正：排除正向计数技能及可拒绝技能的保证收益。源 `f6a61a15…`、专项 59 项／完整 853 项通过；8 局 BTX06 bug 样本已完整审计，seed 4 两开眼恢复行动胜、seed 9 仍到终猜，不与上一版 80 局混算。发现公共技能续演把正向不安／密谋统一奖励 90，已复现优先给医院加密谋；下一步修该偏好，再推进联合反例／事件截止时间规划。

当前新增阶段：开眼实验 `joint_threat`、单因素合法暗牌覆盖与三牌轻量联合投影／威胁排序，真实引擎精算所有适用定式技能路线。默认和公平路径未改；约 30 个单因素场景不具有联合完备保证，不得进入后验频数。共同漏防根两开眼 4 候选已防住实际三条路线；全部 504 套暗牌旧存活 448、新 497，剩余 7 套是针对撤离后的联合攻击。下一步优先候选条件化反例迭代。本轮完整回归 **852 项通过（254.826 秒）**；报告与复现命令见 [联合威胁防守](joint-threat-defense.md)，下文 845 项为上一阶段记录。

共享空间首阶段已实现，入口 `joint_action_space.py`。两开眼可选 `candidate_policy="joint_enumeration"`、CLI `--oracle-candidate-policy joint_enumeration`；默认／公平红方／黑方内部回复未切换。18 项新专项与六剧本／18 合成根／288 引擎合法性抽样通过，完整 **845 项通过（193.648 秒）**，日志 `references/joint-action-space-common-batch-regression-20261014.txt`。明牌小域完整引擎最佳结果对照通过；支持前缀、限次资源、无效填充、必要防守合取／析取和联合排序回调。另修复两开眼原有限时首次完整共同批次／部分世界误计存活；最终源指纹 `7016e4c1…` 的 12 个固定工作量共同根决策与前一诊断相同。BTX 不安≥3 时，因病毒的全局 counter mutation 无效操作前提尚不完备，显式回退；不要把公开高不安当病毒硬事实。

新路径依然只有启发式 shortlist：共同 FS01 根新明牌 4 节点退化，16／48 成功；新暗牌 16 成功，旧 16 失败。不是正式棋力结论。接下来优先联合威胁排序与精确轻量筛选、反例迭代，再公平迁移和 10 seed 批量验收。不要把“全域枚举”误报成“全域引擎模拟”。详见 [共享空间报告](joint-action-space.md)。

用户提出有效操作剪枝和强力快速防守设计后，新增 `benchmarks/ai_defense_pruning_audit.py` 和 5 项反例测试，未改变生产 AI。FS01 失败根条件化实质域 13464／约 2.86 ms，BTX04 初始合成根 85404／13.62 ms；32 个 FS01 失败根计划×3 黑方路线实际结算约 1.125 秒。无效填充尚未纳入统计，筛选档不是完整战略证明。完整 827 项通过（194.083 秒），日志 `references/defense-pruning-design-regression-20261014.txt`。详细方案见 [联合防守设计](joint-defense-solver-design.md)，下一步按共享联合空间／明牌基准、暗牌反例迭代、轻量威胁筛选、公平迁移推进。

最新暗牌防守阶段：完整 822 项通过（188.001 秒），日志 `references/dark-guard-regression-20261014.txt`。可选 `dark_card_policy="adversarial_guard"` 已实现，最多 8 个假设内合法进攻分支与一个联合撤离候选；默认仍 sampled，未新增大厅 ID。分支仅用于鲁棒行动评价，不进入 witness、角色／暗牌后验或证据 RNG。`dark_guard_scoring` 单独关闭新撤离候选。详细范围、命令与结果见 [防守审计](dark-attack-defense-audit.md)。

同源码 `af0a4652…` 的 40 局／两剧本／seed 0–9 已全部完成，无失败任务：FS01 旧／新红胜 1/10、5/10，改善 5／退化 1；BTX04 均 0/10。guard 增加实际 rollout，固定候选／世界数不能称等工作量。共同根 4 个假设各 504 暗牌完整枚举：原危险世界存活 448／504，新计划各 504／504；这未穷举身份或所有能力顺序。原始报告 `dark-guard-vs-matrix-10seeds-fixed-work.json`、`fs01-dark-guard-final-exhaustive-audit.json` 在 2026-10-14 忽略目录。

用户最新优先级：检查防守联合空间和开眼暗牌。共同根各人 7 张牌、9 目标，172872 合法三牌；移除区域无效牌后 33624。开眼暗牌 4／8／16 提议选错，但其中有实际安全候选；其 9 个评价世界职员纵移 0/9。明牌开眼成功、暗牌 48 提议成功。因此后续先做共享系统化联合候选与暗牌反例搜索／穷举基准，避免继续添加定式或只调身份权重。

公平 FS／BTX 粒子红方已默认使用 prior 矩阵重要性提议和合法联合当事人。主线构造器、房间工厂、self-play API／CLI、黑方对弈 CLI 一致；两处联合黑方内部红方模型显式保持旧提议＋旧当事人，避免同时更换对手。原始 `FactorizedBeliefState`／历史 ISMCTS 保留旧基线。

新增独立 `final_guess_probability.py` 和可选逐命令概率审计：同身份表跨剧情汇总、精确计数无关排列，硬域／软评分／完整 matcher 保留。默认终猜和行动算法未改，另有可选边缘 MAP 实验。`ai_causal_audit --guess-probabilities --guess-probability-node-limit 100000` 记录最佳概率、旧猜测的新概率及推荐切换；`--guess-truth` 单独开启真值只读评分。日志默认关闭、不使用 RNG、不进入玩家 API／SSE。终猜提交需读 `context.submitted_guess_before_reveal`，终局公开答案后确定身份不能算行动时效果。

首版六份 seed 0 轨迹、1178 检查点：1122 精确、56 超限，无诊断错误。153 次实际求解，其余同模型缓存，无新证据漂移；详见 [概率日志](final-guess-probability-audit.md)。首版结果在忽略目录 `references/ai-calibration/2026-10-13/joint-guess-probability-audit-smoke-100k.json`。

`extra_identity_partition-v2` 提前分开局外人／模仿者身份，修复 BTX-02G 的全部超限；随后 `predicate_role_classes-v3` 按公开规则的成员资格判定及剧情域划分等价身份类别，保留组内完整槽位／性别精确计数。相同六份轨迹在默认 10000 节点上限下 **1178／1178 精确可用**，旧所有可用概率／质量／支持数一致，真值未排除；总诊断约 83→8 秒。11 角色 BTX-41 初始 534 节点精确计数。

BTX06 命令 57 的根因是宽泛能力来源析取要求 6 名角色完整展开，剧情域无差异。旧算法增大上限后完整完成 255505 节点／15.896 秒，新版 1826 节点／0.381 秒；477876 个身份表及 624 套查询逐一对照一致。报告 `references/ai-calibration/2026-10-14/joint-guess-predicate-partition-validation.json`，单根在 2026-10-13 目录的 `joint-guess-predicate-btx06-root.json`。留出状态与边缘 MAP 比较均已完成，不继续按旧超限 TODO 工作。

留出验证完成：38 份完整轨迹、9 个剧本 ID、7405 检查点全精确，最大 3699 节点；真值未排除，17 次正式终猜均记录提交前概率。报告 `joint-guess-corpus-default24.json`、`joint-guess-corpus-imported10.json`、`joint-guess-corpus-hospital4.json` 在 2026-10-14 忽略目录。旧记录的决策来自不同源码；与当前两个策略的同观察比较分开统计。

可选 `ParticleEnsembleProtagonistAgent(final_guess_policy="cast_map")` 已接入，默认／黑方内部仍 `latent_map`；两开发对弈 CLI 有相应开关。17 个真实终猜根两策略答案相同、均 2/17 终猜胜；四局新固定工作量配对均红胜 0/2，终猜前命令一致。独立四角色反例有 3 倍模型概率收益，实际棋力尚无提升证据。已将 `ai_self_play` 支持审计移至实际提交前，新增 scope，包含合法私密知识。BTX04 的舍入等概率排序已修复；相对容差 16ε、绝对零，不按真值改排序。详见 [终猜实验](cast-marginal-final-guess.md)。

额外身份分组阶段完整 780 项通过（193.998 秒），35 项概率／审计专项通过；日志 `references/joint-guess-extra-partition-regression-20261013.txt` 被忽略。

最新并发评测阶段完整 815 项通过（192.483 秒），并发／续跑／统计专项 17 项通过；日志 `references/parallel-evaluation-regression-20261014.txt` 被忽略。固定工作量四局串行／4 进程的完整决策／replay／胜负相同，28.37→9.18 秒。默认 AI 仍为 prior 矩阵重要性路径／latent_map，评测默认 4 进程、0–9 种子、固定工作量。

实验抽样 `role_sampling_policy="exact_partition"` 已接入，两开发 CLI 有同名开关，比较工具 `--comparison matrix_partition`。按组总质量→整数均匀完整身份→条件剧情，显式 q；行动世界直接重抽完整分区，诊断池最多 192 次，保留独立 RNG 和超限回退。完整密度／排名支持与额外身份、性别、病毒、析取经独立枚举验证。源码指纹 `cf985efa…`：集中软证据身份 TV 0.0907→0.0664、ESS 72→192；六剧本 seed 0 固定小预算 12 局红胜旧 3/6、新 1/6，退化两对，不切默认。146 根／2131 命令硬支持／replay 全通过、无回退，详见 [抽样实验](exact-partition-role-sampling.md)。

最具体反例：`partition-fs01-day3-common-root.json`，位于 2026-10-14 忽略目录。FS01 第 2 轮第 3 天，双方已知女学生关键／巫女杀人狂；2 候选扩大世界仍失败，8 候选含能防御的方案，但 48 世界把失败方案也判为全存活并按尾部值选择它。应先查身份×暗牌组合、黑方能力续演／确定化，别直接调软权重或加世界。概率日志 `partition-fs01-belief-probability-audit.json/.txt` 已完成。上述对局、共同根与完整回归均已结束。

归因复查已完成，`partition-regression-cause-audit.json` 绑定输入 SHA256／源码。FS01 同根身份目标 TV=0，4 身份表等权；实际黑牌女学生 h、职员 v、神社 i1。48 世界有两次职员 v，但均非杀手，杀手×v 为 0/48；v 是进入医院的攻击，h 去学校会正确被禁行，别检查错牌面。独立暗牌 20000 抽 v 约 3.37%，历史强制片段压低该组合；明牌实际／重建三条路线全一致。优先在身份世界内做暗牌敌对／危险覆盖对照，避免继续只扩大身份批次。Easy 旧轨迹末轮公开巫女亲友得到唯一解，新轨迹少此观察剩四表；离线补该事实即恢复唯一解，无现有 witness 漏用证据。27% TV 改善是人工压力状态指标，不是六局实战的误差测量。

默认切换源码 Python 指纹 `63b77dfa833503ee7ba5a92f114fd903872e2214806ed98d6b5f1751b3e71c96`：53 项专项通过，完整 759 项通过（178.932 秒）。实际房间选择公平 AI 后，BTX-01G 第一天默认 192 次提议／12 行动世界，无回退，原子执行三张红牌到 reveal；本机耗时 2.246 秒，仅为单根烟测。前端未改。

切换前的同源码 `2398cf4`、Python 指纹 `c395d03e…` 完成：

- 五类公开状态各 16 seed，矩阵平均身份 TV 降低约 30%～53%；缓存开／关完整候选、q 和 RNG 等价。
- 六剧本 seed 0／3、24 局秒级：红胜旧 3/12／矩阵 5/12，改善两对、退化零对；BTX06 终猜下降。
- BTX04／BTX-01G Easy seed 3、四局固定工作量：双方红胜均 1/2，BTX04 终猜旧 5/9／新 7/9，Easy 均 7/7。
- 384 每日根／5575 命令全部 replay 和硬支持审计通过，无行动回退。未发现矩阵表示的致命缺陷；不宣称所有剧本／预算下严格更强或统计显著胜率提升。

完整报告位于忽略目录 `references/ai-calibration/2026-10-13/`，文件 `matrix-posterior-accuracy-192-cached-16trials.json`、`matrix-default-validation-192-cached-seeds03.json`、`matrix-default-validation-192-fixed-work-seed3.json`。Git 中保留 [精度](matrix-posterior-accuracy.md)、[对弈表](matrix-cross-script-comparison.md)和 [默认验收](matrix-default-validation.md)。这些任务均已结束；接续时仍须核对真实进程／报告，不从本文推断新任务是否运行。

权限恢复后临时目录和本机 HTTP 测试均可运行；此前 WinError 5／10013 是受限环境记录，不修改测试断言、网络代码或 Windows 防火墙规避。用户未追踪 `.codex-remote-attachments/` 不触碰，`references/` 不强制加入 Git。

## 下一步

1. 联合概率／压缩计数／边缘 MAP／精确分区抽样及有限暗牌危险覆盖实验已完成，默认暂不换。先建设开眼／公平共用的系统化三牌候选和暗牌反例搜索，以小空间完整枚举校验；将候选覆盖和攻击场景覆盖分别消融。保留角色后验和鲁棒攻击分支的区别，继续同源码多 seed／留出根。Easy 是轨迹信息量不同，别按错误终猜调身份先验。单 witness leave-one-out 归因和黑方预计泄露评分仍待做。
2. FS-02G／BTX04／BTX06 的危险覆盖、联合防御候选和更早的资源准备；保留日末基线，短跨日规划单独消融。
3. 信息收益与黑方实际信念／回应模型，先做终猜概率诊断再讨论信息隐藏与跨轮回价值。
4. 扩默认矩阵版的 seed／标准与 Easy，再按开眼 → witness／矩阵 → 公平规划迁移 MC。更多未来项见路线图。

## 实际算法与代码入口

| 方向 | 入口 | 要点 |
| --- | --- | --- |
| 规则／阶段 | `game.py`、`engine.py`、`phases/`、`effects/`、`rulesets/` | 正式裁判与轻量搜索转移，禁止全局难追踪 hook |
| 公平红方 | `particle_ensemble.py`、`belief_planner.py` | 合法团队观察，完整三牌候选跨共同世界评价 |
| 后验 | `belief.py`、`belief_posterior.py` | 共同目标、分维维护、target/q 与重复质量 |
| 终猜概率／日志 | `final_guess_probability.py`、`belief_audit.py`、`benchmarks/ai_causal_audit.py` | 精确完整身份表归一化、逐观察批次、离线真值查询隔离 |
| 矩阵／支持 | `belief_matrix.py`、`belief_plot_constraints.py`、`belief_matrix_sampler.py`、`belief_role_solver.py` | 硬域／数量／析取，合法完整分配，小空间枚举和 MAP |
| 分区抽样 | `belief_partition_sampler.py` | 实验完整角色／剧情后验、整数排名、显式 q，诊断池与行动世界分离 |
| 当事人／暗牌 | `belief_culprit_constraints.py`、`belief_culprit_posterior.py`、`belief_dark_constraints.py` | 联合重复限制及公开暗牌 all-different |
| 暗牌进攻压力测试 | `dark_attack_scenarios.py`、`benchmarks/ai_dark_attack_audit.py` | 假设内有限攻击分支与联合撤离，离线完整合法牌面枚举，不改后验 |
| witness | `witness_components.py`、`witness_rules/`、`witness.py` | 编译器读观察、matcher 检查世界，按规则集复用 |
| 黑方／开眼 | `joint_mastermind.py`、`strategic_mcts.py`、`oracle_protagonist.py` | 三牌联合、红方回应；开眼仅诊断／趣味 |
| 执行／网络 | `ai_registry.py`、`ai_decisions.py`、`service.py`、`rooms.py`、`server.py` | AiDecision 与 Trace 分离，revision、授权、SSE |
| 剧本／回放 | `scenarios/`、`scenario_library.py`、`replay.py`、`transcript.py` | 严格验证、结构化时间点和确定性重演 |

路径均相对 `tragedy_sim/`。红方为有限根候选规划器，尚无完整跨日信息集树。8 节点表示约 8 个三牌候选，与黑方 MCTS 节点意义不同。每个世界用采样的危险黑方路线评价，跨世界按存活、原始尾部风险与后置平均值排序；有限采样／候选不能证明必胜或无解。

默认身份目标为公开 setup 下等权剧情组合、每剧情内印刷合法初始身份分配等权，乘硬兼容及启发式 `2**soft_score`。先验及软似然未校准为真实人类剧作家分布。新鲜角色重要性批次固定 `min(192, capacity)`，不混入无 q 旧库、不按随机 ESS 停采。行动世界数与身份提议数不同，证据维护不占行动节点或行动墙钟，端到端响应仍有额外成本。

身份／剧情、当事人、暗牌分维维护。析取保留，未投影关系继续完整 matcher 检查；未采到不写 never，样本 12/12 不写 always。主线小空间精确枚举，终猜仍独立压缩 MAP，不依赖行动世界容量。终猜输出的前列边际不是完整后验。

房间通过 `AiDecision.card_plan` 原子提交，CLI／rollout 缓存后两张并按引擎单步执行；已有全部已录入 FS／BTX 标准剧本的等价回归。执行器不从 last_trace 取行动，模拟不走 HTTP／SSE。部分出牌后的重规划只补未出席位；多人权限不得扩成团队权限。

## 易错规则与信息边界

- 同时点先同时触发强制能力，再由控制方任意排序可选能力。两个杀人狂单独同处必须同时死亡。
- 各主人公各自有轮回限次牌；团队可各用禁止移动、不安 -1、友好 +2。同日友好 +1／+2 冲突必须用引擎合法行动校验。
- 时间旅行者好感至少 2；禁止好感无效；其失败在末日日末可选窗口，区别于轮回结束。因果线按上一轮好感产生下一轮不安。
- 查询返回当前身份。病毒下当前杀人狂可来自初始平民；安全初始推导另存 `initial_roles`，不被后续重查覆盖。原临时工平民答案不能揭露其初始身份，替身需映射回初始列。
- 初始身份、能力来源与死亡替代区分，硬 witness 保留所有合法解释。拒绝／申请／同身份群调查不自动给出单人答案。
- 只用结构化 timing、kind 和公开快照推理；中文文本、标题或剧本 ID 不作证据。公开角色配置／禁用牌等需贯通 view → evidence → sample → determinizer。
- 最终一次猜整套初始身份，全对才胜，正确数量仅供审计。Oracle 终猜直接用答案，不能只看总胜率评估行动防御。
- 公平红方只读合法视图和自己的私密答案；黑方仅补入由已完成公开查询必然推知的答案，病毒历史查询目前取保守知识下界。
- 内部矩阵、采样世界、Trace、真值诊断和完整存档不能进入玩家界面／SSE。开发完整 replay 与玩家观察回放遵守各自信息边界。

## 常用命令

从仓库根目录运行：

```powershell
python -m tragedy_sim --gui --module BTX
python -m tragedy_sim --serve
python -m tragedy_sim --host-room --port 8765
python -X utf8 -m unittest discover -s tests
python -X utf8 -m unittest tests.test_matrix_defaults tests.test_role_importance tests.test_role_support_solver tests.test_joint_culprit_posterior
```

本地浏览器 `http://127.0.0.1:8765/`；LAN 手机使用终端显示地址，同 Wi-Fi。前端构建在 `web/` 中执行 `npm run build`，随后重启 Python 服务；前端另有 test、lint、test:e2e。房间及令牌在内存，重启后消失；LL 强制四人，其余支持 1 名黑方＋1–3 名真人红方。

```powershell
# 默认矩阵红方；两个负开关同时使用才是完整旧消融
python -X utf8 -m benchmarks.ai_self_play --protagonists particle_ensemble --strategy fixed --games 1
python -X utf8 -m benchmarks.ai_self_play --protagonists particle_ensemble --strategy fixed --games 1 --no-matrix-proposals --no-joint-culprits
# 新输出名，默认六剧本 seed 0/3、旧/新 24 局，每局强制 replay/硬支持审计
python -X utf8 -m benchmarks.ai_matrix_validation --output references/ai-calibration/matrix-new.json --max-jobs 4
# 同源码/剧本顺序/预算续跑加 --resume；--fixed-work 关闭双方墙钟
python -X utf8 -m benchmarks.ai_matrix_posterior_accuracy --output references/ai-calibration/accuracy-new.json
python -X utf8 -m benchmarks.ai_mastermind_matrix --scenario official-btx-04-young-womens-battlefield --games 2 --seed 1 --mastermind-ms 1000 --protagonist-ms 1000 --protagonist-nodes 8 --protagonist-particles 12 --joint-reply-model belief --trace --output references/ai-calibration/black-new.json
```

先用 --help 核对参数。self-play API 用 `None` 解析实际策略的默认：公平粒子两项 True，其他策略 False；显式给 Oracle 开启报错。联合黑方回复与历史因果工具显式固定旧基线，默认切换不让旧根诊断暗中改算法。

## 诊断与执行纪律

遇到失败按：引擎结算 → 真值 hard 兼容 → 采样／重建 → 防御候选覆盖 → 同世界评分 → 信息轨迹／终猜模型。joint_plan_followup 是缓存后续牌；no_compatible_factor 查身份与当事人，no_legal_bundle 查联合候选／手牌／公开配置。不要只凭增加粒子后胜负变化归因于预算。

常规对照默认并发 4 进程、固定 seed 0–9、固定工作量；支持非顺序任务 ID 续跑，详见 [实验方法](ai-experiment-protocol.md)。限时用时校准保持串行、空闲机器。保留源码、剧本顺序、难度、seed、对手、horizon、节点、世界数和实际耗时。Easy 与标准共用秘密，不能视为独立剧本。报告 progress.complete／paired_summary 及真实进程决定任务状态，观察超时不重启。墙钟是软截止，原子评价可超限；证据时间单列。

`references/` 被忽略，新 clone 没有本机图片和完整 JSON。专题报告有方法和摘要，按新输出路径重建；禁止 force-add 原始产物。原始规则图片优先，日文 wiki 仅作明确规则核对，不花大量时间搜索完整规则书。旧 HS／AH 已被 HSA／AHR 替代，OF 已删除，UP 主和仙人不在角色范围。

用 apply_patch 编辑、rg 搜索，保护用户改动和附件。每阶段验证后 diff --check，明确选文件提交并推送 origin master。AI 调优参考 [指南](ai-tuning-guide.md)、[witness 组件](witness-components.md)、[覆盖审计](witness-coverage-audit.md)。前端／LAN 任务另读 [路线图](web-and-lan-roadmap.md)、[JSON 协议](json-api.md)和 [README](../README.md)。
