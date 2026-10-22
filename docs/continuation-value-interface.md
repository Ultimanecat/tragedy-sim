# 续局价值接口（T1.1）

T1 的第一步：把日末收益从当日求解器中拆出来，允许替换成整局获胜价值评估。本次只建立接口、T0 兼容实现和失败关闭规则，不改变默认 AI，也不声称已有整局估值。

## 状态

- 接口、上下文和 T0 兼容评估器已实现，9 项专项测试通过。
- 新增未认证的随机 rollout 基线，用于 T1 估值实验；它不能关闭证书。
- 新增基于真实自对弈边界的校准烟测。BTX01 5 局全输：当日存活 Brier 1.000，随机 rollout 0.306；BTX06 1 局全输：1.000／0.268；BTX01 `random` 剧作家 3 局全赢：0.000／0.175；FS01 20 局：0.879／0.308。Brier 受胜负构成影响，样本小不能选估值器。
- `benchmarks.ai_continuation_calibration` 默认剧本已改为 BTX01；FS 作为支线样本显式指定。
- 后续基线默认使用 BTX；FS 没有最终猜测，作为支线策略保留。
- `benchmarks.ai_information_day` 已接入 `--boundary-evaluator`，支持 `day-survival` 与 `unknown`。
- 非认证估值不会进入证书；使用非 `day-survival-v1` 评估器时，常量子树压缩必须显式关闭。
- 实际整局估值器、终猜概率叶值、跨日搜索仍未实现。
- 默认实战 AI 和现有求解入口不变。

## 接口

`tragedy_sim/day_game/value.py`：

```python
@dataclass(frozen=True)
class BoundaryContext:
    world: object
    position: tuple[int, int]
    remaining_loops: int
    remaining_days: int
    utility_version: str = "day-survival-v1"
    scope: str = "known-world"

@dataclass(frozen=True)
class ValueEstimate:
    lower: Fraction
    upper: Fraction
    certified: bool
    scope: str
    version: str
```

`ContinuationEvaluator` 只要求两个成员：

- `version`：非空字符串，作为缓存和证书的收益版本键。
- `evaluate(context) -> ValueEstimate`：返回精确有理数区间。

`ValueEstimate` 的约束：

- `0 <= lower <= upper <= 1`。
- `certified=True` 才允许关闭证书。
- `certified=True` 且 `lower == upper` 才能作为常量折叠。
- 非认证估值可以用于实验，但在信息集树中一律回退为 `[0,1]` 未知叶。

## 已实现的评估器

| 评估器 | 版本 | 行为 |
| --- | --- | --- |
| `DaySurvivalEvaluator` | `day-survival-v1` | 完全复用现有 `day_boundary_value`，返回精确 0/1 |
| `UnknownEvaluator` | `unknown-v1` | 始终返回未认证 `[0,1]`，用于 T1 接口测试和对照 |
| `RandomRolloutEvaluator` | `random-rollout-v1` | 已知世界随机合法续演到终局，返回 Wilson 区间；永远未认证 |

`boundary_context(world, position)` 从剧本读取总天数和总轮回，计算剩余天数／轮回。它只整理上下文，不额外授予隐藏信息；公平使用时仍必须传入授权视图。

## 随机 rollout 基线

`RandomRolloutEvaluator(rollouts=8, max_steps=4096, seed=0)`：

- 每个 rollout 从边界世界克隆，使用带种子的 `random.Random` 随机选择合法动作，直到出现胜者或达到最大步数。
- 全部 rollout 完成时返回胜率的 95% Wilson 区间。
- 有未完成 rollout 时返回未认证 `[0,1]`。
- 终局已确定时直接返回精确 0/1，并标记认证。
- 只接受 `scope="known-world"`；团队／公平模式会拒绝，因为克隆真实世界会泄漏隐藏信息。
- 结果永远是未认证估值，不能关闭信息集树证书，也不进入默认 AI。

这个基线用于 T1 估值方向实验：先比较随机续演、剧本启发式和后续 T2 搜索给出的叶值哪个与实际整局胜负更一致，再决定是否 calibrate 成更强的估值器。

## 校准烟测

`benchmarks/ai_continuation_calibration.py` 用 `ai_self_play.play` 的真实自对弈轨迹，在成功结束一天的边界记录：

- `DaySurvivalEvaluator` 的当日 0/1。
- `RandomRolloutEvaluator` 的区间中点。
- 该局最终胜者。

FS01、`strategic` 剧作家对 `baseline` 主人公、8 节点／深度 8、20 局、33 个日边界（FS 支线样本）：

| 估值器 | Brier |
| --- | --- |
| 当日存活 0/1 | 0.879 |
| 随机 rollout，1 次 | 0.308 |
| 随机 rollout，4 次 | 0.457 |

BTX01、同配置、5 局、100 个日边界，实际胜负包含最终猜测：

| 估值器 | Brier |
| --- | --- |
| 当日存活 0/1 | 1.000 |
| 随机 rollout，1 次 | 0.306 |

BTX06、同配置、1 局、15 个日边界：

| 估值器 | Brier |
| --- | --- |
| 当日存活 0/1 | 1.000 |
| 随机 rollout，1 次 | 0.268 |

BTX01、`random` 剧作家对 `defensive` 主人公、3 局、24 个日边界：

| 估值器 | Brier |
| --- | --- |
| 当日存活 0/1 | 0.000 |
| 随机 rollout，1 次 | 0.175 |

BTX01、`strategic` 剧作家对 `particle_ensemble` 主人公、1 局、20 个日边界：

| 估值器 | Brier |
| --- | --- |
| 当日存活 0/1 | 1.000 |
| 随机 rollout，1 次 | 0.261 |

前 6 局全部由剧作家获胜，所以“活下来=1”的估值全部报错。`random` 剧作家的 3 局全部由主人公获胜，同一估值器的 Brier 变成 0.000。Brier 高度依赖样本胜负构成：全输样本让当日存活看起来极差，全赢样本让它看起来完美。

这说明：

- 当日存活值作为整局胜率估计确实有偏差，但偏差方向取决于未来失败率。
- 保命策略本身可能仍然强；Brier 不能替代同种子对弈的胜率比较。
- 后续校准必须报告胜负构成，并用混合样本；只看全输或全赢样本会得出相反结论。

读数：

- 当日存活值不能代表整局胜率；大量边界在当天存活后仍被剧作家赢下。
- 随机 rollout 明显优于当日存活，但增加采样次数反而变差。原因是随机双方策略与真实 AI 不匹配；更多样本只是把区间收窄到有偏的估计上。
- 这些结果只说明估值方向，不构成策略强弱结论。保命策略的胜率要用同种子对弈、终猜正确数、信息增量单独测。
- 当前样本小，不能据此宣称棋力或最终 Brier。
- 后续基线默认使用 BTX；FS 没有最终猜测，作为支线样本保留。

命令：

```powershell
python -X utf8 -m benchmarks.ai_continuation_calibration `
  --games 20 --rollouts 1 --rollout-steps 512 `
  --output references/ai-calibration/2026-10-21/t1-selfplay-calibration-20g1r.json
```

默认剧本现在是 BTX01；FS 需要显式 `--scenario official-fs-01-first-script`。

## 接入方式

`information_game._Builder` 新增可选 `boundary_evaluator`：

- 未传入时行为与 T0 完全一致。
- 传入 `DaySurvivalEvaluator` 时，信息集树与现有实现逐步等价；测试比较了界、节点、转移和未知叶数量。
- 传入未认证评估器时，边界叶记为未知，`continuation_complete=False`，求解结果不能认证。
- 传入了非 `day-survival-v1` 的评估器且未关闭常量子树压缩时直接报错。常量子树证明的版本是 `fs-all-native-actions/day-survival-v1`，不能跨收益版本复用。

`build_ability_information_tree` 和 `build_root_information_tree` 都暴露了该参数。

## CLI 接入

`benchmarks.ai_information_day` 新增：

```text
--boundary-evaluator {none,day-survival,unknown}
```

- `none`：默认，保持原行为。
- `day-survival`：显式使用 T0 兼容评估器，仍可开启常量子树压缩。
- `unknown`：边界叶全部未知，必须同时传 `--no-constant-compression`。
- 输出新增 `utility` 字段，记录评估器版本；`settings.boundary_evaluator` 记录选择。
- 非日存活评估器会绕开针对 `day-survival-v1` 的空策略黑方快速缓存。

已用 FS01 公开视图做过 3 秒烟测：`day-survival` 完成受预算限制的树，`unknown` 返回未知叶更多的树，两者界均为 `[0,1]`，不产生认证。

## 测试

`tests/test_day_game_continuation_value.py`，9 项通过：

- 日末存活、进入下一轮、轮回结束三类边界的 0/1 与引擎一致。
- 上下文正确计算剩余天数和轮回。
- 未认证估值不能成为证书。
- 非法区间、非法位置、非有理数估值失败关闭。
- `DaySurvivalEvaluator` 与现有信息集树的界、节点和未知叶一致。
- 未认证边界值让树保持未知。
- 缺少版本或 `evaluate()` 的评估器被拒绝；非日存活评估器要求关闭压缩。
- 随机 rollout 同 seed 可复现、永远未认证、团队 scope 与非法参数失败关闭；已结束对局返回精确 0/1。

相关信息集测试 34 项通过。

## 下一步

1. 实现第一个真正的 T1 估值器：读取剧本未来事件、剩余轮回、限次资源、关键人物保护和终猜联合概率。
2. 在日末叶端冻结估值版本、后验更新模型和后续政策，再接入 `full-responses` 诊断。
3. 与当日 0/1 基线做同源码、固定 10 seed 的配对对照，先证明估值方向正确，再谈棋力。
4. 之后再进入 T2 有限跨日。默认 AI 在获得多次配对证据前不切换。
