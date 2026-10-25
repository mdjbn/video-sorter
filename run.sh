#!/usr/bin/env bash
# 一键启动（Linux / macOS / fnOS）
# 用法：./run.sh [--port 8080] [--data-dir /path] [--web-dir web/dist]
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
VENV="server/.venv"
if [ ! -x "$VENV/bin/python" ]; then
  echo "› 创建 Python 虚拟环境 server/.venv"
  "$PY" -m venv "$VENV"
  "$VENV/bin/pip" install -q --upgrade pip
  "$VENV/bin/pip" install -q -r server/requirements.txt
fi

# 网页端：没有构建产物就先构建（需要 Node 18+）
if [ ! -f web/dist/index.html ]; then
  if command -v npm >/dev/null 2>&1; then
    echo "› 构建网页端（npm install && npm run build）"
    (cd web && npm install --no-audit --no-fund && npm run build)
  else
    echo "！未找到 npm，跳过网页端构建；服务端会显示一个提示页。" >&2
  fi
fi

cd server
exec "./.venv/bin/python" -m videosorter --web-dir "../web/dist" "$@"
