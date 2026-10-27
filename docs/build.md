# 构建与发布

三端共用同一份 Python 后端（`server/`），网页端（`web/`）构建后由后端直接托管。
手机端与 Windows 桌面端都是**客户端外壳**，连的是同一台服务器，不做数据同步。

## 1. 服务器（Linux / fnOS / 群晖）

```bash
./run.sh --port 8080
```

已在 `fnOS (Debian 12) + Python 3.11 + ffmpeg 8.1` 上实测。
systemd 常驻示例（`/etc/systemd/system/videosorter.service`）：

```ini
[Unit]
Description=VideoSorter
After=network.target

[Service]
Type=simple
User=<你的用户>
WorkingDirectory=/path/to/视频整理/server
ExecStart=/path/to/视频整理/server/.venv/bin/python -m videosorter --port 8080 --web-dir ../web/dist
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

## 2. 网页端

```bash
cd web
npm install
npm run dev      # 开发：http://localhost:5173，/api 代理到 8080
npm run build    # 产出 dist/，后端自动托管
```

## 3. Android APK

需要 **Android SDK（compileSdk 35）+ JDK 17**。本机没有 SDK，因此这一步在 GitHub Actions 上做（`.github/workflows/android.yml`）：

```bash
# 本地（装好 SDK 后）
cd android
gradle assembleDebug
# 产物：app/build/outputs/apk/debug/app-debug.apk
```

装到手机（首次需允许「安装未知来源应用」）：

```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

打开 App → 填服务器地址 `192.168.1.x:8080` → 账号 `admin` / `admin1234` → 登录。
App 会用 `Authorization: Bearer <token>` 调接口，token 按服务器分别保存在本地。

> 手机端功能：竖向滑动切视频、单击暂停、长按 2×、横向拖动定位、标签小胶囊、整理预览与执行、
> 视频库筛选、上传（SAF 选片）、扫描、三档主题、多服务器切换、退出登录。
> iOS 未做（按约定先只做安卓）。

## 4. Windows 桌面端（可选）

Windows 端必须能整理 **Windows 本机磁盘**，所以安装包里内嵌一份 Python 服务（sidecar）：

1. GitHub Actions `windows.yml`：构建网页端 → PyInstaller 打包 `videosorter-server.exe` → 塞进
   `src-tauri/binaries/` → `cargo build --release` + Tauri NSIS/MSI 安装包。
2. 若要把 ffmpeg 一起带上，取消 `windows.yml` 里下载 ffmpeg 的注释，安装包会大 ~80MB；
   否则需要用户自己把 `ffmpeg.exe`/`ffprobe.exe` 放进程序目录的 `tools/`。

Tauri 外壳（`src-tauri/src/main.rs`）做的事：启动 sidecar → 轮询 `/api/health` → 打开
`http://127.0.0.1:8080` 的窗口 → 退出时杀掉子进程。

## 5. 绿色版（不想装东西时）

Windows 上双击 `packaging\build-portable.bat`，会在 `dist\portable\videosorter-server\` 生成一个
自带 Python 运行时与网页端的目录；把整个目录拷到任何 Windows 机器，双击里面的「启动.bat」即用
（等于自带 Python 的绿色版，不写注册表、不需要管理员权限）。

只想手动拼也行：把 `dist/sidecar/videosorter-server/` 拷过去，`videosorter-server.exe --web-dir webdist`。

桌面端图标是脚本生成的（不依赖 Pillow）：`python packaging/gen-icons.py` → `src-tauri/icons/`。

## 6. 局域网发现（手机自动找服务器）

服务器启动后会在 **UDP 38080** 上监听探测包（`server/videosorter/discovery.py`，纯标准库）。
验证：

```bash
python3 -c "import socket;s=socket.socket(2,2);s.settimeout(2);s.sendto(b'VS_DISCOVER',('127.0.0.1',38080));print(s.recvfrom(2048)[0].decode())"
```

App 登录页点「扫描局域网」→ 向 `255.255.255.255:38080` 与各网卡广播地址发包 → 服务器回
`{"app":"VideoSorter","version":"1.0.0","name":"VideoSorter @ host","port":8080,"ip":"192.168.1.8","tls":false}`
→ App 列出服务器，点一下自动填地址。不想要这个端口就在 config.json 里设 `"discovery": false`。

## 7. 数据与备份

所有状态都在**数据目录**里（SQLite + 缩略图 + HLS 缓存）：

- Linux：`~/.config/video-sorter/`（或 `--data-dir` 指定）
- Windows：`%APPDATA%\VideoSorter\`

备份整个目录即可；视频本体不复制，只在整理时移动。

## 8. 打包成 fnOS 应用（.fpk）

`packaging/fnos/` 是 fnOS 应用工程，`packaging/fnos/build.sh` 负责组装 + 调用 `fnpack` 出包。

### 结构与约定

```
packaging/fnos/
├── build.sh              组装 payload（源码 + 依赖 + webdist）并 fnpack build
├── project/              会被原样拷进 .fpk 的骨架
│   ├── manifest          appname/version/service_port/desktop_* 等
│   ├── ICON.PNG          ICON_256.PNG      （256×256，由 packaging/gen-fnos-icons.py 生成）
│   ├── app/ui/config     桌面入口（.url → videosorter.Application，iframe 打开 :8610）
│   ├── app/ui/images/    icon_64.png / icon_256.png
│   ├── cmd/main          start|stop|restart|status 生命周期脚本
│   ├── cmd/*_init|*_callback   其它生命周期占位（直接 exit 0）
│   ├── config/privilege  {"defaults":{"run-as":"package"}}
│   ├── config/resource   data-share: videosorter/uploads（手机上传落盘）
│   └── wizard/           空目录（fnpack 要求存在）
└── gen-fnos-icons.py     生成上面四个图标
```

装好之后 fnOS 会把这些目录做成软链：`target→@appcenter`、`etc→@appconf`、`var→@appdata`。

### 构建

```bash
# 依赖：fnpack（下面这行只需一次）
curl -fsSL -o /tmp/fnpk/fnpack https://static2.fnnas.com/fnpack/fnpack-1.2.3-linux-amd64
chmod +x /tmp/fnpk/fnpack

bash packaging/fnos/build.sh          # 产物 dist/fnos/videosorter.fpk
```

脚本做的事：生成图标 → 确保 `web/dist` 存在（不存在就 `npm install && npm run build`）→
拷 `server/videosorter` 与 `web/dist` → `pip install --target dist/app/vendor -r server/requirements.txt`
→ 统一权限（NAS 卷上文件权限不可靠，必须在 `/tmp` 的副本里改成 755/644）→ `fnpack build`。

### 运行时怎么起的

`cmd/main` 用的是 fnOS 提供的那套环境变量：

```bash
cd "$TRIM_APPDEST"
PYTHONPATH="$APP_DIR:$APP_DIR/vendor" \
python3 -m videosorter --host 0.0.0.0 --port "$TRIM_SERVICE_PORT" \
    --data-dir "$TRIM_PKGVAR" --web-dir "$APP_DIR/webdist"
```

`VIDEOSORTER_UPLOAD_DIR` 指向 `config/resource` 声明出来的共享目录（`$TRIM_DATA_SHARE_PATHS` 第一项），
`VIDEOSORTER_TOOLS` 指向 `.../target/tools`（放自备 ffmpeg 用）。
`videosorter/config.py` 支持 `VIDEOSORTER_<KEY>` 覆盖任意配置项（`PORT`/`ROOT_DIR`/`UPLOAD_DIR`/`DISCOVERY`…），空值忽略、不写回 `config.json`。

### 本地验证（没有 root 也能做）

`.fpk` 本质是个 tar.gz：解出来的 `app.tgz` 就是 payload。所以可以直接模拟 fnOS 跑一遍：

```bash
T=/tmp/fptest; rm -rf $T; mkdir -p $T/pkg $T/apps/videosorter/{target,var,etc,share}
tar -xzf dist/fnos/videosorter.fpk -C $T/pkg
tar -xzf $T/pkg/app.tgz -C $T/apps/videosorter/target

APP=$T/apps/videosorter
TRIM_APPDEST=$APP/target TRIM_PKGVAR=$APP/var TRIM_PKGETC=$APP/etc \
TRIM_SERVICE_PORT=8612 TRIM_DATA_SHARE_PATHS=$APP/share \
  bash $T/pkg/cmd/main start
curl -s http://127.0.0.1:8612/api/health
```

本仓库实测：这样起起来之后 `VS_BASE=http://127.0.0.1:8612 bash tools/e2e-web.sh` 的
18 项断言（登录/播放/打标签/整理/撤销/管理页各视图）全部通过，
说明打包产物不只是能启动，整条链路是通的。

### 常见问题

- **装完应用中心显示「已停止」**：看 `/var/apps/videosorter/var/info.log`，多半是 8610 端口被占
  （`manifest` 里 `checkport=true`，fnOS 会先检查端口）。
- **打开页面是空白/404**：`.../target/webdist/index.html` 缺失，说明构建时没带上网页端，重跑 `build.sh`。
- **扫不到视频**：目录没授权，见 README「装成 fnOS 应用（.fpk）」里的授权说明。
- **改了 manifest 后 fnpack 报校验失败**：`app/ui/config` 的入口 key 必须等于 `desktop_applaunchname`；
  `app/{desktop_uidir}/` 必须存在；两个 `ICON*.PNG` 必须存在。

## 附：本机编译 Android 的踩坑记录（Linux / fNOS）

这台机器实测下来的三个坑，换机器时同样可能遇到：

1. **JVM 必须跑 UTF-8**：仓库路径里有中文和空格，默认 locale 不是 UTF-8 时 Gradle 会报
   `InvalidPathException: Malformed input or input contains unmappable characters`。构建前：
   ```bash
   export LANG=C.UTF-8 LC_ALL=C.UTF-8
   export JAVA_TOOL_OPTIONS="-Dfile.encoding=UTF-8 -Dsun.jnu.encoding=UTF-8"
   ```
2. **`HOME` 和 `GRADLE_USER_HOME` 换到本地盘**：放在某些 NAS 卷上 Gradle 会报
   `Failed to load native library 'libnative-platform.so'`。设成 `/tmp/...` 即可。
3. **别在特殊权限的卷上直接构建**：fNOS 这类卷新建的文件是 `----------`，Gradle 读不了自己刚写的中间产物
   （`Failed to create MD5 hash for file ...` / `Could not load cache entry (Permission denied)`）。
   把源码 `tar` 复制到 `/tmp` 编，并加 `--no-build-cache`：
   ```bash
   tar -cf - --exclude=build --exclude=.gradle . | tar -xf - -C /tmp/android-src
   chmod -R u+rwX /tmp/android-src && cd /tmp/android-src && gradle assembleDebug --no-build-cache
   ```
4. **JDK 版本**：AGP 8.7 需要 **JDK 17 或 21**，用系统自带的 JDK 25 会直接失败。
5. 不要同时跑 `assembleDebug` 和 `testDebugUnitTest` —— 两个 Gradle 进程会互相覆盖中间产物，
   报一堆莫名其妙的 `Unresolved reference`；串行跑就没问题。

6. **git 也要先修权限**：fNOS 上新建文件是 mode 000，git 会报
   `error: opening .git/config: Permission denied`；目录属主与当前用户不一致时还会报
   `detected dubious ownership`。在项目根执行：
   ```bash
   bash tools/fix-perms.sh
   git config --global --add safe.directory "$(pwd)"
   ```
7. **本仓库已 `git init` 并提交首次版本**（分支 `main`）；推 GitHub 后即可用
   `.github/workflows/` 里的流水线出 APK / Windows 安装包。

## 附：打包相关的两个真实坑（已在代码里修掉）

1. **PyInstaller spec 里不能直接用 `__file__`**：PyInstaller 执行 `.spec` 时不会注入 `__file__`，
   会报 `NameError: name '__file__' is not defined`（Windows CI 上同样会挂）。现在 `server/videosorter.spec`
   已改成 `try: ROOT = ... __file__ ... except NameError: ROOT = os.path.dirname(SPECPATH)`。
2. **打包后的网页端目录探测**：onedir 产物里页面在 `_internal/webdist`（或绿色版里和 exe 同级），
   而开发时在 `web/dist`。`app.py::default_web_dir()` 现在依次找
   `exe 同级 webdist` → `sys._MEIPASS/webdist` → `_internal/webdist` → `server/web/dist` → `web/dist`，
   并有 3 个单测覆盖（`server/tests/test_webfind.py`）。
3. 在 **Linux 上本地打 sidecar** 还额外需要 binutils（PyInstaller 用 `objcopy` 往 ELF 里加 `pydata` 段）；
   没装 binutils 时 PyInstaller 直接报 `On Linux, objdump is required`。Windows / macOS 打包不需要它，
   所以本项目把 sidecar 的构建放在 CI 的 windows runner 上做，Linux 本地只需跑后端测试。
4. **Tauri 本地编译**需要 rust 工具链 + 系统 webview 依赖（Linux 上是 webkit2gtk-4.1），
   没装的话 `cargo check` 会先卡在宿主编译器（`linker 'cc' not found`）。所以 Rust 壳的编译验证交给 CI。

## 附：Windows 安装包里都带了什么

`.github/workflows/windows.yml` 现在会自动：

1. 构建网页端（`web/dist`）；
2. PyInstaller 打出 sidecar（Python 服务 + `_internal/webdist`）；
3. 下载 ffmpeg essentials 并把 `ffmpeg.exe`、`ffprobe.exe` 放进 `src-tauri/tools/`（安装后位于 `<安装目录>/tools/`，
   服务端 `media._tool_dirs()` 会把 exe 同级的 `tools/` 也列进去，所以用户不需要自己装 ffmpeg）；
4. 把 sidecar 与网页端放进 `src-tauri/binaries/`（Tauri 的 `bundle.resources` 用 `binaries/**`、`tools/**`）；
5. `cargo build --release` + `tauri build` 出 NSIS/MSI；
6. 另外打一个 `VideoSorter-portable.zip` 绿色版（解压双击「启动.bat」即用）。

Tauri 壳里的 `sidecar_path()` 会依次找
`<exe>/binaries/videosorter-server.exe`、`<exe>/binaries/videosorter-server/…`、`<exe>/…`、
`<exe>/resources/binaries/…`，启动时若 sidecar 同级有 `webdist/` 会显式传 `--web-dir`，避免代理/路径两套布局差异。

## 8. 只换了网页端时怎么做热更新（不重装 fpk）

fnOS 上安装的应用目录归 `videosorter` 用户所有，普通账号不能直接写。可以直接替换 `webdist` 再重启应用，**不动数据库**：

```bash
FNC='node /vol1/@appshare/Harness/.dsh/profiles/web/node_modules/@fnnas-labs/fnos-cli/skill/../npm/run.cjs'
CONN="--host 192.168.5.100 --port 5666 --scheme http --allow-insecure-http --profile fnos"
WD=/vol1/@appcenter/videosorter/webdist

# 1) 备份现有静态资源
cp -a "$WD" /tmp/vs-webdist-backup-$(date +%H%M%S)

# 2) 临时把目录归属改成当前操作者（uid 825 = Harness）
$FNC $CONN file chown "$WD" --uid 825 --sub --yes

# 3) 替换文件
cd web && npm run build:only && cd ..
rm -rf "$WD"/assets "$WD"/index.html
cp -a web/dist/. "$WD"/
chmod -R u+rwX,go+rX "$WD"

# 4) 归属改回应用用户（uid 975 = videosorter）
$FNC $CONN file chown "$WD" --uid 975 --sub --yes
$FNC $CONN app restart videosorter --yes
```

注意：热更新只覆盖网页资源，`/api/health` 的 `version` 仍是安装包版本；数据库、标签、整理记录不受影响。升级安装包时仍需走「卸载 → 安装」（或应用中心界面升级）。

## 9. fnOS 安装向导：端口与卸载数据

fnOS 的 fpk 支持在**安装**和**卸载**时向用户提问，答案会以环境变量形式传给包内的生命周期脚本。

### 9.1 安装时选择服务端口

- `packaging/fnos/project/wizard/install`：一个 `text` 项，`field = "ui_port"`，默认 `8610`。
- `packaging/fnos/project/app/ui/config` 的 `.url["videosorter.Application"].port` 必须是 **`"${ui_port}"`**（模板变量），这样应用中心「打开」时用的就是你填的端口。**manifest 里不要写 `service_port`**（写死会覆盖向导值），保留 `checkport = true` 即可。
- `cmd/main` 用 `PORT="${ui_port:-${TRIM_SERVICE_PORT:-8610}}"` 启动服务；`cmd/install_init` 校验 1024–65535，端口被占用只提示不阻断（避免升级失败）。

按 CLI 安装时可传参模拟（仅用于自测）：

```bash
fnos-cli ... app install-fpk videosorter.fpk --custom-parameters '[{"key":"ui_port","value":18767}]' --accept-license --yes
```

### 9.2 卸载时选择是否删除数据

- `packaging/fnos/project/wizard/uninstall`：一个 `radio` 项，`field = "wizard_data_action"`，`keep`（默认，保留数据）/ `delete`（删除数据）。
- `cmd/uninstall_callback` 读 `wizard_data_action`：
  - `keep`：什么都不做（`TRIM_PKGVAR` = `/vol1/@appdata/<appname>` 保留，重装后可继续用）。
  - `delete`：删除 `TRIM_PKGVAR`，并清理 `TRIM_DATA_SHARE_PATHS` 中属于本应用的目录（`*/videosorter`、`*/videosorter/*`，即上传目录），**不会**动用户自己添加的源文件夹。
- 一旦包内带了 required 的卸载向导，CLI 的 `app uninstall <app> --yes` 会拒绝执行（`app-center uninstall requires custom wizard parameters; run it from App Center UI`），必须从应用中心界面卸载——这是预期行为。

### 9.3 升级步骤（带向导的包）

1. 应用中心 → 视频整理 → **卸载** → 选择「保留数据」；
2. 应用中心 → 手动安装 → 选择新的 `videosorter.fpk` → 在向导里填写端口（默认 8610）；
3. 安装完成后「打开」会直接指向你填的端口；数据（数据库、缩略图、上传目录里的文件）因为在步骤 1 选择了保留，会自动被新版本接管。
