# 架构

## 一句话

单进程 Python 服务（FastAPI + SQLite）＋ 三套客户端（网页 Vue3 / Android Compose / Windows Tauri），三端各自独立数据库、互不同步：**连哪台主机就整理哪台主机**。

## 服务端

```
FastAPI (app.py)
 ├─ /api/auth/*        登录、改用户名/密码、会话
 ├─ /api/settings,/info
 ├─ /api/sources      源文件夹 CRUD；/api/fs/list 目录选择
 ├─ /api/scan         后台任务（scanner.scan_sources）
 ├─ /api/videos       列表/详情/标签/重命名/删除/封面/播放历史/统计
 ├─ /api/videos/*/raw Range 流；*/play 播放策略；*/hls/* 分片；*/hlsstatus 进度
 ├─ /api/organize     预览 / 执行（后台任务）/ 记录 / 撤销
 ├─ /api/upload       手机上传（流式落盘 → probe → 入库）
 └─ 静态托管 web/dist（SPA 回退 index.html）
```

- **SQLite**（WAL，`synchronous=NORMAL`）存元数据：`videos / tags / sources / organize_batches / organize_logs / play_history / users / tokens / settings`。
- **文件本身不搬进数据库**，只存绝对路径；整理=真实 `os.replace`（跨盘时复制→校验大小→替换→删除）。
- **任务**：扫描、整理、HLS 转码都跑在线程里，前端轮询 `/api/tasks/{id}` 拿进度。

## 播放策略

| 情况 | 策略 |
| --- | --- |
| `.mp4/.m4v/.webm/.mov` + H.264 + AAC/MP3/Opus | 直接 `<video src=/api/videos/{id}/raw>`，支持 Range 拖拽 |
| 其它（MKV/AVI/HEVC/VC-1…） | `/play` 返回 `mode=hls`，后台 ffmpeg 切片（H.264 且 AAC 时 `-c copy` 秒级），前端用 hls.js |
| 文件不存在/丢失 | `mode=missing`，UI 提示并从列表标记 |

## 整理规则

1. 目标目录优先级：标签的 `dir_path`（绝对路径）→ `root_dir/标签名` → 视频原目录/标签名 → 首个源目录/标签名。
2. 目标已存在同名文件 → `名字 (1).mp4`、`(2)`…（计划阶段就决定，预览里能看到「改名」标记）。
3. 每个文件写一条 `organize_logs`，整批一个 `organize_batches`；撤销按批次逆序移回。

## 三端关系

| 端 | 技术 | 连谁 | 数据库 |
| --- | --- | --- | --- |
| 网页 | Vue 3 + Vite + TS | 同源（后端托管） | 无，全走后端 API |
| Android | Kotlin + Compose + Media3 | 可存多台服务器地址，切换连接 | 本地只存服务器列表/凭证 |
| Windows | Tauri 2 + PyInstaller sidecar | 内嵌本机后端 | 本机数据目录 |

手机端/Windows 端不聚合视图，不做跨机同步（用户明确要求）。

## 局域网发现（可选）

`discovery.py` 起守护线程在 UDP `discovery_port`（默认 38080）监听 `VS_DISCOVER`，收到后回
`{app, version, name, port, ip, tls}`。手机 App 用广播/定向广播找服务器，找到后仍走普通 HTTP API
（发现只解决「服务器在哪台机器」，不做鉴权）。关闭：`config.json` 里 `"discovery": false`。
