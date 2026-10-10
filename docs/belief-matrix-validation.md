# 矩阵化信念接入验证（2026-10-10）

本批为组件与采样恢复改造，没有新增大厅 AI 模式。表示细节见 [共用信念矩阵](belief-matrix.md)。

最终完整后端回归 617 项通过；前端本批未修改。文档链接与 diff 检查通过。

## 验证范围

- 已录入的全部 FS/BTX（含难度版本）逐个检查公开视图及完整身份／剧情揭示视图：真实身份不被标 never，任何 always 格子符合真值，实际身份数量落在传播上下界内。
- 覆盖唯一身份、剩余唯一候选、析取＋数量、剧情排除、病毒的初始身份区别、局外人额外身份、模仿者复制与 FS 可选暴徒。
- 暗牌覆盖公开弃牌、禁用牌、可见牌面、all-different 匹配、两张不同实体不安 +1、地点移动佯攻和轮回限次刷新。
- 30 个固定 seed 的正常暗牌抽样保持相同结果；新增格子域过滤不能把临时列表当成实际剩余手牌，专项验证三张实体牌唯一。
- 将旧提议路径强制设为空：关闭矩阵恢复报告 `no_compatible_factor`，开启后恢复 12 个合法世界。此为构造故障测试，不是实战耗尽率改善。
- 原有提议正常时恢复不启动，固定 seed 世界批次等价。所有恢复候选通过 `validate_scenario` 与完整 witness matcher；未投影的关系没有跳过校验。

## 完整对局流程对照

配置：seed 0，定式黑方，公平粒子红方；双方节点预算 4，深度 8，红方 4 世界、日末 horizon。FS01 为 4 天／2 轮，BTX04 为 6 天／3 轮，均为标准版本。没有墙钟截止，运行时间用于流程参考。运行期间有完整回归进程，时间不能作性能排行。

| 剧本 | 关闭／开启恢复 | 胜方 | 失败轮回 | 决策数 | 运行秒数 |
| --- | --- | --- | --- | --- | --- |
| FS01 标准版，6 角色 | 关闭 | 红方直接存活 | 1 | 81 | 1.179 |
| FS01 标准版，6 角色 | 开启 | 红方直接存活 | 1 | 81 | 1.331 |
| BTX04 标准版，9 角色 | 关闭 | 红方直接存活 | 1 | 179 | 4.764 |
| BTX04 标准版，9 角色 | 开启 | 红方直接存活 | 1 | 179 | 4.805 |

两组均没有触发矩阵恢复，也没有进入最终猜测；整局决策摘要逐组相同。四份文本 replay 均完整验证。

- FS01 决策摘要：`17b9a935a3d1873a1c0230681de8b7b61defdfe997b8b824c83e4626a2982765`
- BTX04 决策摘要：`9c5c6b05f3f866130d8ecf0bbab9e2dacb202d4b7bb7fd154e96bc33071bd642`

这是小预算流程验证，不能视为对强黑方胜率，也不能据此证明恢复在真实长局中的收益。

## 可复现消融

```powershell
python -m benchmarks.ai_self_play --scenario official-fs-01-first-script --strategy fixed --protagonists particle_ensemble --games 1 --nodes 4 --depth 8 --protagonist-nodes 4 --seed 0 --json
python -m benchmarks.ai_self_play --scenario official-fs-01-first-script --strategy fixed --protagonists particle_ensemble --games 1 --nodes 4 --depth 8 --protagonist-nodes 4 --seed 0 --disable-matrix-recovery --json
```

JSON 记录 `matrix_recovery_enabled`、`protagonist_matrix_recovery_attempts`、`protagonist_matrix_recovery_worlds`。该开关只控制本局红方因子信念恢复，不关闭黑方回复模型，也不关闭结构等价的暗牌域校验。程序调用 `play(..., protagonist_particles=4, capture_replay=True)` 可明确世界数并保存回放；CLI 的当前默认恰好也是 4 世界。

后续仍需在强黑方、更多 seed 和真实历史根上验证耗尽率与耗时。最终猜测保留已有完整合法 MAP，不改为逐列最大概率。
