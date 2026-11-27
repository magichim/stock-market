import asyncio
import logging
import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/indices")

# 메인 화면 주요 지수 — Yahoo Finance 공개 차트 API(키 없음, 비공식). (Yahoo 심볼, 표시 이름)
INDICES = [
    ("^KS11", "코스피"),
    ("^KQ11", "코스닥"),
    ("^DJI", "다우존스"),
    ("^IXIC", "나스닥"),
    ("KRW=X", "원/달러 환율"),
]
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{}"
CACHE_SECONDS = 60

client = httpx.AsyncClient(timeout=10, headers={"User-Agent": "Mozilla/5.0"})
_cache: tuple[float, list[dict]] | None = None


async def _quote(symbol: str, name: str) -> dict:
    """현재값·전일 종가. 실패하면 둘 다 None.

    전일 종가는 최근 5일 일봉에서 현재값 거래일(거래소 시간대)보다 앞선 마지막 종가 — meta의 chartPreviousClose는 날짜가 어긋날 때가 있다.
    """
    try:
        res = await client.get(CHART_URL.format(symbol), params={"range": "5d", "interval": "1d"})
        res.raise_for_status()
        chart = res.json()["chart"]["result"][0]
        meta = chart["meta"]
        day = lambda ts: datetime.fromtimestamp(ts + meta["gmtoffset"], timezone.utc).date()  # noqa: E731
        today = day(meta["regularMarketTime"])
        closes = zip(chart["timestamp"], chart["indicators"]["quote"][0]["close"])
        prev = [c for t, c in closes if c is not None and day(t) < today]
        return {"name": name, "price": meta["regularMarketPrice"], "prev_close": prev[-1] if prev else None}
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
        log.warning("index quote failed: %s", symbol, exc_info=True)
        return {"name": name, "price": None, "prev_close": None}


@router.get("")
async def indices() -> list[dict]:
    """주요 지수·환율 — 워커별로 60초 캐시한다."""
    global _cache
    if _cache and time.monotonic() - _cache[0] < CACHE_SECONDS:
        return _cache[1]
    data = list(await asyncio.gather(*(_quote(s, n) for s, n in INDICES)))
    _cache = (time.monotonic(), data)
    return data
