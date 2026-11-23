"""장 운영 시간과 거래 가능 판단 (KST). 국내 장의 수집·거래 규칙은 KR_MARKET.md."""

import logging
import time as clock
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

import httpx

from .config import settings
from .models import Stock
from .seed import MARKET_COUNTRY

log = logging.getLogger(__name__)

# 시각은 항상 UTC로 얻고, 국내 시장 판단만 KST(UTC+9 고정, 서머타임 없음)로 바꾼다 — 서버의 시스템 시간대·tzdata에 의존하지 않는다
KST = timezone(timedelta(hours=9), "KST")
OPEN, CLOSE = time(9, 0), time(15, 30)  # 정규장
# NXT(넥스트레이드) 프리마켓·애프터마켓 — 정규장과 겹치는 메인마켓(09:00–15:20)은 정규장으로 본다
NXT_SESSIONS = ((time(8, 0), time(8, 50)), (CLOSE, time(20, 0)))
# 국내 종목 시세 수집 시간 — NXT 프리마켓 시작부터 애프터마켓 끝까지 (NXT 미거래 종목은 is_kr_stock_quote_time으로 더 거른다)
KR_QUOTE_OPEN, KR_QUOTE_CLOSE = time(8, 0), time(20, 0)

# NXT 거래 종목 여부(stocks.nxt_tradable)를 갱신하기 시작하는 시각 — 프리마켓(08:00) 전에 끝내고, 실패해도 다시 시도할 여유를 둔다
NXT_REFRESH_OPEN = time(6, 0)
CLOSE_SETTLE = timedelta(minutes=10)  # 정규장 마감 뒤 종가가 확정됐다고 보는 여유

Session = Literal["regular", "nxt"]

# 국내 개장일 캐시 {날짜: 개장 여부} — 워커마다 하루 한 번 게이트웨이에 묻는다. 실패하면 1분 뒤 다시 묻는다
_trading_days: dict[date, bool] = {}
_retry_at = 0.0


def now_kst() -> datetime:
    return datetime.now(timezone.utc).astimezone(KST)


def is_market_open(now: datetime) -> bool:
    """정규장 시간표만 본다 (휴장일 미반영) — 해외 종목의 수집·거래 시간으로 쓴다."""
    if settings.ignore_market_hours:
        return True
    return now.weekday() < 5 and OPEN <= now.time() < CLOSE


def is_kr_quote_time(now: datetime) -> bool:
    """국내 종목 시세를 수집할 시간인지 (평일 08:00–20:00, NXT 포함). 휴장일은 KIS 게이트웨이가 거른다."""
    if settings.ignore_market_hours:
        return True
    return now.weekday() < 5 and KR_QUOTE_OPEN <= now.time() < KR_QUOTE_CLOSE


def is_nxt_refresh_time(now: datetime) -> bool:
    """NXT 거래 종목 여부를 갱신할 시간인지 (평일 06:00부터 수집이 끝나는 20:00까지 — 하루 한 번은 호출하는 쪽이 지킨다)."""
    if settings.ignore_market_hours:
        return True
    return now.weekday() < 5 and NXT_REFRESH_OPEN <= now.time() < KR_QUOTE_CLOSE


def is_kr_stock_quote_time(stock: Stock, now: datetime) -> bool:
    """수집 시간(is_kr_quote_time) 안에서 이 국내 종목을 수집할지.

    NXT 거래 종목은 내내, 그 밖은 정규장과 마감 뒤 종가를 받을 때까지만 — 프리·애프터마켓에는 값이 바뀌지 않는다.
    종가는 마감 CLOSE_SETTLE 뒤에 수집한 값이어야 확정된 것으로 본다 (15:30 정각 수집은 종가 반영 전일 수 있다).
    """
    if settings.ignore_market_hours or stock.nxt_tradable or OPEN <= now.time() < CLOSE:
        return True
    close = now.replace(hour=CLOSE.hour, minute=CLOSE.minute, second=0, microsecond=0)
    return now >= close and (stock.last_price_at is None or stock.last_price_at < close + CLOSE_SETTLE)


def is_after_close(now: datetime) -> bool:
    """장 마감 스냅샷 시점 — ignore_market_hours와 무관하게 실제 마감 기준."""
    return now.weekday() < 5 and now.time() >= CLOSE


async def is_kr_trading_day(day: date) -> bool:
    """국내 개장일인지 — 주말이 아니고 KIS 휴장일도 아닌 날. 확인하지 못하면 휴장으로 본다 (mock 공급자는 평일이면 개장)."""
    global _retry_at
    if day.weekday() >= 5:
        return False
    if settings.price_provider != "kis":
        return True
    if day not in _trading_days:
        if clock.monotonic() < _retry_at:
            return False
        try:
            async with httpx.AsyncClient(base_url=settings.kis_api_url, timeout=10) as client:
                res = await client.get("/quotes/trading-day", params={"day": day.strftime("%Y%m%d")})
            res.raise_for_status()
            _trading_days[day] = res.json()["trading"]
        except Exception:
            log.exception("kis trading-day check failed")
            _retry_at = clock.monotonic() + 60
            return False
    return _trading_days[day]


async def kr_session(now: datetime) -> Session | None:
    """지금 국내 장 구간 — 정규장 / NXT(프리·애프터마켓) / 닫힘(None). 휴장일이면 닫힘."""
    if settings.ignore_market_hours:
        return "regular"
    t = now.time()
    session: Session | None = (
        "regular" if OPEN <= t < CLOSE else "nxt" if any(start <= t < end for start, end in NXT_SESSIONS) else None
    )
    return session if session and await is_kr_trading_day(now.date()) else None


def is_tradable(stock: Stock, now: datetime, session: Session | None) -> bool:
    """session은 kr_session(now). 국내 종목은 정규장이면 모두, NXT 구간이면 NXT 거래 종목만. 해외 종목은 정규장 시간표."""
    if MARKET_COUNTRY[stock.market] != "KR":
        return is_market_open(now)
    return session == "regular" or (session == "nxt" and stock.nxt_tradable)
