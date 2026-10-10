# AI 模式收敛（2026-10-10）

用户已授权实施。当前已提取公共信念规划层，并收敛大厅／房间入口；历史算法暂留开发基准。下表保留分类理由，实施状态以本段及 [路线图](future-roadmap.md)为准：12 个房间 ID；四个旧实验 ID 返回 `AI_STRATEGY_RETIRED`；三种单步黑方搜索折叠到开发对照；两个联合 ID 由大厅回应模型选项统一配置。

## 当前入口与建议

`web/src/lobbyChoices.ts` 有 16 个策略 ID；随机为双方共用，黑方最多 7 项、红方最多 10 项。实际选择受规则集和主人公人数限制。策略数量不等于独立算法实现数量。

| 类别 | 当前策略 ID | 建议与原因 |
| --- | --- | --- |
| 日常保留 | `random` | 流程检验、最弱对照，双方可用。 |
| 日常保留 | `fixed_mastermind` | 快速黑方基线；搜索续演也使用动态获胜路线。 |
| 日常保留 | `baseline_protagonist`、`defensive_protagonist` | 基础干扰与公开信息防守；轻量基线，多席位可用。 |
| 主线保留 | `strategic_mcts_mastermind` | 通用搜索黑方，作为联合版的对照及共享实现。 |
| 主线保留 | `particle_ensemble_protagonist` | 当前公平红方，FS/BTX 单人控制三席位；后续矩阵化在此推进。 |
| 主线合并入口 | `joint_mastermind`、`belief_joint_mastermind` | 已共用 `JointPlanMastermindAgent`。建议大厅选择“联合搜索”，再选择公开／信念回复模型；目前前者 FS/BTX、后者 BTX。保留不同模型的评测标签。 |
| 开发对照保留 | `mcts_mastermind`、`optimized_mcts_mastermind` | 用户此前明确要求保留朴素和优化 MCTS 基线。建议收起到开发模式，暂不删除实现。 |
| 前端保留（已确认） | `oracle_script_protagonist`、`oracle_cards_protagonist` | 两种开眼红方继续供试玩选择；名称及说明明确标注开眼，分别知道完整剧本、完整剧本与当日暗牌。也用于分离信念、暗牌应对与行动规划错误。 |
| 优先退出独立入口 | `ismcts_legacy_protagonist` | 搜索首张、后两张防守填充的旧中间态；不适合作为当前联合规划主线。 |
| 优先退出独立入口 | `ismcts_protagonist`、`survival_ismcts_protagonist` | 早期团队／当日生存分支；当前粒子集成覆盖主要发展方向。冻结旧基准后可停止维护独立算法分支。 |
| 保留内部模型 | `risk_aware_protagonist` | 历史风险仍用于联合黑方的公开回应估计；建议退出大厅独立入口，保留内部用途和必要对照。 |

日常保留随机、定式、基础干扰、公开防守、粒子集成、联合黑方，加上两种明确标注的开眼红方。策略／朴素／优化 MCTS 通过“显示开发对照”仍可选择。内部公共组件不占用大厅策略名。

## 删除前必须处理的依赖

- `ParticleEnsembleProtagonistAgent` 已解除对 `IsmctsProtagonistAgent` 的继承，公共观察、世界重建、命令执行、trace 与终猜移至 `belief_planner.py`。旧 ISMCTS 也复用该层，仍保留历史基准与回归。
- `JointPlanMastermindAgent` 继承 `StrategicMctsMastermindAgent`，后者继承 `OptimizedMctsMastermindAgent`。先确认继承能力的实际调用，逐步组合化，避免删掉主线需要的搜索基础。
- `RiskAwareProtagonistAgent` 继承公开防守，参与联合黑方回应；基础干扰和公开防守也被多个续演／回退路径复用。
- 两种联合黑方共用类，回复模型适合作为配置。两种 Oracle 的观察权限不同，需保留明确区分。

## 推荐实施顺序

1. 用户确认可选入口收敛范围；将旧 ISMCTS 与历史风险标为冻结，明确大厅／开发模式边界。
2. 保存基准配置、策略 ID、源码指纹及回放验证结果。历史实验继续使用原 ID，不能静默映射为新算法。
3. 提取粒子版实际依赖的公共能力；移除确认无调用的旧分支。搜索内核与可选 AI 分开管理，内部组件不再占用大厅名称。
4. 更新服务端允许列表、前端类型和选择项、CLI、基准工厂、文档；测试现有主线与观察权限。
5. 对停用 ID 返回明确提示；当前房间及保存格式按当时需求处理。旧实现可由 Git 历史取回，无需长期维持每个中间态。

验收包含固定工作量主线行为对照、两人／多人权限、FS/BTX 限制、房间创建和完整 replay。界面精简不视为棋力改进。
