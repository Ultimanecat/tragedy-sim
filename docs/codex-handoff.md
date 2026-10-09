# Codex 会话交接（2026-10-08）

本文是新会话的启动入口，整理截至源码提交 `0ec96eb` 的上下文。本次交接只增加文档。
开始工作时先执行 `git status --short --branch`、`git log -8 --oneline`，确认是否已有后续提交或其他会话的修改。

2026-10-09 接续更新：已补充 BTX 日末强制窗口无死亡尝试的反证组件，修正 BTX10 大小姐被误推为杀人狂。
seed 1、8 候选/32 世界的 BTX10 终猜为 1/9→2/9，BTX04 为 5/9→7/9，BTX08 保持 7/9；均仍黑胜。
`ai_factor_audit` 已保存终猜完整合法观察及真值快照，并支持 `--reanalyze FILE` 离线 source 消融。
本次全量 549 项测试通过。
同日后续接续：补充公开历史联合暗牌提议，修复日末／轮回末 Oracle 在末轮失败后用全知终猜误评存活的问题。
BTX10 seed 1、8 候选/32 世界转为第 4 轮直接红胜；两项各自消融仍黑胜 2/9。
BTX04/08 seed 1 保持黑胜 7/9，FS01 seed 1 保持红胜。全量 553 项测试通过。
`ai_factor_audit --capture-action-worlds` 可保存根观察和采样暗牌／身份联合细节，
`--independent-dark-history` 可关闭新历史提议。仅是离线开发报告，禁止进入玩家界面／公开 replay。
继续接续：FS01 seed 0 的第二轮谋杀日缺少移动已知关键人物的候选，新增硬证据引导的逃离候选后红胜，
`--disable-incident-escape` 完整复现旧败局。候选预算保持不变，无额外奖励；555 项测试通过。
`LoopLossRecord` 每轮汇总的跨命令遗漏已修复，死亡／触发事件从本轮完整日志采集至失败时为止。
FS01 实局第 2 天谋杀现正确记录，决策摘要不变，基准工具 13 项测试通过。接下来进行 A2 强黑方对照。
另修复临时工内部替身进入最终猜测、黑方按运行时角色评分的边界问题。
最终猜测始终枚举初始 cast，AHR 保留每名初始角色表／里两面；完整 559 项测试通过。
强黑方矩阵现逐局原子保存，源码指纹在启动时冻结，读取 `progress.complete` 判断是否完成配对。
工具尚无自动 resume；14 项工具回归通过，包括第二局中断时保留第一局。
本文下方摘要表属于加入该组件前的历史基线，最新结果与接续项见 [校准审计](ai-cutoff-calibration.md)和 [路线图](future-roadmap.md)。

## 先读什么

1. 根目录 [AGENTS.md](../AGENTS.md)：平铺直叙；阶段完成并验证后提交、推送远端。
2. 本文，随后读 [AI 路线图](future-roadmap.md)：当前任务顺序以该文件为准。
3. [近期实验与审计](ai-cutoff-calibration.md)：最近三个 AI 切片的证据、反例和完整决策摘要。
4. 按任务读 [AI 调优指南](ai-tuning-guide.md)、[witness 组件](witness-components.md)、[覆盖审计](witness-coverage-audit.md)。
5. 前端或联机任务另读 [Web/LAN 路线图](web-and-lan-roadmap.md)、[JSON 协议](json-api.md)和 [README](../README.md)。

[AI 阶段性总结](ai-current-state.md)和 [历史对弈结果](ai-benchmark-results.md)保留了多个旧版本。
其中团队 ISMCTS 的候选公式、旧胜率、旧回复模型不能直接套到当前粒子集成版。
遇到文档冲突，核对当前源码与实验配置；不要把历史章节中的“下一步”当成最新任务。

## 用户方向与约束

- 这是桌游自动裁判和局域网联机工具；规则引擎、公开信息和结算正确性优先。
- 当前 AI 主线覆盖全部已录入 FS/BTX 剧本，避免长期只在两个 FS 剧本调参。
- 红方指主人公，黑方指剧作家。当前强红方是一名参与者控制 A/B/C 的两人局团队 AI。
  独立三主人公 AI 仍在后续计划；不能把三个完整团队 AI 当三个独立席位。
- 身份/剧情、事件当事人、当前暗牌分维维护。跨维关联按实际反例增加，完整关联模型优先级较低。
- 证据维护与行动节点预算分开。证据用于缩小可能世界和最终猜测；仍须记录它的实际耗时。
- 黑方应建模红方实际知识、暗牌回应和可能信念。`full`/`hidden` 开眼回复用于诊断，正式棋力评测注明回复模型。
- 允许未来用牺牲一轮换决定性信息的策略；尚未实现可靠的跨轮回价值评估。
  用户已撤销早期“不得为了信息故意输掉本轮”的绝对限制。
- 信息类能力价值已有微量 shaping。用户明确反对为提高能力使用率而硬加奖励；降不安、防御等能力同样重要。
  重复调查、目标身份已知、异界人首轮不可用、因果线跨轮回代价都要计入。
- 保留随机、固定、朴素 MCTS 等可选基线；新算法要有对照、消融、trace 和独立提交。
- 秒级、分钟级预算分别评测；必要时显式使用每步数分钟档。相同节点数不等于相同时间。
- 规则书以用户图片为优先。不要花大量时间联网找完整规则书；明确规则问题可查用户给的日文 wiki。
  入口为 `https://w.atwiki.jp/rooper/`，角色表 `/pages/58.html`，多语言表 `/pages/92.html`。
- 不实现旧 Haunted Stage 和 Another Horizon；已有 HSA、AHR 替代。OF 已删除。
  角色范围为 37 张中的 35 张，排除 UP 主和仙人。
- 新官方剧本继续由用户提供并人工核对；远程 ECS 部署是独立方向，当前交接不包含部署授权或凭据。

## 项目现在能做什么

Python 3.11+，后端无第三方运行依赖。CLI、Tk GUI、React Web、JSON 服务和 LAN 房间均已实现。
规则集包括 FS、BTX、MZ、MC、HSA、WM、AHR、LL，特殊行动由后端提供合法行动，前端不重复实现规则。
已有 35 张范围内角色、22 个官方基础剧本；难度展开后 40 个官方可选条目。
其中 FS/BTX 为 13 个基础剧本、25 个难度版本。

支持 1 名剧作家加 1–3 名主人公玩家；两名主人公玩家轮流担任真人队长并代管 C。
LL 强制四人。房间、令牌和状态保存在服务内存，重启后房间消失。
SSE 推送 revision 通知，断线自动重连并临时使用条件轮询。
剧作家及两人局团队红方可在前端编辑三牌草稿，原子提交；三人/四人局红方继续单步。

### 代码入口

| 方向 | 文件/目录 | 要点 |
| --- | --- | --- |
| 规则裁判 | `tragedy_sim/game.py`、`engine.py`、`domain.py`、`model.py` | 正式 dispatch、观察、决策历史；搜索有专用轻量转移 |
| 阶段与效果 | `phases/`、`effects/`、`rulesets/` | 按阶段和规则集组合；部分其他规则集代码仍在 `rulesets/legacy/` |
| 场景 | `scenarios/`、`scenario_library.py`、`scenario.py` | 严格验证；公开目录不能暴露剧情、身份、当事人 |
| 公平红方主线 | `particle_ensemble.py` | 有限三牌候选跨同一批世界评价，日末默认 |
| 信念/终猜 | `belief.py`、`ismcts.py` | `PublicEvidence`、分维粒子、独立完整身份 MAP |
| witness | `witness_types.py`、`witness_components.py`、`witness_rules/`、`witness.py` | 编译器读合法观察，matcher 判定假设，组件按规则集复用 |
| 诊断红方 | `oracle_protagonist.py` | 开眼剧本＋明牌/暗牌，支持 day/loop/match |
| 黑方 | `ai.py`、`mcts.py`、`optimized_mcts.py`、`strategic_mcts.py`、`joint_mastermind.py` | 定式、基线树搜索、三牌联合、belief 回复 |
| 估值/信息 | `evaluation.py`、`information_value.py` | 剧本条件化威胁、微量信息价值，不能当校准胜率 |
| 执行/网络 | `ai_decisions.py`、`service.py`、`rooms.py`、`server.py` | `AiDecision` 与 Trace 分离，revision 和授权在服务层 |
| 回放/语言 | `replay.py`、`transcript.py`、`locales/terminology.json` | 结构化 timing、确定性重演、中英日术语 |
| Web | `web/src/` | 地图拖牌、三牌草稿、手机固定操作栏、回放、图片 |

R1–R3 重构及三牌接口接入已完成。继续实现时沿这些模块分工，避免重新堆进 `Game` 或建立难追踪的全局 hook。

## 当前 AI 实际算法

公平红方主线 `ParticleEnsembleProtagonistAgent` 从合法团队观察建立 witness，分别采样剧情/身份、事件当事人和暗牌。
每个采样世界借 Oracle 提出完整三牌组合，随后将同一组合在同一批世界上交叉评价。
每个世界还采样可用黑方路线，采用最危险的采样路线评价；跨世界按存活、尾部及估值等排序。
这仍是有限根候选规划器，尚未建立完整跨日信息集树。`node_limit=8` 在此处限制约 8 个三牌候选，
与旧 ISMCTS 的访问计数及黑方 MCTS 节点数含义不同。

当前默认 horizon 为日末；公平粒子版支持 day/loop，Oracle 支持 day/loop/match。
长 horizon 的后续行动由便宜策略补全，误差随距离累积。公开阶段与能力选择常回退公开防守策略。
终猜独立调用 `FactorizedBeliefState.exact_role_map`，按完整初始身份分配选择 MAP，不依赖行动世界容量。
目标是整套猜对获胜，逐角色正确数用于诊断。

房间中的联合黑方与两人局团队红方通过 `AiDecision.card_plan` 原子提交；执行器不从 `last_trace` 取实际行动。
CLI、自对弈和 rollout 继续按引擎单步顺序执行，缓存后两张牌；这与房间批量执行已有等价回归。
不要为每个模拟候选引入 HTTP、SSE 或服务层事务复制。

## 最近完成的三个切片

### `a5e1265`：BTX04 稀有硬约束补样

BTX04 seed 1、8 候选/32 世界，原第 1 轮第 4 天后有 24 次 `no_compatible_factor`。
真实设置始终满足硬 witness；独立随机提议很难同时满足恋爱剧情、班长/打工仔恋爱身份和指定杀人狂路线。
现在先保留原拒绝采样路径，仅当它完全没有提议时才用 `condition_hard=True` 补样。
补样后仍通过原场景验证器和全部 hard matcher。原 24 次回退降为 0，该局仍黑胜、终猜 5/9。

曾试过全局使用硬条件提议：BTX04 seed 2 转红胜，但 BTX08 seed 1 终猜从 7/9 降到 6/9。
正式实现已经收窄；前述全局试验成绩不能当作当前算法的成绩。

### `dcfd35d`：FS01 临界事件防守候选

FS01 seed 1、8 候选/32 世界，原两轮都在第 3 天因女学生自杀失败。
第二轮已公开知道她是当事人，她不安 2、阈值 3，黑方又在她身上放暗牌，原 8 个组合却没有“不安 -1”。
`_incident_guard_targets` 根据当天日程、硬 `culprit_is`、公开阈值及暗牌目标补一个合法联合候选。
它占用既有候选名额，仍由共同世界评分，不额外奖励该牌。
新防守在 32/32 采样世界存活，实际第二轮获胜；4 世界仍红胜，BTX04/08 对照摘要不变。

FS01 seed 0 的旧 32 世界报告曾红胜，当前源码败局。关闭这个新增候选仍得到完全相同败局。
此差异早于本次候选修改，历史源码/配置变化仍须追查，不能称为本次修改引起的退化。

### `0ec96eb`：BTX08 终猜审计

BTX08 seed 1、8 候选/32 世界复现 7/9：大小姐被猜为传谣人，实际是不安定因子；
情报商被猜为平民，实际是传谣人。真实剧本通过全部硬 witness。
前四个最高权重候选对这两人的传谣人位置打平，实际“未知因子”剧情的权重更低。
终猜前显式公开确认身份数为 1；其他身份也可能通过 witness 间接受约束。
目前未找到足以确定因子位置或区分这两人的公开证据，因此保留生产评分，扩充诊断输出。

`final_role_candidates=323288` 是 `exact_role_map` 在剧情、角色域预过滤层累计的配置数。
它在路线类硬 matcher 前累计，不能称为“323288 套通过全部硬证据的世界”。
Trace 的 `final_belief_roles` 从返回的前列 MAP 方案汇总，不能当完整后验边际。

### 固定工作量的重复性基线

统一条件：`ai_factor_audit`，固定黑方 2 节点、depth 8；粒子红方 8 候选、32 世界、日末；搜索无墙钟截止。

| 剧本、种子 | 当前结果 | 完整决策 SHA-256 |
| --- | --- | --- |
| FS01 seed 1 | 红胜，失败 1 轮 | `6a8c670fed6775415358485c1ef572f3680911177f63f57252738a220fbb89e7` |
| FS01 seed 0 | 黑胜，关闭事件候选也相同 | `05b7e3c10fa511aaa294f47e0bc703e2861bfb347e45405fd3049dcdd32f818d` |
| BTX04 seed 1 | 黑胜，终猜 5/9，无采样回退 | `0a94cae98f24d9172be72726a22c278fbb99c410e15925142a9966593646b632` |
| BTX08 seed 1 | 黑胜，终猜 7/9 | `063d3244a95f5ef03ed2b54da61bd532aae53e3c0df8a0c419e74efadbe9cebf` |

这些摘要验证当前基线；改变策略后摘要变化本身不算错误，须解释行动和结算差异。

## 接下来建议怎样接续

当前仍处于路线图 A1。最近没有运行中的任务或未提交实现。

1. BTX10 seed 1 的终猜硬反证已补，仍应检查为何各轮重复失去关键人物巫女，以及其他身份的信息可辨识性。
2. 追查 FS01 seed 0 当前与旧报告的源码/配置差异；随后按 seed 0–4 建立当前版本的统一回归。
3. BTX08 的进一步工作应检查信息能力是否能获得决定性证据、原行动候选是否覆盖这些路径、黑方沉默造成何种歧义。
   最终合法观察和 witness 已保存，可通过 `ai_factor_audit --reanalyze FILE` 离线反复分析，减少重跑成本。
4. 分拆证据、候选生成、模拟、终猜求解与整局计时。最后一次 BTX08 审计记录异常高耗时约 3749.8 秒，
   早先同摘要多次约 80–86 秒；目前原因未查明，不能用单次异常测算算法成本。
5. A1 稳定后进入 A2：`strategic` 对 `joint --joint-reply-model belief` 的相同墙钟、多种子配对，扩到全部标准 FS/BTX。
6. A4 的整局价值校准、黑方逆向信念、跨日搜索仍未完成。历史校准缺终猜红胜标签，模型只保留在离线基准。

不要一开始重新调整信息类奖励或扩大默认粒子数。先取得可复现的具体失败链和同源码消融。
候选覆盖、暗牌压力、身份覆盖、最终信息不足分别需要对应证据。

## 容易犯错的规则与边界

- 同一时点先同时触发所有强制能力，再按控制方选择的顺序发动可选能力。
  两个杀人狂单独同处的强制效果应保留同时触发，不能顺序杀掉第一人后漏掉另一人的效果。
- 各人独立拥有每轮一次的牌，例如禁止移动、不安 -1、友好 +2；全队可各用三张。
  同日友好 +1 与友好 +2 的冲突按引擎规则处理，候选器不能产生非法组合。
- 时间旅行者：好感 **至少 2** 才满足末日要求；禁止友好对其无效。
  其失败发生在最后一天的日末可选能力窗口，与轮回结束失败是不同可观察时点。
  在适用规则前提下，这个时点是强 witness；充分好感也提供否定时间旅行者解释的证据。
- 因果线依据上一轮的好感在下一轮产生不安，评价信息投资须计入跨轮回风险。
- 公开事件使用结构化 `timing`、kind、target 和状态快照推理。日志中文、翻译文本、剧本标题或稳定 ID 不构成身份证据。
- 初始身份、当前临时身份和能力来源要区分；病毒、因子、临时工/临时工？、模仿者容易误删真值。
- BTX11 曾因采样世界漏掉公开角色配置导致整局回退，现已修复。
  神格登场轮回、大人物领地、禁用牌等公开设置须贯通 view → evidence → sample → determinizer。
- 强制死亡批次、护卫、死亡替代等存在多个解释时，硬 witness 必须保留所有合法解释。
- 最终猜测一次提交整套初始身份，公开正确数量，全对才红胜；不逐人回答或逐人公布正确性。
- 红方只读合法 Observation 和自己的私密调查答案。黑方知识下界只在查身份已实际结算后推知红方获得的答案。
  申请、拒绝和查同身份群不能自动揭示单人身份。
- `last_trace`、隐藏采样世界、完整存档和 `.tlr` 可包含秘密。开发报告和结束后完整回放要遵守各自信息边界。
- Oracle 的 BTX 最终猜测直接使用已知答案；仅看总胜率容易掩盖行动阶段失败，须报告失败轮回和原因。

## 常用运行与验证命令

从仓库根目录运行 Python。Web 构建后重启 Python 服务，否则页面可能仍使用旧产物。

```powershell
python -m tragedy_sim --demo --module BTX
python -m tragedy_sim --gui --module BTX
python -m tragedy_sim --serve
# 浏览器 http://127.0.0.1:8765/
python -m tragedy_sim --host-room --port 8765
# 手机与主机同一 Wi-Fi，使用终端显示的局域网地址
```

前端命令在 `web/` 执行：

```powershell
npm install
npm run build
npm test
npm run lint
npm run test:e2e
# 素材或 resources/data.xml 更新后：npm run assets，再 build
```

Python 验证：

```powershell
python -m unittest discover -q
python -m unittest tests.test_belief tests.test_particle_ensemble -q
python -m unittest tests.test_witness tests.test_witness_components -q
python -m unittest tests.test_ai_card_plans tests.test_card_plans tests.test_rooms tests.test_replay -q
```

最近全量验证为 **543 项通过**（`dcfd35d` 切片，约 137 秒）；`0ec96eb` 的诊断/文档切片验证了 51 项相关测试，
并复现 BTX08 完整摘要。这些是历史结果，修改实现后仍需运行适用测试。本次交接无需重跑长对局。

重点诊断入口：

```powershell
python -m benchmarks.ai_factor_audit --scenario official-fs-01-first-script --seed 1 --nodes 8 --worlds 32 --expected-digest 6a8c670fed6775415358485c1ef572f3680911177f63f57252738a220fbb89e7 --output references/ai-calibration/handoff/fs01.json
python -m benchmarks.ai_factor_audit --scenario official-btx-08-mirror-passcode --seed 1 --nodes 8 --worlds 32 --expected-digest 063d3244a95f5ef03ed2b54da61bd532aae53e3c0df8a0c419e74efadbe9cebf --output references/ai-calibration/handoff/btx08.json
python -m benchmarks.ai_cutoff_calibration --scenario official-btx-10-prologue --seed 1 --games 1 --strategy fixed --mastermind-nodes 2 --protagonist-nodes 8 --protagonist-particles 32 --fixed-work --repeat-check --output references/ai-calibration/handoff/btx10.json
```

`ai_factor_audit` 的黑方、depth、horizon 在工具中固定；仅支持列出的配置参数。
`ai_self_play` 的 CLI 与 `play()` Python 参数不完全相同；独立世界数可用校准工具或 `play(protagonist_particles=...)`。

全矩阵和黑方配对：

```powershell
python -m benchmarks.ai_calibration_matrix --output-dir references/ai-calibration/handoff/matrix --protagonist-nodes 8 --protagonist-particles 32 --games 2 --seed 1 --max-jobs 3
# 后续继续同配置时加 --resume；改源码/剧本/预算会产生新指纹目录
python -m benchmarks.ai_mastermind_matrix --scenario official-btx-04-young-womens-battlefield --games 2 --seed 1 --mastermind-ms 1000 --protagonist-ms 1000 --protagonist-nodes 8 --protagonist-particles 32 --joint-reply-model belief --trace --output references/ai-calibration/handoff/black-pair.json
```

先用 `--help` 核对参数。固定工作量用于复现/标签采集；等时间评测使用墙钟工具并报告实际超时。
矩阵基准串行运行，避免 CPU 竞争改变限时轨迹。Windows 浏览器长局 E2E 也应串行，
并发短连接曾导致 `WSAENOBUFS`，不是 MZ 等规则非确定性。

## 实验资料与报告读取

`references/` 在 `.gitignore` 中，本机有原图、下载资料和完整实验 JSON，新 clone 不会获得这些文件。
本次交接已把结论和复现摘要写进 Git；不要用 `git add -f references/` 将整批原始报告推送。
同一工作目录的新会话可直接读取；换机器时按命令重建所需报告。

- `references/ai-calibration/2026-09-26/paired-seeds/run-ca235d3f4410e6e4/`：旧 4 世界共同 seed 1/2。
- `references/ai-calibration/2026-09-26/paired-seeds/run-0fff68345b298496/`：旧 32 世界共同 seed 1/2。
- `references/ai-calibration/2026-09-29/`：补样、FS01 候选、BTX08 终猜审计与消融。
- 文件名含 `conditioned` 的部分报告对应已放弃的全局硬条件提议；
  `fallback-only`、`incident-guard` 和 `final-audit` 对应后续切片，须结合提交与摘要确认。

PowerShell 读取 JSON：

```powershell
$report = Get-Content references/ai-calibration/2026-09-29/btx08-seed1-final-audit.json | ConvertFrom-Json
$report.final_guesses | Format-Table
$report.final_belief_setups | ConvertTo-Json -Depth 8
# 校准矩阵单局胜负在 .matches[0].red_win；audit 胜负在 .winner
```

报告中 `joint_plan_followup` 是缓存的后续牌，不是新搜索或异常回退。
`no_compatible_factor` 应检查身份和当事人两个维度；`no_legal_bundle` 检查联合候选/手牌/公开设置。
检查顺序为：引擎结算 → 真值 hard 相容 → 采样与重建 → 防守候选覆盖 → 同世界评分 → 最终信息与先验。
先读具体 trace 再归因；不要仅凭提高粒子数后胜负变化推断预算不足。

不同难度、种子、源码指纹、对手、horizon、候选数和世界数都要保留。
Easy 与标准共用秘密，不能当独立样本；缺终猜红胜时不能拟合可靠终猜胜率。

## 交接执行纪律

保留用户未提交修改，避免将其他会话改动混入本次提交。用 `apply_patch` 编辑、`rg` 搜索。
每个完成切片先验收，再 `git diff --check`、明确选择文件 `git add`、commit、push `origin master`。
三牌/信息边界/规则修改必须有对应回归；文档交接只核对路径、命令和 diff。
后续会话没有必要重做已完成的 A3 或重新迁移前端；从本文未完成项接续。
