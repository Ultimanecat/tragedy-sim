# tragedy-sim

Python 版《悲剧轮回》模拟器，逐阶段实现。

**当前仅实现第一阶段：FS / BTX 共用的基础出牌、揭示与行动结算。**
不是完整 FS / BTX 对局：没有身份能力、好感能力、剧作家能力、事件、剧本胜负、AI 或联网。
`--module` 记录本次练习的模组依据；现阶段两者的基础牌与执行逻辑相同。

## 运行

需要 Python 3.11+，使用标准库，无需安装依赖。在项目目录运行：

```powershell
python -m tragedy_sim --demo
python -m tragedy_sim --demo --module BTX
python -m tragedy_sim
```

前两条自动演示一次双方出牌，第三条进入本地人工操作模式。
程序仅输出文字，不需要加载图片或联网。

## 手动完成第一次出牌

启动 `python -m tragedy_sim` 后依次输入：

```text
hand m
play m h student
play m i2 hospital
play m p1a doctor
play a h student
play b fi hospital
play c g2 doctor
board
resolve
board
```

预期：男学生由学校横移到都市（两张横移不抵消）；医院密谋仍为 0；医生不安 1、友好 2。
`m` 的 `i2` 和 `c` 的 `g2` 进入公开留置区，其余已用牌立即回手。
执行 `resolve` 前棋盘状态不变，`board` 只显示暗牌归属与目标。

操作命令：

| 命令 | 用途 |
| --- | --- |
| `hand m` / `hand a` | 查看指定玩家的可用手牌 |
| `play <玩家> <牌> <目标>` | 玩家 m / a / b / c 按顺序出牌 |
| `board` | 公开棋盘、暗牌位置和公开留置牌 |
| `view a` | A 的视角，只显示 A 自己的暗牌内容 |
| `resolve` | 六张牌全部放好后揭示并结算 |
| `log` | 已揭示行动及公开结算日志 |
| `next` | **练习控制**：保留棋盘与限次牌使用记录，轮换领队，进入下一次出牌 |
| `reset` | **练习控制**：恢复初始棋盘与全部手牌，开始新的练习轮回 |
| `help` / `quit` | 帮助 / 退出 |

`next` / `reset` 只能在结算完成后使用；它们不是完整的日末或轮回流程。
下一次出牌的领队按 A → B → C 轮换，三名主人公从当次领队开始出牌。

这是可信本地操作者使用的热座/调试程序。可以查询所有人的手牌，输入历史也会显示牌名；
视角过滤不等于防作弊安全边界。以后联机时，完整状态必须留在服务端。

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

牌组依据：用户提供的 `resources/data.xml` 手牌索引、FS / BTX 右上角牌表和对应牌面。
不使用“追加牌”中的不安 +2、希望、绝望等卡牌。

## 代码与验证

```powershell
python -m unittest discover -v
```

- `tragedy_sim/cards.py`：独立牌组、限次标记、地图。
- `tragedy_sim/engine.py`：`ActionGame`、`Character`、出牌与结算、玩家视图。
- `tragedy_sim/cli.py`：命令行交互和自动演示。
- `tests/test_actions.py`：规则、信息可见性、资源索引及 CLI 测试。
- [docs/rules-actions.md](docs/rules-actions.md)：规则来源、已实现范围及后续边界。

引擎与界面分离，可直接调用：

```python
from tragedy_sim import ActionGame

game = ActionGame(module="FS")
game.play("m", "i2", "doctor")
print(game.view("a")["pending"])  # 可见 m 和 doctor，不可见 i2
```

## 后续逐步扩展

先确认基础出牌，再分别加入好感能力、剧作家/身份能力、事件，最后连接完整轮回与胜负。
实现顺序与游戏内结算顺序是两回事：新增能力时需继续以 FS / BTX 标注的触发时机为准。

资源图片和 XML 保持用户提供的原样，没有打包进 Python 分发文件；代码运行不依赖资源。
不在本仓库替这些社区翻译或游戏图片声明新的授权。
