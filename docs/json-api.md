# JSON 游戏服务协议 v1

领域引擎、Python 前端和网络传输通过 `GameService` 隔离。所有公开协议值都是普通 JSON；
内部效果队列、Python 对象和规则实现不会跨越接口边界。

## 启动

```powershell
python -m tragedy_sim --serve
```

默认监听 `127.0.0.1:8765`。开发 React 前端时可以明确允许其来源：

```powershell
python -m tragedy_sim --serve --allow-origin http://localhost:5173
```

在 `web/` 执行 `npm run build` 后，同一个 Python 进程会从 `http://127.0.0.1:8765/`
提供生产前端；静态路径经过目录边界校验，并附带 CSP 与 `nosniff` 响应头。没有构建目录时 `/v1` 接口仍可独立使用。

除非已经在外层配置 TLS、身份认证、限流与可信反向代理，否则不要监听公网地址。
当前服务的活动对局和局域网房间保存在进程内；服务重启前应通过 snapshot 接口保存。

家庭局域网模式显式监听全部本地接口，并打印经过筛选的私有 IPv4 地址：

```powershell
python -m tragedy_sim --host-room --port 8765
```

不要将该端口转发到公网。

## 基本流程

前端可以先读取公开内容目录：

```text
GET /v1/modules?lang=zh
GET /v1/catalog/{module}?lang=en
```

`lang` 支持 `zh`、`en`、`ja`，省略时为中文；不支持的值返回 `UNSUPPORTED_LANGUAGE`。
目录包含模块能力、地点、计数物、规则、身份、事件、角色和双方行动牌定义，前端不需要导入 Python 目录。

创建教学对局：

```http
POST /v1/games
Content-Type: application/json

{"module":"BTX"}
```

也可传入完整的 `scenario`，或传入现有 JSON 存档的 `snapshot`。创建响应包含：

- 随机 `session_id`；
- 当前 `revision`；
- 管理令牌和 `m/a/b/c` 四个座位令牌；
- 旁观者公开视图。

创建响应中的凭据只能交给房主。未来联机大厅应负责把单独的座位令牌安全地分发给对应玩家。

读取视图：

```http
GET /v1/games/{session_id}/view?viewer=spectator
GET /v1/games/{session_id}/view?viewer=m&lang=ja
Authorization: Bearer {mastermind_token}
```

旁观者视图不需要令牌。私密视图只能使用相同座位的令牌或管理令牌。

视图顶层包含 `phase` / `phase_name` 和 `timing` / `timepoint`。每条 `events[]` 也包含：

```json
{"timing":"day_end","timepoint":"第 3 天结束时","kind":"protagonists_lost","message":"主人公失败。"}
```

`timing` 是供程序、AI 与规则检查使用的稳定 ID；`timepoint` 是按 `lang` 生成的显示文本。
前端不得根据 `message` 或当前 `phase` 反推效果时点。内部必要选择会继承外层规则时间点。

读取合法行动：

```http
GET /v1/games/{session_id}/actions?actor=m
Authorization: Bearer {mastermind_token}
```

每个行动包含稳定于当前 revision 的 `id`、`type`、展示 `label` 和非秘密
`parameters`。选项的内部结算效果不会返回前端。

可选的 `ui.source` 是不参与行动身份计算的展示提示，表示该行动由哪个角色发动。它只会随本来就对该操作者可见的
行动返回，供界面实现“先选择角色，再选择能力”；客户端仍不得从 `label` 文本反推角色或规则效果。

提交行动：

```http
POST /v1/games/{session_id}/commands
Authorization: Bearer {seat_token}
Content-Type: application/json

{"action_id":"…","expected_revision":12}
```

revision 不匹配返回 HTTP 409 与 `STALE_REVISION`，客户端应刷新视图和合法行动，不能盲目重试旧命令。

管理接口需要管理令牌：

```text
GET    /v1/games/{session_id}/snapshot
GET    /v1/games/{session_id}/replay?lang=zh
DELETE /v1/games/{session_id}
```

回放只能在正式结束后导出。

## 局域网房间流程

房间码是保留前导零的六位数字字符串；客户端不得按整数解析。

房间层与 `GameService` 分离，并持有真正的游戏座位令牌。浏览器只获得独立房间令牌，不能选择其他玩家视角：

```text
POST   /v1/rooms                         创建房间并占据一个座位
GET    /v1/rooms/{code}                  读取公开大厅状态
POST   /v1/rooms/{code}/join             占据空座位
POST   /v1/rooms/{code}/ready            设置自己的准备状态
POST   /v1/rooms/{code}/start            房主在所需参与者均准备后开始
POST   /v1/rooms/{code}/leave            开始前释放自己的座位
POST   /v1/rooms/{code}/kick             房主释放误占座位
GET    /v1/rooms/{code}/updates          比较房间与游戏 revision
DELETE /v1/rooms/{code}                  房主关闭房间
```

创建请求示例：

```json
{"module":"BTX","nickname":"房主","seat":"m","spectators":true,"protagonist_count":2}
```

`protagonist_count` 可为 1、2、3，省略时为 3。LL 只接受 3。公开房间状态提供 `required_seats`、
`ready_to_start`、`logical_leader` 与 `human_leader`，客户端不应自行推导动态控制权。

创建者获得 `credential.room_token`、`credential.admin_token` 和自己的 `seat`；加入者只获得自己的
`room_token` 和 `seat`。房间公开响应只包含昵称、准备/在线状态、房间阶段及 revision，不包含游戏 session、
身份、剧本或其他令牌。昵称限制为 1–24 个可见字符。

对局开始后，各浏览器使用自己的房间令牌访问：

```text
GET  /v1/rooms/{code}/game/view
GET  /v1/rooms/{code}/game/actions
POST /v1/rooms/{code}/game/commands
```

命令正文仍然只有 `action_id` 和 `expected_revision`，最终由原有 `GameService` 校验。房主另可使用管理令牌访问
`game/snapshot` 和 `game/replay`。`updates` 接受 `room_revision` 与 `game_revision` 查询参数，返回
`room_changed` / `game_changed`；第一版客户端每秒轮询，但只在 revision 变化时重新读取游戏视图。

少人数模式不改变规则引擎的 `m/a/b/c` 逻辑 actor。`game/actions` 返回该真人此刻获准执行的所有合法行动和
`controlled_actors`；`game/view` 的 `controlled_hands` 只包含其当前获准查看的手牌。两名主人公玩家时，
A、B 固定控制自己的行动牌，当天真人领队额外控制 C 的行动牌和逻辑领队负责的团队选择；领队轮换后旧的
action ID 会因 revision 变化失效。服务端在提交时重新计算授权，浏览器不能声明或扩大自己的控制范围。

房间导出的 `.tlr` 仍以原始逻辑命令重演；以 `# ROOM_ACTOR` 开头的注释额外记录真人参与者昵称与实际逻辑
actor，旧版解析器会安全忽略这些注释。

房间码和所有令牌均由密码学安全随机源生成（房间码为便于手工输入的六位数字，访问令牌仍保持高熵）。HTTP 层限制正文大小、请求频率和字段集合；等待、进行中和已结束房间
分别在长时间无活动后清理。令牌保存在浏览器本地以支持刷新重连，但不会跨浏览器或设备自动复制。

## 稳定错误结构

```json
{
  "protocol_version": 1,
  "error": {
    "code": "STALE_REVISION",
    "message": "对局状态已经改变，请刷新后重试",
    "details": {"expected": 4, "current": 5}
  }
}
```

前端应根据 `code` 决定行为，将 `message` 用于直接提示。不要解析中文错误文本。

## Python 内部客户端

Tk 热座界面现在通过 `LocalGameClient` 使用同一份 JSON 协议。它没有 HTTP 序列化开销，
但仍会强制 JSON 拷贝、revision 检查、稳定行动 ID 和座位权限。旧测试可以通过兼容属性访问
领域对象；GUI 生产代码不再直接读取或修改 `Game`。
