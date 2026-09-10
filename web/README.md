# Web client

This directory owns the browser client. Its only rules boundary is JSON protocol v1;
it must not import Python sources or inspect localized messages to decide game flow.

- `src/api/types.ts` is the frozen TypeScript contract.
- `fixtures/protocol-v1/` contains deterministic responses for offline UI development.
- The authoritative protocol narrative remains `docs/json-api.md`.

## 开发

```powershell
npm install
npm run dev
```

另开一个终端运行：

```powershell
python -m tragedy_sim --serve --allow-origin http://localhost:5173
```

Vite 会把 `/v1` 代理到 Python 服务。浏览器中的座位切换器只用于本地单机调试；每次切换都会丢弃前一视角的私密 UI 状态。

## 生产构建

```powershell
npm run build
cd ..
python -m tragedy_sim --serve
```

Python 服务会在 `http://127.0.0.1:8765/` 托管 `web/dist`，并继续在 `/v1` 提供 JSON API。
`npm test`、`npm run lint` 和 `npm run build` 分别运行组件/客户端测试、静态检查和类型检查加生产构建。
首次运行浏览器回归前执行 `npx playwright install chromium`，之后用 `npm run test:e2e`；测试会自行启停本地 Python 服务。

家庭局域网模式使用生产构建：

```powershell
python -m tragedy_sim --host-room --port 8765
```

大厅凭据保存在 `tragedy-sim.room.v1`，只包含当前浏览器的席位令牌；刷新或短暂断网后会继续该席位。
邀请链接使用 `?room=XXXXXX`，未入座的访客不会获得任何玩家令牌。
