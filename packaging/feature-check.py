#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""VideoSorter 功能自查（黑盒：拉起已安装的 sidecar，用 HTTP 逐项验证功能是否实现/可用）。

用法：
    D:\\Software\\python\\311\\python.exe feature-check.py [--port 8099] [--keep]

产物：
    %TEMP%\\vs-feature\\feature-report.md   人读报告
    %TEMP%\\vs-feature\\feature-report.json 机读结果
    %TEMP%\\vs-feature\\server.log          sidecar 日志
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import traceback
from pathlib import Path

import httpx

# ---------------------------------------------------------------- 常量与状态
INSTALL = Path(os.environ.get("VS_INSTALL", r"D:\Software\VideoSorter"))
PORT = 8099
BASE = f"http://127.0.0.1:{PORT}"
TMP = Path(os.environ.get("TEMP", ".")) / "vs-feature"
DATA = TMP / "data"
MEDIA = TMP / "media"
SUB = MEDIA / "子目录"
UPDIR = TMP / "上传测试"
CROSS = Path(r"D:\aiworkspaces\deepseekharness\videosorter\cross-device-out")
FFMPEG = INSTALL / "tools" / "ffmpeg.exe"
FFPROBE = INSTALL / "tools" / "ffprobe.exe"
SIDECAR = INSTALL / "binaries" / "videosorter-server.exe"
if not SIDECAR.exists():
    # 兼容另一种暂存方式：整个 videosorter-server 目录被放进 binaries/（多一层）
    SIDECAR = INSTALL / "binaries" / "videosorter-server" / "videosorter-server.exe"
LOG = TMP / "server.log"

CHECKS: list[dict] = []
S: dict = {}
PROC: subprocess.Popen | None = None
C = httpx.Client(base_url=BASE, timeout=120.0, follow_redirects=False)


class Fail(Exception):
    pass


def check(area: str, name: str, manual: bool = False):
    def deco(fn):
        CHECKS.append({"area": area, "name": name, "fn": fn, "manual": manual})
        return fn
    return deco


def need(resp, code=200, what=""):
    if resp.status_code != code:
        raise Fail(f"{what} → 期望 {code}，实际 {resp.status_code}: {resp.text[:240]}")
    return resp


def jget(path, code=200, what=""):
    r = C.get(path)
    need(r, code, what or path)
    try:
        return r.json()
    except Exception:
        return r.text


def jpost(path, body=None, code=200, what=""):
    r = C.post(path, json=body) if body is not None else C.post(path)
    need(r, code, what or path)
    try:
        return r.json()
    except Exception:
        return r.text


def jput(path, body, code=200, what=""):
    r = C.put(path, json=body)
    need(r, code, what or path)
    return r.json()


# ---------------------------------------------------------------- 服务进程
def port_busy(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", port)) == 0


def kill_stragglers():
    """清掉可能占着 8080/8099/38080 的旧实例（我自己之前装的测试进程）。"""
    ps = (
        "Get-Process videosorter-server,video-sorter-desktop -ErrorAction SilentlyContinue "
        "| ForEach-Object { $_.Kill() }"
    )
    subprocess.run(["pwsh", "-NoProfile", "-Command", ps], capture_output=True)


def start_server(wait: float = 40.0) -> float:
    global PROC
    LOG.parent.mkdir(parents=True, exist_ok=True)
    logf = open(LOG, "ab")
    logf.write(f"\n===== start {time.strftime('%H:%M:%S')} =====\n".encode())
    logf.flush()
    t0 = time.time()
    PROC = subprocess.Popen(
        [str(SIDECAR), "--host", "127.0.0.1", "--port", str(PORT), "--data-dir", str(DATA)],
        stdin=subprocess.DEVNULL, stdout=logf, stderr=subprocess.STDOUT,
        # 不要加 creationflags=CREATE_NO_WINDOW：没有控制台的父进程里再拉 ffmpeg，
        # 子进程会以 0xC0000142（STATUS_DLL_INIT_FAILED）退出，HLS 全挂。
        # 真实桌面应用走的是 GUI 子系统 + stdio=null，实测 HLS 正常（见 probe-app-hls.py）。
    )
    while time.time() - t0 < wait:
        if port_busy(PORT):
            try:
                r = C.get("/api/health")
                if r.status_code == 200:
                    return time.time() - t0
            except Exception:
                pass
        if PROC.poll() is not None:
            raise Fail(f"sidecar 启动即退出，exit={PROC.returncode}（看 {LOG}）")
        time.sleep(0.25)
    raise Fail(f"sidecar {wait:.0f}s 内没起来")


def stop_server():
    global PROC
    if PROC and PROC.poll() is None:
        PROC.terminate()
        try:
            PROC.wait(timeout=10)
        except subprocess.TimeoutExpired:
            PROC.kill()
    PROC = None
    for _ in range(40):
        if not port_busy(PORT):
            return
        time.sleep(0.2)


# ---------------------------------------------------------------- 素材
def gen(name: str, args: list[str]) -> Path:
    out = MEDIA / name
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and out.stat().st_size > 0:
        return out
    r = subprocess.run([str(FFMPEG), "-y", "-v", "error", *args, str(out)], capture_output=True)
    if r.returncode != 0:
        raise Fail(f"生成素材 {name} 失败：{r.stderr.decode('utf-8', 'replace')[:200]}")
    return out


def prepare_media():
    for d in (TMP, MEDIA, SUB, UPDIR):
        d.mkdir(parents=True, exist_ok=True)
    base_v = ["-f", "lavfi", "-i", "testsrc2=size=320x240:rate=15"]
    gen("a_direct.mp4", base_v + ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
                                 "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                                 "-c:a", "aac", "-shortest"])
    gen("b_mpeg4.mp4", base_v + ["-t", "3", "-c:v", "mpeg4", "-q:v", "6", "-an"])
    gen("c_mkv.mkv", base_v + ["-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an"])
    gen("中文 空格 名字.mp4", base_v + ["-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an"])
    gen("noaudio.mp4", base_v + ["-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an"])
    gen("long30s.mp4", ["-f", "lavfi", "-i", "testsrc2=size=320x240:rate=10", "-t", "30",
                        "-c:v", "libx264", "-crf", "40", "-pix_fmt", "yuv420p", "-an"])
    gen("子目录/子目录里的视频.mp4", base_v + ["-t", "2", "-c:v", "libx264",
                                             "-pix_fmt", "yuv420p", "-an"])
    bad = MEDIA / "broken.mp4"
    if not bad.exists():
        bad.write_bytes(b"this is not a real video file\n" * 40)
    (MEDIA / "note.txt").write_text("不是视频，扫描应忽略", encoding="utf-8")


# ================================================================ 检查项
# ---------- 启动与静态资源
@check("启动与静态资源", "health 关键字段齐全")
def c01():
    d = jget("/api/health")
    missing = [k for k in ("ok", "app", "version", "media_ready", "ffmpeg", "ffprobe",
                           "platform", "python", "web", "data_dir", "discovery") if k not in d]
    if missing:
        raise Fail(f"缺字段 {missing}")
    if not d["media_ready"]:
        raise Fail("media_ready=false")
    if not Path(d["ffmpeg"]).exists():
        raise Fail(f"ffmpeg 路径不存在：{d['ffmpeg']}")
    if not d["web"]:
        raise Fail("web=false（webdist 没找到）")
    S["health"] = d
    return f"version={d['version']} python={d['python']}"


@check("启动与静态资源", "首页 index.html 可取")
def c02():
    r = C.get("/")
    need(r, 200, "/")
    if "text/html" not in r.headers.get("content-type", ""):
        raise Fail(f"content-type={r.headers.get('content-type')}")
    if 'id="app"' not in r.text and "createApp" not in r.text:
        raise Fail("首页不像 Vue 入口")
    return f"{len(r.content)} 字节"


@check("启动与静态资源", "前端 JS/CSS 资源可取")
def c03():
    r = C.get("/")
    import re
    assets = re.findall(r'(?:src|href)="(/assets/[^"]+)"', r.text)
    if not assets:
        raise Fail("首页没引用 /assets/*")
    codes = []
    for a in assets[:4]:
        rr = C.get(a)
        codes.append(rr.status_code)
        if rr.status_code != 200:
            raise Fail(f"{a} → {rr.status_code}")
    return f"{len(assets)} 个资源，抽查 {codes}"


@check("启动与静态资源", "SPA 深链接回落到 index.html")
def c04():
    r = C.get("/videos")
    need(r, 200, "/videos")
    if "text/html" not in r.headers.get("content-type", ""):
        raise Fail(f"content-type={r.headers.get('content-type')}")
    return "200 html"


@check("启动与静态资源", "不存在的 API 返回 404 JSON")
def c05():
    r = C.get("/api/definitely-not-exist")
    need(r, 404, "/api/definitely-not-exist")
    d = r.json()
    if d.get("status") != 404 or not d.get("detail"):
        raise Fail(f"错误结构异常：{d}")
    return f"detail={d['detail']}"


@check("启动与静态资源", "OpenAPI 文档可访问")
def c06():
    r = C.get("/docs")
    need(r, 200, "/docs")
    r2 = C.get("/openapi.json")
    need(r2, 200, "/openapi.json")
    n = len(r2.json().get("paths", {}))
    S["paths"] = n
    return f"{n} 个路径"


# ---------- 认证
@check("认证", "未登录访问受保护接口返回 401")
def c07():
    r = C.get("/api/videos")
    need(r, 401, "/api/videos 未登录")
    return f"detail={r.json().get('detail')}"


@check("认证", "错密码登录被拒（中文错误）")
def c08():
    r = C.post("/api/auth/login", json={"username": "admin", "password": "wrong-pass"})
    need(r, 401, "错密码")
    detail = r.json().get("detail", "")
    if not any("\u4e00" <= ch <= "\u9fff" for ch in detail):
        raise Fail(f"错误信息不是中文：{detail}")
    return detail[:40]


@check("认证", "默认账号 admin/admin1234 登录成功")
def c09():
    d = jpost("/api/auth/login", {"username": "admin", "password": "admin1234"})
    if not d.get("token"):
        raise Fail(f"没返回 token：{d}")
    if not C.cookies.get("vs_token"):
        raise Fail("没种下 vs_token cookie")
    S["token"] = d["token"]
    return f"token={d['token'][:8]}… user={d.get('user')}"


@check("认证", "/api/auth/me 返回当前用户")
def c10():
    d = jget("/api/auth/me")
    u = d.get("user") or {}
    if u.get("username") != "admin":
        raise Fail(f"user={u}")
    return f"username={u.get('username')}"


@check("认证", "会话列表可查（含 token 前缀与时间）")
def c11():
    d = jget("/api/auth/sessions")
    items = d.get("sessions") or []
    if not items:
        raise Fail("sessions 为空")
    for k in ("token", "created_at", "last_used_at"):
        if k not in items[0]:
            raise Fail(f"缺 {k}：{items[0]}")
    # 前端 web/src/api.ts:166 的会话类型里声明了 current: boolean，后端 auth.py:107-110
    # 的 sessions() 没有这个字段 —— 不是功能缺失（UI 也不用它），但类型对不上，记下来。
    cur = all("current" in x for x in items)
    S["sessions_have_current"] = cur
    return f"{len(items)} 个会话，current 字段={'有' if cur else '缺（前端类型声明了）'}"


@check("认证", "登出后 cookie 失效，重新登录恢复")
def c12():
    jpost("/api/auth/logout", None)
    r = C.get("/api/videos")
    if r.status_code != 401:
        raise Fail(f"登出后仍可访问：{r.status_code}")
    jpost("/api/auth/login", {"username": "admin", "password": "admin1234"})
    jget("/api/videos")
    return "登出→401，重登→200"


# ---------- 源目录
@check("源目录", "内置上传目录已登记为源（kind=upload 且不可删）")
def c13():
    d = jget("/api/sources")
    ups = [s for s in d["sources"] if s.get("kind") == "upload"]
    if not ups:
        raise Fail(f"没有 kind=upload 的源：{d['sources']}")
    u = ups[0]
    if u.get("deletable") is not False:
        raise Fail(f"上传源 deletable={u.get('deletable')}")
    S["upload_source"] = u
    return f"path={u['path']}"


@check("源目录", "添加中文路径源目录")
def c14():
    d = jpost("/api/sources", {"path": str(MEDIA)})
    if not d.get("ok"):
        raise Fail(str(d))
    S["src"] = d["source"]
    return f"id={d['source']['id']}"


@check("源目录", "重复添加同一目录被拒")
def c15():
    r = C.post("/api/sources", json={"path": str(MEDIA)})
    need(r, 400, "重复添加")
    return r.json().get("detail", "")[:40]


@check("源目录", "添加不存在的目录被拒")
def c16():
    r = C.post("/api/sources", json={"path": str(MEDIA / "根本不存在的目录")})
    need(r, 400, "不存在目录")
    return r.json().get("detail", "")[:40]


@check("源目录", "目录浏览 /api/fs/list")
def c17():
    d = jget("/api/fs/list?path=D%3A%5C")
    if not d.get("dirs"):
        raise Fail(f"没列到目录：{str(d)[:200]}")
    S["fs"] = d
    return f"{len(d['dirs'])} 个子目录，parent={d.get('parent')}"


@check("源目录", "目录浏览支持跳转子目录")
def c18():
    d = jget("/api/fs/list?path=" + str(MEDIA).replace("\\", "%5C"))
    names = [x["name"] for x in d.get("dirs", [])]
    if "子目录" not in names:
        raise Fail(f"没看到 子目录：{names}")
    return f"persisted path={d['path']}"


@check("源目录", "修改源目录路径")
def c19():
    tmp = TMP / "改路径测试"
    tmp.mkdir(exist_ok=True)
    d = jput(f"/api/sources/{S['src']['id']}", {"path": str(tmp)})
    if not d.get("ok"):
        raise Fail(str(d))
    back = jput(f"/api/sources/{S['src']['id']}", {"path": str(MEDIA)})
    return f"改到 {tmp.name} 再改回"


@check("源目录", "内置上传源不允许删除")
def c20():
    sid = S["upload_source"]["id"]
    r = C.delete(f"/api/sources/{sid}")
    need(r, 400, "删上传源")
    return r.json().get("detail", "")[:40]


# ---------- 扫描
@check("扫描", "启动扫描任务并跑完")
def c21():
    d = jpost("/api/scan", {"source_ids": [S["src"]["id"]]})
    if not d.get("task_id"):
        raise Fail(str(d))
    tid = d["task_id"]
    t0 = time.time()
    while time.time() - t0 < 180:
        t = jget(f"/api/tasks/{tid}")
        if t["status"] != "running":
            break
        time.sleep(0.3)
    if t["status"] != "done":
        raise Fail(f"任务状态 {t['status']}：{t.get('error') or t.get('message')}")
    S["scan_task"] = t
    return f"{time.time() - t0:.1f}s percent={t['percent']} result={t.get('result')}"


@check("扫描", "入库视频数正确（递归、忽略非视频、容错坏文件）")
def c22():
    d = jget("/api/videos?limit=500")
    names = {x["filename"] for x in d["items"]}
    expect = {"a_direct.mp4", "b_mpeg4.mp4", "c_mkv.mkv", "中文 空格 名字.mp4",
              "noaudio.mp4", "long30s.mp4", "子目录里的视频.mp4"}
    missing = expect - names
    if missing:
        raise Fail(f"缺 {missing}；实际 {sorted(names)}")
    if "note.txt" in names:
        raise Fail("txt 被当成视频入库")
    S["total_after_scan"] = d["total"]
    S["vids"] = {x["filename"]: x for x in d["items"]}
    return f"共 {d['total']} 条；broken.mp4 {'已入库' if 'broken.mp4' in names else '被跳过'}"


@check("扫描", "二次扫描识别「未变化」")
def c23():
    d = jpost("/api/scan", {})
    tid = d["task_id"]
    t0 = time.time()
    while time.time() - t0 < 120:
        t = jget(f"/api/tasks/{tid}")
        if t["status"] != "running":
            break
        time.sleep(0.3)
    r = t.get("result") or {}
    added = r.get("added", 0)
    if added:
        raise Fail(f"二次扫描仍 added={added}：{r}")
    return f"result={r}"


@check("扫描", "full 强制重扫可用")
def c24():
    d = jpost("/api/scan", {"full": True})
    tid = d["task_id"]
    t0 = time.time()
    while time.time() - t0 < 180:
        t = jget(f"/api/tasks/{tid}")
        if t["status"] != "running":
            break
        time.sleep(0.3)
    if t["status"] != "done":
        raise Fail(f"full 扫描失败：{t.get('error')}")
    return f"result={t.get('result')}"


@check("扫描", "查询不存在的任务返回 404")
def c25():
    r = C.get("/api/tasks/nope-1234")
    need(r, 404, "未知任务")
    return r.json().get("detail", "")[:30]


@check("扫描", "取消已完成任务不报错")
def c26():
    tid = S["scan_task"]["id"] if isinstance(S.get("scan_task"), dict) else ""
    r = C.post(f"/api/tasks/{tid}/cancel")
    need(r, 200, "cancel")
    return str(r.json())[:60]


# ---------- 视频库
@check("视频库", "列表返回 items/total/counts")
def c27():
    d = jget("/api/videos")
    for k in ("items", "total", "counts"):
        if k not in d:
            raise Fail(f"缺 {k}")
    for k in ("all", "untagged", "source"):
        if k not in d["counts"]:
            raise Fail(f"counts 缺 {k}：{d['counts']}")
    return f"total={d['total']} counts={d['counts']}"


@check("视频库", "按状态筛选 untagged / tagged / missing")
def c28():
    out = {}
    for st in ("untagged", "tagged", "missing", "organized"):
        d = jget(f"/api/videos?status={st}")
        out[st] = d["total"]
    return f"{out}"


@check("视频库", "文件名关键字搜索（中文子串）")
def c29():
    d = jget("/api/videos?q=" + "中文")
    names = [x["filename"] for x in d["items"]]
    if not any("中文" in n for n in names):
        raise Fail(f"没搜到：{names}")
    return f"命中 {len(names)} 条"


@check("视频库", "排序 size desc / name asc")
def c30():
    d = jget("/api/videos?sort=size&order=desc&limit=500")
    sizes = [x["size"] for x in d["items"]]
    if sizes != sorted(sizes, reverse=True):
        raise Fail("size desc 未生效")
    d2 = jget("/api/videos?sort=name&order=asc&limit=500")
    names = [x["filename"] for x in d2["items"]]
    if names != sorted(names):
        raise Fail(f"name asc 未生效：{names[:5]}")
    return f"max={sizes[0]} min={sizes[-1]}"


@check("视频库", "分页 limit/offset 生效")
def c31():
    a = jget("/api/videos?limit=2&offset=0")
    b = jget("/api/videos?limit=2&offset=2")
    if len(a["items"]) != 2 or not b["items"]:
        raise Fail(f"limit 异常 a={len(a['items'])} b={len(b['items'])}")
    if a["items"][0]["id"] == b["items"][0]["id"]:
        raise Fail("offset 未生效（两页首条相同）")
    return f"a={[x['id'] for x in a['items']]} b={[x['id'] for x in b['items']]}"


@check("视频库", "非法参数被拒（limit=0 → 422）")
def c32():
    r = C.get("/api/videos?limit=0")
    need(r, 422, "limit=0")
    return "422"


@check("视频库", "单条详情可取")
def c33():
    vid = S["vids"]["a_direct.mp4"]["id"]
    d = jget(f"/api/videos/{vid}")
    if d["id"] != vid or not d.get("raw_url"):
        raise Fail(str(d)[:200])
    return f"id={vid} {d['filename']} status={d['status']}"


@check("视频库", "不存在的视频 id → 404")
def c34():
    r = C.get("/api/videos/999999")
    need(r, 404, "不存在 id")
    return r.json().get("detail", "")


@check("视频库", "统计 /api/stats 与列表一致")
def c35():
    d = jget("/api/stats")
    lst = jget("/api/videos?limit=1")
    if d["total"] != lst["total"]:
        raise Fail(f"stats.total={d['total']} 列表 total={lst['total']}")
    for k in ("bytes", "tagged", "untagged", "organized", "tagged_pending",
              "missing", "last_scan_at", "tags", "sources"):
        if k not in d:
            raise Fail(f"stats 缺 {k}")
    src = [s for s in d["sources"] if s["path"] == str(MEDIA)]
    if not src:
        raise Fail("stats.sources 里没有刚加的源")
    S["stats"] = d
    return f"total={d['total']} bytes={d['bytes']} 源计数={src[0]['count']}"


# ---------- 封面
@check("封面", "封面接口返回 JPEG")
def c36():
    vid = S["vids"]["a_direct.mp4"]["id"]
    r = C.get(f"/api/videos/{vid}/thumb")
    need(r, 200, "thumb")
    if r.headers.get("content-type", "").split(";")[0] != "image/jpeg":
        raise Fail(f"content-type={r.headers.get('content-type')}")
    if not r.content.startswith(b"\xff\xd8"):
        raise Fail("不是 JPEG 数据")
    S["thumb_id"] = vid
    return f"{len(r.content)} 字节"


@check("封面", "封面按 480 宽缩放（ffprobe 校验）")
def c37():
    vid = S["thumb_id"]
    f = DATA / "thumbs" / f"{vid}.jpg"
    if not f.exists():
        C.get(f"/api/videos/{vid}/thumb")
        time.sleep(1)
    if not f.exists():
        raise Fail(f"缩略图没落盘：{f}")
    r = subprocess.run([str(FFPROBE), "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height", "-of", "csv=p=0", str(f)],
                       capture_output=True, text=True)
    wh = r.stdout.strip()
    if not wh.startswith("480"):
        raise Fail(f"尺寸={wh}")
    return f"{wh} / {f.stat().st_size} 字节"


@check("封面", "文件不存在的视频封面 → 404")
def c38():
    # 造一条指向不存在文件的记录：上传后删文件，再看 thumb
    # 注意不能用「先复制到上传目录再上传」的写法 —— 同名会自动改名成 ghost (1).mp4，
    # 删掉 ghost.mp4 之后真实文件还在，封面会被重新生成，测试就骗自己了。
    UPDIR.mkdir(parents=True, exist_ok=True)
    blob = (MEDIA / "a_direct.mp4").read_bytes()
    d = C.post("/api/upload", files={"file": ("ghost.mp4", blob, "video/mp4")},
               data={"dir": str(UPDIR)}).json()
    vid = d["video"]["id"]
    (DATA / "thumbs" / f"{vid}.jpg").unlink(missing_ok=True)
    Path(d["path"]).unlink(missing_ok=True)
    r = C.get(f"/api/videos/{vid}/thumb")
    if r.status_code != 404:
        raise Fail(f"期望 404，实际 {r.status_code} {r.text[:60]}")
    S["ghost_vid"] = vid
    return f"404 {r.text[:40]}"


# ---------- 播放与流
@check("播放", "h264/aac mp4 判定可直放")
def c39():
    vid = S["vids"]["a_direct.mp4"]["id"]
    d = jget(f"/api/videos/{vid}/play")
    if d.get("mode") != "direct":
        raise Fail(str(d))
    S["direct_id"] = vid
    return f"mode=direct reason={d.get('reason')}"


@check("播放", "原始流 /raw 返回 200 + 正确头")
def c40():
    r = C.get(f"/api/videos/{S['direct_id']}/raw")
    need(r, 200, "raw")
    h = r.headers
    if not h.get("content-length") or h.get("accept-ranges") != "bytes":
        raise Fail(f"头异常：{dict(h)}")
    if "video/mp4" not in h.get("content-type", ""):
        raise Fail(f"content-type={h.get('content-type')}")
    return f"{h['content-length']} 字节 {h.get('content-type')}"


@check("播放", "Range 请求返回 206 与正确片段")
def c41():
    with C.stream("GET", f"/api/videos/{S['direct_id']}/raw",
                  headers={"Range": "bytes=0-99"}) as r:
        if r.status_code != 206:
            raise Fail(f"状态 {r.status_code}")
        cr = r.headers.get("content-range", "")
        body = b"".join(r.iter_bytes())
    if not cr.startswith("bytes 0-99/"):
        raise Fail(f"Content-Range={cr}")
    if len(body) != 100:
        raise Fail(f"实际长度 {len(body)}")
    return cr


@check("播放", "尾部 Range（bytes=-100）")
def c42():
    with C.stream("GET", f"/api/videos/{S['direct_id']}/raw",
                  headers={"Range": "bytes=-100"}) as r:
        if r.status_code != 206:
            raise Fail(f"状态 {r.status_code}")
        cr = r.headers.get("content-range", "")
        n = len(b"".join(r.iter_bytes()))
    if n != 100:
        raise Fail(f"长度 {n}，Content-Range={cr}")
    return cr


@check("播放", "越界 Range → 416")
def c43():
    r = C.get(f"/api/videos/{S['direct_id']}/raw",
              headers={"Range": "bytes=999999999-"})
    need(r, 416, "越界 Range")
    return r.json().get("detail", "")


@check("播放", "非法 Range → 416")
def c44():
    r = C.get(f"/api/videos/{S['direct_id']}/raw", headers={"Range": "bytes=abc"})
    need(r, 416, "非法 Range")
    return r.json().get("detail", "")


@check("播放", "下载模式带附件头与中文文件名")
def c45():
    r = C.get(f"/api/videos/{S['direct_id']}/raw?download=1")
    need(r, 200, "download")
    cd = r.headers.get("content-disposition", "")
    if "attachment" not in cd or "filename*=UTF-8''" not in cd:
        raise Fail(f"Content-Disposition={cd}")
    return cd[:70]


@check("播放", "文件被移走后 /raw 返回 404")
def c46():
    vid = S["ghost_vid"]
    r = C.get(f"/api/videos/{vid}/raw")
    need(r, 404, "ghost raw")
    return r.json().get("detail", "")


# ---------- HLS 转码
@check("HLS", "非直放编码（mpeg4）走 HLS")
def c47():
    vid = S["vids"]["b_mpeg4.mp4"]["id"]
    d = jget(f"/api/videos/{vid}/play")
    if d.get("mode") != "hls":
        raise Fail(f"mode={d.get('mode')} {d}")
    S["hls_id"] = vid
    return f"mode=hls status={d.get('status')} copy={d.get('copy')}"


@check("HLS", "mkv 容器走 HLS")
def c48():
    vid = S["vids"]["c_mkv.mkv"]["id"]
    d = jget(f"/api/videos/{vid}/play")
    if d.get("mode") != "hls":
        raise Fail(f"mode={d.get('mode')}")
    return f"mode=hls status={d.get('status')}"


@check("HLS", "m3u8 播放列表可取")
def c49():
    vid = S["hls_id"]
    t0 = time.time()
    r = C.get(f"/api/videos/{vid}/hls/index.m3u8")
    need(r, 200, "index.m3u8")
    if "#EXTM3U" not in r.text:
        raise Fail(r.text[:120])
    segs = [ln.strip() for ln in r.text.splitlines()
            if ln.strip() and not ln.startswith("#")]
    if not segs:
        raise Fail("播放列表没有分片")
    S["hls_seg"] = segs[0]
    return f"{time.time() - t0:.1f}s {len(segs)} 个分片"


@check("HLS", "首个 ts 分片可取且有数据")
def c50():
    vid = S["hls_id"]
    r = C.get(f"/api/videos/{vid}/hls/{S['hls_seg']}")
    need(r, 200, "seg")
    if len(r.content) < 1000:
        raise Fail(f"分片太小 {len(r.content)}")
    if "mp2t" not in r.headers.get("content-type", ""):
        raise Fail(f"content-type={r.headers.get('content-type')}")
    return f"{len(r.content)} 字节"


@check("HLS", "转码状态接口字段齐全")
def c51():
    d = jget(f"/api/videos/{S['hls_id']}/hlsstatus")
    for k in ("video_id", "status", "percent", "ready", "finished", "error"):
        if k not in d:
            raise Fail(f"缺 {k}：{d}")
    return f"status={d['status']} ready={d['ready']} finished={d['finished']}"


@check("HLS", "关闭转码后回退直放并给出 warning")
def c52():
    jput("/api/settings", {"transcode": False})
    try:
        vid = S["vids"]["c_mkv.mkv"]["id"]
        d = jget(f"/api/videos/{vid}/play")
        if d.get("mode") != "direct" or not d.get("warning"):
            raise Fail(str(d))
    finally:
        jput("/api/settings", {"transcode": True})
    return f"warning={d.get('warning')}"


@check("HLS", "分片名合法性校验（路径穿越 → 404）")
def c53():
    r = C.get(f"/api/videos/{S['hls_id']}/hls/..%2f..%2fconfig.json")
    need(r, 404, "非法分片名")
    return r.json().get("detail", "")


# ---------- 标签
@check("标签", "标签列表结构")
def c54():
    d = jget("/api/tags")
    if "tags" not in d:
        raise Fail(str(d)[:200])
    return f"{len(d['tags'])} 个标签"


@check("标签", "新建标签（名称/颜色/目录）")
def c55():
    for name, color, dirp in (("测试标签A", "#35d18a", ""), ("测试标签B", "#ff8800", "自定义目录B")):
        d = jpost("/api/tags", {"name": name, "color": color, "dir_path": dirp})
        if not d.get("ok"):
            raise Fail(str(d))
        S.setdefault("tags", {})[name] = d["tag"]
    a, b = S["tags"]["测试标签A"], S["tags"]["测试标签B"]
    if a["color"] != "#35d18a" or b["dir_path"] != "自定义目录B":
        raise Fail(f"A={a} B={b}")
    return f"A={a['id']} B={b['id']}"


@check("标签", "重名标签被拒")
def c56():
    r = C.post("/api/tags", json={"name": "测试标签A"})
    need(r, 400, "重名标签")
    return r.json().get("detail", "")[:40]


@check("标签", "修改标签名与颜色")
def c57():
    tid = S["tags"]["测试标签B"]["id"]
    d = jput(f"/api/tags/{tid}", {"name": "测试标签B2", "color": "#123456"})
    if d["tag"]["name"] != "测试标签B2" or d["tag"]["color"] != "#123456":
        raise Fail(str(d))
    jput(f"/api/tags/{tid}", {"name": "测试标签B", "color": "#ff8800"})
    return "改名改色成功（已改回）"


@check("标签", "给视频打标签（POST /tag）")
def c58():
    tid = S["tags"]["测试标签A"]["id"]
    for fn in ("a_direct.mp4", "noaudio.mp4"):
        vid = S["vids"][fn]["id"]
        d = jpost(f"/api/videos/{vid}/tag", {"tag_id": tid})
        if d["tag_id"] != tid or d["status"] != "tagged":
            raise Fail(f"{fn}: {d}")
    return f"2 个视频 → 标签 {tid}"


@check("标签", "PATCH /videos/{id} 同样能改标签")
def c59():
    tid = S["tags"]["测试标签A"]["id"]
    vid = S["vids"]["long30s.mp4"]["id"]
    r = C.patch(f"/api/videos/{vid}", json={"tag_id": tid})
    need(r, 200, "patch tag")
    if r.json()["tag_id"] != tid:
        raise Fail(str(r.json())[:150])
    return "ok"


@check("标签", "标签计数与实际一致")
def c60():
    d = jget("/api/tags")
    a = [t for t in d["tags"] if t["id"] == S["tags"]["测试标签A"]["id"]][0]
    lst = jget(f"/api/videos?tag={a['id']}&limit=500")
    if a["count"] != lst["total"]:
        raise Fail(f"tag.count={a['count']} 列表={lst['total']}")
    S["tagA_count"] = a["count"]
    return f"count={a['count']}"


@check("标签", "多标签并集筛选 tags=1,2")
def c61():
    a = S["tags"]["测试标签A"]["id"]
    vid = S["vids"]["c_mkv.mkv"]["id"]
    b = S["tags"]["测试标签B"]["id"]
    jpost(f"/api/videos/{vid}/tag", {"tag_id": b})
    d = jget(f"/api/videos?tags={a},{b}&limit=500")
    ids = {x["tag_id"] for x in d["items"]}
    if not ids <= {a, b} or len(ids) < 2:
        raise Fail(f"结果标签集合={ids}")
    # 还原：把 b 标签摘掉
    jpost(f"/api/videos/{vid}/tag", {"tag_id": None})
    return f"{d['total']} 条，覆盖 {sorted(ids)}"


@check("标签", "未打标签筛选 tag=none")
def c62():
    d = jget("/api/videos?tag=none&limit=500")
    bad = [x["filename"] for x in d["items"] if x["tag_id"] is not None]
    if bad:
        raise Fail(f"混入有标签的：{bad}")
    return f"{d['total']} 条"


@check("标签", "删除标签会释放视频（released）")
def c63():
    b = S["tags"]["测试标签B"]["id"]
    d = C.delete(f"/api/tags/{b}").json()
    if not d.get("ok") or "released" not in d:
        raise Fail(str(d))
    lst = jget(f"/api/videos?tag={b}")
    if lst["total"] != 0:
        raise Fail(f"删标签后仍有 {lst['total']} 条挂着")
    return f"released={d['released']}"


@check("标签", "给不存在的标签打标 → 404")
def c64():
    vid = S["vids"]["a_direct.mp4"]["id"]
    r = C.post(f"/api/videos/{vid}/tag", json={"tag_id": 999999})
    need(r, 404, "不存在标签")
    return r.json().get("detail", "")


# ---------- 整理
@check("整理", "预览计划（items/groups/total_bytes）")
def c65():
    a = S["tags"]["测试标签A"]["id"]
    d = jpost("/api/organize/preview", {"tag_ids": [a]})
    for k in ("items", "total", "total_bytes", "skipped", "groups"):
        if k not in d:
            raise Fail(f"缺 {k}")
    if d["total"] < 2:
        raise Fail(f"计划里只有 {d['total']} 个")
    S["plan"] = d
    return f"{d['total']} 个 / {d['total_bytes']} 字节 / groups={[(g['tag_name'], g['count']) for g in d['groups']]}"


@check("整理", "预览空标签列表 → 空计划")
def c66():
    d = jpost("/api/organize/preview", {"tag_ids": []})
    return f"total={d['total']}"


@check("整理", "没有可整理视频时执行被拒（400）")
def c67():
    r = C.post("/api/organize/execute", json={"tag_ids": []})
    need(r, 400, "空标签执行")
    return r.json().get("detail", "")[:40]


@check("整理", "执行整理（跨盘 D: 目标）")
def c68():
    shutil.rmtree(CROSS, ignore_errors=True)
    CROSS.mkdir(parents=True, exist_ok=True)
    jput("/api/settings", {"root_dir": str(CROSS)})
    a = S["tags"]["测试标签A"]["id"]
    d = jpost("/api/organize/execute", {"tag_ids": [a]})
    if not d.get("task_id"):
        raise Fail(str(d))
    tid = d["task_id"]
    t0 = time.time()
    while time.time() - t0 < 180:
        t = jget(f"/api/tasks/{tid}")
        if t["status"] != "running":
            break
        time.sleep(0.4)
    if t["status"] != "done":
        raise Fail(f"整理失败：{t.get('error') or t.get('message')}")
    S["org_task"] = t
    return f"{time.time() - t0:.1f}s result={t.get('result')}"


@check("整理", "整理落点采用 root_dir/标签名（全局根目录生效）")
def c69():
    a = S["tags"]["测试标签A"]["id"]
    tag = [t for t in jget("/api/tags")["tags"] if t["id"] == a][0]
    want = CROSS / tag["name"]
    files = sorted(p.name for p in CROSS.rglob("*.mp4")) if CROSS.exists() else []
    if len(files) < 2:
        plan = S.get("plan") or {}
        dirs = sorted({it.get("dir") for it in plan.get("items", [])})
        raise Fail(
            f"{want} 下没有文件（只有 {files}）。实际整理目标 = {dirs}；"
            f"tags.dir_path = {tag.get('dir_path')!r} —— 创建标签时 tags_routes.py:56 "
            f"就把 default_tag_dir() 的结果写死进了 dir_path，而 organizer.resolve_tag_dir "
            f"优先用 dir_path，所以之后在设置里改 root_dir 对已有标签不生效"
        )
    mover = [p for p in CROSS.rglob("*.mp4")]
    if not all(p.parent == want or want in p.parents for p in mover):
        raise Fail(f"没落在 {want}；实际 {[str(p.parent) for p in mover][:3]}")
    S["moved"] = [str(p) for p in mover]
    return f"{want.name} 下 {len(files)} 个文件"


@check("整理", "整理后状态与统计同步（organized）")
def c70():
    d = jget("/api/videos?status=organized&limit=500")
    if d["total"] < 2:
        raise Fail(f"organized={d['total']}")
    st = jget("/api/stats")
    if st["organized"] < 2:
        raise Fail(f"stats.organized={st['organized']}")
    return f"列表 {d['total']} / stats {st['organized']}"


@check("整理", "整理记录可查（批次）")
def c71():
    d = jget("/api/organize/records")
    items = d.get("items") or []
    if not items:
        raise Fail("没有批次记录")
    b = items[0]
    for k in ("id", "created_at", "files", "dirs"):
        if k not in b:
            raise Fail(f"缺 {k}：{b}")
    S["batch"] = b["id"]
    return f"batch={b['id']} files={b['files']}"


@check("整理", "撤销整批 → 文件回原位")
def c72():
    d = jpost(f"/api/organize/undo/{S['batch']}")
    if "restored" not in d:
        raise Fail(str(d))
    if d.get("failed"):
        raise Fail(f"有失败项：{d['failed']}")
    left = list(CROSS.rglob("*.mp4")) if CROSS.exists() else []
    if left:
        raise Fail(f"目标目录还留着 {[p.name for p in left]}")
    back = [p.name for p in MEDIA.rglob("*.mp4")]
    if not any("a_direct" in n for n in back):
        raise Fail(f"源目录没恢复：{back}")
    jput("/api/settings", {"root_dir": ""})
    return f"restored={d['restored']}"


# ---------- 上传
@check("上传", "上传 mp4 入库并落盘")
def c73():
    src = MEDIA / "a_direct.mp4"
    with open(src, "rb") as fh:
        r = C.post("/api/upload", files={"file": ("上传测试.mp4", fh, "video/mp4")},
                   data={"dir": str(UPDIR)})
    need(r, 200, "upload")
    d = r.json()
    if not d.get("ok") or not d["video"]["id"]:
        raise Fail(str(d)[:200])
    p = Path(d["path"])
    if not p.exists() or p.parent != UPDIR:
        raise Fail(f"落盘位置 {p}")
    S["upload_vid"] = d["video"]["id"]
    return f"id={d['video']['id']} → {p.name}"


@check("上传", "不支持的类型被拒（400）")
def c74():
    r = C.post("/api/upload",
               files={"file": ("note.txt", b"hello", "text/plain")},
               data={"dir": str(UPDIR)})
    need(r, 400, "txt 上传")
    return r.json().get("detail", "")[:50]


@check("上传", "同名文件自动加序号不覆盖")
def c75():
    src = MEDIA / "a_direct.mp4"
    with open(src, "rb") as fh:
        d = C.post("/api/upload", files={"file": ("上传测试.mp4", fh, "video/mp4")},
                   data={"dir": str(UPDIR)}).json()
    name = Path(d["path"]).name
    if name == "上传测试.mp4":
        raise Fail(f"同名被覆盖/没加序号：{name}")
    S["upload_vid2"] = d["video"]["id"]
    return name


@check("上传", "上传时直接指定标签")
def c76():
    a = S["tags"]["测试标签A"]["id"]
    src = MEDIA / "noaudio.mp4"
    with open(src, "rb") as fh:
        d = C.post("/api/upload", files={"file": ("带标签上传.mp4", fh, "video/mp4")},
                   data={"dir": str(UPDIR), "tag_id": str(a)}).json()
    if d["video"]["tag_id"] != a:
        raise Fail(str(d["video"])[:200])
    S["upload_vid3"] = d["video"]["id"]
    return f"tag_id={a} status={d['video']['status']}"


@check("上传", "上传后立即可播放（play/raw）")
def c77():
    vid = S["upload_vid"]
    d = jget(f"/api/videos/{vid}/play")
    if d.get("mode") not in ("direct", "hls"):
        raise Fail(str(d))
    r = C.get(f"/api/videos/{vid}/raw")
    need(r, 200, "raw")
    return f"mode={d['mode']} raw={len(r.content)}B"


@check("上传", "上传目录被登记为可扫描源（kind=upload）")
def c78():
    d = jget("/api/sources")
    ups = [s for s in d["sources"] if s.get("kind") == "upload"]
    if not ups:
        raise Fail(f"源里没有 kind=upload 的源：{[(s['path'], s.get('kind')) for s in d['sources']]}")
    up = ups[0]
    if not Path(up["path"]).is_dir():
        raise Fail(f"上传源路径不存在：{up}")
    if up.get("deletable"):
        raise Fail(f"上传源被标成可删除：{up}")
    # 备注：无自定义 upload_dir / root_dir 时，内置上传源落在 <data_dir>\uploads
    # （README 说的「第一条普通源\手机上传」只在 upload_dir 或 root_dir 有值时出现）
    return up["path"]


# ---------- 历史
@check("历史", "保存播放进度")
def c79():
    vid = S["vids"]["long30s.mp4"]["id"]
    d = jpost(f"/api/videos/{vid}/history", {"position": 12.5, "duration": 30})
    if not d.get("ok"):
        raise Fail(str(d))
    S["hist_vid"] = vid
    return "ok"


@check("历史", "历史列表带进度与时间")
def c80():
    d = jget("/api/history?limit=60")
    items = d.get("items") or []
    if not items:
        raise Fail("历史为空")
    hit = [x for x in items if x.get("id") == S["hist_vid"]]
    if not hit:
        raise Fail(f"没找到 {S['hist_vid']}：{[x.get('id') for x in items][:5]}")
    if abs(hit[0]["position"] - 12.5) > 0.01 or not hit[0].get("watched_at"):
        raise Fail(str(hit[0])[:200])
    return f"position={hit[0]['position']} watched_at={hit[0]['watched_at']}"


@check("历史", "同一视频重复保存只留一条")
def c81():
    vid = S["hist_vid"]
    for pos in (13.0, 14.0):
        jpost(f"/api/videos/{vid}/history", {"position": pos, "duration": 30})
    items = jget("/api/history?limit=200")["items"]
    same = [x for x in items if x.get("id") == vid]
    if len(same) != 1:
        raise Fail(f"{len(same)} 条重复")
    if abs(same[0]["position"] - 14.0) > 0.01:
        raise Fail(f"没更新到最新 position={same[0]['position']}")
    return f"1 条，position={same[0]['position']}"


@check("历史", "删除单条历史")
def c82():
    vid = S["upload_vid3"]
    jpost(f"/api/videos/{vid}/history", {"position": 1, "duration": 2})
    d = C.delete(f"/api/history/{vid}").json()
    left = [x for x in jget("/api/history?limit=200")["items"] if x.get("id") == vid]
    if not d.get("ok") or left:
        raise Fail(f"{d} left={left}")
    return "ok"


@check("历史", "清空全部历史")
def c83():
    jpost(f"/api/videos/{S['hist_vid']}/history", {"position": 3, "duration": 30})
    d = C.delete("/api/history").json()
    n = len(jget("/api/history")["items"])
    if not d.get("ok") or n:
        raise Fail(f"清空后还有 {n} 条")
    return f"清空，剩余 {n} 条"


@check("历史", "删视频后历史保留并标 deleted")
def c84():
    vid = S["upload_vid"]
    jpost(f"/api/videos/{vid}/history", {"position": 2, "duration": 3})
    d = C.delete(f"/api/videos/{vid}?file=0").json()
    if not d.get("ok"):
        raise Fail(str(d))
    items = jget("/api/history?limit=200")["items"]
    hit = [x for x in items if x.get("id") == vid]
    if not hit:
        raise Fail("历史记录被一起删了（应保留）")
    if not hit[0].get("deleted") or hit[0].get("status") != "deleted":
        raise Fail(str(hit[0])[:200])
    return f"deleted={hit[0]['deleted']} filename={hit[0]['filename']}"


# ---------- 缓存
@check("缓存", "缓存统计结构")
def c85():
    d = jget("/api/cache")
    for k in ("thumbs", "hls", "total_bytes", "data_dir", "thumb_dir", "hls_dir"):
        if k not in d:
            raise Fail(f"缺 {k}")
    S["cache"] = d
    return f"thumbs={d['thumbs']} hls={d['hls']}"


@check("缓存", "清理缩略图缓存")
def c86():
    before = jget("/api/cache")["thumbs"]["count"]
    d = jpost("/api/cache/clear", {"target": "thumbs"})
    if not d.get("ok"):
        raise Fail(str(d))
    after = jget("/api/cache")["thumbs"]["count"]
    if after != 0:
        raise Fail(f"清理后还剩 {after} 个")
    return f"{before} → {after}，freed={d.get('freed_bytes')}"


@check("缓存", "封面会在再次访问时重建")
def c87():
    vid = S["thumb_id"]
    r = C.get(f"/api/videos/{vid}/thumb")
    need(r, 200, "重建封面")
    if not (DATA / "thumbs" / f"{vid}.jpg").exists():
        raise Fail("没重新落盘")
    return f"{len(r.content)} 字节"


@check("缓存", "清理 HLS 分片")
def c88():
    d = jpost("/api/cache/clear", {"target": "hls"})
    if not d.get("ok"):
        raise Fail(str(d))
    if jget("/api/cache")["hls"]["count"] != 0:
        raise Fail("HLS 目录没清干净")
    return f"freed={d.get('freed_bytes')}"


# ---------- 设置
@check("设置", "设置读取含 12 个键与默认值")
def c89():
    d = jget("/api/settings")
    st, de = d["settings"], d["defaults"]
    if len(de) != 12:
        raise Fail(f"defaults {len(de)} 个：{sorted(de)}")
    if set(st) != set(de):
        raise Fail(f"settings/defaults 键不一致：{set(st) ^ set(de)}")
    S["settings"] = st
    return f"{len(de)} 键"


@check("设置", "修改主题并持久化")
def c90():
    old = jget("/api/settings")["settings"]["theme"]
    d = jput("/api/settings", {"theme": "dark"})
    if d["settings"]["theme"] != "dark":
        raise Fail(str(d)[:150])
    on_disk = json.loads((DATA / "config.json").read_text(encoding="utf-8"))
    if on_disk.get("theme") != "dark":
        raise Fail(f"config.json 没落盘：{on_disk.get('theme')}")
    jput("/api/settings", {"theme": old})
    return f"{old} → dark → {old}"


@check("设置", "非法 host 被静默忽略")
def c91():
    old = jget("/api/settings")["settings"]["host"]
    d = jput("/api/settings", {"host": "10.1.2.3"})
    if d["settings"]["host"] != old:
        raise Fail(f"host 被改了：{d['settings']['host']}")
    return f"host 保持 {old}"


@check("设置", "改端口返回 restart_required")
def c92():
    old = jget("/api/settings")["settings"]["port"]
    d = jput("/api/settings", {"port": 9099})
    if d.get("restart_required") is not True:
        raise Fail(str(d)[:200])
    jput("/api/settings", {"port": old})
    return f"true（已改回 {old}）"


@check("设置", "信息接口 /api/info 字段齐全")
def c93():
    d = jget("/api/info")
    for k in ("version", "data_dir", "platform", "python", "ffmpeg", "ffprobe",
              "media_ready", "root_dir", "upload_dir", "web_dir", "discovery", "discovery_port"):
        if k not in d:
            raise Fail(f"缺 {k}")
    if not d["media_ready"] or not Path(d["ffmpeg"]).exists():
        raise Fail("ffmpeg 未就绪")
    return f"version={d['version']} web_dir={Path(d['web_dir']).name}"


# ---------- APK / 发现
@check("APK 分发", "APK 列表接口（免登录）")
def c94():
    r = C.get("/api/app/apk")
    need(r, 200, "apk 列表")
    d = r.json()
    for k in ("version", "apps", "releases"):
        if k not in d:
            raise Fail(f"缺 {k}")
    return f"apps={len(d['apps'])} version={d['version']}"


@check("APK 分发", "下载不存在的 APK → 404")
def c95():
    r = C.get("/api/app/apk/videosorter-1.0.0-arm64-v8a.apk")
    need(r, 404, "不存在的 apk")
    return r.json().get("detail", "")[:40]


@check("局域网发现", "UDP 38080 回包（VS_DISCOVER）")
def c96():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(3.0)
    try:
        s.sendto(b"VS_DISCOVER", ("127.0.0.1", 38080))
        data, addr = s.recvfrom(2048)
    except socket.timeout:
        raise Fail("3s 内没收到回包（端口没监听？）")
    finally:
        s.close()
    d = json.loads(data.decode("utf-8", "replace"))
    if int(d.get("port", 0)) != PORT:
        raise Fail(f"回包端口不对：{d}")
    return f"{d}"


# ---------- 安全
@check("安全", "静态目录穿越拿不到源码")
def c97():
    r = C.get("/%2e%2e%2f%2e%2e%2fserver%2fvideosorter%2fconfig.py")
    body = r.text[:4000] if r.status_code == 200 else ""
    if "DEFAULTS" in body or "discovery_port" in body:
        raise Fail("泄露了服务端源码")
    return f"{r.status_code}（未泄露）"


@check("安全", "API 路径穿越被拦")
def c98():
    r = C.get("/api/%2e%2e%2f%2e%2e%2fserver%2fvideosorter%2fapp.py")
    if r.status_code == 200 and "FastAPI" in r.text:
        raise Fail("通过 /api/ 拿到了源码")
    return f"{r.status_code} {r.text[:60]}"


# ---------- 凭据管理
@check("凭据管理", "修改用户名并可回退")
def c99():
    d = jpost("/api/auth/username", {"username": "admin2"})
    if not d.get("ok"):
        raise Fail(str(d))
    jpost("/api/auth/logout", None)
    jpost("/api/auth/login", {"username": "admin2", "password": "admin1234"})
    jpost("/api/auth/username", {"username": "admin"})
    jpost("/api/auth/logout", None)
    jpost("/api/auth/login", {"username": "admin", "password": "admin1234"})
    return "admin → admin2 → admin"


@check("凭据管理", "旧密码不对时改密码被拒")
def c100():
    r = C.post("/api/auth/password", json={"old_password": "bad", "new_password": "whatever1"})
    if r.status_code == 200:
        raise Fail("错误旧密码竟然通过了")
    return f"{r.status_code} {r.json().get('detail', '')[:40]}"


@check("凭据管理", "改密码成功且新密码可登录")
def c101():
    d = jpost("/api/auth/password", {"old_password": "admin1234", "new_password": "tmp-pass-9527"})
    if not d.get("ok"):
        raise Fail(str(d))
    try:
        jpost("/api/auth/logout", None)
        jpost("/api/auth/login", {"username": "admin", "password": "tmp-pass-9527"})
    finally:
        jpost("/api/auth/password", {"old_password": "tmp-pass-9527", "new_password": "admin1234"})
        jpost("/api/auth/logout", None)
        jpost("/api/auth/login", {"username": "admin", "password": "admin1234"})
    return "改密→登录→改回 全通"


@check("凭据管理", "revoke-all 让旧 cookie 失效")
def c102():
    old_cookie = C.cookies.get("vs_token")
    jpost("/api/auth/revoke-all", None)
    r = C.get("/api/videos")
    if r.status_code != 401:
        raise Fail(f"撤销后仍可访问：{r.status_code}")
    jpost("/api/auth/login", {"username": "admin", "password": "admin1234"})
    new_cookie = C.cookies.get("vs_token")
    S["cookie_changed"] = old_cookie != new_cookie
    return f"旧 cookie 失效，新 cookie {'已变' if S['cookie_changed'] else '相同（可疑）'}"


# ---------- 视频编辑（重命名 / 取消标签 / 连带删文件）
@check("视频编辑", "重命名（自动补扩展名，文件真的改名）")
def c104():
    vid = S["vids"]["noaudio.mp4"]["id"]
    d = jpost(f"/api/videos/{vid}/rename", {"name": "改名后 的名字"})
    if d.get("filename") != "改名后 的名字.mp4":
        raise Fail(f"文件名={d.get('filename')!r}")
    p = Path(d["path"])
    if not p.exists():
        raise Fail(f"磁盘上没找到 {p}")
    d2 = jpost(f"/api/videos/{vid}/rename", {"name": "noaudio.mp4"})
    if d2.get("filename") != "noaudio.mp4":
        raise Fail(f"改回失败：{d2.get('filename')!r}")
    return "noaudio.mp4 → 改名后 的名字.mp4 → 改回"


@check("视频编辑", "重命名撞名被拒（409）")
def c105():
    a = S["vids"]["a_direct.mp4"]["id"]
    r = C.post(f"/api/videos/{a}/rename", json={"name": "中文 空格 名字.mp4"})
    if r.status_code != 409:
        raise Fail(f"期望 409，实际 {r.status_code} {r.text[:80]}")
    return r.json().get("detail", "")[:50]


@check("视频编辑", "取消标签回到「未打标签」")
def c106():
    vid = S["vids"]["c_mkv.mkv"]["id"]
    tid = jget("/api/tags")["tags"][0]["id"]
    jpost(f"/api/videos/{vid}/tag", {"tag_id": tid})
    d = jpost(f"/api/videos/{vid}/tag", {"tag_id": None})
    if d.get("tag_id") is not None or d.get("status") != "idle":
        raise Fail(f"取消后 tag_id={d.get('tag_id')} status={d.get('status')}")
    return "tag_id=None status=idle"


@check("视频编辑", "删除视频并连带删文件（file=1）")
def c107():
    blob = (MEDIA / "a_direct.mp4").read_bytes()
    d = C.post("/api/upload", files={"file": ("要删的.mp4", blob, "video/mp4")},
               data={"dir": str(UPDIR)}).json()
    vid = d["video"]["id"]
    p = Path(d["path"])
    if not p.exists():
        raise Fail(f"上传后文件不在：{p}")
    r = C.delete(f"/api/videos/{vid}?file=1")
    need(r, 200, "delete file=1")
    j = r.json()
    if not j.get("file_removed"):
        raise Fail(f"file_removed={j.get('file_removed')}")
    if p.exists():
        raise Fail(f"文件还在：{p}")
    if C.get(f"/api/videos/{vid}").status_code != 404:
        raise Fail("记录没删掉")
    return "文件与记录都已清理"


@check("扫描", "文件被删后扫描标记 missing")
def c108():
    def scan_wait() -> dict:
        tid = jpost("/api/scan", {})["task_id"]
        for _ in range(400):
            t = jget(f"/api/tasks/{tid}")
            if t["status"] != "running":
                return t
            time.sleep(0.2)
        raise Fail("扫描一直不结束")

    victim = MEDIA / "会被删掉.mp4"
    shutil.copyfile(MEDIA / "a_direct.mp4", victim)
    scan_wait()
    rows = [v for v in jget("/api/videos?status=all&limit=500")["items"] if v["filename"] == "会被删掉.mp4"]
    if not rows:
        raise Fail("新文件没入库")
    victim.unlink()
    scan_wait()
    names = [v["filename"] for v in jget("/api/videos?status=missing&limit=500")["items"]]
    if "会被删掉.mp4" not in names:
        raise Fail(f"missing 列表里没有它：{names[:5]}")
    return f"missing={len(names)} 条，含会被删掉.mp4"



def c103():
    before = {
        "videos": jget("/api/videos?limit=1")["total"],
        "tags": len(jget("/api/tags")["tags"]),
        "settings": jget("/api/settings")["settings"]["theme"],
        "sources": len(jget("/api/sources")["sources"]),
    }
    stop_server()
    dt = start_server()
    jpost("/api/auth/login", {"username": "admin", "password": "admin1234"})
    after = {
        "videos": jget("/api/videos?limit=1")["total"],
        "tags": len(jget("/api/tags")["tags"]),
        "settings": jget("/api/settings")["settings"]["theme"],
        "sources": len(jget("/api/sources")["sources"]),
    }
    if before != after:
        raise Fail(f"重启前后不一致：{before} → {after}")
    return f"{before}（重启耗时 {dt:.1f}s）"


# ================================================================ 主流程
def main() -> int:
    global INSTALL, PORT, BASE, FFMPEG, FFPROBE, SIDECAR
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8099)
    ap.add_argument("--keep", action="store_true", help="保留临时数据目录")
    ap.add_argument("--install", default=str(INSTALL))
    args = ap.parse_args()

    INSTALL = Path(args.install)
    FFMPEG = INSTALL / "tools" / "ffmpeg.exe"
    FFPROBE = INSTALL / "tools" / "ffprobe.exe"
    SIDECAR = INSTALL / "binaries" / "videosorter-server.exe"
    if not SIDECAR.exists():
        SIDECAR = INSTALL / "binaries" / "videosorter-server" / "videosorter-server.exe"
    PORT = args.port
    BASE = f"http://127.0.0.1:{PORT}"
    C.base_url = BASE

    for p in (SIDECAR, FFMPEG, FFPROBE):
        if not p.exists():
            print(f"[环境] 缺文件：{p}", file=sys.stderr)
            return 2

    if not args.keep:
        shutil.rmtree(TMP, ignore_errors=True)
    TMP.mkdir(parents=True, exist_ok=True)
    kill_stragglers()
    time.sleep(0.6)

    print("准备素材…", flush=True)
    prepare_media()
    print(f"启动 sidecar（端口 {PORT}，数据目录 {DATA}）…", flush=True)
    dt = start_server()
    print(f"起来了（{dt:.1f}s）\n", flush=True)

    fails = 0
    for i, c in enumerate(CHECKS, 1):
        t0 = time.time()
        try:
            detail = c["fn"]()
            c["ok"], c["detail"] = True, str(detail or "")
        except Fail as e:
            c["ok"], c["detail"] = False, f"❌ {e}"
            fails += 1
        except Exception as e:  # noqa: BLE001
            c["ok"] = False
            c["detail"] = f"💥 {type(e).__name__}: {e}"
            fails += 1
            if os.environ.get("VS_TRACE"):
                traceback.print_exc()
        c["ms"] = int((time.time() - t0) * 1000)
        flag = "OK  " if c["ok"] else "FAIL"
        print(f"[{flag}] {i:3d} {c['area']} / {c['name']}  ({c['ms']}ms)  {c['detail'][:110]}",
              flush=True)

    stop_server()

    # 报告
    total = len(CHECKS)
    ok = total - fails
    areas: dict[str, list] = {}
    for c in CHECKS:
        areas.setdefault(c["area"], []).append(c)

    lines = ["# VideoSorter 功能自查报告", "",
             f"- 结果：**{ok}/{total} 通过**，{fails} 项失败",
             f"- 被测二进制：`{SIDECAR}`",
             f"- 数据目录：`{DATA}`（一次性）",
             f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}", ""]
    for area, items in areas.items():
        good = sum(1 for x in items if x["ok"])
        lines.append(f"## {area}（{good}/{len(items)}）")
        lines.append("")
        lines.append("| 结果 | 用例 | 实测 |")
        lines.append("| --- | --- | --- |")
        for x in items:
            mark = "✅" if x["ok"] else "❌"
            det = x["detail"].replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {mark} | {x['name']} | {det[:200]} |")
        lines.append("")
    report_md = TMP / "feature-report.md"
    report_md.write_text("\n".join(lines), encoding="utf-8")
    (TMP / "feature-report.json").write_text(
        json.dumps([{k: v for k, v in c.items() if k != "fn"} for c in CHECKS],
                   ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n===== {ok}/{total} 通过，{fails} 失败 =====")
    print(f"报告：{report_md}")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
