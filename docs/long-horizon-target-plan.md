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

## 状态

- [x] 记录计划
- [ ] 诊断扫描
- [ ] 选定目标剧本
- [ ] 实现 `TwoDayProtagonistAgent`
- [ ] 配对验证
