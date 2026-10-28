"""单用户认证：PBKDF2 口令散列 + 服务端签发的随机令牌。

网页端用 HttpOnly Cookie，手机端用 Authorization: Bearer <token>，两者共用一张表。
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Any

from .db import Database, now_iso

ITERATIONS = 200_000
TOKEN_BYTES = 32


def hash_password(password: str, *, salt: bytes | None = None, iterations: int = ITERATIONS) -> str:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${dk.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = hashed.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iters)
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


class AuthService:
    def __init__(self, db: Database, username: str = "admin", password: str = "admin1234"):
        self.db = db
        self.ensure_user(username, password)

    def ensure_user(self, username: str, password: str) -> None:
        row = self.db.query_one("SELECT id FROM users LIMIT 1")
        if row is None:
            self.db.execute(
                "INSERT INTO users (username, pass_hash, created_at) VALUES (?,?,?)",
                (username, hash_password(password), now_iso()),
            )

    # ---------- 用户 ----------
    def user(self) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT id, username, created_at FROM users LIMIT 1")
        return dict(row) if row else None

    def check_credentials(self, username: str, password: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM users WHERE username=?", (username,))
        if row and verify_password(password, row["pass_hash"]):
            return {"id": row["id"], "username": row["username"]}
        return None

    def change_password(self, old_password: str, new_password: str) -> tuple[bool, str]:
        row = self.db.query_one("SELECT * FROM users LIMIT 1")
        if not row:
            return False, "账号不存在"
        if not verify_password(old_password, row["pass_hash"]):
            return False, "当前密码不正确"
        if len(new_password) < 6:
            return False, "新密码至少 6 位"
        self.db.execute("UPDATE users SET pass_hash=? WHERE id=?", (hash_password(new_password), row["id"]))
        self.revoke_all()
        return True, "密码已更新，请重新登录"

    def rename_user(self, new_name: str) -> tuple[bool, str]:
        new_name = new_name.strip()
        if len(new_name) < 2:
            return False, "用户名至少 2 个字符"
        row = self.db.query_one("SELECT id FROM users LIMIT 1")
        if not row:
            return False, "账号不存在"
        self.db.execute("UPDATE users SET username=? WHERE id=?", (new_name, row["id"]))
        return True, "用户名已更新"

    # ---------- 令牌 ----------
    def issue_token(self, user_id: int) -> str:
        token = secrets.token_urlsafe(TOKEN_BYTES)
        self.db.execute(
            "INSERT INTO tokens (token, user_id, created_at, last_used_at) VALUES (?,?,?,?)",
            (token, user_id, now_iso(), now_iso()),
        )
        return token

    def verify_token(self, token: str | None) -> bool:
        if not token:
            return False
        row = self.db.query_one("SELECT user_id FROM tokens WHERE token=?", (token,))
        if not row:
            return False
        self.db.execute("UPDATE tokens SET last_used_at=? WHERE token=?", (now_iso(), token))
        return True

    def revoke(self, token: str) -> None:
        self.db.execute("DELETE FROM tokens WHERE token=?", (token,))

    def revoke_all(self) -> None:
        self.db.execute("DELETE FROM tokens")

    def sessions(self, current: str | None = None) -> list[dict[str, Any]]:
        return [
            {"token": r["token"][:8] + "…", "created_at": r["created_at"],
             "last_used_at": r["last_used_at"],
             "current": bool(current) and r["token"] == current}
            for r in self.db.query("SELECT * FROM tokens ORDER BY created_at DESC")
        ]
