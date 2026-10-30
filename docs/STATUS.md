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
| 后端 | 接口/扫描/播放/整理/撤销/上传/发现 | ✅ 本机通过 | `cd server && .venv/bin/python -m pytest -q` → **127 passed**（Windows 上 118 passed / 9 skipped，见下）|
| 后端 | Range 播放 + 按需 HLS 转码 | ✅ 本机通过 | pytest 内 mkv→HLS 用例（`index.m3u8` + `seg00000.ts`）|
| 网页端 | 类型检查 + 生产构建 | ✅ 本机通过 | `cd web && npx vue-tsc --noEmit && npm run build:only` |
| 网页端 | 端到端（登录/播放/打标签/主题/整理/撤销/管理页） | ✅ 本机通过 | `bash tools/e2e-web.sh` → **21/21 PASS**（CI：`.github/workflows/e2e.yml`）|
| 网页端 | 整理失败明细 / 不可写提示条 / 缓存设置（1.3.6） | ✅ 本机通过 | 18941 实例 + puppeteer 逐场景截图，见 `docs/screenshots/v136*.png`、`v136b-*.png` |
| 安卓 | 四条体验改进（1.3.7：滚动位置 / 去水波 / 排序按钮 / 横屏全屏） | ✅ 真机通过 | 见下方「安卓真机实测（1.3.7）」，截图 `v136c-*.png`、`v136g-*.png`、`v137-*.png` |
| fnOS | 打成 `.fpk` 应用包 | ✅ 本机通过 | `bash packaging/fnos/build.sh` → `dist/fnos/videosorter.fpk`（3.5 MB）|
| fnOS | 包内应用启动 + 生命周期脚本 | ✅ 本机通过 | 解包后模拟 `TRIM_*` 环境跑 `cmd/main start/status/stop`，`/api/health` 正常 |
| fnOS | 包内应用端到端 | ✅ 本机通过 | 用包内实例跑 `tools/e2e-web.js` → **21/21 PASS**（含真实文件移动与撤销）|
| fnOS | 应用中心里真安装 | ⚠️ 未验证 | 需要 NAS 管理员在应用中心手动安装（本机无 root）|
| 安卓 | 编译 APK | ✅ 本机通过（JDK21+Gradle8.11+SDK35） | `assembleRelease`（固定证书签名）→ `app-<abi>-release.apk`；CI 也会出 APK artifact|
| 安卓 | 单元测试（normalize/主题/解析/发现/整理摘要/缓存上限） | ✅ 本机通过 | `testDebugUnitTest` → **25/25** |
| 安卓 | 真机运行（Xiaomi M2104K10AC / Android 13 / adb 无线） | ✅ 已验证 | 登录（局域网发现）→ 上传 → 播放（直放 + HLS 转码）→ 打标签 → 整理 → 下载全链路通过；见下方「安卓真机实测」 |
| 桌面端 | Rust 代码编译（Windows 目标） | ✅ 本机通过 | `cargo check --target x86_64-pc-windows-gnu`（用 zig 充当 C 编译器/链接器）|
| 桌面端 | 链接 exe / NSIS / MSI 打包 | ✅ CI 通过 | `windows.yml`（windows-latest）→ `VideoSorter_1.0.0_x64-setup.exe` 67 MB / `.msi` 90 MB |
| 发布 | tag 触发一键出包 | ✅ 已跑通 | `v1.3.6`、`v1.3.7` 五个 job 全绿，Release 六个附件（x86/arm fpk、arm64/armeabi APK、Windows exe/msi）|\n| 发布 | Windows 打包的 ffmpeg 下载 | ✅ 加多源回退 | gyan.dev 偶发 503 会卡死整个 job，`windows.yml` 现在按 gyan.dev → GyanD/codexffmpeg → BtbN 顺序重试，每个源 3 次并校验体积 |

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

### 安卓真机实测（2026-10-26）

设备：`M2104K10AC`（chopin，Xiaomi，Android 13 / SDK 33，1080×2400），服务端是 fnOS 上的 `.fpk` 实例（`:8610`）。
跑通链路：UDP 局域网发现 → 登录 → 手机上传（`/api/upload`）→ 播放列表 → 直放 mp4 / HLS 转码 mkv（`.mkv` 需 ffmpeg 切片）→
播放页打标签 → 整理页执行移动（文件真的进了 `uploads/<标签>/`）→ 列表长按「下载到手机」（DownloadManager + Bearer）→ 三档主题切换。

真机上发现并修掉的问题（都是后端早就对了、手机端自己写错的地方）：

| # | 现象 | 原因 | 修法 |
| --- | --- | --- | --- |
| 1 | 登录提示「连不上服务器」 | `ping()` 把 `/api/health` 反序列化成 `Map<String,String>`，里面是 bool/数字 | 改成解析 `JsonObject` 判 `ok` |
| 2 | 列表页整页崩 | 后端无播放历史时 `position` 是 `null`，模型声明成非空 `Double` | `Double? = null` |
| 3 | 播放报 `ERROR_CODE_IO_BAD_HTTP_STATUS` | ExoPlayer 请求 `/raw` 没带令牌（401） | `DefaultHttpDataSource.Factory().setDefaultRequestProperties(headers)` + `DefaultMediaSourceFactory` |
| 4 | 整理页提示「接口不存在」 | `preview()` 写成 GET，服务端是 POST | 改 POST |
| 5 | 设置页「扫描源文件夹」报错 | `scan()` 同样 GET vs POST | 改 POST |
| 6 | 列表行没有文件名 | 后端字段叫 `filename`，模型字段叫 `name` 又没加 `@SerialName` | 加 `@SerialName("filename")` |
| 7 | 列表缩略图全空白 | Coil 的 OkHttpClient 不带 `Authorization` → `/thumb` 401 | `MainActivity` 里给 Coil 装带拦截器的 ImageLoader（token 实时读） |
| 8 | 356 KB 显示成「0 MB」 | 体积格式化只做了 MB 一档 | 抽出 `sizeText()`（B/KB/MB） |
| 9 | 设置页版本写死 `v0.1.0` | 硬编码字符串 | `BuildConfig.VERSION_NAME` + `buildFeatures.buildConfig = true` |
| 10 | 播放页空态与「加载中…」同时出现 | 两个分支没互斥 | 统一 `noteText` 互斥渲染 |
| 11 | mkv 首次播放偶发失败 | 没等 HLS 切片就绪就交给 ExoPlayer | 轮询 `/hlsstatus` + 「首次播放需转码处理 · N%」提示 |
| 12 | 播完轻点没反应 | `play()` 在 `STATE_ENDED` 下无效 | 先 `seekTo(0)` 再 `play()` |

**安卓端已知限制**：用固定正式证书签 `assembleRelease`（未开混淆）；`@zseven-w/dsh-android` 插件在本机会话里仍认不出 adb（其 `AdbToolchain` 在插件启动时就缓存了解析结果，需重启宿主服务），调试全程用原始 `adb` 命令。

### 安卓真机实测（2026-10-30，1.3.6）

设备同上（`M2104K10AC` / Android 13），服务端换成自建 18941 实例（数据 `/tmp/vs-and-data`）。
覆盖安装 `adb install -r videosorter-1.3.6-arm64-v8a.apk` → `versionCode=10306 / versionName=1.3.6`，
`firstInstallTime` 保持 2026-10-29 不变，证明固定证书的覆盖升级链路正常。

| 场景 | 结果 |
| --- | --- |
| 设置 → 缓存与储存 → 本机播放缓存 | 新增卡片，显示「已用 X MB / 上限 Y」；「缓存上限」弹窗五档 256MB/512MB/1GB/2GB/4GB |
| 改缓存上限 → 2 GB | toast「已保存，重新进入播放页后生效」，卡片显示「2 GB · 越滑越顺，但会占手机空间」；`run-as … cat shared_prefs/vs_session.xml` → `media_cache_mb="2048"`；进播放页再回来两处都稳定 2 GB |
| 整理 → 目标目录不可写 | 红块「1 个被跳过：目标目录不可写」+ 常见原因说明 + 「知道了」 |
| 整理 → 整批失败 | 红块「上次整理失败」+ 后端 detail 原文 |
| 整理 → 部分成功 | 「整理 2 个 → 旅行 / 美食」+「撤销」；红块「1 个被跳过」；待整理剩 1 个 |
| 启动 / 播放 / 连通性 | 1.3.6 App 连 1.3.6 后端正常播放，关于页显示 v1.3.6 |

### 安卓真机实测（2026-10-31，1.3.7）

覆盖安装 `adb install -r videosorter-1.3.7-arm64-v8a.apk` → `versionCode=10307 / versionName=1.3.7`，
`firstInstallTime` 仍为 2026-10-29，固定证书覆盖升级链路正常。

| 场景 | 结果 |
| --- | --- |
| 视频库滚动位置 | 造 12 个测试视频（共 17 个）滚到底 → 切播放页 → 切回，位置完整保留 |
| 播放页点标签 | 抓点击瞬间（`input tap … &` + `sleep 0.09` + `screencap`），标签纯色填充、无灰斑水波 |
| 标签排序按钮 | 每张卡右侧 `扫描 \| ↑ \| ↓`；连点 12 次 **12/12 生效**；release 包再连点 8 次 **8/8 生效**；1.3.7 release 包连点 6 次 **6/6 生效**；首行 ↑ / 末行 ↓ 禁用无反应；点卡片正文仍打开「编辑标签」 |
| 播放页全屏 | 点右下角按钮 → 屏幕从 1080×2400 变 2400×1080，状态栏/导航栏/底栏/标题/标签/进度条全部淡出，只留视频 + 退出按钮；点退出或按返回键回到竖屏且 UI 复原 |
| 全屏手势 | 全屏下上下滑切视频、轻点唤出/收起控件、双击快进都正常；横屏控件有渐变垫底，可读 |
| 全屏暂停 | 暂停时自动显示标题、标签胶囊、进度条与右侧按钮组（播放中轻点也能唤出） |

排序按钮走过一段弯路：先做「长按/握把拖动」，连续三版都没能稳定（根因是手势要和 `LazyColumn` 抢事件），
最后按用户要求改成按钮。完整复盘见 `docs/HANDOFF.md` §8.24–§8.27。

### 平台差异：只读目录预检用例在 Windows 跳过（2026-10-30）

`server/tests/test_paths_writable.py` 里 9 个用例靠 `chmod 0o555` 制造不可写目录来断言预检。
这在 POSIX 上成立，Windows 上不成立（chmod 只切只读位、`os.access(W_OK)` 照旧为真），
所以它们挂 `@pytest.mark.skipif(os.name == "nt")`，Windows 上只跑两条不打 chmod 的回归用例
（`effective_ids` 抛 `NotImplementedError` 时仍判可写 / 仍判只读）。

同一次发版还修了一个真 bug：`organizer._writable_reason()` 把两次 `os.access` 包在同一个 `try` 里，
Windows 上 `effective_ids=True` 抛异常后连普通判定也没跑到，导致**所有可写目录都被判成不可写**。
改完 CI 的 windows job 才转绿。详见 `docs/HANDOFF.md` §8.20。

## 四、接下来还需要什么

1. ✅ 仓库已开源：<https://github.com/mdjbn/video-sorter>，`v1.0.0` 已发布全部安装包。
2. **手机真机**：`adb install app-arm64-v8a-release.apk`，验证局域网发现、上下滑播放、上传下载（Media3 在真机上的行为）。
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
| `backend.yml` | push main / PR | `pytest`（127 项） | ✅ |
| `web.yml` | push main | `vue-tsc` + `vite build` | ✅ |
| `e2e.yml` | push main / PR | 起服务 + Puppeteer 真实浏览器 21 项断言 | ✅ |
| `android.yml` | push main（android/**）/ 手动 | 单测 + `assembleRelease`（签名校验）→ APK artifact | ✅ |
| `windows.yml` | 手动 / 由 Release 调用 | PyInstaller sidecar + Tauri 打包 → NSIS/MSI | ✅ |
| `fnos.yml` | 手动 / 由 Release 调用 | `fnpack build` → `.fpk` | ✅ |
| `release.yml` | tag `v*` | 汇总上面全部产物发 Release | ✅ |

发布操作见 [release.md](release.md)。
