"""KIS 게이트웨이 — vendor 샘플 함수를 /api/{카테고리}/{API명}으로 노출한다.

/        모니터링 페이지        /meta/status  상태 JSON
/apis    API 목록 페이지        /meta/apis    목록 JSON
/quotes  수집기용 묶음 조회 (quotes.py)
"""

import os
import time
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import quotes, vendor
from .config import settings

STATIC = Path(__file__).parent / "static"
STARTED = time.time()
VENDOR_VERSION = vendor.vendor_version()

app = FastAPI(title="KIS gateway")
app.include_router(quotes.router)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.exception_handler(vendor.KisError)
async def kis_error(_: Request, e: vendor.KisError) -> JSONResponse:
    return JSONResponse({"detail": e.message}, status_code=e.status)


@app.get("/api/{category}/{name}")
def call_get(category: str, name: str, request: Request) -> dict:
    key = f"{category}/{name}"
    if key in vendor.APIS and vendor.APIS[key].kind == "order":
        raise vendor.KisError(405, "주문 API는 POST(JSON)로 호출한다")
    return vendor.call(key, dict(request.query_params))


@app.post("/api/{category}/{name}")
def call_post(category: str, name: str, args: dict, request: Request) -> dict:
    """JSON 본문만 받는다 — 다른 사이트의 폼 전송으로는 호출할 수 없다 (CSRF)."""
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).netloc != request.headers.get("host"):
        raise vendor.KisError(403, "허용되지 않은 Origin")
    return vendor.call(f"{category}/{name}", args)


@app.get("/meta/status")
def status() -> dict:
    kinds = [a.kind for a in vendor.APIS.values()]
    return {
        "pid": os.getpid(),
        "uptime_seconds": round(time.time() - STARTED),
        "env": settings.kis_env,
        "allow_order": settings.kis_allow_order,
        "configured": settings.configured,
        "token_expires_at": vendor.token_expires_at(),
        "vendor_version": VENDOR_VERSION,
        "apis": {k: kinds.count(k) for k in ("rest", "order", "websocket")},
        "calls": vendor.totals,
        "upstream": vendor.upstream,
        "recent": list(vendor.recent),
    }


@app.get("/meta/apis")
def apis() -> list[dict]:
    return vendor.catalog()


@app.get("/", include_in_schema=False)
def monitor_page() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/apis", include_in_schema=False)
def apis_page() -> FileResponse:
    return FileResponse(STATIC / "apis.html")
