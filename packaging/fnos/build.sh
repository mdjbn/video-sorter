#!/usr/bin/env bash
# 打 fnOS 应用包（.fpk）
#
# 用法： bash packaging/fnos/build.sh [输出目录]
# 依赖： fnpack（https://static2.fnnas.com/fnpack/fnpack-1.2.3-linux-amd64）、python3、npm（首次构建网页端时）
#
# 产物： dist/fnos/videosorter_<version>_x86.fpk
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
OUT="${1:-$ROOT/dist/fnos}"
WORK="${VS_FNOS_WORK:-/tmp/vs-fnos-build}"
PROJ="$WORK/videosorter"
FNPACK="${FNPACK:-/tmp/fnpk/fnpack}"

say() { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

[ -x "$FNPACK" ] || die "找不到 fnpack：$FNPACK（可从 https://static2.fnnas.com/fnpack/fnpack-1.2.3-linux-amd64 下载）"

say "1/6 生成图标"
python3 "$ROOT/packaging/gen-fnos-icons.py" >/dev/null

say "2/6 准备网页端 dist"
if [ ! -f "$ROOT/web/dist/index.html" ]; then
  command -v npm >/dev/null 2>&1 || die "web/dist 不存在且没有 npm，请先构建网页端"
  ( cd "$ROOT/web" && { [ -d node_modules ] || npm install; } && npm run build )
fi

say "3/6 组装 fnOS 工程到 $PROJ"
rm -rf "$PROJ"
mkdir -p "$PROJ"
cp -a "$HERE/project/." "$PROJ/"
mkdir -p "$PROJ/app/videosorter" "$PROJ/app/vendor" "$PROJ/app/webdist" "$PROJ/app/tools"

# 后端源码（不含 __pycache__ / 测试 / 开发依赖）
cp -a "$ROOT/server/videosorter/." "$PROJ/app/videosorter/"
find "$PROJ/app/videosorter" -type d -name '__pycache__' -prune -exec rm -rf {} +
find "$PROJ/app/videosorter" -type d -name 'tests' -prune -exec rm -rf {} + 2>/dev/null || true
find "$PROJ/app/videosorter" -name '*.pyc' -delete
cp -a "$ROOT/web/dist/." "$PROJ/app/webdist/"
cat > "$PROJ/app/tools/README.md" <<'EOF'
把 ffmpeg / ffprobe 放到这里即可让「视频整理」优先使用自带的二进制；
不放也能用，会自动回退到系统 PATH 里的 ffmpeg（fnOS 自带）。
EOF

say "4/6 安装 Python 运行时依赖到 app/vendor"
PY="${VS_PYTHON:-$ROOT/server/.venv/bin/python}"
[ -x "$PY" ] || PY="$(command -v python3)"
"$PY" -m pip install --quiet --disable-pip-version-check --no-cache-dir \
  --target "$PROJ/app/vendor" -r "$ROOT/server/requirements.txt"

# 去掉第三方依赖里的字节码缓存，减小体积
find "$PROJ/app/vendor" -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
find "$PROJ/app/vendor" -name "*.pyc" -delete 2>/dev/null || true

say "5/6 规范化文件权限（NAS 卷上的权限不可靠）"
chmod -R u+rwX "$PROJ"
find "$PROJ" -type d -exec chmod 755 {} +
find "$PROJ" -type f -exec chmod 644 {} +
chmod 755 "$PROJ"/cmd/* 2>/dev/null || true
find "$PROJ/app/vendor" -type f \( -name '*.so' -o -name '*.so.*' \) -exec chmod 755 {} + 2>/dev/null || true

say "6/6 fnpack build"
mkdir -p "$OUT"
cd "$PROJ"
"$FNPACK" build --directory "$PROJ" | tail -5
PKG="$(ls -1 "$PROJ"/*.fpk 2>/dev/null | head -1)"
[ -n "${PKG:-}" ] || die "fnpack 没有产出 .fpk，检查上面的输出"
cp -f "$PKG" "$OUT/"
chmod 644 "$OUT/$(basename "$PKG")"
say "完成： $OUT/$(basename "$PKG")  ($(du -h "$PKG" | cut -f1))"
