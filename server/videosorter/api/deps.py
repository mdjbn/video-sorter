"""FastAPI 依赖：认证、分页参数。"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request

from ..state import get_state


def current_token(request: Request) -> str | None:
    token = request.cookies.get("vs_token")
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        token = header[7:].strip()
    return token


def require_user(request: Request) -> dict[str, Any]:
    st = get_state()
    token = current_token(request)
    if not st.auth.verify_token(token):
        raise HTTPException(status_code=401, detail="未登录或登录已过期")
    user = st.auth.user()
    if not user:
        raise HTTPException(status_code=401, detail="账号不存在")
    return user
