# 开眼搜索记录与计时（2026-10-16）

## 修复

此前 self-play 仅保存带 `root_actions` 的公平搜索记录。开眼的 `OracleTrace.elapsed_ms` 未累计到 `protagonist_search_seconds`，因此该字段错误为0；整局elapsed、行动、技能、回放和胜负仍有效。

现新增开发报告字段 `oracle_searches`，每项包含 `loop`、`day`、发起规划的 `actor` 和完整 `trace`。按同一策略对象的新trace身份去重：第二、第三张缓存牌沿用原trace，只记一次；中途确实重新规划产生新trace时另记。它与公平的 `protagonist_searches` 分开，没有新增大厅策略或玩家API字段。

逐根trace保留合法空间枚举数、共同场景数、轻量投影、真实续演及反例统计。新增 `candidate_values`：

- 完整三牌 `bundle` 与是否被选中；
- 原始horizon／当日存活比例；
- 包含限次资源与重复惩罚的状态值；
- 与真实选择函数一致的 `selection_key`，顺序为原始horizon存活、当日存活、状态值、当日状态值。

这些字段供离线解释“生成了哪些计划、为何选它”。状态值不等于后验概率，有限场景全存活也不证明实际必胜；开眼知晓剧本，不能把它的身份知识输入公平AI。

`protagonist_search_seconds` 累加每次新三牌规划的 `elapsed_ms/1000`，包含重建与候选评价，不含所有技能选择、黑方搜索或整局其他成本。技能转换另有 `oracle_skill_evaluations`，整局仍用 `elapsed_seconds`。不能把此字段当端到端响应保证。

## 验证

源码指纹 `da172a34…`：

- 原测试先因沙箱TemporaryDirectory写权限出现8个错误，同范围提升权限重跑并扩到65项专项全部通过，没有跳过测试。
- 从Git `cea5ca4` 在内存加载旧 self-play 与旧Oracle，FS01／BTX04、两开眼模式共4组完整前后对局。44根／578命令的决策、replay、技能、轮回失败与终猜一致；无三倍计时。
- 联合反例候选再测FS01／BTX06、seed1、mean／worst共4局，与前一源码 `bb2259bb…` 对应轨迹逐项相同。22根／362命令回放与公开真值审计通过，四局均行动胜。
- 每根候选数与实际评价数一致、恰好一个选中项；最高selection_key对应实际三牌，总搜索时间等于逐根时间之和。此次修复不改变算法，不作新增棋力提升结论。
- 完整 **882项通过（230.343秒，与对弈并行）**，全部测试正常执行，未跳过权限相关用例。

原始报告 `references/ai-calibration/2026-10-16/verify_oracle_telemetry.json`（含Git文件SHA）与 `oracle-telemetry-joint-smoke.json`；完整回归日志 `references/oracle-telemetry-regression-20261016.txt`。

下一阶段可利用这些记录审计公平迁移：保持身份后验质量，分别检查联合候选覆盖、假设内暗牌覆盖、同批次存活及状态估值，避免仅凭最终胜负归因。
