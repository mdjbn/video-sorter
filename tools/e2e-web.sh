#!/usr/bin/env bash
# 一键端到端：起服务 → 跑 tools/e2e-web.js（真实浏览器）→ 收尾。
# 依赖：server/.venv（或 run.sh 建好的）、ffmpeg、node + puppeteer。
# 用法：bash tools/e2e-web.sh            （默认端口 18931）
#       PORT=18800 VS_NODE_PATH=/path/to/node_modules bash tools/e2e-web.sh
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
PORT="${PORT:-18931}"
DATA="${DATA:-/tmp/vs-e2e-data}"
SRC="${SRC:-/tmp/vs-e2e-src}"
MASTER="${MASTER:-/tmp/vs-demo/master}"
NODE_PATH_MOD="${VS_NODE_PATH:-/tmp/uiprev/node_modules}"
PY="$ROOT/server/.venv/bin/python"

[ -x "$PY" ] || { echo "先跑一次 ./run.sh 建 venv"; exit 1; }
bash tools/make-demo-videos.sh "$MASTER" >/dev/null   # 每次都重建，保证正好 4 个样片

rm -rf "$DATA" "$SRC"
cp -r "$MASTER" "$SRC"

# 端口被占（比如上次测试没退干净）就直接报错，免得打到别人的数据上
if curl -s -m 1 "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
  echo "端口 $PORT 已被占用，先停掉它（或换 PORT=... 重跑）"
  exit 1
fi

echo "→ 启动服务 :$PORT（数据 $DATA）"
( cd "$ROOT/server" && PYTHONPATH="$ROOT/server" exec "$PY" -m videosorter \
    --host 127.0.0.1 --port "$PORT" --data-dir "$DATA" --web-dir "$ROOT/web/dist" ) \
  > /tmp/vs-e2e-server.log 2>&1 &
SRV=$!
trap 'kill $SRV 2>/dev/null' EXIT
for i in $(seq 1 60); do
  curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null && break
  sleep 0.5
done
curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null || { echo "服务没起来，见 /tmp/vs-e2e-server.log"; exit 1; }

echo "→ 跑浏览器 E2E"
NODE_PATH="$NODE_PATH_MOD" VS_BASE="http://127.0.0.1:$PORT" VS_SRC="$SRC" VS_SHOTS=/tmp \
  node tools/e2e-web.js
CODE=$?
echo "→ 截图：/tmp/e2e-player.png /tmp/e2e-manage.png"
exit $CODE
