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
`{"app":"VideoSorter","version":"0.1.0","name":"VideoSorter @ host","port":8080,"ip":"192.168.1.8","tls":false}`
→ App 列出服务器，点一下自动填地址。不想要这个端口就在 config.json 里设 `"discovery": false`。

## 7. 数据与备份

所有状态都在**数据目录**里（SQLite + 缩略图 + HLS 缓存）：

- Linux：`~/.config/video-sorter/`（或 `--data-dir` 指定）
- Windows：`%APPDATA%\VideoSorter\`

备份整个目录即可；视频本体不复制，只在整理时移动。

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
