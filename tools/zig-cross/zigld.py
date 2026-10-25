#!/usr/bin/env python3
"""把 rustc 传给 linker 的参数转发给 zig cc（目标 x86_64-windows-gnu）。
过滤掉 lld 不认识的 Windows 链接参数（--disable-auto-image-base 等）。"""
import subprocess, sys
ZIG = "/tmp/tc/zig-linux-x86_64-0.13.0/zig"
DROP = {
    "-Wl,--disable-auto-image-base",
    "-Wl,--dynamicbase",
    "-Wl,--nxcompat",
    "-Wl,--high-entropy-va",
}
args = [a for a in sys.argv[1:] if a not in DROP and not a.startswith("--target=")]
sys.exit(subprocess.run([ZIG, "cc", "-target", "x86_64-windows-gnu"] + args).returncode)
