# ECS 试部署：直接使用公网 IP

这份配置针对 Alibaba Cloud Linux 4、Nginx、Certbot 5.7.0、公网 IP
`47.93.184.53`，仓库位于 `/home/admin/akarin/tragedy-sim`。
已有的域名站点保持原样。以下命令在 ECS 的 root shell 执行。
在每一步检查通过后继续；遇到冲突或错误时停止并保留当前配置。

## 1. 启动仅供本机访问的后端

确认 `id admin` 成功，并检查服务器仓库是否有需要保留的未提交修改：

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
test -f web/dist/index.html
install -m 644 deploy/tragedy-sim.service /etc/systemd/system/tragedy-sim.service
systemctl daemon-reload
systemctl enable --now tragedy-sim
curl --fail --silent --show-error http://127.0.0.1:8765/v1/health
```

健康检查应返回包含 `"status":"ok"` 的 JSON。失败时查看
`journalctl -u tragedy-sim -n 80 --no-pager`。不要向公网开放 8765。

## 2. 在 Nginx 上准备 IP 证书验证

ECS 安全组及服务器防火墙须允许 TCP 80/443，`conf.d` 须从 Nginx 的
`http` 上下文加载。确认没有现成的 `listen 443 ssl default_server`，
否则先处理冲突。若 `/etc/nginx/conf.d/tragedy-sim.conf` 已存在，先检查它
是否为此前安装的游戏配置；不要覆盖其他服务的文件。然后安装仅提供
HTTP-01 验证的临时配置：

```bash
nginx -T 2>&1 | grep -E 'listen .*443.*default_server|server_name 47\.93\.184\.53'
install -d -m 755 /var/www/tragedy-acme/.well-known/acme-challenge
install -m 644 deploy/nginx-ip-bootstrap.conf /etc/nginx/conf.d/tragedy-sim.conf
nginx -t
systemctl reload nginx
curl -i http://47.93.184.53/.well-known/acme-challenge/no-such-file
```

最后一条应返回此临时站点的 404。若看到其他域名的重定向，
检查是否有更高优先级的 IP 站点或 80 端口默认规则。

## 3. 申请 IP 的 HTTPS 证书

Certbot 5.4+ 支持通过 `--webroot` 申请 IP 证书。IP 证书只有约六天有效期，
所以自动续期必须正常运行。Nginx 插件目前不能自动安装 IP 证书。

```bash
certbot certonly --webroot --webroot-path /var/www/tragedy-acme \
  --preferred-profile shortlived --ip-address 47.93.184.53
certbot certificates
test -f /etc/letsencrypt/live/47.93.184.53/fullchain.pem
test -f /etc/letsencrypt/live/47.93.184.53/privkey.pem
```

若已有同名证书，Certbot 可能生成不同的目录名；以 `certbot certificates`
实际显示的路径为准，相应调整下一步配置中的证书路径。

## 4. 启用 HTTPS 代理

最终配置只让游戏服务接收来自 Nginx 的本机流量，同时提供 IP 的 443 站点。
IP 地址的 HTTPS 连接可能不发送 SNI，因此配置为 443 的默认站点；
已有域名站点仍由其域名 SNI 匹配。未发送 SNI 的旧客户端将收到 IP 证书。
若已有另一个 443 默认站点，先停止并检查冲突。

```bash
install -m 644 deploy/nginx-tragedy.conf /etc/nginx/conf.d/tragedy-sim.conf
nginx -t
systemctl reload nginx
curl --fail --silent --show-error https://47.93.184.53/v1/health
```

健康检查应返回包含 `"status":"ok"` 的 JSON，且 `curl` 无证书警告。
执行 `nginx -t` 失败时不要 reload；还原临时配置并检查报错。
代理按来源 IP 限速、限制并发连接，并关闭公网不需要的 `/v1/games`
本地单人会话入口。游戏页面和房间接口仍共用一个来源，SSE 可正常工作。

## 5. 验证续期与多人联机

将续期后的 Nginx 重载钩子安装到 Certbot 的钩子目录，并检查自动续期任务：

```bash
install -m 755 deploy/renew-nginx.sh /etc/letsencrypt/renewal-hooks/deploy/tragedy-nginx-reload.sh
certbot renew --dry-run
systemctl list-timers --all | grep -E 'certbot|snap.certbot'
```

确认已有定时续期且至少每天运行一次；若没有，先配置定时任务再对外分享地址。
随后在手机浏览器打开 `https://47.93.184.53/`，创建房间，
另一台设备通过邀请链接加入，测试一整天出牌与 SSE 更新。

房间状态目前只存在于 Python 进程内。重启服务会清空房间；保持单实例运行，
不要配置多个后端进程或负载均衡。服务器若启用 SELinux 且阻止 Nginx
连接后端，检查审计日志，再按需开启 `httpd_can_network_connect`。
当前是小范围公网试玩配置，未经过完整的抗滥用审计；长期公开前
仍需限制总房间数与 AI 并发负载。
