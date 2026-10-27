"""封面必须是视频的第一帧（旧规则是取 15% 处）。"""
from __future__ import annotations

import subprocess
import shutil
from pathlib import Path

import pytest

from conftest import make_video


def _raw(exe: str, src: str, at: float | None) -> bytes:
    """把源视频的某一帧或封面图缩成 40x24 RGB 原始字节。"""
    cmd = [exe, "-hide_banner", "-loglevel", "error", "-y"]
    if at is not None:
        cmd += ["-ss", f"{at:.2f}"]
    cmd += ["-i", src, "-frames:v", "1", "-vf", "scale=40:24", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    return subprocess.run(cmd, check=True, capture_output=True).stdout


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="需要 ffmpeg")
def test_thumb_is_first_frame(env):
    client, cfg = env["client"], env["cfg"]
    # 用随时间变化的测试图案（testsrc2）：第一帧与 15% 处的画面差异明显
    src = Path(env["src"]) / "首帧封面.mp4"
    subprocess.run([shutil.which("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25",
                    "-f", "lavfi", "-i", "sine=frequency=440", "-t", "8",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(src)], check=True)

    client.post("/api/auth/login", json={"username": "admin", "password": "admin1234", "remember": True})
    client.post("/api/sources", json={"path": str(env["src"])})
    tid = client.post("/api/scan", json={}).json()["task_id"]
    for _ in range(120):
        t = client.get(f"/api/tasks/{tid}").json()
        if t["status"] != "running":
            assert t["status"] == "done", t
            break
    vid = next(v["id"] for v in client.get("/api/videos?limit=50").json()["items"]
               if v["filename"] == "首帧封面.mp4")

    thumb = client.get(f"/api/videos/{vid}/thumb")
    assert thumb.status_code == 200 and len(thumb.content) > 500
    thumb_file = Path(env["data"]) / "probe_thumb.jpg"
    thumb_file.write_bytes(thumb.content)

    exe = shutil.which("ffmpeg")
    got = _raw(exe, str(thumb_file), None)
    first = _raw(exe, str(src), 0.0)
    mid = _raw(exe, str(src), 1.2)

    def dist(a: bytes, b: bytes) -> float:
        return sum(abs(x - y) for x, y in zip(a, b)) / max(1, len(a))

    assert dist(got, first) < dist(got, mid), (dist(got, first), dist(got, mid))
