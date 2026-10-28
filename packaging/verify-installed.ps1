<#
.SYNOPSIS
    安装包端到端验收：验证装好的应用 ① 双击能起服务、② 源目录计数与删源、③ ffmpeg 能被找到。

.DESCRIPTION
    只从外部打 HTTP API 验装好的二进制，不读源码、不直连数据库。默认模式复刻「资源管理器双击」
    （UseShellExecute=$true，GUI 父进程没有控制台）—— 这是 bug ①（sidecar 在无效 stdio 下不监听）
    的唯一触发条件，换成带控制台/重定向的启动方式就永远测不出来。

    在无交互桌面的 CI runner 上用 -SkipUi：直接拉起 sidecar，仍能覆盖 ②③，覆盖不到 ①。
    退出码：0 = 全通过；1 = 断言失败；2 = 环境问题（缺 ffmpeg / 缺二进制 / 端口占死）。

.EXAMPLE
    # 本机：验证 NSIS 装好的应用（默认安装目录、默认 8080）
    pwsh -NoProfile -File packaging\verify-installed.ps1

.EXAMPLE
    # CI：装到临时目录，跳过 GUI，直接用仓库里下好的 ffmpeg 造测试素材
    pwsh -NoProfile -File packaging\verify-installed.ps1 -InstallDir $env:RUNNER_TEMP\VideoSorter -SkipUi -FfmpegDir src-tauri\tools

.NOTES
    桌面端的端口/URL 在代码里是写死的 8080（src-tauri/src/main.rs:41、tauri.conf.json:18），
    所以 -Port 改别的值时只能配 -SkipUi 用，UI 模式必须留默认 8080。
#>
param(
    [string]$InstallDir = 'D:\Software\VideoSorter',
    [int]$Port = 8080,
    [string]$SrcDir = '',
    [string]$FfmpegDir = '',
    [string]$User = 'admin',
    [string]$Password = 'admin1234',
    [switch]$SkipUi
)

$ErrorActionPreference = 'Stop'
$base = "http://127.0.0.1:$Port"
$appExe = Join-Path $InstallDir 'video-sorter-desktop.exe'
$sidecarExe = Join-Path $InstallDir 'binaries\videosorter-server.exe'
if (-not (Test-Path $sidecarExe)) {
    # 兼容另一种暂存方式：整个 videosorter-server 目录被放进 binaries/
    $sidecarExe = Join-Path $InstallDir 'binaries\videosorter-server\videosorter-server.exe'
}
$appDataDir = Join-Path $env:APPDATA 'VideoSorter'
$cLenName = '测试 视频_b.mp4'   # 中文 + 空格 + 下划线：一次卡住编码/空格/LIKE 通配符串号三个坑
$asciiName = 'clip-a.mp4'
$fail = 0
$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession

function Step($msg) { Write-Output ""; Write-Output ("== " + $msg) }
function Fail($msg) { Write-Output ("❌ FAIL: " + $msg); $script:fail++ }

function Test-PortFree([int]$p, [int]$timeoutMs = 8000) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while ($sw.ElapsedMilliseconds -lt $timeoutMs) {
        $n = (Get-NetTCPConnection -State Listen -LocalPort $p -ErrorAction SilentlyContinue | Measure-Object).Count
        if ($n -eq 0) { return $true }
        Start-Sleep -Milliseconds 300
    }
    return $false
}

function Get-Json([string]$url, [string]$method = 'Get', $body = $null) {
    $p = @{ Uri = $url; Method = $method; WebSession = $session; UseBasicParsing = $true }
    if ($body) { $p.ContentType = 'application/json'; $p.Body = $body }
    return (Invoke-WebRequest @p).Content | ConvertFrom-Json
}

function Resolve-Ffmpeg {
    $cands = @()
    if ($FfmpegDir) { $cands += $FfmpegDir }
    $cands += (Join-Path $InstallDir 'tools')
    $repoRoot = Split-Path -Parent $PSScriptRoot
    $cands += (Join-Path $repoRoot 'src-tauri\tools')
    $cands += (Join-Path $repoRoot 'server\tools')
    foreach ($d in $cands) {
        if (-not $d) { continue }
        $p = Join-Path $d 'ffmpeg.exe'
        if (Test-Path $p) { return (Resolve-Path $p).Path }
    }
    $cmd = Get-Command ffmpeg.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

# ── 0. 前置检查：二进制、端口、测试素材 ────────────────────────────────────
Step '0. 前置检查（二进制 / 端口 / 测试素材）'
if (-not (Test-Path $InstallDir)) { Write-Output ("❌ FAIL: 安装目录不存在：$InstallDir"); exit 2 }
Write-Output ("   安装目录 = " + $InstallDir)
if ($SkipUi) {
    if (-not (Test-Path $sidecarExe)) { Write-Output ("❌ FAIL: 找不到 sidecar：$sidecarExe"); exit 2 }
} else {
    if (-not (Test-Path $appExe)) { Write-Output ("❌ FAIL: 找不到主程序：$appExe"); exit 2 }
    if ($Port -ne 8080) { Write-Output ("⚠️  警告：桌面端端口写死 8080，-Port $Port 只对 /api 轮询有效，UI 模式请用默认值") }
}

Get-Process -Name 'video-sorter-desktop', 'videosorter-server' -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }
if (-not (Test-PortFree $Port)) {
    Write-Output ("❌ FAIL: 端口 $Port 被别的进程占着（上一次强杀留下的孤儿 sidecar？先解决再测）")
    exit 2
}
Write-Output ("   端口 $Port 空闲 = True")

if (-not $SrcDir) { $SrcDir = Join-Path $env:TEMP 'videosorter-e2e\src' }
New-Item -ItemType Directory -Force -Path $SrcDir | Out-Null
$ffmpeg = Resolve-Ffmpeg
foreach ($name in @($asciiName, $cLenName)) {
    $f = Join-Path $SrcDir $name
    if (Test-Path $f) { continue }
    if (-not $ffmpeg) { Write-Output ("❌ FAIL: 缺测试素材 $f，且找不到 ffmpeg 生成"); exit 2 }
    & $ffmpeg -hide_banner -loglevel error -y -f lavfi -i 'testsrc=size=320x240:rate=10' -t 2 -pix_fmt yuv420p $f
    if (-not (Test-Path $f)) { Write-Output ("❌ FAIL: ffmpeg 没能生成 $f"); exit 2 }
}
Write-Output ("   测试素材 = $SrcDir（{0}）" -f ((@($asciiName, $cLenName) | ForEach-Object { (Get-Item (Join-Path $SrcDir $_)).Length }) -join ' / '))
Write-Output ("   用于造素材的 ffmpeg = " + $(if ($ffmpeg) { $ffmpeg } else { '(素材已存在，未用)' }))

$tmpRoot = Join-Path $env:TEMP 'videosorter-e2e'
$sidecarLog = Join-Path $tmpRoot 'sidecar.log'
$proc = $null
$logOut = $null
$procCountName = 'videosorter-server'

try {
    # ── 1. 启动 ───────────────────────────────────────────────────────────
    if ($SkipUi) {
        Step '1. 直接拉起 sidecar（-SkipUi：覆盖不到 bug ①，只验 ②③）'
        $dataDir = Join-Path $tmpRoot 'data'
        if (Test-Path $dataDir) { Remove-Item $dataDir -Recurse -Force }
        New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
        $logOut = Join-Path $tmpRoot 'sidecar.out.log'
        $logErr = Join-Path $tmpRoot 'sidecar.err.log'
        $proc = Start-Process -FilePath $sidecarExe `
            -ArgumentList @('--host', '127.0.0.1', '--port', "$Port", '--data-dir', $dataDir) `
            -WorkingDirectory (Split-Path $sidecarExe) -PassThru `
            -RedirectStandardOutput $logOut -RedirectStandardError $logErr
        $expectDataDir = $dataDir
    } else {
        Step '1. 像用户双击那样启动（GUI 父进程无控制台 —— bug ① 的触发条件）'
        if (Test-Path $appDataDir) { Remove-Item $appDataDir -Recurse -Force }
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $appExe
        $psi.UseShellExecute = $true
        $psi.WorkingDirectory = $InstallDir
        $proc = [System.Diagnostics.Process]::Start($psi)
        $expectDataDir = $appDataDir
    }

    $health = $null
    $i = 0
    for ($i = 1; $i -le 40; $i++) {
        Start-Sleep -Milliseconds 500
        try { $health = Get-Json "$base/api/health"; break } catch {}
    }
    if (-not $health) {
        Write-Output ("❌ FAIL: 20s 内 /api/health 没有响应")
        if ($SkipUi -and (Test-Path $logErr)) { Write-Output '   --- sidecar stderr ---'; Get-Content $logErr -Tail 20 }
        Fail 'not healthy -> 应用/服务没起来'
        throw 'health-timeout'
    }
    Write-Output ("✅ health ok  等待秒数≈{0:N1}" -f ($i / 2))
    Write-Output ("   media_ready = " + $health.media_ready)
    Write-Output ("   ffmpeg      = " + $health.ffmpeg)
    Write-Output ("   data_dir    = " + $health.data_dir)
    if (-not $health.media_ready) { Fail 'media_ready 仍为 false（ffmpeg 没找到，见 bug ③）' }
    if (-not $health.ffmpeg) { Fail 'health.ffmpeg 为空' }

    # ── 2. 登录 ───────────────────────────────────────────────────────────
    Step '2. 登录'
    $loginBody = @{ username = $User; password = $Password; remember = $true } | ConvertTo-Json -Compress
    $login = Invoke-WebRequest "$base/api/auth/login" -Method Post -WebSession $session -UseBasicParsing `
        -ContentType 'application/json' -Body $loginBody
    Write-Output ("✅ 登录 {0}" -f $login.StatusCode)

    # ── 3. 加源 + 扫描 ────────────────────────────────────────────────────
    Step '3. 添加源目录并扫描'
    $r = Invoke-WebRequest "$base/api/sources" -Method Post -WebSession $session -UseBasicParsing `
        -ContentType 'application/json' -Body (@{ path = $SrcDir } | ConvertTo-Json -Compress)
    Write-Output ("   添加源 {0}" -f $r.StatusCode)
    $tid = (Get-Json "$base/api/scan" 'Post' '{}').task_id
    $t = $null
    # 最多等 120s：这台机器上偶发「ffprobe 启动挂住」，改了 media.py 让它 20s 超时后重试，
    # 最坏情况扫描要 40s 上下，所以窗口给足，别把偶发的慢当成失败。
    for ($i = 0; $i -lt 240; $i++) {
        Start-Sleep -Milliseconds 500
        $t = Get-Json "$base/api/tasks/$tid"
        if ($t.status -ne 'running') { break }
    }
    Start-Sleep -Milliseconds 500
    Write-Output ("   扫描任务结束：status={0} message={1}" -f $t.status, $t.message)
    Write-Output ("   扫描任务详情：" + ($t | ConvertTo-Json -Compress -Depth 4))
    if ($t.status -ne 'done') { Fail ("扫描任务没 done（status=$($t.status) message=$($t.message)）") }

    # ── 4. 视频库与源计数（bug ② 的核心断言）───────────────────────────────
    Step '4. 视频库与源计数（bug ② 的核心断言）'
    $videos = Get-Json "$base/api/videos"
    $sources = Get-Json "$base/api/sources"
    $stats = Get-Json "$base/api/stats"
    $mysrc = $sources.sources | Where-Object { $_.kind -ne 'upload' } | Select-Object -First 1
    if (-not $mysrc) { Fail '没找到刚加的源目录'; throw 'no-source' }
    $statCount = ($stats.sources | Where-Object { $_.id -eq $mysrc.id }).count
    $names = @($videos.items | ForEach-Object { $_.filename })
    Write-Output ("   视频条数 = " + $videos.items.Count)
    Write-Output ("   源目录 = " + $mysrc.path)
    Write-Output ("   源的视频计数 = {0}（修复前恒为 0）" -f $mysrc.count)
    Write-Output ("   /api/stats 里同一源计数 = {0}" -f $statCount)
    Write-Output ("   文件名 = " + ($names -join ' | '))
    if ($videos.items.Count -lt 2) { Fail '扫描没扫到 2 个测试视频' }
    if (-not ($names -contains $cLenName)) { Fail "中文/空格/下划线文件名没入库（$cLenName）" }
    if ($mysrc.count -ne $videos.items.Count) { Fail '源计数与视频总数不一致' }
    if ($statCount -ne $mysrc.count) { Fail 'stats 与 sources 计数不一致' }

    # ── 5. 删源级联 ───────────────────────────────────────────────────────
    Step '5. 写播放记录后删源目录'
    foreach ($v in $videos.items) {
        Invoke-WebRequest "$base/api/videos/$($v.id)/history" -Method Post -WebSession $session -UseBasicParsing `
            -ContentType 'application/json' -Body '{"position":5.0,"duration":20}' | Out-Null
    }
    $del = Invoke-WebRequest "$base/api/sources/$($mysrc.id)" -Method Delete -WebSession $session -UseBasicParsing
    Write-Output ("   删除源 {0} -> {1}" -f $mysrc.id, $del.Content)
    $after = Get-Json "$base/api/videos"
    $hist = Get-Json "$base/api/history"
    $undeleted = @($hist.items | Where-Object { -not $_.deleted })
    Write-Output ("   删源后视频库条数 = {0}（期望 0）" -f $after.items.Count)
    Write-Output ("   播放记录 {0} 条，其中未标 deleted 的 {1} 条（期望 0）" -f $hist.items.Count, $undeleted.Count)
    if ($after.items.Count -ne 0) { Fail '删源后视频库没清空（bug ② 未修复）' }
    if ($undeleted.Count -ne 0) { Fail '播放记录没标 deleted' }

    # ── 6. 收尾 ───────────────────────────────────────────────────────────
    Step '6. 收尾：退出并确认没留后台进程'
    if (-not $SkipUi) {
        $proc.Refresh()
        if (-not $proc.HasExited) { $proc.CloseMainWindow() | Out-Null }
        for ($i = 0; $i -lt 20; $i++) {
            Start-Sleep -Milliseconds 500
            if ($proc.HasExited) { break }
        }
        Write-Output ("   主进程已退出 = " + $proc.HasExited)
        if (-not $proc.HasExited) { Fail '关窗口后主进程 10s 内没退出' }
        Start-Sleep -Seconds 2
    }
    $left = @(Get-Process -Name $procCountName -ErrorAction SilentlyContinue)
    Write-Output ("   残留 sidecar 进程数 = {0}（期望 0）" -f $left.Count)
    if ($SkipUi) {
        if ($left.Count -gt 0) { Write-Output '   （-SkipUi 模式下 sidecar 由本脚本拉起，下面统一清理）' }
    } elseif ($left.Count -ne 0) {
        Fail '关窗口后 sidecar 没被回收（main.rs 的 ExitRequested 没生效）'
    }
} catch {
    if ($_.Exception.Message -ne 'health-timeout') { Write-Output ("❌ 脚本异常：" + $_.Exception.Message) }
} finally {
    foreach ($n in @('video-sorter-desktop', 'videosorter-server')) {
        Get-Process -Name $n -ErrorAction SilentlyContinue |
            ForEach-Object { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }
    }
}

Write-Output ''
if ($fail -eq 0) {
    Write-Output '===== 全部通过 ====='
    exit 0
} else {
    Write-Output ("===== 有 " + $fail + " 项失败 =====")
    exit 1
}
