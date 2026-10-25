#!/usr/bin/env python3
import subprocess, sys
ZIG = "/tmp/tc/zig-linux-x86_64-0.13.0/zig"
args, out = [], []
for a in sys.argv[1:]:
    if a.startswith("--target="):
        t = a.split("=", 1)[1]
        t = t.replace("-pc-", "-").replace("unknown-linux-gnu", "linux-gnu")
        out += ["-target", t]
    else:
        out.append(a)
sys.exit(subprocess.run([ZIG, "cc"] + out).returncode)
