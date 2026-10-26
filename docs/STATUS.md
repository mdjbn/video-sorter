# 交付状态与验证矩阵

> 三条里程碑（M1 服务端+网页端、M2 安卓端、M3 Windows 桌面端/发版）的代码都已落地。
> 下表区分「本机已验证」与「只能在 CI / 真机上验证」，避免把没跑过的当成跑过了。

## 一、能直接跑起来的（服务器 / 网页端）

```bash
git clone <repo> && cd video-sorter
chmod +x run.sh
./run.sh                 # 首次会自动建 venv、装依赖、构建网页端
# 打开 http://<服务器IP>:8080  （默认账号 admin / admin1234）
```

- 数据默认在 `~/.config/video-sorter/`（Linux）/ `%APPDATA%\VideoSorter`（Windows），可用 `--data-dir` 指定。
- systemd 常驻模板：`packaging/videosorter.service`。

## 二、验证矩阵

| 模块 | 项目 | 状态 | 证据 |
| --- | --- | --- | --- |
| 后端 | 接口/扫描/播放/整理/撤销/上传/发现 | ✅ 本机通过 | `cd server && .venv/bin/python -m pytest -q` → **23 passed** |
| 后端 | Range 播放 + 按需 HLS 转码 | ✅ 本机通过 | pytest 内 mkv→HLS 用例（`index.m3u8` + `seg00000.ts`）|
| 网页端 | 类型检查 + 生产构建 | ✅ 本机通过 | `cd web && npx vue-tsc --noEmit && npm run build:only` |
| 网页端 | 端到端（登录/播放/打标签/主题/整理/撤销/管理页） | ✅ 本机通过 | `bash tools/e2e-web.sh` → **18/18 PASS**（CI：`.github/workflows/e2e.yml`）|
| fnOS | 打成 `.fpk` 应用包 | ✅ 本机通过 | `bash packaging/fnos/build.sh` → `dist/fnos/videosorter.fpk`（3.5 MB）|
| fnOS | 包内应用启动 + 生命周期脚本 | ✅ 本机通过 | 解包后模拟 `TRIM_*` 环境跑 `cmd/main start/status/stop`，`/api/health` 正常 |
| fnOS | 包内应用端到端 | ✅ 本机通过 | 用包内实例跑 `tools/e2e-web.js` → **18/18 PASS**（含真实文件移动与撤销）|
| fnOS | 应用中心里真安装 | ⚠️ 未验证 | 需要 NAS 管理员在应用中心手动安装（本机无 root）|
| 安卓 | 编译 APK | ✅ 本机通过（JDK21+Gradle8.11+SDK35） | `assembleDebug` → `dist/android/app-debug.apk`（20 MB，v1.0.0）；CI 也会出 APK artifact|
| 安卓 | 单元测试（normalize/主题/解析/发现） | ✅ 本机通过 | `testDebugUnitTest` → **8/8** |
| 安卓 | 真机/模拟器运行 | ⚠️ 未验证 | 本机无 KVM 权限、无设备；需 `adb install dist/android/app-debug.apk` |
| 桌面端 | Rust 代码编译（Windows 目标） | ✅ 本机通过 | `cargo check --target x86_64-pc-windows-gnu`（用 zig 充当 C 编译器/链接器）|
| 桌面端 | 链接 exe / NSIS / MSI 打包 | ✅ CI 通过 | `windows.yml`（windows-latest）→ `VideoSorter_1.0.0_x64-setup.exe` 67 MB / `.msi` 90 MB |
| 桌面端 | 绿色版 zip | ✅ CI 通过 | `windows.yml` → `VideoSorter-portable.zip` 91 MB |
| 发布 | tag 触发一键出包 | ✅ 已跑通 | `v1.0.0` → Release 五个附件（APK / NSIS / MSI / 绿色版 zip / fpk）|

## 三、本机如何验证 Windows 目标的 Rust 代码（无 gcc/mingw 的情况）

机器上没有 gcc、没有 mingw，直接 `cargo build` 会在 proc-macro 链接阶段报 `linker cc not found`。
用 zig 既当 C 编译器又当链接器即可跑通 `cargo check`（不做最终链接，够验证代码正确性）：

```bash
# 1) 取 zig（自带 glibc/mingw 头文件与 lld）
curl -LO https://ziglang.org/download/0.13.0/zig-linux-x86_64-0.13.0.tar.xz && tar xf zig-linux-x86_64-0.13.0.tar.xz

# 2) 让 rustc 找得到 cc / c++ / ar
mkdir -p /tmp/tc/bin
printf '#!/bin/sh\nexec %s cc "$@"\n'  "$PWD/zig-linux-x86_64-0.13.0/zig" > /tmp/tc/bin/cc
printf '#!/bin/sh\nexec %s c++ "$@"\n' "$PWD/zig-linux-x86_64-0.13.0/zig" > /tmp/tc/bin/c++
printf '#!/bin/sh\nexec %s ar "$@"\n'  "$PWD/zig-linux-x86_64-0.13.0/zig" > /tmp/tc/bin/ar
chmod +x /tmp/tc/bin/*

# 3) 交叉目标 C 编译器（zig 的 triple 写法，cc-rs 会传 --target=x86_64-pc-windows-gnu，需要转换）
#    另需 windres 与 dlltool 的替身：见仓库 tools/zig-cross/README.md
export PATH=/tmp/tc/bin:$PATH
export CC_x86_64_pc_windows_gnu=/tmp/tc/bin/zigcc.py
export AR_x86_64_pc_windows_gnu=/tmp/tc/bin/ar
cd src-tauri && cargo check --target x86_64-pc-windows-gnu
```

`cargo check` 阶段需要 `src-tauri/binaries/` 里至少有一个文件（Tauri 的 `bundle.resources` 校验），
可以先放个占位文件，CI 里则由 PyInstaller 产物填充。

## 四、接下来还需要什么

1. ✅ 仓库已开源：<https://github.com/mdjbn/video-sorter>，`v1.0.0` 已发布全部安装包。
2. **手机真机**：`adb install app-debug.apk`，验证局域网发现、上下滑播放、上传下载（Media3 在真机上的行为）。
3. **fnOS 应用中心**：用管理员在应用中心手动安装 `videosorter.fpk`，验证图标、启动/停止、授权目录。
4. **Windows 桌面端**：装 NSIS 包，验证 sidecar 起服务、WebView2 加载、退出时子进程被回收。

## 五、fnOS 应用包

`packaging/fnos/` 是可直接安装到 fnOS 应用中心的应用工程，
`bash packaging/fnos/build.sh` 出 `dist/fnos/videosorter.fpk`；安装后桌面出现「视频整理」图标，
服务跑在 8610（专用应用用户，非 root），数据在 `/var/apps/videosorter/var`，
手机上传落到共享目录 `videosorter/uploads`。细节与排错见 `docs/build.md` 第 8 节。

包内 payload = `videosorter/`（后端源码）+ `vendor/`（FastAPI/uvicorn 等依赖，pip --target 装好）
+ `webdist/`（网页端构建产物），运行时用 fnOS 自带的 `python3`（3.11）启动，不需要 Docker、不需要联网装依赖。

## 六、CI 与发布

| 工作流 | 触发 | 内容 | 最近状态 |
|---|---|---|---|
| `backend.yml` | push main / PR | `pytest`（23 项） | ✅ |
| `web.yml` | push main | `vue-tsc` + `vite build` | ✅ |
| `e2e.yml` | push main / PR | 起服务 + Puppeteer 真实浏览器 18 项断言 | ✅ |
| `android.yml` | push main（android/**）/ 手动 | 单测 8 项 + `assembleDebug` → APK artifact | ✅ |
| `windows.yml` | 手动 / 由 Release 调用 | PyInstaller sidecar + Tauri 打包 → NSIS/MSI + 绿色版 zip | ✅ |
| `fnos.yml` | 手动 / 由 Release 调用 | `fnpack build` → `.fpk` | ✅ |
| `release.yml` | tag `v*` | 汇总上面全部产物发 Release | ✅ |

发布操作见 [release.md](release.md)。
