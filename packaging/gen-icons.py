"""生成桌面端图标（纯标准库，不依赖 Pillow）。

绿色圆角方块 + 深色播放三角，与手机端 ic_launcher 同一套视觉。
输出：src-tauri/icons/{icon.png,32x32.png,128x128.png,128x128@2x.png,icon.ico}
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

ACCENT = (0x35, 0xD1, 0x8A)      # #35D18A
ACCENT_DARK = (0x1F, 0xA9, 0x6B)  # 下缘稍暗，做一点立体感
DARK = (0x06, 0x23, 0x1A)        # 三角 / 播放符号


def _lerp(a: int, b: int, t: float) -> int:
    return int(round(a + (b - a) * t))


def render(size: int) -> list[list[tuple[int, int, int, int]]]:
    px: list[list[tuple[int, int, int, int]]] = []
    pad = size * 0.06
    radius = size * 0.22
    x0, y0, x1, y1 = pad, pad, size - pad, size - pad

    # 播放三角（等边，略微右移，视觉居中）
    tri = [
        (size * 0.40, size * 0.30),
        (size * 0.40, size * 0.70),
        (size * 0.72, size * 0.50),
    ]

    def inside_round_rect(x: float, y: float) -> bool:
        if not (x0 <= x <= x1 and y0 <= y <= y1):
            return False
        cx = min(max(x, x0 + radius), x1 - radius)
        cy = min(max(y, y0 + radius), y1 - radius)
        return (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2

    def inside_tri(x: float, y: float) -> bool:
        (ax, ay), (bx, by), (cx, cy) = tri
        d1 = (x - bx) * (ay - by) - (ax - bx) * (y - by)
        d2 = (x - cx) * (by - cy) - (bx - cx) * (y - cy)
        d3 = (x - ax) * (cy - ay) - (cx - ax) * (y - ay)
        neg = d1 < 0 or d2 < 0 or d3 < 0
        pos = d1 > 0 or d2 > 0 or d3 > 0
        return not (neg and pos)

    for j in range(size):
        row: list[tuple[int, int, int, int]] = []
        for i in range(size):
            x, y = i + 0.5, j + 0.5
            if inside_tri(x, y) and inside_round_rect(x, y):
                row.append((*DARK, 255))
            elif inside_round_rect(x, y):
                t = (y - y0) / max(1.0, (y1 - y0))
                row.append((_lerp(ACCENT[0], ACCENT_DARK[0], t),
                            _lerp(ACCENT[1], ACCENT_DARK[1], t),
                            _lerp(ACCENT[2], ACCENT_DARK[2], t), 255))
            else:
                row.append((0, 0, 0, 0))
        px.append(row)
    return px


def write_png(path: Path, px: list[list[tuple[int, int, int, int]]]) -> bytes:
    size = len(px)
    raw = b"".join(
        b"\x00" + b"".join(bytes(px[j][i]) for i in range(size)) for j in range(size)
    )

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9))
    png += chunk(b"IEND", b"")
    path.write_bytes(png)
    return png


def main() -> None:
    out = Path(__file__).resolve().parents[1] / "src-tauri" / "icons"
    out.mkdir(parents=True, exist_ok=True)
    pngs = {}
    for size in (512, 256, 128, 64, 32, 16):
        pngs[size] = write_png(out / f"_tmp{size}.png", render(size))
    # Tauri 约定的文件名
    (out / "icon.png").write_bytes(pngs[512])
    (out / "32x32.png").write_bytes(pngs[32])
    (out / "128x128.png").write_bytes(pngs[128])
    (out / "128x128@2x.png").write_bytes(pngs[256])
    # Windows .ico：PNG 内嵌格式
    sizes = [256, 128, 64, 48, 32, 16]
    entries, offsets, blob = b"", 6 + 16 * len(sizes), b""
    for size in sizes:
        data = pngs[size if size in pngs else 32]
        w = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", w, w, 0, 0, 1, 32, len(data), offsets)
        offsets += len(data)
        blob += data
    (out / "icon.ico").write_bytes(struct.pack("<HHH", 0, 1, len(sizes)) + entries + blob)
    for size in (512, 256, 128, 64, 32, 16):
        (out / f"_tmp{size}.png").unlink(missing_ok=True)
    print("icons ->", out)


if __name__ == "__main__":
    main()
