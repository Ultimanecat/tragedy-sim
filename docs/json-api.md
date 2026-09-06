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

除非已经在外层配置 TLS、身份认证、限流与可信反向代理，否则不要监听公网地址。
当前服务的活动对局保存在进程内；服务重启前应通过 snapshot 接口保存。持久化房间仓库和断线重连属于后续联机层。

## 基本流程

前端可以先读取公开内容目录：

```text
GET /v1/modules
GET /v1/catalog/{module}
```

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
GET /v1/games/{session_id}/view?viewer=m
Authorization: Bearer {mastermind_token}
```

旁观者视图不需要令牌。私密视图只能使用相同座位的令牌或管理令牌。

读取合法行动：

```http
GET /v1/games/{session_id}/actions?actor=m
Authorization: Bearer {mastermind_token}
```

每个行动包含稳定于当前 revision 的 `id`、`type`、展示 `label` 和非秘密
`parameters`。选项的内部结算效果不会返回前端。

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
GET    /v1/games/{session_id}/replay
DELETE /v1/games/{session_id}
```

回放只能在正式结束后导出。

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
