# 用 zig 在没有 gcc 的机器上验证 Windows 目标的 Rust 代码

`src-tauri/` 是为 Windows 编译的 Tauri 2 外壳。CI 用 `windows-latest` 正常构建；
但在 Linux 开发机（没有 gcc / mingw）上想先跑一遍 `cargo check` 时，可以用 zig 自带的 C 编译器与链接器。

目录里的两个脚本：

- `zigcc.py`：cc-rs 调用 C 编译器时的包装。zig 的 target 写法是 `x86_64-windows-gnu`，
  而 cc-rs 传的是 `--target=x86_64-pc-windows-gnu`，脚本负责改写并去掉重复参数。
- `zigld.py`：rustc 链接阶段的包装（只在真链接时需要；`cargo check` 用不到）。
  会丢掉 lld 不认识的 Windows 链接参数（`--disable-auto-image-base` 等）。

还需要两个替身（windres / dlltool），`cargo check` 阶段 tauri-winres 会调用 `x86_64-w64-mingw32-windres`：

```sh
printf '#!/bin/sh\nexec <zig路径> dlltool "$@"\n' > /tmp/tc/bin/x86_64-w64-mingw32-dlltool
printf '#!/usr/bin/env python3\n...生成空 ar 归档...\n' > /tmp/tc/bin/x86_64-w64-mingw32-windres
chmod +x /tmp/tc/bin/x86_64-w64-mingw32-*
```

完整命令见 `docs/STATUS.md` 第三节。**注意：这只验证代码能编译，产物 exe 仍需在 Windows/CI 上链接。**
