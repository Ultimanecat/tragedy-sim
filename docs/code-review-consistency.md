# 代码一致性审查汇总与修复台账（2026-10-29）

## 目的

按三类问题做一次全仓一致性审查：

1. 已实现但从未调用（死代码、只被自身测试覆盖的 API）。
2. 硬编码或临时算法桥接（魔法阈值、写死角色/剧本/天数、绕过正式接口的适配）。
3. 假实现 / mock 当真实（常量桩、占位 fallback、注释声称已实现但未接线、文档与代码不符）。

四个子审查分别负责 day_game、AI/信念/搜索、引擎/规则、服务/前端，各自输出带 `file:line` 证据的报告。

## 分报告

| 范围 | 报告 | 条数 |
| --- | --- | --- |
| day_game | [review-day-game.md](review-day-game.md) | 24（高 3 / 中 11 / 低 10） |
| AI、信念、搜索 | [review-ai.md](review-ai.md) | 27（中 13 / 低 14） |
| 引擎、规则 | [review-engine.md](review-engine.md) | 17（高 2 / 中 7 / 低 8） |
| 服务、前端 | [review-service.md](review-service.md) | 24（高 2 / 中 9 / 低 13） |

## 跨报告的共同结论

### 1. day_game 目前是离线诊断层

`tragedy_sim/` 生产代码没有导入 `tragedy_sim.day_game` 的调用点；只有 `tests/test_day_game_*.py` 和诊断脚本使用。这解释了 2026-10-28 的整局对照为何只是"脚本包装粒子策略"，而不是分层估值接入。

处理决定：

- 保留该定位，在包文档和路线图继续写明"离线诊断，未接默认 AI"。
- 唯一整局接入脚本从被忽略的 `references/` 移入 `benchmarks/`，纳入版本控制：`benchmarks/ability_guard_probe.py`、`benchmarks/ability_guard_diagnostic.py`。
- 在真正接入前，不给 day_game 增加生产入口。

### 2. "已实现但未调用"主要集中在三类

- 历史/替代策略：`IsmctsProtagonistAgent`、`SurvivalIsmctsProtagonistAgent`、`legacy_joint_search` 分支、`PersistentBeliefState.sync`、`BeliefParticleFilter`。
- 非默认候选策略：`candidate_policy="joint_threat"` 的 `JointActionSpace`、`JointThreatRanker`；`final_guess_policy=cast_map`。
- 只被测试使用的原型契约：`tragedy_sim/domain/**`、`wm.cast_spell`、阶段扩展 `extended/replaced`。

处理决定：先修行为错误，再逐项决定删除或标注。本轮不批量删除，避免在缺少基准的情况下扩大风险；每项在下面的台账里给出处置。

### 3. 硬编码集中在"角色 id + 剧本 id + 天数 + 阈值"

- 引擎/规则：`PLOT_TARGETS` 13 条剧情映射、坐标表副本、`module in {...}` 能力差异、`role_slots` 未校验身份集合。
- AI：`belief.py` 的角色数 6 阈值、软 witness 接受常数、暗牌历史先验常数、信息奖励 0.012 上限。
- day_game：`threats.py` 的角色集合与严重度表、`defense_capabilities.py` 的卡牌 id、`plan_search.py` 三牌/64 步。

处理决定：阈值类抽成具名常量或参数（已完成一部分），角色/剧情类改为从 `catalog` / `ModuleSpec` / 剧本元数据读取（列为后续项）。

### 4. 假实现中最危险的是"叶值 / 终局语义"

- `DefenseLeafEstimator` 曾恒 `hard_ok=True`、非终局 `survival=0.5`，导致 `loop_end` 与 `survived_day` 同分。
- `advance_two_days` 曾让调用方叶值覆盖失败终局。
- `DayTransitionResult.lost` 曾把尚未结算的 `final_guess` 算作失败。

处理决定：三处都已修，并加回归测试。

## 已修复（本轮提交）

| 提交 | 内容 |
| --- | --- |
| `8e83dab` | `PublicStateDeterminizer` 硬编码只允许 `protagonists` 阶段，日初重建粒子永远为空；`role_distribution` 已知角色覆盖后验；新增公开事故时间表 API。 |
| `0e226ec` | 幻想版图回声重复计入禁止密谋；剧本指定的从者/手下初始区域未写入 `_loop_initial_locations`；`DefenseLeafEstimator` 恒等叶值；`advance_two_days` 失败终局被叶值覆盖；`lost` 混入 `final_guess`；`_first_legal` 取 `actions[0]`；`plan_counter_defense` 静默丢弃非 transfer 能力；`resample_branch` 粒子数默认不一致；`plan_search` 文档与行为不符。 |
| 本轮后续 | `oracle_protagonist` BTX 日终分数二次线性变换；`belief.py` 死分支；`belief.py` 角色数阈值具名化；`belief_planner` `part_timer` 回填；能力诊断脚本纳入 `benchmarks/`；`secret_dossier` 对 `initial_location`/`role_source` 的 KeyError 与 `part_timer_question` 缺键；GUI/CLI 缺 AHR 里身份；CLI `--lang` 未接入视图与 AHR 终猜键；4 项 `loop_options` 的 `IndexError`；伪 Bearer 解锁高限流；MZ+ 宣称动词；witness 死亡线索漏 `revived`/`character_arrived`。 |
| `ed1359b` 与本轮 | 删除 `ismcts` 的 `legacy_joint_search` 死分支与 `_legacy_bundle`；软 witness 接受曲线与暗牌历史先验抽成具名常量；`plan_search` 的三牌/64 步/候选上限参数化并写进结果；SSE 事件流在房间禁止旁观时要求有效令牌；`common/roles` 的 `(not False)` 与预言家报错文本；`--practice`/`--gui` 重复 parser 参数；`DEFAULT_PORT` 常量；能力诊断按公开事故类型选择目标，不再只看最早事故。 |

修复都带回归测试：

- `tests/test_engine_review_regressions.py`：回声禁止密谋计数、剧本初始区域。
- `tests/test_day_game_threats.py`：后验合并、优先级、公开事故表。
- `tests/test_day_game_observation.py`：日初分支真实重采样。
- `tests/test_day_game_defense_value.py`：叶值区分存活/失败。
- `tests/test_oracle_protagonist.py`：BTX 单次分数变换。
- `tests/test_scenario_library.py`：4 项 `loop_options` 展开。
- `tests/test_service.py`：伪 Bearer 令牌不被认为已认证。

## 待修台账

按"先行为、后结构"排序。

### 已处理：行为正确性

| 项 | 证据 | 处置 |
| --- | --- | --- |
| `loop_options` 第 4 项起 `IndexError` | `scenario_library.py:36-46` | 已修：第 4 项起用 `-loops-<n>` 后缀，加回归测试 |
| 伪 Bearer 解锁高限流 | `server.py:175-181` | 已修：只有会话／房间真实令牌才算已认证 |
| SSE 无令牌绕过旁观限制 | `server.py:76-97` | 已修：房间禁止旁观时要求有效令牌 |
| `secret_dossier` 缺键崩溃 | `hotseat.py:284-299` | 已修：`initial_location`/`role_source`/`part_timer_question` |
| GUI/CLI 缺 AHR 里身份 | `hotseat.py:280-288`、`cli.py:287-293` | 已修：资料页列出 `hidden_roles` |
| witness 死亡线索漏复活／登场 | `witness_rules/common_death_clues.py:22-39` | 已修 |
| MZ+ 宣称动词错 | `cli.py:267` | 已修 |
| CLI `--lang` 未接入视图、AHR 终猜 KeyError | `cli.py` 多处 | 已修 |

### 需要规则确认（未改）

| 项 | 证据 | 原因 |
| --- | --- | --- |
| FS/BTX `role_slots` 接受未实现身份 | `rulesets/scenario_roles.py:114-120`、`common/roles.py:4-9` | 已修：`role_slot_pool(module)` 以该模组规则 X/Y 能引入的身份为白名单，FS/BTX 拒绝 prophet 等，MC-10/MZ-07 仍通过 |
| 侍从随行 `forced=True` 未被 `move` 读取 | `rulesets/characters.py:117-142`、`effects/movement.py:6-15` | 需要确认随行是否无视禁行／移动锁 |
| 幻想回声是否计入"同一张牌"禁止计数 | `engine.py` 回声逻辑 | 已按"同一张牌只算一次"修；仍需对照官方 FAQ |
| common/legacy 两份 `_ahr_incident` 语义不一致 | `common/incidents.py:115-185`、`legacy/incidents.py:356-461` | 需要确认哪份语义正确，不能只按代码删 |

### 需要设计或前端验证

| 项 | 证据 | 原因 |
| --- | --- | --- |
| `mastermind_search_clone` 对主人公策略也提供全信息 | `service.py:468-478`、`rooms.py:510-518` | 主人公 oracle 本身是开眼诊断策略，需先决定房间是否允许开眼 |
| 联合候选／威胁排序非默认路径 | `particle_ensemble.py:720-737` | 需决定是否作为正式可选策略 |
| `joint_mastermind` 每次评估新建估值器 | `joint_mastermind.py:108-113` | 缓存会改变 RNG 序列，需要配对验证后再改 |
| 私有成员跨模块调用 | `evaluation.py:184-208` 等 | 需要先设计公开只读接口 |
| Web 返回大厅不释放座位 | `web/src/App.tsx:851-857`、`989` | 已修：先关闭/离开房间再清本地状态，失败保留房间 |
| Web 契约 fixture 漂移 | `web/src/App.test.tsx:11-12` | 已修：`benchmarks/snapshot_protocol_fixtures.py` 生成快照，`tests/test_web_fixtures.py` 守卫键集漂移 |

### 已完成的清理

| 项 | 证据 | 处置 |
| --- | --- | --- |
| `ismcts` 的 `legacy_joint_search` 死分支 | `ismcts.py:45`、`230-256`、`304-389` | 已删除，含 `_legacy_bundle` |
| `belief.py` 死分支、魔法阈值 | `belief.py:1205-1215`、`898` | 已删除／具名化 |
| 软 witness 接受曲线与暗牌历史先验 | `belief.py:745`、`1577-1586` | 抽成模块常量 |
| `particle_ensemble` 塑形常量 | `particle_ensemble.py:522`、`790-830` | 抽成模块常量 |
| `plan_search` 三牌／64 步／候选上限 | `plan_search.py:37-103` | 参数化并写进结果 |
| `PublicBeliefPlanner` 占位 fallback | `belief_planner.py:399` | `choose_action` 标为抽象方法 |
| `common/roles` 的 `(not False)` 与预言家文案 | `rulesets/common/roles.py:35-39` | 简化 |
| 未使用 CLI 参数、重复端口常量 | `cli.py:469-470`、`server.py:8765` | 删除／提取 `DEFAULT_PORT` |

## 配对对照复核（干净工作区）

修复后重跑 `python -m benchmarks.ability_guard_probe 6`（BTX01、固定黑方、固定节点预算、seed 0–5）：

| 策略 | 胜局 | 计划动作数 |
| --- | --- | --- |
| 普通粒子 | 4/6 | — |
| 能力门控 + 分层选择 | 4/6 | 0／0／3／18／21／24 |

六个种子胜负完全一致，能力链确实执行（seed 0/3/5 各 4 次 transfer 请求），但结果不变。

对比三次迭代：

1. 旧版（时间上限、无条件铺垫）：0/3，明显退化。
2. 加公开时间表门控：5/8 对 4/8，仅 seed 0 翻转。
3. 按公开事故类型选目标 + 只看目标事故作硬威胁：4/6 对 4/6，无差异。

结论：测量与目标选择缺陷已修（可重复、按事故类型、按截止日），能力链也能执行，但 BTX01 这些种子的实际失败来源是 `主人公死亡`、`时间旅行者日末能力`、`亲友死亡`，第 5 天大小姐自杀不是瓶颈。分层估值仍未在真正需要长期防守的局面里被检验。

## 验证

- 全量 pytest（12 worker）：1197 passed、1 skipped、1179 subtests，约 46 秒。
- 定向：`tests/test_engine_review_regressions.py`、`tests/test_day_game_*.py`、`tests/test_oracle_protagonist.py`、`tests/test_particle_ensemble.py`、`tests/test_ismcts.py`、`tests/test_belief.py`。

## 纪律

- 修复前先复现，修复后加回归测试。
- 只改行为明确的缺陷；规则本意不确定的进"存疑待确认"，不猜。
- 每批修复后跑全量；本地提交，推送由用户决定。
