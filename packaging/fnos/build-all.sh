#!/usr/bin/env bash
# 一次打两个架构的 fnOS 应用包：x86（x86_64）与 arm（arm64/aarch64）
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
OUT="${1:-$ROOT/dist/fnos}"
VS_ARCH=x86 bash "$HERE/build.sh" "$OUT"
VS_ARCH=arm bash "$HERE/build.sh" "$OUT"
ls -lh "$OUT"/videosorter-*.fpk
