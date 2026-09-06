# tragedy-sim

Python 版《悲剧轮回》本地热座模拟器。FS、BTX、OF、MZ、MC、HSA 对局现已串通：
出牌、好感（界面称“友好”）能力、剧作家与身份能力、事件、日末、轮回与胜负。

支持 FS 的全部 6 个规则 X/Y、7 种事件，BTX 的全部 12 个规则 X/Y、9 种事件，
OldFashion（OF）的全部 12 个规则 X/Y、8 种事件和 11 名登场角色，
MidnightZone（MZ）的全部 12 个规则 X/Y、11 种事件与 Ex / 身份宣称规则，
MysteryCircle（MC/MCX）的全部 12 个规则 X/Y、11 种事件、Ex 槽与事件移动限制，
以及 HauntedStageAgain（HSA）的全部 12 个规则 X/Y、11 种事件、尸体/群聚事件与诅咒牌规则。
内置各模组速查表对应的角色池及能力（MC 使用“手下”替换“军人”）。以用户提供的中文模组速查表为优先依据。
这是由真人控制双方的热座/裁判工具，不含 AI 或远程大厅。

## JSON 服务

后端提供版本化 JSON 接口；现有 Tk GUI 也通过同一个本地客户端边界读取状态、查询行动并提交命令，
不再直接操作 `Game` 对象。
启动本机服务：

```powershell
python -m tragedy_sim --serve
```

默认仅监听 `127.0.0.1:8765`。接口采用按座位访问令牌、稳定行动 ID 和乐观 revision，
可作为后续 React 前端及远程联机大厅的基础。完整端点和安全说明见 [JSON 游戏服务协议](docs/json-api.md)。

## 本地热座 GUI

Python 3.11+ 的 Windows/macOS 官方安装通常自带 Tk，无需安装第三方库：

```powershell
python -m tragedy_sim --gui
python -m tragedy_sim --gui --module BTX
python -m tragedy_sim --gui --module OF
python -m tragedy_sim --gui --module MZ
python -m tragedy_sim --gui --module MC
python -m tragedy_sim --gui --module HSA
python -m tragedy_sim --gui --script examples/btx-tutorial.json
python -m tragedy_sim --gui --load tragedy-session.json
```

完整对局结束后可在 GUI 选择“导出纯文本回放”，并通过“打开回放”逐项查看每次决策和结算。也可以直接启动：

```powershell
python -m tragedy_sim --gui --replay tragedy-replay.tlr
```

`.tlr` 是 UTF-8 纯文本：正文逐项列出双方暗牌、能力选择、猜测及其结算，结构化字段可由程序确定性重演。它包含剧本与全部秘密，只应在对局结束后查看或分享。

安装项目后也可以运行 `tragedy-sim-gui`。窗口提供：

- 四区域公共棋盘、事件日程、公开留置牌、角色能力、完整公开日志和规则速查；
- 手牌/目标选择、能力与事件选项、友好能力确认、最终猜测；
- 剧作家专属的规则、身份、当事人和内部使用记录；
- 换座位自动遮挡、`Esc` 手动遮挡、窗口失焦/最小化遮挡，以及旧按钮失效保护；
- 新建 FS/BTX/OF/MZ/MC 教学局、载入自定义剧本、恢复/保存任意中间状态，以及打开只读回放。

热座交接时，其他玩家应先移开视线，再由界面提示的玩家点击“我是该玩家”。
公共棋盘永远从 `spectator` 视角渲染，不会因为私密操作区展开而改变。
这是防止同桌误露信息的隐私帘，不是账户认证；屏幕共享、截图、终端历史和直接读取含秘密的存档仍可泄密。

如果 Python 未包含 Tk，GUI 会给出明确错误；命令行模式不受影响。

## 运行

需要 Python 3.11+，使用标准库，无需安装依赖。在项目目录运行：

```powershell
python -m tragedy_sim --demo
python -m tragedy_sim --demo --module BTX
python -m tragedy_sim --demo --module OF
python -m tragedy_sim --demo --module MZ
python -m tragedy_sim --demo --module MC
python -m tragedy_sim --module FS
python -m tragedy_sim --script examples/btx-tutorial.json
```

前两条自动演示“触发谋杀 → 第一轮失败 → 重置 → 第二轮获胜”；后两条进入人工对局。
没有参数时默认运行原创 FS 教学剧本。`--script` 以文件中的模组为准。
程序仅输出文字，不需要加载图片或联网。

## 手动完成第一天

启动 `python -m tragedy_sim` 后依次输入：

```text
hand m
next m
play m h student
play m i2 hospital
play m p1a doctor
play a h student
play b fi hospital
play c g2 doctor
board
resolve
next m
board
```

预期：男学生由学校横移到都市（两张横移不抵消）；医院密谋仍为 0；医生不安 1、友好 2。
`m` 的 `i2` 和 `c` 的 `g2` 进入公开留置区，其余已用牌立即回手。
执行 `resolve` 前棋盘状态不变，`board` 只显示暗牌归属与目标。
`resolve` 先统一揭示、移动，再给剧作家一个私密的行动能力窗口；`next m` 才继续结算计数物。

接着按阶段操作：

```text
options m
next m
options a
choose a 1
options m
choose m 1
next a
next m
next m
```

这段示例跳过剧作家可选能力；领队 A 声明医生的第一项友好能力，剧作家选择执行，患者不安 +1。
随后结算当天事件（第 1 天没有预定事件），换领队、结束第 1 天。下一天从 B 开始主人公出牌。
每次操作后都有下一步提示；`options` 的编号取决于当前状态，其他对局应重新查看，不要照抄编号。

操作命令：

| 命令 | 用途 |
| --- | --- |
| `hand m` / `hand a` | 查看指定玩家的可用手牌 |
| `play <玩家> <牌> <目标>` | 玩家 m / a / b / c 按顺序出牌 |
| `board` / `status` | 公开棋盘、临界值、尸体、护卫、事件日程、历史确认信息、能力使用情况 |
| `view a` | A 的视角，只显示 A 自己的暗牌内容 |
| `view m` | 剧作家私密视角：额外显示身份、实际规则 X/Y、当事人；不要向主人公展示 |
| `inspect doctor` | 角色初始/当前区域、禁行区域、属性、能力、被动特性 |
| `rules` | 本模组所有可能规则、身份能力、事件效果和固定初始牌组；不显示剧本答案 |
| `resolve` | 本日要求的牌齐全后统一揭示，进入行动能力窗口 |
| `options <座位>` | 合法能力或必要目标选项；`options m` 是私密窗口 |
| `choose <座位> <编号>` | 选择当前选项；好感能力声明后须由剧作家确认执行或拒绝 |
| `log` | 已揭示行动及公开结算日志 |
| `next [座位]` | 依次推进阶段；不代打行动牌，不跳过强制效果或必要选择 |
| `guess <领队> <角色> <身份ID>` | BTX/OF/MZ 最终猜测：所有角色的初始身份必须猜对，一次错误即败 |
| `final <领队>` | BTX/OF/MZ 轮回之间，放弃剩余轮回并提前猜测 |
| `save "session.json"` | 保存到新文件；已存在的文件不会覆盖；路径可加双引号 |
| `replay "finished.tlr"` | 正式结束后导出纯文本完整信息回放；不会覆盖已有文件 |
| `help` / `quit` | 帮助 / 退出 |

日常领队按 A → B → C 轮换；中途结束轮回不会额外轮换。
失败之后用 `next m` 开始下一轮。FS 轮回耗尽即判负；BTX/OF/MZ 会进入最终猜测。
完整对局没有任意 `reset` 按钮。保留了独立的第一阶段练习：`python -m tragedy_sim --practice`。

恢复存档：

```powershell
python -m tragedy_sim --load session.json
```

存档使用 JSON 剧本和命令重放，可恢复到暗牌未揭示、目标选择或能力确认途中。
存档含完整秘密，不应在游戏中发给主人公；退出不会自动保存。

这是可信本地操作者使用的热座/调试程序。默认输出只含公开信息，身份、当事人与隐藏能力来源不会自动透露。
但是同一操作者可以主动查询私密视角，输入历史也会显示出牌内容；视角过滤不是防作弊安全边界。
实际同桌游玩需隔离私密操作的屏幕和终端历史，或由独立裁判输入命令。讨论限制由真人遵守。

## 自定义剧本

复制 [FS 示例](examples/fs-tutorial.json)、[BTX 示例](examples/btx-tutorial.json)、
[OF 示例](examples/of-tutorial.json)、[MZ 示例](examples/mz-tutorial.json)、
[MC 示例](examples/mc-tutorial.json) 或 [HSA 示例](examples/hsa-tutorial.json) 后修改。
文件包含身份与当事人答案，主人公请勿提前阅读；这是原创教学剧本，不是官方剧本转录。

`main_plot` 选一个规则 Y，`subplots` 在 FS 选一个 X，在 BTX/OF/MZ 选两个不同 X。
`cast` 是角色 ID → 身份 ID，余下普通角色填写 `ordinary`。
规则、身份、事件 ID 可用 `rules` 查；全部角色见 [catalog.py](tragedy_sim/catalog.py)。
`incidents` 每条包含 `day`、`kind`、`culprit`，同一天最多一起事件。MZ 的连续杀人允许重复当事人；
伪造事件还必须用 `public_kind` 填写主人公看到的已知事件 ID（可来自其他模组），实际类型只在剧作家资料中出现。
身份数量、上限、少女条件、模组、日期和重复当事人会在开始前检查。

当前接受 1–8 天、1–8 轮和各模组速查表允许的角色。暂不支持任意额外剧本规则、延迟登场、其余模组或扩展角色；
不支持的字段会明确报错，不会静默忽略。也不自动 OCR 或导入整个资源包。
后续规则集采用 Haunted Stage Again（HSA）与 Another Horizon Revised（AHR）；旧版 HS / AH 不列入实现范围。

## 当前牌组

剧作家每次使用自己的三张牌；每名主人公各有独立的八张牌，每次各出一张。

| 牌 ID | 剧作家 m | 主人公 a / b / c |
| --- | --- | --- |
| `p1a`, `p1b` | 不安 +1，两个独立副本 | — |
| `p1` | — | 不安 +1 |
| `p-1` | 不安 -1 | 不安 -1，每轮回限一次 |
| `fp` | 禁止不安 | — |
| `fg` | 禁止友好 | — |
| `i1`, `i2` | 密谋 +1 / +2；+2 每轮回限一次 | — |
| `g1`, `g2` | — | 友好 +1 / +2；+2 每轮回限一次 |
| `fi` | — | 禁止密谋 |
| `h`, `v` | 横移 / 纵移 | 横移 / 纵移 |
| `d` | 斜移，每轮回限一次 | — |
| `fm` | — | 禁止移动，每轮回限一次 |

牌组依据：用户提供的 `resources/data.xml` 手牌索引、FS / BTX / OF / MZ 右上角牌表和对应牌面。
不使用“追加牌”中的不安 +2、希望、绝望等卡牌。

## 代码与验证

```powershell
python -m unittest discover -v
```

- `tragedy_sim/cards.py`：独立牌组、限次标记、地图。
- `tragedy_sim/engine.py`：`ActionGame`、`Character`、出牌与结算、玩家视图。
- `tragedy_sim/catalog.py`：角色、规则 X/Y、身份、事件及公开规则文案。
- `tragedy_sim/scenario.py`：JSON 剧本、严格校验、教学示例。
- `tragedy_sim/flow.py`、`model.py`：显式阶段表、阶段位置、决策/结算记录，以及供搜索算法使用的状态转移接口。
- `tragedy_sim/game.py`：完整流程编排、效果队列、选择、胜负、知识记录和存档。
- `tragedy_sim/replay.py`、`transcript.py`：纯文本回放、确定性校验、只读时间线和人类可读决策说明。
- `tragedy_sim/cli.py`：完整对局、行动练习、中文提示和自动演示。
- `tests/`：行动、能力、事件、胜负、信息过滤、CLI/GUI、存档及纯文本回放；覆盖 FS/BTX 的 114 种、OF 的 105 种组合及 MZ 专项规则。
- [完整对局规则说明](docs/rules-match.md)、[基础行动来源](docs/rules-actions.md)。

引擎与界面分离，可直接调用：

```python
from tragedy_sim import Game

game = Game()  # 默认 FS 教学剧本，或传入经过校验的剧本字典
game.dispatch("m", "next")
game.dispatch("m", "play", card="i2", target="doctor")

# AI/分析工具可以枚举合法动作，并在副本上模拟而不修改原局面：
actions = game.legal_actions("m")
candidate = dict(actions[0])
result = game.simulate(candidate.pop("actor"), candidate.pop("action"), **candidate)
print(game.view("a")["pending"])  # 可见 m 和 doctor，不可见 i2
print(game.controller)             # 当前应操作的座位
```

完整对局统一通过 `dispatch` 修改，非法命令回滚，成功命令进入存档历史。
`state`、`roles` 等内部状态仅供引擎或测试使用；直接修改这些字段不会记录到存档。
独立出牌练习的 `ActionGame` API 保持兼容。

资源图片和 XML 保持用户提供的原样，没有打包进 Python 分发文件；代码运行不依赖资源。
不在本仓库替这些社区翻译或游戏图片声明新的授权。
