# 长期防守目标剧本选择（2026-10-29）

## 背景

2026-10-28 的配对实验在 BTX01 上做，结论是分层估值"没有可测提升"。复盘发现 BTX01 的失败来源是 `主人公死亡`、`时间旅行者日末能力`、`亲友死亡`，第 5 天大小姐自杀不是瓶颈。继续在 BTX01 上调估值没有意义。

## 选择标准

目标剧本必须同时满足：

1. **失败来自长期累积**，不是单次事故：失败条件是"某个计数在轮末达到阈值"或"某角色计数累积到阈值"。
2. **累积过程跨越至少 3 天**，让当日防守和长期投入存在真实取舍。
3. **防守手段是出牌与能力，不是纯搜索**：红方可以用 `fi`、`fm`、移动、能力链等方式干扰累积。
4. **普通粒子红方确实会输在这条线上**（用诊断确认，不靠推测）。
5. 不含跨轮保留（那是 T3），先保持 T2 范围。

## 候选

| 剧本 | 规则 Y | 累积方式 |
| --- | --- | --- |
| `official-fs-02-prevailing-secrecy` | protect：轮回结束学校密谋 ≥2 | 版图密谋逐日累积，红方只能当日禁止 |
| `official-tragic-aiplay-fs-02g` | avenger：主谋初始区域密谋 ≥2 | 版图密谋累积 |
| `official-tragic-aiplay-btx-01g` | sign：关键人物密谋 ≥2 | 角色密谋累积 |
| `official-btx-04-young-womens-battlefield` | sign：关键人物（需少女属性）密谋 ≥2 | 角色密谋累积 |
| `official-btx-05-lesser-of-two-evils` | sealed：神社密谋 ≥2 | 版图密谋累积 |
| `official-btx-11-neverending-happy-sad-story` | bomb：魔女初始区域密谋 ≥2 | 版图密谋累积 |

对照组：`official-btx-01-machina-solar-cogwheel`、`official-btx-02-traditional-ensemble-murder`。

## 第一步：诊断扫描

脚本 `benchmarks/long_horizon_target_scan.py`：

- 用公平粒子红方对固定黑方，固定节点预算，seed 0–2。
- 记录胜方、每轮失败原因、失败发生在第几轮第几天、当天的版图密谋与关键角色密谋、已发生事件。
- 输出 markdown 表，按"长期累积是否是败因"筛选。

## 第二步：接入真实策略

选定剧本后写 `TwoDayProtagonistAgent`：

- 公开信念采样（现有 `ParticleInformationPolicy`）。
- `classify_threats` + `select_primary_threat` 选当日主威胁。
- 候选日计划：纯防守、能力铺垫、信息调查、混合。
- 分层估值排序（`select_defense_action` / `DefenseLeafEstimator`）。
- 第二天叶值先用当前粒子策略的当日存活，不直接上完整 T2 搜索。

## 第三步：配对验证

- 固定节点预算、同种子、10 组以上。
- 主指标最终胜率；中间指标记录当日存活率、义务完成率、已知威胁覆盖率。
- 不通过不切默认 AI。

## 诊断结果（2026-10-29，seed 0–1，固定节点预算）

普通粒子红方对固定黑方：

| 剧本 | 规则 Y | 结果 |
| --- | --- | --- |
| `official-fs-02-prevailing-secrecy` | protect 学校 | seed1 两轮规则 Y 失败，但仍赢下比赛（另一轮存活） |
| `official-tragic-aiplay-fs-02g` | avenger 主谋初始区域 | **seed1 黑方全胜，3 轮全为规则 Y 失败** |
| `official-tragic-aiplay-btx-01g` | sign 关键人物 | 混合：主人公死亡与规则 Y |
| `official-btx-04-young-womens-battlefield` | sign 关键人物 | seed1 两轮规则 Y 失败 |
| `official-btx-05-lesser-of-two-evils` | sealed 神社 | 两个种子都在第 7 天规则 Y 失败，但只输 1/3 轮，仍赢比赛 |
| `official-btx-11-neverending-happy-sad-story` | bomb 魔女初始区域 | 规则 Y 失败在第 6 天，重复出现 |
| `official-btx-01`（对照） | change | 失败来源是主人公死亡/时间旅行者，不是长期累积 |
| `official-btx-02`（对照） | murder_plan | 身份能力致死，混合 |

关键限制：FS 没有终猜，且"只要有一轮存活即获胜"，所以**比赛胜率对长期防守不敏感**；BTX 有终猜，全轮失败后还有猜身份翻盘。因此主指标改用：

1. **规则 Y 轮回失败率**（长期防守是否真的挡住累积）。
2. 比赛胜率（次要，样本更大时才看）。

## 选定目标（2026-10-29 修订）

原计划主目标是 `official-tragic-aiplay-fs-02g`（avenger）。实现第一版 agent 后确认这条线**结构上接近不可防**：

- 主谋（brain）的身份能力每天在剧作家能力阶段给所在版图密谋 +1；
- 规则 Y 要求该版图轮回末 <2，但能力单独就能在第 2 天把计数推到 2；
- 禁止密谋（`fi`）只挡行动牌，挡不住能力；主人公也没有稳定的杀死主谋手段。

因此 avenger 不能用来测"防守是否有效"，保留为反例。修订后的目标：

- **主目标**：`official-fs-02-prevailing-secrecy`（protect，学校密谋 ≥2）。
  - 累积主要来自行动牌，红方可以用 `fi` 每天干扰；
  - 5 天 × 3 轮，基线在 seed1/2 各输 2 轮规则 Y。
- **副目标**：`official-btx-05-lesser-of-two-evils`（sealed，神社密谋 ≥2）。
  - 7 天 × 3 轮，基线三种子都在第 7 天规则 Y 输 1 轮；
  - 验证更长跨日与 BTX 终猜。
- **反例**：`official-tragic-aiplay-fs-02g`（avenger），记录为"能力驱动的不可防累积"。

规则 Y 在本项目里是隐藏信息（`known_plots` 初始为空，由能力公开），所以 agent 必须维护"Y 目标"的后验：avenger 要看主谋（brain）的初始区域，sealed 看神社，protect 看学校。第一步实现放在 `day_game/threats.py` 的 `classify_plot_threats`。

## 状态

- [x] 记录计划
- [x] 诊断扫描
- [x] 选定目标剧本
- [x] 规则 Y 后验威胁分类（`classify_plot_threats`，5 项测试）
- [x] 第一版 `TwoDayProtagonistAgent`（规则 Y 风险覆盖，单步贪心）
- [x] 配对实验（含开眼 ablation）
- [x] 后验覆盖版（`posterior_cover`）
- [x] 8 种子配对（protect / sealed）
- [ ] 信息获取版：用公开角色/事件更新规则 Y 后验
- [ ] 评估是否需要 T2 两日搜索

## 2026-10-29 配对结果

固定节点预算、同种子、固定黑方；主指标为规则 Y 轮回失败数。

| 剧本 | 基线 | 隐藏-Y agent | 开眼-Y agent |
| --- | --- | --- | --- |
| `official-fs-02-prevailing-secrecy` | 3/3 胜，规则 Y 失败 4 | 3/3 胜，规则 Y 失败 4 | 3/3 胜，规则 Y 失败 **1** |
| `official-btx-05-lesser-of-two-evils` | 3/3 胜，规则 Y 失败 3 | 3/3 胜，规则 Y 失败 2 | 3/3 胜，规则 Y 失败 **0** |

结论：

1. **覆盖机制有效**：知道规则 Y 目标后，每天用 `fi` 禁止该版图密谋，protect 的规则 Y 失败从 4 降到 1，sealed 从 3 降到 0。
2. **隐藏-Y 下几乎无提升**：规则 Y 初始后验是平坦的（protect 0.4 / avenger 0.4 / …），protect 的学校从 0 直接跳到 3，agent 没有机会在"计数已出现"之后再反应。
3. 覆盖动作只能是 `fi`。`p-1` / `g1` 这类牌不保护密谋累积；第一版把任何计数牌都当覆盖，导致策略变差，已修。
4. avenger 仍是反例：主谋能力每天给初始版图 +1，`fi` 挡不住能力。

## 2026-10-29 后验覆盖实验

新增 `posterior_cover` 模式：规则 Y 目标未知时，按粒子世界的主规则后验覆盖风险最高的版图（不要求计数已经出现）。8 种子配对：

| 剧本 | 基线（规则 Y 失败 / 胜场） | 后验覆盖（规则 Y 失败 / 胜场） |
| --- | --- | --- |
| FS protect | 6 / 8 | 5 / 8 |
| BTX-05 sealed | 8 / 8 | 7 / 8 |

方向正确但幅度小：两个剧本各 24 轮里都只多救回 1 轮，胜场不变。原因有两条：

1. 后验在第一天是平坦的，覆盖的期望收益低；
2. 每天最多覆盖 2 个目标，而规则 Y 可能落在第 3 个版图上。

## 下一步

规则 Y 隐藏且日程公开，主角方的长期防守必须先做信息获取：

1. 找出带 `reveal` / `culprit` / `plot` 能力的角色所在剧本，用能力公开身份或当事人，收窄规则 Y 后验。
2. agent 增加"信息动作"分支：在知识增益与当日防守之间排序，用现有 `information_value` 近似。
3. 后验收窄后（例如主规则概率 >0.8）再激活覆盖；否则不盲目覆盖。
4. 最后再考虑 T2 两日搜索，用两日叶值评估"今天探测、明天防守"的组合。
