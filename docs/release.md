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
| （并行）`docker` | `ghcr.io/mdjbn/video-sorter` 的 amd64+arm64 镜像 | 10–25 min |

`android` / `windows` / `fnos` 三个 job 并行（都只 `needs: [test]`）；`publish` 的条件是
`!cancelled() && needs.android.result == 'success' && needs.fnos.result == 'success'`，
所以 **Windows 失败只会少 `VideoSorter-<版本>-x64-setup.exe` 和 `.msi` 两个资产，不会拦住发布**。
`publish` 里会把 `windows-desktop` artifact 里的 NSIS/MSI 改名成这两个固定名字再挂上去。

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
另外 GHCR 包首次创建后默认可能是 private，需要在
`https://github.com/users/mdjbn/packages/container/video-sorter/settings` 把可见性改成 Public。

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

## 本地等价命令（不依赖 CI）

```bash
bash tools/e2e-web.sh                      # 后端 + 网页端端到端（真实浏览器）
cd server && .venv/bin/python -m pytest -q # 后端单测
cd android && gradle assembleDebug testDebugUnitTest   # 需要 JDK 17/21 + Android SDK
bash packaging/fnos/build.sh               # 需要 fnpack
packaging/build-portable.bat               # Windows 上打绿色版
docker compose -f packaging/docker/docker-compose.yml config   # 校验 compose（本机没 docker 权限也能跑）
docker build -f packaging/docker/Dockerfile -t videosorter:dev .  # 需要能访问 docker daemon
```
