#!/usr/bin/env bash
# 在 Linux/macOS 上构建 sidecar（Windows 请用 GitHub Actions 或直接在 Windows 上运行）
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> 构建网页端"
(cd web && npm install --no-audit --no-fund && npm run build:only)

echo "==> 安装 Python 依赖"
python3 -m venv server/.venv 2>/dev/null || true
./server/.venv/bin/pip install -q -U pip
./server/.venv/bin/pip install -q -r server/requirements.txt pyinstaller

echo "==> PyInstaller 打包"
./server/.venv/bin/pyinstaller server/videosorter.spec --noconfirm --distpath dist/sidecar --workpath build/pyi

echo "==> 完成：dist/sidecar/videosorter-server/"
