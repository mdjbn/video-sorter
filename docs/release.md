# 发布流程（GitHub Release）

仓库：<https://github.com/mdjbn/video-sorter>

## 一次性准备

- `main` 上一切正常（`backend` / `web` / `E2E` / `android` 四个工作流绿色）。
- 想发 Windows 安装包时，**不需要**本地有 Windows 或 Rust —— 由 `windows-latest` runner 编译。

## 发一个版本

```bash
# 1) 版本号：九处保持一致 —— server/videosorter/__init__.py、web/package.json、web/package-lock.json（两处）、
#    android/app/build.gradle.kts 的 versionName、packaging/fnos/project/manifest、src-tauri/Cargo.toml、
#    src-tauri/Cargo.lock（name = "video-sorter-desktop" 那段）、src-tauri/tauri.conf.json
#    （另有 web/src/views/Manage.vue 的兜底版本号，跟着改）
#    server/videosorter/__init__.py → __version__
#    web/package.json → version
#    android/app/build.gradle.kts → versionName
#    packaging/fnos/project/manifest → version
# 2) 提交
git add -A && git commit -m "chore: bump version x.y.z"
git push origin main
# 3) 打 tag（触发 Release 工作流）
git tag -a vX.Y.Z -m "VideoSorter X.Y.Z"
git push origin vX.Y.Z
```

随后看 <https://github.com/mdjbn/video-sorter/actions> 里的 **Release** run：

| job | 产物 | 大约耗时 |
|---|---|---|
| `test` | pytest（守门） | 1–2 min |
| `android` | `videosorter-apk/*.apk` | 4–6 min |
| `windows` | `windows-desktop/*.exe`(NSIS) + `*.msi` | 20–40 min |
| `fnos` | `videosorter-fpk/*.fpk` | 3–5 min |
| `publish` | 汇总成 6 个资产挂到 Release | 1 min |
| （并行）`docker` | `ghcr.io/mdjbn/video-sorter` + `1045188196/videosorter` 的 amd64+arm64 镜像 | 10–25 min |

`android` / `windows` / `fnos` 三个 job 并行（都只 `needs: [test]`）；`publish` 的条件是
`!cancelled() && needs.android.result == 'success' && needs.fnos.result == 'success'`，
所以 **Windows 失败只会少 `VideoSorter-<版本>-x64-setup.exe` 和 `.msi` 两个资产，不会拦住发布**。
`publish` 里会把 `windows-desktop` artifact 里的 NSIS/MSI 改名成这两个固定名字再挂上去；
注意 artifact 会保留 `nsis/`、`msi/` 子目录（实测下载下来是 `windows-desktop/nsis/VideoSorter_1.3.3_x64-setup.exe`），
所以整理脚本用 `find` 找文件而不是 `*.exe` 通配。

`publish` 用 `softprops/action-gh-release@v2` 挂载；`permissions: contents: write` 在
`release.yml` 顶层声明，复用工作流（`workflow_call`）继承该权限。

## 常见问题

**Android 步骤 `Setup Android SDK` 失败**：不要用 `android-actions/setup-android@v3`，
它在自带 SDK 的 runner 上会去装早已废弃的 `tools` 包（`Failed to find package 'tools'`）。
现在的 `android.yml` 直接用 runner 自带的
`$ANDROID_HOME/cmdline-tools/*/bin/sdkmanager` 装 `platforms;android-35`。

**Release 里只有部分产物**：`android` 或 `fnos` 失败则不会创建 Release（属于该发）；
只有 Windows 挂了时 Release 照发，只是缺 exe/msi —— 去 Actions 页面单独 **Run workflow** 跑
`windows-desktop` 定位问题，修好后重打 tag（或手动补挂资产）。

**镜像没推上去**：`docker` 工作流只在推 `v*` tag 或手动触发时 push（main 上的普通推送只做构建 + 容器冒烟）。
推两个仓库：GHCR 用内置 `GITHUB_TOKEN`；Docker Hub 用仓库 secret `DOCKERHUB_USERNAME` / `DOCKERHUB_TOKEN`
（PAT 需要 read+write，失效了就在 Docker Hub 重新生成再 `PUT /actions/secrets/DOCKERHUB_TOKEN`）。
GHCR 包若被设成 private，需要在 `https://github.com/users/mdjbn/packages/container/video-sorter/settings` 改 Public；
Docker Hub 的仓库默认 public。

**tag 打错了要重来**：
```bash
git tag -d vX.Y.Z                  # 删本地
git push origin :refs/tags/vX.Y.Z  # 删远端
git tag -a vX.Y.Z -m "..."         # 重新打在当前 commit 上
git push origin vX.Y.Z
```
Release 已发布时，先删对应 Release（或让它随 tag 一起走），再重打 tag。

**fnos-fpk 的 403 `Resource not accessible by integration`**：fpk 工作流**不要**自己
挂 Release（tag 直跑时默认 token 只有只读权限）。附件统一由 `release.yml` 的
`publish` job 负责。

**复用工作流拿不到 secrets**：`release.yml` 里 `android` / `windows` / `fnos` 都是用
`uses: ./.github/workflows/xxx.yml` 的复用工作流，GitHub **不会**自动把仓库 secrets 传进去。
凡是复用工作流里用到 secrets 的（现在只有 Android 签名证书那四个 `ANDROID_KEYSTORE_*`），
调用处必须写 `secrets: inherit`，否则会出现「本地/单跑 android.yml 正常，走 Release 就报
`缺少 secrets.ANDROID_KEYSTORE_BASE64`」的谜案（2026-10-29 真实踩过，见 `965d2a2`）。

**`apksigner` 输出格式随 build-tools 版本变**：runner 上是 build-tools 37，行首是
`V2 Signer: certificate SHA-256 digest:`；老的 34/35 是 `Signer #1 certificate SHA-256 digest:`。
`android.yml` 的校验步骤因此不 grep 固定前缀，而是先 `out="$(apksigner verify -v --print-certs ...)"`
再 `case "$out" in *"certificate SHA-256 digest"*)` 判定，并且不把 apksigner 的非零退出直接短路。

## 本地等价命令（不依赖 CI）

```bash
bash tools/e2e-web.sh                      # 后端 + 网页端端到端（真实浏览器）
cd server && .venv/bin/python -m pytest -q # 后端单测
cd android && gradle assembleRelease testDebugUnitTest   # 需要 JDK 17/21 + Android SDK + 签名证书（见 docs/build.md §3）
bash packaging/fnos/build.sh               # 需要 fnpack
packaging/build-portable.bat               # Windows 上打绿色版
docker compose -f packaging/docker/docker-compose.yml config   # 校验 compose（本机没 docker 权限也能跑）
docker build -f packaging/docker/Dockerfile -t videosorter:dev .  # 需要能访问 docker daemon
```
