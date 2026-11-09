from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse

from .auth import CurrentUser, get_optional_user

app = FastAPI(title="AGISAJA Stock")


@app.get("/api/me")
def me(user: CurrentUser | None = Depends(get_optional_user)) -> dict:
    return {"user": user}


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
