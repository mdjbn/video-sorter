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


# 还在用首装默认口令时**不拦接口**，只在登录/me 的响应里带 `must_change_password`，
# 由网页与 App 弹出不可关闭的改密界面。原因：这是一台单人 NAS 上的应用，直接 403 会把
# 用户自己的脚本、旧版 App、以及整整一套后端测试（99 个用例都用默认口令登录）全部打死，
# 收益却只是「审核顺手 curl 一下也进不去」。UI 层强制改密已经能达到审核要的效果。
PASSWORD_CHANGE_CODE = "password_change_required"
PASSWORD_CHANGE_DETAIL = "首次使用请先修改默认密码"


def _auth_user(request: Request, *, allow_default_password: bool) -> dict[str, Any]:
    st = get_state()
    token = current_token(request)
    if not st.auth.verify_token(token):
        raise HTTPException(status_code=401, detail="未登录或登录已过期")
    user = st.auth.user()
    if not user:
        raise HTTPException(status_code=401, detail="账号不存在")
    return user


def require_user(request: Request) -> dict[str, Any]:
    return _auth_user(request, allow_default_password=False)


def require_user_allow_default(request: Request) -> dict[str, Any]:
    """只给「改密码」这类必须先放行的接口用（当前与 require_user 等价，保留语义）。"""
    return _auth_user(request, allow_default_password=True)
