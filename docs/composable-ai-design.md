# 可组合 AI：信息策略 + 行动策略（设计草案）

## 目标

每个主人公 AI 都拆成两部分：

- **信息策略**：决定 AI 相信什么，给行动策略什么世界、身份和事故当事人。
- **行动策略**：只基于信息策略给出的快照选行动，不直接读真实游戏。

这样可以分开回答两个问题：

- 信息变好，行动会不会变好？
- 同样的信息下，行动策略是不是瓶颈？

## 接口草案

```python
@dataclass(frozen=True)
class BeliefSnapshot:
    worlds: tuple[Game, ...]              # 已确定化的世界，可含真实或采样身份
    known_roles: Mapping[str, str]        # 信息策略允许行动层使用的身份
    known_culprits: Mapping[int, str]     # 信息策略允许行动层使用的事故当事人
    source: str                           # public_particles / oracle_script / oracle_cards
    diagnostics: Mapping[str, Any]        # 采样数、失败原因、后验质量

class InformationPolicy(Protocol):
    def build(self, game, view, offers, *, budget, rng) -> BeliefSnapshot: ...

class ActionPolicy(Protocol):
    def choose(self, snapshot, view, offers, *, budget) -> dict: ...

class ComposedProtagonistAgent:
    """信息层和行动层组合；行动层看不到真实 game。"""
    def choose_action(self, *, participant, view, offers):
        snapshot = self.information.build(...)
        return self.action.choose(snapshot, view, offers)
```

关键约束：

- 行动策略只能拿快照、公开视图和合法行动，不能再读 `game.roles` 或 `game.scenario`。
- 信息策略决定是否作弊；开眼策略只改快照内容，不改行动代码。
- 快照在一次决策内冻结；信息策略版本、采样数、后验版本进入缓存键。
- 终猜也从快照产生；终猜策略属于信息策略或单独层，不能偷偷用真实剧本。

## 当前进度（2026-10-25）

- 新增 `tragedy_sim/composition.py`：`BeliefSnapshot`、`InformationPolicy`、`ActionPolicy`、`ComposedProtagonistAgent`。
- 新增 `ParticleInformationPolicy`，把公开粒子采样从 `ParticleEnsembleProtagonistAgent` 中拆出来；粒子代理现在通过该策略拿快照。
- 行动策略仍暂时留在 `ParticleEnsembleProtagonistAgent` 内，下一步再拆成独立 `ParticleActionPolicy`。
- 现有粒子测试和开眼测试通过。

## 现有实现怎么映射

| 现有 AI | 信息策略 | 行动策略 |
| --- | --- | --- |
| `particle_ensemble` | 公开 witness／分维粒子采样 | 粒子世界联合搜索 |
| `oracle_script` | 剧本身份 + 事故当事人，不看当天黑牌 | 脚本感知三牌联合搜索 |
| `oracle_cards` | 剧本身份 + 当天黑牌 | 同上 |
| `defensive` | 公开信息 | 防守启发式 |
| `baseline` | 公开信息 | 基础干扰启发式 |

## 已做的诊断混合

给 `particle_ensemble` 加了 `information_policy="oracle"`：

- 信息层：把采样世界里的身份改成真实身份，并把未来两天真实事故当事人告诉行动层。
- 行动层：仍然是原来的粒子联合搜索。
- 用途：只做诊断，不暴露到大厅。

BTX01、5 个种子：

| 信息策略 | 主人公胜局 |
| --- | --- |
| `public` | 2/5 |
| `oracle` | 3/5 |

两种都反复在第 5 天失去大小姐。说明只把身份和当事人信息补对，当前粒子行动策略仍然防不住这条事故。样本小，但方向清楚：这条失败是行动层问题，不是单纯信息不足。

## 迁移步骤

1. 新增 `BeliefSnapshot`、`InformationPolicy`、`ActionPolicy` 协议和 `ComposedProtagonistAgent`。
2. 先把粒子集成拆成公开信息策略和粒子行动策略，保留旧类作为兼容包装。
3. 再把开眼红方拆成开眼信息策略和脚本行动策略。
4. 最后把防守、基础干扰也包装成简单信息策略加行动策略。
5. 房间注册表按“信息策略 + 行动策略”组合配置，大厅只暴露稳定组合。

## 风险

- 粒子采样和行动评分目前耦合很紧，拆分会牵动缓存、日志和测试。
- 快照可能很大，组合层要避免重复复制游戏。
- 行动层如果还能拿到 `game`，信息边界会重新漏掉；接口必须在类型和测试上限制。
- 开眼组合只能作为诊断，不能进入公平大厅。
