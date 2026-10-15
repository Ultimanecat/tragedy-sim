# 身份内暗牌保守估值（2026-10-15）

## 问题与实现

BTX04 的已知身份回放中，第二天关键人物可能被放密谋 +2，原算法仍选择三张友好牌。当天不会立即失败，反例搜索的当日截止点也无法发现轮回末规则 Y 的失败。轻量排序把少数危险暗牌的状态成本平均后，友好准备收益超过了防守收益。

开眼新增可选 `dark_state_policy="mean"|"worst"`，默认保持 mean。`worst` 同时用于联合候选排序及真实续演后的状态估值：在同一身份／剧本假设的暗牌场景中取最低状态分。当前存活比例仍为第一排序项，原来的危险度、限次牌成本和定式技能路线检查保持。该开关没有增加跨日搜索深度，也没有提供暗牌完备证明。

`JointThreatRanker` 的 worst 模式拒绝混合身份或剧本，追加场景时也检查此边界。公平多世界迁移应先在各身份假设内评价暗牌，再按后验质量聚合身份；压力场景的数量不能作为身份或暗牌后验概率。当前公平主线及黑方内部回应未切换。

另修复开眼暗牌重建中的运行时身份遗漏：病毒已将平民变成杀人狂时，脚本知情的开眼样本保留当前身份。只读取明确授权的当前身份，不读取今日黑牌或剧作家私密手牌；公平 helper 的 `script_aware_rollout=False` 不进入这条同步分支。公共视图与正式游戏均不修改。

## 验证与复现

专项覆盖均值与最坏值的差异、混合身份拒绝、BTX04 提前挡密谋以及病毒身份同步。重建的 BTX04 第二天根中，两版当前日都存活 31/31；均值选择三张友好牌，保守版选择禁止密谋保护关键人物。这个单根结果仍需完整对局检验。

对弈工具提供 `--state-ablation`，固定候选、技能及未来事件估值，仅比较 mean／worst；完整 replay 和公开真值仍逐局审计。示例：

```powershell
python -X utf8 -m benchmarks.ai_oracle_defense_validation --scenario official-btx-04-young-womens-battlefield --candidate joint_counterexample --future-incident-policy impact --state-ablation --workers 4 --output references/dark-state-10seeds.json
```

省略 `--seed` 使用 0–9。节点限制代表固定候选预算，额外反例和技能模拟仍独立计数，不称等 CPU 时间。并发计时只用于运行成本观察。

## 首轮完整结果

源码指纹 `fa420597…`，FS01／FS-02G／BTX04／BTX06，各 seed 1／6，固定红黑候选预算 4，共 16 局：

- 最终行动胜均为 8/8，没有整体胜率提升证据。
- BTX04 均值版两局各输一轮，保守版两局首轮获胜。
- 其余三个剧本两版均首轮获胜；总轮回失败 2→0。
- 96 个行动根、1536 条命令全部通过完整 replay、公开硬证据与矩阵真值审计。

完整 **879 项测试通过（257.652 秒，与对弈并行）**；85 项专项通过。原始报告 `references/ai-calibration/2026-10-15/dark-state-cross-script-smoke.json`，测试日志 `references/dark-state-final-regression-20261015.txt`。

接续评测已启动：BTX04／06 × seed 0–9 × 两版，共 40 局，黑方预算提高到 16，红方保持 4；报告 `references/ai-calibration/2026-10-16/dark-state-btx-10seeds-black16.json`。两版在同一源码比较，不能与黑方预算 4 的旧报告直接合并。代码在指纹冻结期间不修改，完成后再据同种子回放分析退化。
