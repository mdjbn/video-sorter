#!/usr/bin/env bash
# 生成 E2E 用的 4 个短样片（纯 ffmpeg lavfi，不依赖素材）。
# 用法：bash tools/make-demo-videos.sh [目标目录]   （默认 /tmp/vs-demo/master）
set -euo pipefail
OUT="${1:-/tmp/vs-demo/master}"
FFMPEG="${FFMPEG:-ffmpeg}"
rm -rf "$OUT"
mkdir -p "$OUT/手机导入"
gen() { # gen 文件名 时长 源
  "$FFMPEG" -y -v error -f lavfi -i "$3" -t "$2" -c:v libx264 -preset veryfast -pix_fmt yuv420p -c:a aac -shortest "$OUT/$1"
}
gen "东京街头夜景漫步.mp4" 6 "testsrc=size=640x360:rate=25"
gen "海边日落延时摄影.mp4" 4 "testsrc2=size=640x360:rate=25"
gen "手机导入/周末骑行.mkv" 3 "smptebars=size=640x360:rate=25"
gen "手机导入/镜头语言笔记.avi" 5 "testsrc=size=480x270:rate=24"
echo "样例视频已生成：$OUT"
ls -lh "$OUT" "$OUT/手机导入"
