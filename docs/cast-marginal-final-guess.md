# 完整身份表边缘 MAP 终猜实验（2026-10-14）

## 两个目标与实现边界

原 `latent_map` 已一次提交完整身份表；它先选择单个潜在剧情世界的 MAP，再使用那个世界的身份表。新增 `cast_map` 汇总同身份表的全部剧情质量，选择整套身份猜对概率最大的表。两者沿用同一 `uniform-printed-casts-v1` 先验、硬约束和软评分。

入口为 `ParticleEnsembleProtagonistAgent(final_guess_policy="cast_map")`；默认仍为 `latent_map`，大厅没有新增 AI ID。黑方内部回应模型保持默认旧终猜。这个开关只影响最终一次猜测，日常行动候选、世界采样、RNG、信息奖励、rollout 和行动预算均不改。

`final_guess_node_limit` 默认 100000，独立于行动节点预算。完整分区计算超限或不可用时回退旧完整世界 MAP；Trace 留下 `cast_map_<状态>`，概率为空，不把 top 代表归一化。成功时 `belief_source=exact_cast_marginal_map`，Trace 保存真实整套概率和不同身份表支持数量；不从一个 MAP 代表伪造角色边际。

## 评测口径修复

`ai_self_play` 原来在提交终猜并公开答案后重新审计支持集。现在在实际提交前采集合法团队观察、推断 Trace 和硬兼容性，包含团队收到的安全初始身份知识；明确标为 `final_inference_scope=before_guess_submission`。

`final_role_candidates_scope` 区分 `complete_cast_tables` 和 `propagated_latent_support_bound`，两个数量不能直接比较精度。真实初始剧本只在推断完成后用于检查兼容性和结果，不送给红方策略。真实世界完整支持检查同时验证印刷合法性、已知角色／剧情条件及共同目标正权重。

## 稳定的数值等概率处理

BTX04 的一次配对曾出现正确人数 7/9→5/9。两表的未归一化质量可精确写成同一个 `8√2/21`，浮点结果相差约 `4×10^-18`。原求解器把这点舍入差异用作排名依据。

现按 `16 × float_info.epsilon` 的相对舍入容差识别等概率，再以完整身份表的固定字典序选代表；绝对容差为零。真实的小概率优势不会被统一抹平，硬零支持也不改变。`tie_policy` 和容差进入开发 JSON。独立测试覆盖顺序无关的舍入等值，以及 `1e-50` 量级下仍保留的真实优势。修复后两策略该局均为 7/9。

## 已完成结果

- 四角色独立 BTX 反例：旧所选表概率 `0.00308642`，边缘 MAP 为 `0.00925926`，同一模型下提高 3 倍。输入仅有公开 setup，不按剧本编号选择策略。
- 38 份已保存完整轨迹重演，得到 17 个实际终猜根；两种当前策略答案全部相同，概率全部精确可用。终猜获胜均 2/17，历史记录也为 2/17。这个条件化根统计不等于整局胜率；没有进入终猜的 21 局不纳入该分母。
- 新源码固定工作量闭环：BTX04、BTX-01G 标准，各 seed 0、两策略，共四局；黑方三牌联合、belief 回应，黑节点 4，红候选 2、世界 4，深度 4，无墙钟截止。每一对终猜前的全部原命令一致。

| 剧本 | latent_map | cast_map | 实际终猜人数 |
| --- | --- | --- | --- |
| BTX04 | 黑胜 | 黑胜 | 均 7/9 |
| BTX-01G 标准 | 黑胜 | 黑胜 | 均 5/7 |

双方红胜均 **0/2**；小预算、两剧本一 seed，不构成统计性棋力结论。BTX-01G 错误表的模型概率约 83.3%，说明“提高同一模型下的终猜目标”仍受观察和后验模型约束；单个反例不足以校准先验或调整权重。保持实验选项，后续优先调查未区分的世界、信息获取与规划。

完整开发产物在忽略目录 `references/ai-calibration/2026-10-14/`：

- `cast-map-final-root-comparison-stable-ties.json`：38 份轨迹、17 根、当前两个策略及历史猜测分开。
- `cast-map-paired-stable-ties-fixed-work.json`：四局真实对弈、完整 replay、提交前审计与配对命令检查。
- `cast-map-paired-stable-tie-roots.json`：配对局终猜的同根复查。

冻结 Python 源码指纹 `53ee31a3…`。舍入修复前的文件只作问题复现，不合并计算最终结果或胜率。

完整后端回归 792 项通过（181.520 秒），终猜／概率／粒子默认专项 57 项通过。覆盖可选开关的行动与 RNG 等价、超限回退、提交前私密知识、权限隔离、数值等概率稳定性和比较报告续跑；完整日志位于忽略目录 `references/cast-map-stable-ties-regression-20261014.txt`。

## 复现与后续

```powershell
python -X utf8 -m benchmarks.ai_self_play --scenario official-btx-04-young-womens-battlefield --strategy joint --joint-reply-model belief --protagonists particle_ensemble --final-guess-policy cast_map --nodes 4 --protagonist-nodes 2 --protagonist-particles 4 --depth 4 --games 1 --seed 0 --json
python -X utf8 -m benchmarks.ai_final_guess_comparison references/ai-calibration/2026-10-13/matrix-default-validation-192-cached-seeds03.json --output references/cast-map-comparison.json
```

两个开发对弈 CLI（`ai_self_play`、`ai_mastermind_matrix`）均支持 `--final-guess-policy` 和 `--final-guess-node-limit`。离线比较可传多份完成报告、筛选 `--scenario`；`--max-jobs` 分阶段运行，`--resume` 要求源码、输入 SHA256、配置与已完成行顺序一致。未完成报告不能作为比较输入。

下一步以仍未区分的互斥世界为入口：检查证据、后验抽样、联合防御和更早的能力准备。精确分区可复用于身份／剧情后验抽样，但须独立验证密度、完整世界和重演过滤，再做对弈；不硬性提高好感技能使用率，不按本次两剧本调权。终猜只选最优表无法补足缺少的证据。
