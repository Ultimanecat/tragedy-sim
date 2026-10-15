# 开眼技能执行审计（2026-10-15）

## 已确认和修正

1. `DefensiveProtagonistAgent` 原先给不安 −1 相同优先级，会对 0 不安使用能力。现在识别明确为零的无效目标，区分实际不安与已知当事人。密谋 −1 同样不优先清零值。
2. 已知亲友／关键人物复活优先于普通目标，不无条件复活已知攻击身份；杀人需已知安全且有收益，不杀已知亲友，也不无条件杀未知身份。规则合法选项没有删除。
3. 两种开眼在技能阶段使用私密的当前身份／剧本当事人副本，与“知道完整剧本”的定义一致。不会写入 Game 的公开知识、日志或 witness，也不复制当前暗牌。公平模拟的 `script_aware_rollout=False` 原样保留授权视图。
4. 开眼的降不安／降密谋目标以真实一次选择结算后现有估值作比较；引擎的显式接受窗口也要结算，若可拒绝则取实际回应的较差值。最初只选择能力、未执行接受时计数未改变，专门测试发现并修正。无需递归整日 rollout；真实转换次数单列为 `oracle_skill_evaluations`。
5. 已知 BTX 剧本没有病毒时，通过显式 `global_counter_mutation_excluded=True` 不变量允许高不安联合空间。纯公共调用仍保留保护，已知含病毒仍回退。未来公平调用需证明整个身份／剧情支持都排除全局变更，不能直接使用真实剧本。
6. 轻量评分识别可安全击杀非关键当事人的防线；目标有护卫、仆人替代、时间旅行者或临时工替换时不假定能移除，关键人物／亲友也不计入安全击杀。

## 消融接口与信息边界

保留 `skill_information="public"|"script"`，开眼默认 script。公共档只控制技能策略的信息；出牌仍知道剧本，暗牌档仍不知道今日黑牌。CLI／MatchResult 分别为 `--oracle-skill-information`、`oracle_skill_information`。

评测工具 `--skill-ablation --candidate joint_counterexample` 在相同对手、候选策略、预算和种子下对比 public/script；无需创建更多大厅 AI ID。共享公开技能基线的修正也影响公平续演和黑方近似回应，跨源码报告须分开。新增的 variant 汇总覆盖实际标签，避免非旧矩阵标签显示为空。

```powershell
python -X utf8 -m benchmarks.ai_oracle_defense_validation --scenario official-btx-06-secret-that-was-kept --seed 1 --seed 6 --candidate joint_counterexample --oracle oracle_script --skill-ablation --workers 4 --output references/skill-ablation.json
```

## 当前证据和未完成问题

最终源 `eb810c51…`，专项 106 项、完整 **873 项通过（215.710 秒）**；日志 `references/oracle-skill-execution-regression-20261015.txt`。

BTX06 seed 1／6 共 4 局，全部 replay／公开证据真值审计通过，public/script 最终均行动获胜。seed 1 两档均首轮胜；seed 6 public 首轮胜、script 先输两轮后胜。此为 bug 小样本，未证明技能信息版本棋力提升。原始报告 `references/ai-calibration/2026-10-15/skill-context-counterfactual-smoke.json`。仅补私密信息、不做结算后目标比较的原型曾使 script seed 6 三轮全输，开发报告另存 `skill-context-smoke.json`，不合并样本。

BTX06 的医院事件当事人是媒体人，失踪当事人是职员。开眼会为了防当天失踪给职员降不安，次日医院当事人仍过高。现有事件进度在临界值封顶：不安 2 和 3 都是已达临界，减少超额值的作用低估；日末另有统一低权重的未来不安项，仍不足以体现致命事件的后续防守成本。下阶段按事件影响／防线成本改善这个未来项，避免按剧本编号或目标角色定制。

该阶段仍未实现完整跨日树搜索、技能序列敌对搜索、事件截止时间／可达性约束或公平矩阵迁移。一步估值不能证明最优顺序或必胜。
