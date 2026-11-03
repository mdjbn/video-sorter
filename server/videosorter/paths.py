"""目录重叠判断（源目录之间、标签目录之间、源目录与标签目录之间）。

为什么需要它：扫描范围 = 所有启用源目录 + 每个标签的目标目录。一旦两处范围
互相包含，同一个文件就会被两个入口各扫一次——以前靠 `scan_sources()` 内部那张
`planned` 字典去重，可那只是一次扫描内的保险；只要两个扫描并发（手机端点一次、
网页端点一次），同一个文件就会被两边同时 INSERT，撞 `videos.path` 的 UNIQUE
约束，整轮扫描报 IntegrityError（实测：3 个并发全量扫描，2 个直接失败）。

所以在**写入配置时就**把这些重叠拦住，扫描时就不可能出现同一文件属于两个目录。

规则（与产品约定一致）：
  1. 源目录之间不能重叠（相同或互相包含）；
  2. 源目录不能位于任何标签目录内部；
  3. 标签目录不能位于任何源目录内部；
  4. 标签目录之间不能重叠。

重叠判定必须用「分隔符边界」而不是裸 `startswith`：`/a/bc` 并不在 `/a/b` 里面，
裸前缀会把它们判成重叠，用户会莫名其妙被拒。
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["norm_path", "is_same_dir", "is_under", "overlaps", "overlap_message"]


def norm_path(path: str | Path) -> str:
    """规范化成可比较的绝对路径：展开 ~、解析相对段、去掉尾部分隔符。

    解析失败（比如路径里有坏链接）时退回字符串形式，别让判断本身抛异常——
    用户填了个不存在的目录时，校验应该给出「目录不存在」而不是崩掉。
    """
    raw = str(path).strip().strip('"').strip("'")
    if not raw:
        return ""
    try:
        resolved = Path(raw).expanduser().resolve()
    except (OSError, RuntimeError):
        return raw.rstrip("/\\")
    text = str(resolved)
    # 根目录（`/`）不能再去尾部分隔符，否则会变成空串
    if len(text) > 1:
        text = text.rstrip("\\/")
    return text


def is_same_dir(a: str | Path, b: str | Path) -> bool:
    na, nb = norm_path(a), norm_path(b)
    return bool(na) and na == nb


def is_under(child: str | Path, parent: str | Path) -> bool:
    """child 是否**严格位于** parent 之下（不含 child == parent）。"""
    nc, npar = norm_path(child), norm_path(parent)
    if not nc or not npar or nc == npar:
        return False
    for sep in {os.sep, "/", "\\"}:
        prefix = npar if npar.endswith(sep) else npar + sep
        if nc.startswith(prefix):
            return True
    return False


def overlaps(a: str | Path, b: str | Path) -> bool:
    """两个目录是否重叠：相同、a 在 b 内、或 b 在 a 内。"""
    if is_same_dir(a, b):
        return True
    return is_under(a, b) or is_under(b, a)


def overlap_message(new_path: str | Path, other_path: str | Path, other_label: str) -> str:
    """拼一句能让人看懂的重叠原因（说明是谁包含谁）。"""
    if is_same_dir(new_path, other_path):
        return f"和{other_label}「{other_path}」是同一个目录"
    if is_under(new_path, other_path):
        return f"这个目录在{other_label}「{other_path}」里面"
    return f"{other_label}「{other_path}」在这个目录里面"
