# 续局价值接口（T1.1）

T1 的第一步：把日末收益从当日求解器中拆出来，允许替换成整局获胜价值评估。本次只建立接口、T0 兼容实现和失败关闭规则，不改变默认 AI，也不声称已有整局估值。

## 状态

- 接口、上下文和 T0 兼容评估器已实现，9 项专项测试通过。
- 新增未认证的随机 rollout 基线，用于 T1 估值实验；它不能关闭证书。
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

## 接入方式

`information_game._Builder` 新增可选 `boundary_evaluator`：

- 未传入时行为与 T0 完全一致。
- 传入 `DaySurvivalEvaluator` 时，信息集树与现有实现逐步等价；测试比较了界、节点、转移和未知叶数量。
- 传入未认证评估器时，边界叶记为未知，`continuation_complete=False`，求解结果不能认证。
- 传入了非 `day-survival-v1` 的评估器且未关闭常量子树压缩时直接报错。常量子树证明的版本是 `fs-all-native-actions/day-survival-v1`，不能跨收益版本复用。

`build_ability_information_tree` 和 `build_root_information_tree` 都暴露了该参数。

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
