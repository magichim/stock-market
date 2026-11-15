"""수익률 리더보드 (DB_DESIGN.md "리더보드 계산"). 실시간은 수집 직후 Redis ZSET에 캐시한다.

순위는 이 서비스 DB에서 user_id로 매기고, 표시 정보는 predict-market 내부 API에서 받아 합친다 (with_users).
"""

import logging
from datetime import date

import httpx

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .users import fetch_users

log = logging.getLogger(__name__)

REALTIME_KEY = "stock:lb:realtime"
FAR_PAST, FAR_FUTURE = date(1970, 1, 1), date(9999, 12, 31)

# 계좌 평가액 V = 현금 + Σ 보유수량 × 최신가
ACCOUNT_VALUES = """
account_values AS (
    SELECT a.id, a.user_id, a.event_id, a.initial_cash,
           a.cash + COALESCE(SUM(h.quantity * s.last_price), 0) AS value
    FROM accounts a
    LEFT JOIN holdings h ON h.account_id = a.id
    LEFT JOIN stocks s ON s.id = h.stock_id
    GROUP BY a.id
)"""

# 구간 [start, end) 수익률 = 끝 평가액 / 기준 평가액 - 1
#  기준: start 전 마지막 스냅샷, 없으면 initial_cash (구간 중 가입 · 이벤트)
#  끝: 진행 중(ongoing)이면 현재 평가액, 끝났으면 end 전 마지막 스냅샷
# end 전에 거래가 한 번이라도 있던 계좌만 순위에 든다
RANKING_SQL = text(f"""
WITH {ACCOUNT_VALUES}
SELECT v.user_id,
       (CASE WHEN CAST(:ongoing AS BOOLEAN) THEN v.value ELSE COALESCE(last_in.total_value, v.value) END)
         / COALESCE(base.total_value, v.initial_cash) - 1 AS return_rate
FROM account_values v
LEFT JOIN LATERAL (
    SELECT total_value FROM equity_snapshots e
    WHERE e.account_id = v.id AND e.snapshot_date < :start ORDER BY e.snapshot_date DESC LIMIT 1
) base ON true
LEFT JOIN LATERAL (
    SELECT total_value FROM equity_snapshots e
    WHERE e.account_id = v.id AND e.snapshot_date < :end ORDER BY e.snapshot_date DESC LIMIT 1
) last_in ON true
WHERE v.event_id IS NOT DISTINCT FROM CAST(:event_id AS BIGINT)
  AND EXISTS (
    SELECT 1 FROM trades t
    WHERE t.account_id = v.id AND t.executed_at < (CAST(:end AS DATE)::timestamp AT TIME ZONE 'Asia/Seoul')
  )
ORDER BY return_rate DESC, v.user_id
LIMIT :limit
""")


async def ranking(
    session: AsyncSession, *, start: date, end: date, ongoing: bool, event_id: int | None = None, limit: int = 100
) -> list[tuple[int, float]]:
    """(user_id, 수익률) 내림차순."""
    params = {"start": start, "end": end, "ongoing": ongoing, "event_id": event_id, "limit": limit}
    return [(uid, float(rate)) for uid, rate in await session.execute(RANKING_SQL, params)]


async def refresh_realtime(session: AsyncSession, redis: Redis) -> None:
    """기본 계좌 누적 수익률을 임시 키에 만들어 RENAME으로 원자 교체한다."""
    rows = await ranking(session, start=FAR_PAST, end=FAR_FUTURE, ongoing=True, limit=1_000_000)
    tmp = REALTIME_KEY + ":tmp"
    async with redis.pipeline(transaction=True) as pipe:
        pipe.delete(tmp)
        if rows:
            pipe.zadd(tmp, {str(uid): rate for uid, rate in rows})
            pipe.rename(tmp, REALTIME_KEY)
        else:
            pipe.delete(REALTIME_KEY)
        await pipe.execute()


async def realtime_ranking(session: AsyncSession, redis: Redis, limit: int) -> list[tuple[int, float]]:
    if not await redis.exists(REALTIME_KEY):
        await refresh_realtime(session, redis)
    return [(int(uid), score) for uid, score in await redis.zrevrange(REALTIME_KEY, 0, limit - 1, withscores=True)]


async def with_users(rows: list[tuple[int, float]]) -> list[dict]:
    """predict-market 프로필을 붙인다. 봇·게스트·admin(ranked=false)과 아직 정리되지 않은 탈퇴 사용자는 뺀다.

    프로필 API가 실패하면 순위는 그대로 두고 이름만 비워 내린다.
    """
    try:
        users = await fetch_users([uid for uid, _ in rows])
    except httpx.HTTPError:
        log.exception("user profile lookup failed")
        users = None
    result = []
    for uid, rate in rows:
        u = users.get(uid) if users is not None else {}
        if u is None or u.get("ranked") is False:
            continue
        result.append(
            {
                "username": u.get("username"),
                "display_name": u.get("display_name"),
                "avatar_url": u.get("avatar_url"),
                "return_rate": rate,
            }
        )
    return result
