# AI 信念变化日志与因果审计

日志仅用于开发诊断，存放在忽略的 `references/`。不进入玩家界面、SSE 或公开游戏日志。正式游戏的 replay 格式不变。

## 记录内容

- 发生证据变化的授权观察的轮回、日期、阶段、事件游标；不为无变化的重复读取写空记录。
- 新增／移除的硬约束和软线索，以及重复观察次数、来源组件、证据原始时间点。
- 原始 `PublicWitness` JSON 与中文解释同时保存，便于检查文本与机器约束是否一致。
- 原始对局已记录的角色采样频率，以及按硬证据过滤后的事件当事人候选。样本频率不当作完整后验概率；12/12 个样本相同也不自动成为新的硬证据。
- 启用运行时日志后，粒子规划器自动补充当事人／暗牌样本、历史出牌模型。新的 self-play 搜索记录也保留这些维度，旧报告缺失的字段留空，不事后编造。

公开知识镜像在后续阶段重新编译时不重复记作新线索；重复的实际观察仍记数。日志不影响 RNG、候选选择或节点预算，默认关闭。开启日志有额外观测开销，等墙钟排名时须使用同一采集配置。

## 使用方式

已有 `ai_mastermind_matrix --trace` 报告含 `replay_text` 时，可重演并逐命令审计：

```powershell
python -m benchmarks.ai_causal_audit references/ai-calibration/2026-10-10/btx04-seed2-hard-routes.json --output references/ai-calibration/2026-10-10/btx04-belief-changes.json --belief-log references/ai-calibration/2026-10-10/btx04-belief-changes.txt
```

典型记录：

```text
[第1轮 · 第 1 轮回结束时]
  新增硬：第6天事件当事人：女学生（证据时间：第1轮 · 第 6 天事件阶段；来源：public_suicide_victim）
  新增硬：女学生身份约束：亲友（来源：public_role_reveal）
[第2轮 · 第 5 天主人公出牌阶段]
  采样世界 12 个；以下是样本频率，不是完整后验概率：
    女学生：亲友 12
    第6天当事人硬约束候选：女学生
```

重演工具在每个命令完成后检查授权观察，属于更密集的离线监测。实际 AI 在调用证据刷新时才记录新增证据；原始采样行来自保存的搜索 Trace，不把重演后的新采样混充为原对局结果。

运行时也可给某个规划器的 `evidence_ledger.audit` 赋值 `BeliefAuditTrail()`，随后读取 `audit.entries` 或 `audit.to_text()`；默认值为 `None`。这个入口不授予额外信息权限。

## 同根开眼对照

```powershell
python -m benchmarks.ai_causal_audit references/ai-calibration/2026-10-10/btx04-seed2-hard-routes.json --strategy strategic --compare-roots --output references/ai-calibration/2026-10-10/btx04-root-comparison.json
```

针对自杀日及前一天，在完全相同的真实根节点比较原记录、重新采样的信念红方、仅知剧本红方与知剧本及当日暗牌红方，分别使用日末／轮回末 horizon。所有计划再用同一组动态黑方定式评价实际世界的日末／轮回末表现；另外改变后续红方填充为知剧本策略，单独诊断未来动作模型误差。

这些是有限候选的同根反事实测试，不是整局胜率或无解证明。重采样红方使用新建候选池，原记录保留独立行；当前开眼候选器与公平粒子候选器也有覆盖差异，不能把全部差异都归因于信息权限。知剧本诊断不会把最终猜测的正确答案作为轮回存活。

审计顺序：直接原因是否形成证据 → 硬候选是否保留事实 → 当前防御是否进入候选 → 后续动作及资源模型是否可靠。死亡立即失败保留关键人物／城市阈值下的不安定因子析取；亲友在轮回结束时公开，必须区分时间点。
