from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Query, Request

from ..db import SessionLocal
from ..leaderboard import FAR_PAST, ranking, realtime_ranking, with_users
from ..market import now_kst
from .trading import find_event

router = APIRouter(prefix="/api")


@router.get("/leaderboard")
async def leaderboard(
    request: Request,
    period: Literal["realtime", "month", "year"] = "realtime",
    year: int | None = Query(None, ge=2000, le=2100),
    month: int | None = Query(None, ge=1, le=12),
    event: str | None = None,
    limit: int = Query(50, ge=1, le=100),
) -> list[dict]:
    """수익률 순위 — 비로그인도 볼 수 있다. event를 주면 period를 무시하고 그 이벤트 계좌로 매긴다.

    realtime: 기본 계좌 누적 수익률 (Redis 캐시, 수집 주기마다 갱신)
    month/year: 그 구간 수익률 (KST, 기본은 이번 달/올해)
    """
    today = now_kst().date()
    async with SessionLocal() as session:
        if event:
            ev = await find_event(session, event)
            rows = await ranking(
                session, start=FAR_PAST, end=ev.end_date + timedelta(days=1),
                ongoing=today <= ev.end_date, event_id=ev.id, limit=limit,
            )
        elif period == "realtime":
            rows = await realtime_ranking(session, request.app.state.redis, limit)
        else:
            y = year or today.year
            if period == "year":
                start, end = date(y, 1, 1), date(y + 1, 1, 1)
            else:
                m = month or today.month
                start = date(y, m, 1)
                end = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
            rows = await ranking(session, start=start, end=end, ongoing=today < end, limit=limit)
    return await with_users(rows)
