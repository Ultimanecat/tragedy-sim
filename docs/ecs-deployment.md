# ECS 试部署：tragedy.niegu.top

这份配置针对 Alibaba Cloud Linux 4、现有 Nginx/Certbot、仓库路径
`/home/admin/akarin/tragedy-sim`。使用独立子域名，保留原有 `niegu.top` 站点。
以下命令在 ECS 的 root shell 执行。完成每一步的检查后再继续。

## 1. 安装并检查后端

确认 `id admin` 成功，并确认服务器上的仓库没有需要保留的未提交修改：

```bash
cd /home/admin/akarin/tragedy-sim
git status --short --branch
git pull --ff-only origin master
python3 -m venv .venv
.venv/bin/python -m pip install -e .
cd web
npm ci
npm run build
cd ..
```

如服务器有未提交修改，先停止，不要覆盖它们。Node 版本须满足 Vite 的要求。

```bash
test -f web/dist/index.html
install -m 644 deploy/tragedy-sim.service /etc/systemd/system/tragedy-sim.service
systemctl daemon-reload
systemctl enable --now tragedy-sim
systemctl status tragedy-sim --no-pager
curl --fail --silent --show-error http://127.0.0.1:8765/v1/health
```

健康检查应返回包含 `"status":"ok"` 的 JSON。失败时查看
`journalctl -u tragedy-sim -n 80 --no-pager`。不要向公网开放 8765。

## 2. 配置 Nginx 和 HTTPS

DNS 中 `tragedy.niegu.top` 的 A 记录须指向 ECS 公网地址；安全组及服务器防火墙允许
TCP 80/443。确认 `command -v certbot` 有输出。若没有 Certbot，先安装 Certbot 及其 Nginx 插件。
Nginx 的 `conf.d` 应从 `http` 上下文加载配置，且没有其他同名 `server_name`。
游戏 API 使用 Bearer 令牌，不能给整个站点添加占用 `Authorization` 请求头的 Basic Auth。
模板按来源 IP 对一般请求和创建房间分别限速，并限制同时连接数；
公网实例还会关闭不需要的 `/v1/games` 本地单人会话入口。

```bash
install -m 644 deploy/nginx-tragedy.conf /etc/nginx/conf.d/tragedy-sim.conf
nginx -t
systemctl reload nginx
certbot --nginx -d tragedy.niegu.top
nginx -t
systemctl reload nginx
```

若 `nginx -t` 失败，保持现有 Nginx 进程不变，先修正配置。
Certbot 如询问是否将 HTTP 跳转至 HTTPS，请选择跳转。

## 3. 验证

```bash
curl --fail --silent --show-error https://tragedy.niegu.top/v1/health
systemctl status tragedy-sim nginx --no-pager
```

第一条命令应返回包含 `"status":"ok"` 的 JSON。
随后在手机浏览器打开 `https://tragedy.niegu.top/`，创建房间，另一台设备通过邀请链接加入。
测试一整天出牌和 SSE 状态更新。SSE 心跳间隔为 15 秒；Nginx 已关闭响应缓冲。

房间状态目前只存在于 Python 进程内。重启服务会清空房间；保持单实例运行，
不要启动多个后端进程或配置负载均衡。服务器若启用 SELinux 且阻止 Nginx 连接后端，
检查审计日志，再按需开启 `httpd_can_network_connect`。当前是小范围公网试玩配置，
未经过完整的抗滥用审计；长期公开前仍需限制总房间数与 AI 并发负载。
