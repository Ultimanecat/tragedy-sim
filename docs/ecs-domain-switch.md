# 在现有 ECS 上启用域名入口

以下命令针对 `tragedy.niegu.top`，保留已有的 IP 入口和其他网站。
两种入口共用同一个 Python 游戏进程；房间链接会使用打开页面时的地址。
在 ECS 的 root shell 执行。不要将后端 8765 端口开放到公网。

先确认 DNS 已指向这台 ECS，游戏后端健康，并且没有其他配置占用游戏子域名：

```bash
cd /home/admin/akarin/tragedy-sim
git status --short --branch
git pull --ff-only origin master
curl --fail --silent --show-error http://127.0.0.1:8765/v1/health
nginx -T 2>&1 | grep -n 'server_name tragedy.niegu.top'
certbot certificates
```

若 `nginx -T` 显示已有这个子域名的站点，先检查现有配置，
不要直接安装第二份重复的 `server_name`。若没有，再添加独立站点：

```bash
install -m 644 deploy/nginx-domain.conf /etc/nginx/conf.d/tragedy-domain.conf
nginx -t
systemctl reload nginx
certbot --nginx -d tragedy.niegu.top --redirect
nginx -t
systemctl reload nginx
curl --fail --silent --show-error https://tragedy.niegu.top/v1/health
```

健康检查应返回包含 `"status":"ok"` 的 JSON，且无证书警告。
`nginx -t` 失败时不要 reload。Certbot 的 Nginx 插件会修改
`/etc/nginx/conf.d/tragedy-domain.conf`，后续不要直接用仓库模板覆盖它。
已有 `niegu.top` 和 `goods2life.niegu.top` 站点应仍能访问。

手机访问 `https://tragedy.niegu.top/` 即可创建房间并分享链接。
IP 入口仍然可用，其短期证书仍须自动续期。若之后只想保留域名，
先完成域名联机验证，再单独撤下 IP 入口和证书。

## 后续一键更新

在游戏结束、没有需要保留的房间时，以 root 身份运行：

```bash
cd /home/admin/akarin/tragedy-sim
bash deploy/update-ecs.sh
```

脚本会检查本地仓库是否干净，快进拉取 `origin/master`，按需更新依赖，构建前端，
重启 `tragedy-sim` 服务，再检查本机健康接口。首次使用仍需按部署说明
安装 Python 虚拟环境、前端依赖和 systemd 服务。重启会清空所有房间；
脚本不会改动 Nginx 配置，也不会自动更新已安装的 systemd unit 文件。
如果仓库有本地修改，先人工检查，脚本不会覆盖它们。
