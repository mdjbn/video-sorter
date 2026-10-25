#!/usr/bin/env bash
# fNOS / 某些挂载卷上新文件会以 mode 000 创建（只有 root 或 ACL 能读），
# 会让 git、gcc、gradle 等自己读不了自己刚写的文件。在项目根跑一次即可。
set -e
cd "$(dirname "$0")/.."
find . -path ./web/node_modules -prune -o -path ./.git -prune -o -type d -exec chmod u+rwx {} + 2>/dev/null || true
find . -path ./web/node_modules -prune -o -path ./.git -prune -o -type f -exec chmod u+rw {} + 2>/dev/null || true
find .git -type d -exec chmod u+rwx {} + 2>/dev/null || true
find .git -type f -exec chmod u+rw {} + 2>/dev/null || true
echo "permissions fixed"
