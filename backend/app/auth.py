"""agisaja.com이 발급한 access 쿠키를 검증한다. 로그인·refresh·로그아웃은 agisaja.com 서버만 처리한다 (AUTH.md)."""

import jwt
from fastapi import HTTPException, Request
from pydantic import BaseModel

from .config import settings

SESSION_FLAG_COOKIE = "has_session"


class CurrentUser(BaseModel):
    id: int
    username: str


def _decode_access(token: str) -> CurrentUser | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        if payload.get("typ") != "access":
            return None
        return CurrentUser(id=int(payload["sub"]), username=payload["username"])
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        return None


def get_optional_user(request: Request) -> CurrentUser | None:
    """로그인 사용자, 비로그인이면 None.

    access가 없거나 만료됐는데 has_session이 있으면 세션은 살아 있는 것 — 비로그인으로 응답하지 않고
    401을 내 프론트가 agisaja.com에서 refresh하도록 한다.
    """
    user = _decode_access(request.cookies.get(settings.access_cookie, ""))
    if user is None and SESSION_FLAG_COOKIE in request.cookies:
        raise HTTPException(401, "access token expired")
    return user
