# Witness 组件架构

Witness 不再由一个总编译流程按规则集写死调用。组件注册表位于
`tragedy_sim/witness_components.py`，编译实现位于
`tragedy_sim/witness_rules/`；`RulesetWitnessCompiler` 只负责按注册顺序调度和消融，`FsbtxWitnessCompiler` 是兼容旧调用的薄子类。

## 三层职责

1. `PublicWitness` 只描述公开观察所得的约束，不读取真实剧本。
2. `WitnessComponentSpec` 声明组件 ID、独立编译函数和所有可消融 source。
3. `RULESET_WITNESS_COMPONENTS` 为每个规则集显式组合有序组件。

组件顺序是确定性接口的一部分：AI 的证据摘要和固定种子实验依赖稳定顺序，重构或复用组件时不得无意重排。

## 复用原则

- 跨规则集完全同义的公开现象使用同一个 `common.*` 组件，例如事件状态、好感拒绝和事件效果位置。
- 仅某规则集成立的推断使用规则集前缀，例如 `fs.key_death`、`btx.immediate_death_loss`。
- 名称相似但规则含义不同的效果不能为了复用而合并。新规则集应先证明前提、时间点和反例均一致。
- 一个组件可产生同一因果族的多个 source；source 用于精细消融，组件 ID 用于整体隔离和规则集装配。

## 添加组件

1. 在 `tragedy_sim/witness_rules/` 编写只接收玩家公开 `view` 的编译函数，返回 `PublicWitness` 列表。跨组件共享的值类型放在 `witness_types.py`，不要从总编译器反向导入。
2. 在注册表中添加 `WitnessComponentSpec`，完整列出其可能产生的 source。
3. 仅将该 spec 加入规则确实相同的规则集元组；不要修改共享组件来偷渡规则集特例。
4. 添加正例、反例、无效果/旧日志兼容、真实世界不被删除和 source 消融测试。
5. 运行 `registered_sources(module)` 覆盖检查、完整测试以及相同种子的启用/关闭对弈。

## 添加规则集

新规则集先建立自己的有序组件元组。可以直接复用已经验证同义的 `common.*` spec，再追加专属组件。尚未建立组件表的规则集返回空 witness，而不是自动继承 FS/BTX 假设。这样 MZ、MC 等规则集不会因为共享事件名称而误用不同版本的规则。

## 兼容和消融

- `disabled_sources={...}`：关闭一个具体观察来源，适合消融实验。
- `disabled_components={...}`：关闭整个因果组件，适合定位组件级错误。
- `include_joint=False`：保留旧的联合软 witness 开关。

存档和 replay 仍保存公开事件，而不是保存编译后的候选世界；组件升级后可从公开历史重新计算证据。旧事件缺少新快照字段时，组件必须不生成该硬约束。

FS/BTX 当前所有注册的 witness 都由独立函数编译，总编译器不再保存具体观察规则。死亡与轮回末组件仍包含 FS/BTX 分支；向新规则集复用它们前，必须拆出差异并分别验证，不能因事件名称相同就直接注册。

剧作家能力阶段的 `mastermind_ability_route` 是**硬析取**：`roles` 中任一“身份—候选角色”路线，或 `plots` 中任一副规则路线成立即可。匹配器对整个隐藏世界检查析取；最终身份求解器也枚举这些硬路线作为构造分支。不能把公开的 +1 直接记成某个角色的已知身份；医生的可拒绝身份、BTX 因子与大人物领地均需保留替代解释。若某规则集在相同时间点还有未建模的强制转移，应先跳过推断。
