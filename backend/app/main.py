import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import redis.asyncio as aioredis
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text

from .auth import CurrentUser, get_optional_user, origin_allowed
from .config import settings
from .db import Base, apply_schema_patches, engine, ensure_database
from .prices import run_close_recorder, run_collector
from .routers.leaderboard import router as leaderboard_router
from .routers.stocks import router as stocks_router
from .routers.trading import router as trading_router
from .seed import seed_stocks
from .users import client as users_client
from .users import fetch_users

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await ensure_database()
    async with engine.begin() as conn:
        # 워커 여러 개가 동시에 스키마를 바꾸지 않도록 직렬화
        await conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('stock-market-schema'))"))
        await conn.run_sync(Base.metadata.create_all)
        await apply_schema_patches(conn)
        await seed_stocks(conn)
    app.state.redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    tasks = [asyncio.create_task(job(app.state.redis)) for job in (run_collector, run_close_recorder)]
    yield
    for task in tasks:
        task.cancel()
    await app.state.redis.aclose()
    await engine.dispose()
    await users_client.aclose()


app = FastAPI(title="AGISAJA Stock", lifespan=lifespan)


@app.middleware("http")
async def reject_cross_site_writes(request: Request, call_next):
    """인증이 쿠키로 자동 전송되므로, 다른 사이트에서 보낸 상태 변경 요청(CSRF)은 막는다."""
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.url.path.startswith("/api/") and not origin_allowed(request):
        return JSONResponse({"detail": "cross-site request blocked"}, status_code=403)
    return await call_next(request)


@app.get("/api/me")
async def me(user: CurrentUser | None = Depends(get_optional_user)) -> dict:
    """로그인 사용자 — JWT의 id·username에 predict-market 프로필(닉네임·아바타)을 붙인다.

    프로필 조회가 실패해도 로그인 상태는 유지한다 (JWT 값만 내린다).
    """
    if user is None:
        return {"user": None}
    try:
        profile = (await fetch_users([user.id])).get(user.id, {})
    except httpx.HTTPError:
        log.exception("profile lookup failed")
        profile = {}
    return {
        "user": {
            "id": user.id,
            "username": profile.get("username", user.username),
            "display_name": profile.get("display_name"),
            "avatar_url": profile.get("avatar_url"),
        }
    }


app.include_router(stocks_router)
app.include_router(trading_router)
app.include_router(leaderboard_router)


# --- 프로덕션 SPA 서빙 — nginx가 모든 요청을 이 앱으로 넘기고, frontend/dist가 있으면 정적 파일도 여기서 응답한다.
# dev에서는 dist가 없으면 등록되지 않고 vite dev 서버(5273)가 페이지를 낸다. API 라우트는 이 위에 둔다.
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

if FRONTEND_DIST.is_dir():

    @app.get("/{path:path}", include_in_schema=False)
    def spa_fallback(path: str) -> FileResponse:
        """빌드 산출물 파일이면 그대로, 나머지 경로는 index.html로 응답한다. 없는 /api 경로는 404."""
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404)
        file = (FRONTEND_DIST / path).resolve()
        if path and file.is_file() and file.is_relative_to(FRONTEND_DIST):
            return FileResponse(file)
        return FileResponse(FRONTEND_DIST / "index.html")
