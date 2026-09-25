#!/usr/bin/env bash
# Update the existing single-instance ECS deployment. Run as root after games finish.
set -Eeuo pipefail

service_name=tragedy-sim
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"

fail() {
  printf '部署失败（第 %s 行）。Python 服务若尚未重启，仍保持原进程。\n' "$1" >&2
}
trap 'fail "$LINENO"' ERR

if (( EUID != 0 )); then
  printf '请用 root 运行：sudo bash deploy/update-ecs.sh\n' >&2
  exit 1
fi

for command in git npm systemctl curl; do
  if ! command -v "$command" >/dev/null 2>&1; then
    printf '缺少命令：%s\n' "$command" >&2
    exit 1
  fi
done

cd -- "$repo_dir"
if [[ "$(git branch --show-current)" != master ]]; then
  printf '当前分支不是 master，已停止。\n' >&2
  exit 1
fi
if [[ -n "$(git status --porcelain)" ]]; then
  printf '仓库存在未提交修改或未跟踪文件，已停止。请先检查 git status。\n' >&2
  exit 1
fi
if [[ ! -x .venv/bin/python ]]; then
  printf '缺少 .venv/bin/python，请先完成首次部署。\n' >&2
  exit 1
fi
if ! systemctl cat "$service_name" >/dev/null 2>&1; then
  printf '找不到 systemd 服务 %s，请先完成首次部署。\n' "$service_name" >&2
  exit 1
fi

printf '注意：重启 %s 会清空所有正在进行的房间。\n' "$service_name"
printf '[1/4] 拉取 master 最新代码...\n'
previous_commit="$(git rev-parse HEAD)"
git pull --ff-only origin master

printf '[2/4] 构建 Web 前端...\n'
if [[ ! -x web/node_modules/.bin/vite ]] || ! git diff --quiet "$previous_commit" HEAD -- web/package.json web/package-lock.json; then
  printf '前端依赖缺失或依赖清单已更新，正在执行 npm ci...\n'
  (cd web && npm ci)
fi
if ! git diff --quiet "$previous_commit" HEAD -- pyproject.toml; then
  printf 'Python 项目配置已更新，正在更新虚拟环境...\n'
  .venv/bin/python -m pip install -e .
fi
(cd web && npm run build)
test -s web/dist/index.html

printf '[3/4] 重启 Python 服务...\n'
systemctl restart "$service_name"
systemctl is-active --quiet "$service_name"

printf '[4/4] 检查本机健康接口...\n'
health=""
for attempt in {1..10}; do
  if health="$(curl --fail --silent --max-time 2 http://127.0.0.1:8765/v1/health)"; then
    break
  fi
  sleep 1
done
if [[ "$health" != *'"status":"ok"'* ]]; then
  printf '健康接口返回异常：%s\n' "$health" >&2
  journalctl -u "$service_name" -n 30 --no-pager >&2
  exit 1
fi

printf '部署完成：%s\n' "$(git rev-parse --short HEAD)"
printf '健康接口：%s\n' "$health"
