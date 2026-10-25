"""生成 fnOS 应用图标（纯标准库）。

复用 packaging/gen-icons.py 的绘制逻辑，输出：
- packaging/fnos/project/ICON.PNG (256x256)
- packaging/fnos/project/ICON_256.PNG (256x256)
- packaging/fnos/project/app/ui/images/icon_256.png / icon_64.png
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJ = HERE / "fnos" / "project"


def _load_renderer():
    spec = importlib.util.spec_from_file_location("vs_gen_icons", HERE / "gen-icons.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    assert spec and spec.loader
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def main() -> None:
    gen = _load_renderer()
    targets = {
        PROJ / "ICON.PNG": 256,
        PROJ / "ICON_256.PNG": 256,
        PROJ / "app" / "ui" / "images" / "icon_256.png": 256,
        PROJ / "app" / "ui" / "images" / "icon_64.png": 64,
    }
    cache: dict[int, bytes] = {}
    for path, size in targets.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if size not in cache:
            cache[size] = gen.write_png(path, gen.render(size))
        else:
            path.write_bytes(cache[size])
        print("icon ->", path.relative_to(HERE.parent), f"({size}x{size})")


if __name__ == "__main__":
    main()
