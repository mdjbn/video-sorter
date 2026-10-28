# VideoSorter 的 Docker 镜像：网页端 + 后端服务（不含安卓 App / 桌面端外壳）
#
# 构建（在仓库根目录）：
#   docker build -f packaging/docker/Dockerfile -t videosorter:1.3.4 .
#   docker buildx build --platform linux/amd64,linux/arm64 -f packaging/docker/Dockerfile -t videosorter:1.3.4 .
#
# 运行：
#   docker run -d --name videosorter -p 8080:8080 \
#     -v /你的/视频目录:/videos -v /你的/数据目录:/data videosorter:1.3.4

# syntax=docker/dockerfile:1

# ---------- 1) 构建网页端 ----------
FROM node:20-bookworm-slim AS web
WORKDIR /build
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
# 只跑 vite build（跳过 vue-tsc，镜像构建快一些；类型检查交给 CI）
RUN npm run build:only

# ---------- 2) 运行时 ----------
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/server

# 上传目录固定放进数据卷，不要跟着源目录散落在 /videos 里；监听地址/端口给个默认
ENV VIDEOSORTER_UPLOAD_DIR=/data/uploads \
    VIDEOSORTER_HOST=0.0.0.0 \
    VIDEOSORTER_PORT=8080

# ffmpeg/ffprobe 是硬依赖：封面、时长、HLS 转码都要用
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg ca-certificates tini \
 && rm -rf /var/lib/apt/lists/*

# 版本号由 CI 用 --build-arg 传进来（本地构建不传也行，只写进 LABEL）
ARG VERSION=dev
LABEL org.opencontainers.image.title="VideoSorter" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.licenses="MIT"

WORKDIR /app
COPY server/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY server/ ./server/
COPY --from=web /build/dist ./webdist

# 非 root 运行；uid/gid 可用 --build-arg 调整以匹配宿主的视频目录权限
ARG UID=1000
ARG GID=1000
RUN groupadd -g "${GID}" videosorter \
 && useradd -u "${UID}" -g "${GID}" -m -s /usr/sbin/nologin videosorter \
 && mkdir -p /data /videos \
 && chown -R "${UID}:${GID}" /data /app

USER ${UID}:${GID}
VOLUME ["/data"]
EXPOSE 8080/tcp
# 局域网发现（手机 App 自动找服务器）走 UDP；bridge 网络下建议用 host 网络（见 README）
EXPOSE 38080/udp

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD ["python", "-c", "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=3).status == 200 else 1)"]

# tini 做 init，收得到 SIGTERM，uvicorn 能优雅退出
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "videosorter", "--host", "0.0.0.0", "--port", "8080", "--data-dir", "/data", "--web-dir", "/app/webdist"]
