from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from ..state import get_state
from .deps import current_token, require_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str = ""
    password: str = ""
    remember: bool = True


class PasswordIn(BaseModel):
    old_password: str
    new_password: str


class UsernameIn(BaseModel):
    username: str


@router.post("/login")
def login(body: LoginIn, response: Response) -> dict[str, Any]:
    st = get_state()
    user = st.auth.check_credentials(body.username.strip(), body.password)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码不正确")
    token = st.auth.issue_token(int(user["id"]))
    max_age = 7 * 24 * 3600 if body.remember else None
    response.set_cookie("vs_token", token, httponly=True, samesite="lax", max_age=max_age, path="/")
    return {"ok": True, "token": token, "user": user,
            "expires_in": max_age or 0, "remember": body.remember}


@router.post("/logout")
def logout(request: Request, response: Response) -> dict[str, Any]:
    st = get_state()
    token = current_token(request)
    if token:
        st.auth.revoke(token)
    response.delete_cookie("vs_token", path="/")
    return {"ok": True}


@router.get("/me")
def me(request: Request, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    st = get_state()
    return {"user": user, "sessions": st.auth.sessions(current_token(request)),
            "version": st.cfg.version}


@router.post("/password")
def change_password(body: PasswordIn, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    st = get_state()
    ok, msg = st.auth.change_password(body.old_password, body.new_password)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "message": msg}


@router.post("/username")
def change_username(body: UsernameIn, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    st = get_state()
    ok, msg = st.auth.rename_user(body.username)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "message": msg, "user": st.auth.user()}


@router.get("/sessions")
def sessions(request: Request, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    st = get_state()
    return {"sessions": st.auth.sessions(current_token(request))}


@router.post("/revoke-all")
def revoke_all(response: Response, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    st = get_state()
    st.auth.revoke_all()
    response.delete_cookie("vs_token", path="/")
    return {"ok": True, "message": "已退出所有设备"}
