"""按目录做路径前缀比较。

踩过的坑：视频路径入库时是 `str(Path)`，在 Windows 上是反斜杠；源目录却可能
是用户手输、或从网页端带进来的正斜杠。以前这里直接拼 `path LIKE '源目录/%'`，
结果在 Windows 上永远匹配 0 行——源列表的视频数恒为 0，删源目录也不会连带清
理视频。另外源目录里可能含 `_` / `%`，拼进 LIKE 还会被当成通配符。

所以统一改成 `substr(col, 1, N) = 前缀` 的精确比较，并给两种分隔符各准备一
个前缀候选。
"""

from __future__ import annotations

import os

__all__ = ["dir_prefixes", "under_dir"]


def dir_prefixes(path: str) -> list[str]:
    """返回「位于该目录之下」的前缀候选，每个都以分隔符结尾。"""
    base = str(path).rstrip("/\\")
    return [base + sep for sep in sorted({os.sep, "/", "\\"})]


def under_dir(column: str, path: str) -> tuple[str, tuple[object, ...]]:
    """生成 SQL 条件与参数，用于匹配 *column* 落在 *path* 目录之下的行。"""
    prefixes = dir_prefixes(path)
    clause = "(" + " OR ".join(f"substr({column}, 1, ?) = ?" for _ in prefixes) + ")"
    params: list[object] = []
    for prefix in prefixes:
        params.append(len(prefix))
        params.append(prefix)
    return clause, tuple(params)
