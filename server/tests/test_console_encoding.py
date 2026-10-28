"""Windows 上 stdout 编码不是 UTF-8 时，启动横幅里的中文会把服务带崩。

真实事故：GitHub Actions 的 windows runner 上 cp1252 控制台跑打包好的 sidecar，
`__main__.py` 打印「网页端：」时抛 UnicodeEncodeError，20 秒内 /api/health 一直没有响应，
装包冒烟直接判失败。用例盯两件事：辅助函数把 errors 调松、`--help` 在这种编码下也能正常退出。
"""
from __future__ import annotations

import io
import os
import pathlib
import subprocess
import sys

from videosorter.__main__ import _safe_stdio


def test_safe_stdio_replaces_unencodable_chars() -> None:
    buf = io.BytesIO()
    stream = io.TextIOWrapper(buf, encoding="cp1252", errors="strict")
    old = sys.stdout
    sys.stdout = stream
    try:
        _safe_stdio()
        print("网页端：http://127.0.0.1:8080/")  # 修之前这里抛 UnicodeEncodeError
        stream.flush()
    finally:
        sys.stdout = old

    raw = buf.getvalue()
    assert b"http://127.0.0.1:8080/" in raw       # 能编的照常输出
    assert b"?" in raw                            # 编不了的被替换，而不是抛异常


def test_safe_stdio_tolerates_stream_without_reconfigure() -> None:
    old = sys.stdout
    sys.stdout = io.StringIO()  # 没有 encoding / reconfigure 的假流
    try:
        _safe_stdio()  # 不能抛
    finally:
        sys.stdout = old


def test_help_works_with_cp1252_stdio() -> None:
    # 子进程里没有 pytest 那套 sys.path 注入，得自己给 cwd 和 PYTHONPATH，
    # 否则 windows runner 上会报 "No module named videosorter"（真踩过）。
    server_dir = pathlib.Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONIOENCODING": "cp1252", "PYTHONPATH": str(server_dir)}
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "videosorter", "--help"],
        capture_output=True,
        cwd=server_dir,
        env=env,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")[-2000:]
