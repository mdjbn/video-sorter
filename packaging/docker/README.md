# 用 Docker 跑 VideoSorter

镜像里跑的是**网页端 + 后端服务**（Linux 版），打开浏览器就是完整界面；安卓 App、桌面端外壳不在镜像里（它们只是客户端，照样连这个服务）。

## 直接用 CI 构建好的镜像（推荐）

发版（推 `v*` tag）时 GitHub Actions 会自动构建 `linux/amd64` + `linux/arm64` 并推到 GHCR，直接跑就行：

```bash
# Docker Hub（最省事，国内拉取也快）
docker run -d --name videosorter --restart unless-stopped \
  -p 8080:8080 \
  -v /你的/视频目录:/videos \
  -v /你的/数据目录:/data \
  1045188196/videosorter:latest

# 或者 GHCR（同一个镜像，换仓库而已）
#   ghcr.io/mdjbn/video-sorter:latest
```

两个仓库内容完全一致：Docker Hub `1045188196/videosorter`、GHCR `ghcr.io/mdjbn/video-sorter`。
可用标签：`latest`（最新 tag）、`<版本号>`（如 `1.3.3`）、`<major>.<minor>`（如 `1.3`）、`edge`（main 分支最近一次手动构建）、`sha-<短哈希>`。
main 分支上的普通推送只构建 amd64 并跑一次容器冒烟（等 `/api/health` healthy、断言版本号/media_ready/web），**不推镜像**；
想在 main 上出镜像就在 Actions 里手动 Run 一次 `docker` 工作流。

> 首次推送后 GHCR 上的包默认可能是 **private**：去
> `https://github.com/users/mdjbn/packages/container/video-sorter/settings` 把可见性改成 Public，
> 否则别人 `docker pull` 前得先 `docker login ghcr.io`。

## 最快上手（本地自己构建）

```bash
# 在仓库根目录
docker build -f packaging/docker/Dockerfile -t videosorter:1.3.3 .

docker run -d --name videosorter --restart unless-stopped \
  -p 8080:8080 \
  -v /vol1/1000/video:/videos \
  -v /vol1/1000/docker-data/videosorter:/data \
  videosorter:1.3.3
```

浏览器打开 `http://<NAS 的 IP>:8080`，首次登录 **admin / admin1234**（登录后可在「设置」里改）。然后在视频库页把 `/videos` 添加为源文件夹、扫描即可。

或者用 compose（目录里 `videos` 换成你的真实目录）：

```bash
cd packaging/docker
docker compose up -d --build
```

## 镜像里有什么

| 项 | 说明 |
|---|---|
| 基础镜像 | `python:3.11-slim-bookworm`，多阶段构建（`node:20` 只用来编译网页端） |
| ffmpeg | 已装（封面抽帧、时长探测、HLS 转码都依赖它） |
| 服务 | `python -m videosorter --host 0.0.0.0 --port 8080 --data-dir /data --web-dir /app/webdist` |
| 进程管理 | `tini` 做 PID 1，`docker stop` 能优雅退出 |
| 用户 | 非 root（默认 uid/gid 1000，可用 `--build-arg UID=… --build-arg GID=…` 对齐视频目录属主） |
| 健康检查 | 每 30s 打 `/api/health` |

## 两个卷

- `/data`：数据库、封面缓存、HLS 转码缓存、`config.json`。**这个必须持久化**，删了等于清空媒体库（视频文件本身不受影响）。
- `/videos`（或你自己的任意路径）：源视频目录。容器里要能**读**，用「整理」功能还要能**写**（同盘是 `os.replace` 改名，跨盘走复制+校验+删除）。
  - 建议一个源目录只挂一个卷：把「整理」后的标签目录放在同一个卷里，避免跨卷复制大文件。

上传目录默认固定到 `/data/uploads`（`VIDEOSORTER_UPLOAD_DIR`），这样手机/网页上传的视频不会散落进视频目录；想改就换成别的路径，或让它在源目录下。

## 环境变量

所有配置项都能用 `VIDEOSORTER_<键名大写>` 覆盖（见 `server/videosorter/config.py` 的 `DEFAULTS`），只影响本次进程、不写回 `config.json`：

| 变量 | 默认 | 说明 |
|---|---|---|
| `VIDEOSORTER_PORT` | `8080` | 监听端口 |
| `VIDEOSORTER_HOST` | `0.0.0.0` | 监听地址 |
| `VIDEOSORTER_UPLOAD_DIR` | `/data/uploads`（镜像里写死） | 上传落盘目录 |
| `VIDEOSORTER_ROOT_DIR` | 空 | 整理后的根目录；空=「源目录/标签名」 |
| `VIDEOSORTER_DISCOVERY` | `true` | 局域网 UDP 发现开关 |
| `VIDEOSORTER_DISCOVERY_PORT` | `38080` | 发现端口 |
| `VIDEOSORTER_TRANSCODE` | `true` | 关掉就只能直放，不能转 HLS |

## 局域网发现 / 手机 App

手机 App 用 UDP 广播 38080 来找服务器，服务端返回里带着自己认为的 IP（`_local_ipv4()`）。**bridge 网络下这个 IP 是容器内网地址（172.17.x.x），手机连不上**。三种办法，任选：

1. **host 网络**（最省事）：compose 里打开 `network_mode: host`、删掉 `ports`，然后 `VIDEOSORTER_PORT` 保持 8080（或改成你想要的端口）。
2. **手机手动填地址**：App 登录页直接输入 `NAS的IP:8080`，不用「扫描局域网」。
3. 端口映射 + 关掉发现：`VIDEOSORTER_DISCOVERY=false`，同样手动填地址。

## 多架构

基础镜像和 ffmpeg 都有 arm64 版本，直接多架构构建即可：

```bash
docker buildx build --platform linux/amd64,linux/arm64 \
  -f packaging/docker/Dockerfile -t videosorter:1.3.3 --push .
```

（`--push` 需要先 `docker login` 到你的 registry；本机只构建不推就用 `--load` 或去掉 `--push`。）
CI 里的 `.github/workflows/docker.yml` 就是这么做的（QEMU 跑 arm64），并且会同时推到 GHCR 与 Docker Hub，
不用自己在本机折腾。

## 和 fnOS 的 `.fpk` 比，差在哪

- 没有应用中心的图标/入口和安装向导，端口固定 8080（可用环境变量改），不会有「开机自启」——交给 `restart: unless-stopped`。
- 数据目录从 `/vol1/@appdata/videosorter` 变成你的 `/data` 卷；两个方向都能迁移：把旧 `config.json` 和 `data.sqlite3` 拷过去即可（老库里 `upload_dir` 是绝对路径，进容器后要在设置里改成本地可见的路径）。
- 卸载：`docker rm -f videosorter` 后数据还在 `/data` 卷里，删卷才清空。
- 镜像不含安卓 APK（`/api/app/*` 相关下载会 404），需要的话把 apk 放进 `/data/apk/` 目录，服务会自动提供下载（登录页底部会出现下载 App 提示）。

## 资源建议

- CPU：HLS 转码吃 CPU（`transcode_preset=veryfast`），不做转码（全是 mp4/h264）基本不吃。
- 内存：扫描时每个 worker 会跑 ffprobe，3 个 worker 大约 200–400MB，够 1GB 就正常跑。
- 磁盘：`/data` 的 HLS 缓存会按视频大小增长，看完的可以定期清（「设置」里有清理入口）。

## 已知限制

- 写这份说明的机器**没有 Docker 权限**（`/var/run/docker.sock` 属 `root:docker`，当前用户不在组里，`sudo` 又被 `no_new_privileges` 拦住），所以镜像由 **GitHub Actions 构建并验证**（`.github/workflows/docker.yml`：构建 → 起容器等 healthy → 断言 `/api/health` 的 `version`/`media_ready`/`web`），本地只做了 `docker compose config` 与「按镜像布局手动起服务」的等价验证。首次构建若失败，大概率是 `web/package-lock.json` 与 node 版本（`npm ci` 要求锁文件匹配）。
- 网页端构建用 `npm run build:only` 跳过 `vue-tsc` 类型检查，类型问题由 CI 的 `test` job 覆盖。
- 镜像不打安卓 App / Windows 安装包。
