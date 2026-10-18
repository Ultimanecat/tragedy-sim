# Codex 会话交接（2026-10-18）

先执行 `git status --short --branch`、`git log -8 --oneline`。以当前源码、[AI路线图](future-roadmap.md)和本页为准；专题报告保存历史证据，不按历史段落的“下一步”重复开发。保护用户附件 `.codex-remote-attachments/`。

## 当前状态与下一步

- 核心方向及长期接口见 [联合行动博弈内核](certified-day-game-design.md)。T0.1–T0.3已完成；精确混合策略实现与验证见 [专项报告](exact-day-mixed-strategies.md)。默认AI未改，最终目标为整局获胜概率。
- T0.4进行中：[分块公平内核及菜单缓存](exact-day-fair-worlds.md)、[公开联合后验桥](public-posterior-day.md)和[兼容隐藏历史](compatible-history-day.md)已验收。中途根可用独立`history_node_limit`重放完整事件／自身命令；同setup多历史作为对抗列，原质量只计一次。预算不完整需拒绝或显式`allow_state_prior`，后者不认证完整隐藏状态。下一步改善观察政策和信息集能力树，完整transition继续作裁判。
- 当前Python指纹 `bfc136fc…`；完整回归1055项通过（366.656秒，`references/exact-day-history-regression-20261018.txt`），针对性55项通过。全量退出0，HTTP收尾出现一次连接中断后台日志，功能断言均通过。FS01压力根的12个setup均完成51节点历史重建，原质量1/10，无状态先验质量；原生可变状态核对见历史支持报告。
- 内置跳过政策的菜单依赖特化已完成：完整规则状态缓存可复用相同日末值，自定义／子类政策仍保留授权历史。两世界固定24项2.844→0.497秒；FS01、FS02及中途公开根固定工作量结果等价。只优化该确定性政策及日末0/1效用，未切换默认AI，也不构成整局棋力提升证据。
- 新发现待修：`PublicSkipOptionalPolicy`v1只识别`pass`，原生可选技能菜单使用`next`，可能选中首项技能。下一步单独修复、更新政策版本并验收；历史性能报告针对旧版本，不可直接当新政策的棋力／耗时证据。
- T0.3历史FS01第2轮第2天压力根的全域界仍为[1/2,1]，两个红牌各1/2经原生504列／509单元格核验保障1/2，未证明最优；此前499存活／5失败为单候选列计数，均不是对弈胜率。默认仍IID、sampled暗牌和legacy候选。
- 已确认单因素暗牌遗漏：FS01 seed2根中保护性的“职员不安−1”掩盖“女学生斜移＋职员不减不安”的联合攻击。四组控制结算评分／引擎一致，见 [因果报告](joint-dark-probe-miss.md)。尚未证明该根有统一必胜防守，优先全域对抗验收，勿只调身份概率。
- 当前无在途评测，不再轮询旧句柄。历史版本、实验数字、旧任务ID与原交接全文见 [归档](archive/README.md)；`references/`中的本机原始资料不会随新clone提供。

## 已完成基础与阅读入口

- witness／硬域／析取／完整matcher、矩阵共同target/q与独立RNG、联合当事人和整套终猜概率已接入；读 [后验精度](matrix-posterior-accuracy.md)、[支持审计](exact-role-support-audit.md)、[终猜实验](cast-marginal-final-guess.md)。
- 联合三牌空间、有限暗牌压力、已知世界反例迭代和效果缓存已实现；现有策略限制与有限能力定式不等于全域精确，读 [共享空间](joint-action-space.md)、[反例防守](counterexample-defense.md)及核心设计。
- 日志计时、存活排序、技能执行及病毒当前身份同步已修复；阶段证据保留在归档／专题报告，避免重复开发。源码、规则和下列信息边界仍须逐项核对。

## 代码入口

下列路径相对 `tragedy_sim/`：

| 方向 | 文件 |
| --- | --- |
| 正式裁判／阶段 | `game.py`、`engine.py`、`phases/`、`effects/`、`rulesets/` |
| 公平规划／世界重建 | `particle_ensemble.py`、`belief_planner.py` |
| 身份／剧情后验 | `belief.py`、`belief_posterior.py`、`belief_matrix*.py`、`belief_role_solver.py`、`belief_partition_sampler.py`、`action_role_sampling.py` |
| 当事人／暗牌域 | `belief_culprit_constraints.py`、`belief_culprit_posterior.py`、`belief_dark_constraints.py` |
| 终猜／审计 | `final_guess_probability.py`、`belief_audit.py`；另有 `benchmarks/ai_causal_audit.py` |
| 防守空间／攻击 | `joint_action_space.py`、`joint_defense_ranker.py`、`dark_attack_scenarios.py`、`defense_counterexamples.py` |
| 完整日末基准／缓存 | `day_game/{cards,continuation,pure,keys,kernel,cached,local_cards,compiled,edges}.py`；`benchmarks/ai_exact_day.py --backend compiled`（默认reference），测试`tests/test_day_game*.py` |
| 精确混合策略 | `day_game/{matrix,zero_sum,engine_game}.py`；`benchmarks/ai_exact_day.py --mode mixed --backend cached`；有理数LP、完整域最优回应、Double Oracle与可靠区间 |
| 有限世界公平内核 | `day_game/{bayesian_matrix,bayesian,fair_engine}.py`；`benchmarks/ai_bayesian_day.py --worlds <json>`；显式世界输入，公开后验入口见下一行 |
| 公开后验桥 | `day_game/{posterior,public_day}.py`、`benchmarks/ai_public_day.py --view <json>`；只读团队视图，共用角色分区／合法联合当事人，保留失败质量与重建范围 |
| witness／AI | `witness_components.py`、`witness_rules/`、`witness.py`；`joint_mastermind.py`、`strategic_mcts.py`、`oracle_protagonist.py` |
| 执行／网络／存档 | `ai_registry.py`、`ai_decisions.py`、`service.py`、`rooms.py`、`server.py`、`scenario_library.py`、`replay.py`、`transcript.py` |

红方仍为有限共同世界／根候选规划器，尚无完整跨日信息集树。红方8节点约为8个三牌候选，与黑方MCTS节点意义不同。默认身份目标为公开setup下等权剧情组合、每剧情内合法印刷初始身份等权，乘硬兼容及 `2**soft_score`；先验／软似然未校准成人类分布。

房间用 `AiDecision.card_plan` 原子提交；CLI／rollout缓存后两牌，按正式引擎单步执行。执行器不从Trace取行动，模拟不走HTTP／SSE。部分出牌只补未出席位，多人权限不得扩大成团队权限。

## 易错规则与信息边界

- 同时点先同时触发强制能力，再由控制方排序可选能力；两个杀人狂单独同处同时死亡。
- 主人公各有独立限次牌，可各用禁止移动、不安−1、友好+2。同日友好+1/+2冲突用引擎合法行动校验。相同方向移动只计一次，不抵消；不同方向组合用正式规则。
- `choose`编号从1起；带数字选项的资源顺序不能随意规范化。真实FS01根还要防职员密谋2→行动加1→同区医生主谋加1→日末杀手杀死主人公，保护女学生不覆盖这条攻击。
- 数值缓存只服务已知剧本／当日0/1；不能拿来做公平信息集或新续局效用。观察边缓存默认关闭，使用`--edge-cache-capacity N`显式开启；资源原序、完整历史和可变别名入键。紧凑副本不导出完整replay；反事实替换须同步剧作家自己记忆中的牌面，保持红方暗置信息不变。
- T0.3续演读取完整状态，包括私密能力使用标志；知道剧本仍不保证知道这些字段。当前证书只适用于报告声明的完整状态续演模型；单世界迁移也要审计信息集。压力根返回策略在独立核验中没有非平凡红方能力选择，保障未依赖该私密历史。
- 混合策略JSON以`fraction`为准，`value`只作显示；受限矩阵值不等于全域值，界由完整域最优回应给出。未知单元格保留收益范围，不写作0；合法无效果牌也可能影响混合博弈。`DoubleOracle`只可对同一不可变收益模型续跑。
- T0.4每世界质量使用原概率，遗漏质量保留区间，粒子质量加总1不自动证明完整。`--complete-posterior`仅为调用者断言；当前CLI输入假设未自动核实为实际后验，固定跳过技能政策较弱，不能据此报告实战棋力。观察政策不读取私密命令占位符／序号；旧保守信息缓存键不能直接当选招输入。
- 公开后验CLI无真实剧本参数，不能用公开ID查秘密剧本。setup后验完整仍不保证私密使用历史完整；角色与当事人有独立支持计数，失败重建不重新归一化。重建须保留视图角色顺序，数字选项会受顺序影响。证据／重建在行动时钟之前完成。
- 当前引擎末日好感≤2时允许时间旅行者宣败，需3才能挡住；禁止好感无效，失败时间点为末日日末可选窗口，区别于轮回结束。若改阈值必须同步规则、witness、估值和测试。因果线按上一轮好感产生下一轮不安。
- 初始身份、当前身份、能力来源、替代死亡分开。查询返回当前身份，病毒下杀人狂可来自初始平民；安全初始推导另存，不被重查覆盖。原临时工平民答案不能揭露初始身份，替身需映射回初始列。
- 拒绝／申请／同身份群调查不自动给单人答案；硬witness保留全部合法解释。只用结构化timing、kind、公开快照，中文文案、标题、剧本ID不作证据。
- 终猜一次提交整套初始身份，全对才赢；正确数量供审计。Oracle知道答案，不能用其总胜率评估行动防御。
- 公平红方只读合法视图和自己的私密答案。黑方补入公开查询必然透露的知识，病毒历史查询目前用保守知识下界。
- 内部矩阵、世界、Trace、真值诊断、完整存档不进玩家界面／SSE。已知无病毒的剪枝不变量只能用于授权假设作用域；公开高不安不证明有病毒。
- FS01历史失败根职员纵移v会进入医院；横移h去学校会被禁行。不要检查错牌面。BTX06医院当事人为媒体人，巫女是传播的当事人。

## 常用命令与执行纪律

仓库根目录：

```powershell
python -m tragedy_sim --gui --module BTX
python -m tragedy_sim --host-room --port 8765
python -X utf8 -m unittest discover -s tests
python -X utf8 -m unittest tests.test_oracle_protagonist tests.test_joint_defense_ranker tests.test_defense_counterexamples
python -X utf8 -m benchmarks.ai_self_play --protagonists particle_ensemble --strategy fixed --games 1
python -X utf8 -m benchmarks.ai_matrix_validation --output references/ai-calibration/matrix-new.json --max-jobs 4
python -X utf8 -m benchmarks.ai_oracle_defense_validation --scenario official-btx-04-young-womens-battlefield --candidate joint_counterexample --future-incident-policy impact --state-ablation --workers 4 --output references/ai-calibration/oracle-new.json
```

先用 `--help` 核对参数。浏览器 `http://127.0.0.1:8765/`，同Wi-Fi手机使用终端LAN地址。`web/` 中 `npm run build` 后重启服务；另有test／lint／test:e2e。房间和令牌在内存，重启即消失。LL强制四人，其余支持1黑方＋1–3真人红方。

失败按“引擎结算 → 真值hard兼容 → 采样重建 → 候选覆盖 → 同世界评分 → 信息轨迹／终猜”排查。`joint_plan_followup`是缓存续牌；`no_compatible_factor`查身份／当事人，`no_legal_bundle`查联合空间／手牌／公开配置。

常规对照默认4进程、seed0–9、固定工作量、任务ID续跑；记录源码／剧本指纹、难度、seed、对手、horizon、节点、世界数和实际用时。Easy与标准共用秘密，不算独立剧本。计时校准串行空闲；墙钟软截止可原子超限。真实句柄与完整报告共同确认状态，观察超时不重启。评测期间冻结生产Python。见 [实验方法](ai-experiment-protocol.md)。

`references/`忽略，新clone没有本机图片／完整JSON／隔离原型，按专题报告方法重建，禁止force-add。合法可玩剧本以 `ScenarioLibrary.list()` 为准，原始转录源未必已注册。规则图片优先，wiki仅作明确核对，不花大量时间搜索规则书。旧HS／AH、OF、UP主和仙人不在实现范围。

用apply_patch编辑、rg搜索；每阶段验证后 `git diff --check`，明确选文件提交并推送 `origin master`。沙箱遇临时目录／本地HTTP测试权限时按范围申请提升，不跳过测试。AI读 [调优指南](ai-tuning-guide.md)、[witness组件](witness-components.md)、[覆盖审计](witness-coverage-audit.md)；前端／LAN读 [计划](web-and-lan-roadmap.md)、[JSON协议](json-api.md)和 [README](../README.md)。
