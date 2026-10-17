# FS精确日末基准（T0.1，2026-10-17）

当前交付为独立的已知剧本诊断内核。默认AI、大厅和网络协议不变。长期算法契约与论文统一读 [核心设计](certified-day-game-design.md)，实施顺序读 [路线图](future-roadmap.md)。

## 范围与接口

根为FS：完整剧本已知、黑方三个靶位已公开且牌面未知、红方尚未出牌。两人团队模式统一控制三席。只求固定靶位下的纯策略保障`max_red min_black`；黑牌在揭牌前提交，揭牌后的能力按真实引擎的顺序选择。

| 入口 | 职责 |
| --- | --- |
| `CompleteCardSpace` | 各席实际剩余手牌×合法目标，保留限次牌所有者、多张禁止密谋及全部合法无效牌；只做引擎合法性过滤。 |
| `engine_red_bundles` | 慢速独立裁判，每个出牌前缀重新查询引擎合法行动并做完整transition；支持已出0–2张的前缀。 |
| `commit_pair` | 完整clone上替换合法黑牌面并恢复对应手牌，以引擎transition提交三张红牌。原局不变。 |
| `DayContinuationSolver` | 从揭牌或后续能力窗口展开所有合法能力、顺序、目标、拒绝及跳过；黑方min、团队红方max。 |
| `PureDaySolver` | 全红牌域×全合法黑牌域，调用完整能力树；可传合法warmstart调整顺序，全域保持不变。 |
| `WorkLimit` | 整次求解共用节点／时间预算，逐收益单元不重置。 |

本版不做启发式剪枝、状态压缩、转置缓存或定式续演。只有0/1效用本身支持的界剪枝：某红牌找到一个必败黑方回应即可证明该行值0；某行全部黑牌都证明存活即可证明纯策略值1。

`day-survival-v1`将当天正常结束或主人公直接获胜赋1，进入轮回结束／最终猜测或剧作家获胜赋0，不进入下一轮。该定义用于战术裁判，不能解释为整局胜率。未来T1–T3会扩展独立续局评价接口。

## 结果与预算

- `bounds.lower/upper`为已证明界；预算或深度限制下未知子树保留[0,1]。`certified_pure_value`只在二者相等时成立。
- `action_domain_complete=true`说明枚举器定义完整合法域，不表示每个组合都已结算。`belief_domain_complete=true`只针对已知的这一个剧本；`known_script=true / fair_policy=false`明确标注。
- 报告给出完整域大小、已检查行／收益单元、能力节点／边、出牌transition、时间和停止原因。已检查单元可能含未完成能力树，需结合上下界及`continuation_stop_reasons`阅读。
- 节点预算计非终端决策节点展开；叶子不额外计节点，transition单独计数。时间为软截止，当前原子clone／transition可能略超时；完整域计数和输入准备也消耗实际时间。
- `red_bundle`可在值未知时给出当前下界最好的合法方案。它没有“保证存活”的含义，必须检查其下界。

所有状态与真值只用于离线私有诊断。公平多世界版本需要共同红方信息集策略，不能直接平均各已知世界的最优技能选择。当前结果不构成混合策略、完整世界后验或跨日最优性证明。

## 验证与成本

新增19项专项测试通过；完整回归926项通过（274.335秒）。完整FS根红牌368640套、黑牌720套；弃置黑方密谋+2后为504套。独立真实引擎枚举核对0／1／2张红牌前缀，保留各席限次资源；完整能力树与无剪枝递归裁判核对联合攻击四组控制、医生减不安防自杀及黑方拒绝。

小局面分别证明：完整720黑牌回应下纯保障1；全部120红牌各有引擎证实的失败回应时纯保障0。另测节点／深度／时间耗尽、源码冻结、回放根选择及无完整值时不误报已求解。

真实FS01 seed2、第2轮第2天：368640红牌×504黑牌约1.86亿收益单元，且每单元还有日末能力树。源码指纹`43c9dba9b9bdc3b8bff7ca3b717ce58dcad05136c694d9cd059c35a99bda3155`，10000ms／20000节点预算，使用已知候选作warmstart的一次串行诊断：

| 指标 | 结果 |
| --- | --- |
| 已检查红牌／收益单元 | 1／24（末单元未完成） |
| 能力节点／transition | 1911／2311 |
| 出牌transition | 72 |
| 总用时／停止原因 | 10.001秒／time_limit |
| 纯策略上下界 | [0,1]，未求解 |

warmstart第一套是`c禁止移动→女学生、a禁止密谋→职员、b纵移→巫女`。它在本次限制内既未证明存活，也未证明必败。无warmstart的限时诊断同样未知，不能据此比较棋力或判定该根无防守。

当前瓶颈是完整clone／transition及重复能力子树。T0.2优先保留此路径作金标准，再逐步验证无损规则／信息状态key与局部结算压缩。对超大根直接延长暴力枚举仍可能成本很高；尚无生产棋力提升结论。

## 运行

```powershell
python -X utf8 -m unittest tests.test_day_game tests.test_ai_exact_day -v
python -X utf8 -m benchmarks.ai_exact_day --scenario official-fs-01-first-script --nodes 20000 --time-ms 10000 --output references/exact-day.json
```

重建历史失败根可追加`--report references/ai-calibration/2026-10-16/fair-residual-production-10seeds.json --variant joint_candidates_residual_marginal --seed 2 --loop 2 --day 2`。`--warmstart`接受JSON三牌方案数组，只改变遍历顺序，非法方案直接报错。

报告保留源码／剧本指纹、全部初始化命令、预算、域和认证范围。历史评测输入及本次原始JSON位于忽略目录`references/ai-calibration/2026-10-17/`，新clone不带这些本机文件；测试中保存了可复现的控制局面与穷举裁判。完整回归记录见交接说明。
