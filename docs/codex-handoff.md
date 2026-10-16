# Codex 会话交接（2026-10-16）

先执行 `git status --short --branch`、`git log -8 --oneline`。以当前源码、[AI路线图](future-roadmap.md)和本页为准；专题报告保存历史证据，不按历史段落的“下一步”重复开发。保护用户附件 `.codex-remote-attachments/`。

## 当前状态与在途任务

- 最新只读复查已完成，生产仍2527183：seed2漏的是两槽联合条件。女学生斜移单因素保留原“职员不安−1”，谋杀不触发；同时把职员牌改为禁止友好即触发谋杀、关键人物死亡，第三张医生牌保持原横移即可。四组控制结算轻量评分／引擎一致，详见 [联合遗漏因果报告](joint-dark-probe-miss.md)。当前该组25/504黑牌、红方枚举47904套；替代计划只能防已找出的反例，尚未证明全攻击下有必胜方案。诊断session33054已正常退出，无在途任务；用户本次要求诊断，未实现新策略。
- 当前生产Python指纹 `9c41de0c…`：可选 `action_role_sampling_policy=residual_small` 已接入公平红方、self-play及矩阵评测；完整907项通过（271.093秒），12项抽样专项。默认IID、sampled暗牌、legacy候选及大厅／黑方内部回复均未切换。小精确支持逐项认证合法联合当事人后做残差抽样；未知／超预算／组合相关拒绝明确回退IID且不耗额外抽样RNG，诊断记录原质量和实际副本数。见 [行动抽样](small-role-action-sampling.md)。
- 本阶段所有任务已正常退出，无在途评测：full test12661、生产配对94744、原型90869、恢复旧评测46455、联合攻击审计76019。旧54764已消失，确认无存活Python后严格resume补末2局，原38局保留。不要继续轮询这些句柄，也不要重跑已完成样本。
- 源码 `b55296ad…` 的边缘攻击覆盖40局全部完成：FS01旧guard7/10→marginal6/10，BTX04为3/10→0/10，总计10/20→6/20、2改善／6退化、p=.289；449根／6902命令审计通过，不切默认。最后BTX04一局约519秒，联合排序成本仍高。报告 `fair-marginal-guard-10seeds.json`，见 [边缘覆盖](fair-marginal-guard.md)。
- FS01残差原型10seed：IID6/10→残差5/10、3改善／4退化。生产20局复跑已验证：IID10局与冻结旧版、残差10局与原型，完整决策／replay／技能／失败／终猜及逐根候选评分全部一致；103根／1498命令审计通过，不把复跑重复计入胜率。报告 `fair-residual-production-10seeds.json`、`verify_residual_production.json`。
- 最新明确缺口：seed0末日“后验职员杀手.25、行动4样本全遗漏”已在同根以4套完整支持修复；seed2第2轮第2天身份4套和谋杀当事人职员都已覆盖，边缘攻击仍把所选三牌判全存活。固定同根／原样本的合法联合牌检查找到 `d女学生+fg职员+fp医生` 在incident_pressure路线致败，所有marginal分支均漏测。原始 `audit_residual_seed2_joint_gap.py/.json`；下步优先公平的候选条件化反例，不能继续仅调身份概率。
- 前期公平联合候选 `7cbbc3ad…` 40局为6/20→10/20，6改善／2退化、p=.289，442根／6508命令审计通过；开眼worst暗牌状态40局16/20→20/20，均为有限实验，保持开关。详细历史读专题文档，不再等待已退出旧进程。
- 保护用户附件 `.codex-remote-attachments/`；`references/` 忽略，不强制提交。当前无前端改动。

## 已完成的关键基础

- 证据、行动、终猜三条路径分离；witness按规则集组件化，硬域／剧情数量／析取及完整matcher保留。always／never来自逻辑证明，未采到不写never，12/12不写always。
- 后验有共同target/q、重复质量、独立RNG和ESS；批次固定 `min(192, capacity)`，不按随机ESS停采。证据维护不占行动节点或行动墙钟。见 [后验精度](matrix-posterior-accuracy.md)、[支持审计](exact-role-support-audit.md)。
- 完整身份表终猜概率、压缩计数与逐观察日志已实现；38份轨迹／7405点精确可用。可选 `cast_map` 与 `exact_partition` 保留实验，当前真实棋力未证明提升。边际概率不能当整套猜对概率。见 [终猜实验](cast-marginal-final-guess.md)、[概率日志](final-guess-probability-audit.md)。
- 共享 `JointActionSpace` 支持席位资源、部分出牌、无效填充与必要防守析取；联合轻量评分、合法暗牌单因素覆盖、候选条件化反例迭代已接入开眼。FS01旧根在504合法暗牌×三条固定技能路线内全存活；不代表任意技能顺序的完备证明。见 [共享空间](joint-action-space.md)、[反例防守](counterexample-defense.md)。
- 地点效果压缩保留实体牌成员与限次消耗，轻量排序增量缓存保留有序分数；旧8局843命令完全等价。mean／worst在缓存容量0/1/64时追加场景与重算相同。
- 已修公共技能有害正向计数偏好、开眼零值降计数与角色相关杀人／复活；开眼技能使用私密副本，真实接受／拒绝后估值；已知无病毒允许高不安联合搜索，病毒仍保护。病毒变身后的开眼暗牌样本保留当前身份，公平helper不读取真实身份。见 [技能执行](oracle-skill-execution.md)、[未来事件成本](future-incident-defense.md)。

## 接下来

1. 安全排序修复及完整回归／16局行为对照已完成，不再重复等待旧进程。
2. 日志计时修复已验收，后续调优读取候选selection_key／存活／状态值解释决策；不要重启旧评测。三牌规划耗时仍不等于所有技能选择或端到端耗时。
3. 公平联合候选、边缘覆盖及残差抽样均已实现并跑完对照，默认不变。优先迁移候选条件化联合暗牌反例：在每个原角色／当事人组内查证并加攻击，所有候选在共同扩展场景复评，原组质量不变。已有seed2真实授权根及引擎反例，先写可提交的合成回归；不能让不同组各自选最佳计划再平均。更大预算／完整小支持显式加权和BTX04跨日准备另做消融。
4. 增加留出FS／BTX标准／Easy及11角色BTX-41；先开眼诊断，再公平规划。黑方升级、信息隐藏／终猜概率、短跨日分别实验。MC的witness／矩阵迁移在公开规划可靠后启动，其他长期项读路线图。

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
| witness／AI | `witness_components.py`、`witness_rules/`、`witness.py`；`joint_mastermind.py`、`strategic_mcts.py`、`oracle_protagonist.py` |
| 执行／网络／存档 | `ai_registry.py`、`ai_decisions.py`、`service.py`、`rooms.py`、`server.py`、`scenario_library.py`、`replay.py`、`transcript.py` |

红方仍为有限共同世界／根候选规划器，尚无完整跨日信息集树。红方8节点约为8个三牌候选，与黑方MCTS节点意义不同。默认身份目标为公开setup下等权剧情组合、每剧情内合法印刷初始身份等权，乘硬兼容及 `2**soft_score`；先验／软似然未校准成人类分布。

房间用 `AiDecision.card_plan` 原子提交；CLI／rollout缓存后两牌，按正式引擎单步执行。执行器不从Trace取行动，模拟不走HTTP／SSE。部分出牌只补未出席位，多人权限不得扩大成团队权限。

## 易错规则与信息边界

- 同时点先同时触发强制能力，再由控制方排序可选能力；两个杀人狂单独同处同时死亡。
- 主人公各有独立限次牌，可各用禁止移动、不安−1、友好+2。同日友好+1/+2冲突用引擎合法行动校验。相同方向移动只计一次，不抵消；不同方向组合用正式规则。
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
