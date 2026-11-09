"""首装默认口令的强制改密提示。

fnOS 应用中心上架自查里没有直接写这条，但审核同学装完就用 admin/admin1234 进去，
几乎必然被判「弱口令」。这里的做法：登录 / me 的响应里带 `must_change_password`，
网页与 App 拿到 true 就弹出不可关闭的改密界面，改完才放行。
"""
from __future__ import annotations


def _login(client, password: str = "admin1234"):
    return client.post("/api/auth/login",
                       json={"username": "admin", "password": password, "remember": False})


def test_fresh_install_requires_password_change(env) -> None:
    r = _login(env["client"])
    assert r.status_code == 200, r.text
    assert r.json()["must_change_password"] is True
    token = r.json()["token"]
    me = env["client"].get("/api/auth/me", headers={"Authorization": "Bearer " + token})
    assert me.json()["must_change_password"] is True


def test_after_change_flag_clears(env) -> None:
    c = env["client"]
    token = _login(c).json()["token"]
    h = {"Authorization": "Bearer " + token}
    r = c.post("/api/auth/password",
               json={"old_password": "admin1234", "new_password": "nas-2026-ok"}, headers=h)
    assert r.status_code == 200, r.text
    # 改完密码会吊销全部令牌，得重新登录
    r2 = _login(c, "nas-2026-ok")
    assert r2.status_code == 200, r2.text
    assert r2.json()["must_change_password"] is False
    # 旧口令不再可用
    assert _login(c).status_code == 401


def test_flag_survives_restart(env) -> None:
    """进程重启后（缓存清空）仍然按数据库里的哈希判断，不能误报。"""
    c, cfg = env["client"], env["cfg"]
    token = _login(c).json()["token"]
    assert c.post("/api/auth/password", headers={"Authorization": "Bearer " + token},
                  json={"old_password": "admin1234", "new_password": "nas-2026-ok"}).status_code == 200

    from videosorter.auth import AuthService
    from videosorter.db import Database
    fresh = AuthService(Database(cfg))
    assert fresh.is_default_password() is False


def test_default_password_detected_for_existing_db(env) -> None:
    """老库升级：没改过密码的照样会被判出来，改过的不会。"""
    from videosorter.auth import DEFAULT_PASSWORD, AuthService, hash_password
    from videosorter.db import Database

    db = Database(env["cfg"])
    svc = AuthService(db)  # 已存在用户，不会重建
    assert svc.is_default_password() is True

    db.execute("UPDATE users SET pass_hash=?", (hash_password(DEFAULT_PASSWORD + "x"),))
    assert AuthService(db).is_default_password() is False
