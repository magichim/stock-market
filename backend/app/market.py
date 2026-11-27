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

# 그날 개장일 확인과 NXT 거래 종목 여부(stocks.nxt_tradable) 갱신을 시작하는 시각 — 프리마켓(08:00) 전에 끝내고, 실패해도 다시 시도할 여유를 둔다
KR_PREPARE_OPEN = time(4, 0)
# 국내 종목의 종가(stock_closes)를 기록하는 시각 — 정규장 마감 시각, 수집 주기와 별개로 하루 한 번
CLOSE_PRICE_AT = time(15, 30)
# 수집 회차·종가 기록을 실제로 실행하는 지연 — APP_ENV=dev면 30초. 판단(시간표·날짜)은 원래 시각으로 한다
SCHEDULE_DELAY = timedelta(seconds=30 if settings.app_env == "dev" else 0)

Session = Literal["regular", "nxt"]

# 국내 개장일 캐시 {날짜: 개장 여부} — 워커마다 하루 한 번 게이트웨이에 묻는다. 실패하면 1분 뒤 다시 묻는다
_trading_days: dict[date, bool] = {}
_retry_at = 0.0


def now_kst() -> datetime:
    return datetime.now(timezone.utc).astimezone(KST)


def next_collect_at(after: datetime, interval: int) -> datetime:
    """after(KST) 다음 수집 회차 — KST 자정부터 interval초 간격 (interval=1200이면 매시 00·20·40분)."""
    midnight = datetime.combine(after.date(), time(), KST)
    return midnight + timedelta(seconds=((after - midnight).total_seconds() // interval + 1) * interval)


def is_collect_tick(t: time, interval: int) -> bool:
    """t(KST 시각)가 수집 회차와 겹치는지 — next_collect_at과 같은 기준."""
    return (t.hour * 3600 + t.minute * 60 + t.second) % interval == 0


def is_market_open(now: datetime) -> bool:
    """정규장 시간표만 본다 (휴장일 미반영) — 해외 종목의 수집·거래 시간으로 쓴다."""
    if settings.ignore_market_hours:
        return True
    return now.weekday() < 5 and OPEN <= now.time() < CLOSE


def is_kr_quote_time(now: datetime) -> bool:
    """국내 종목 시세를 수집할 시간인지 (평일 08:00–20:00, NXT 포함 — 애프터마켓 마감 20:00 회차까지). 휴장일은 is_kr_collect_day로 따로 거른다."""
    if settings.ignore_market_hours:
        return True
    return now.weekday() < 5 and KR_QUOTE_OPEN <= now.time() <= KR_QUOTE_CLOSE


def is_kr_prepare_time(now: datetime) -> bool:
    """개장일 확인·NXT 거래 종목 여부 갱신을 할 시간인지 (평일 04:00부터 수집이 끝나는 20:00까지)."""
    if settings.ignore_market_hours:
        return True
    return now.weekday() < 5 and KR_PREPARE_OPEN <= now.time() < KR_QUOTE_CLOSE


async def is_kr_collect_day(now: datetime) -> bool:
    """수집기가 오늘 국내 종목을 다룰지 — 개장일일 때만 (확인 결과는 워커 메모리에 그날 하루 남는다)."""
    return settings.ignore_market_hours or await is_kr_trading_day(now.date())


def is_kr_stock_quote_time(stock: Stock, now: datetime) -> bool:
    """수집 시간(is_kr_quote_time) 안에서 이 국내 종목을 수집할지.

    NXT 거래 종목은 내내, 그 밖은 정규장(09:00–15:30, 15:30 회차 포함)에만 — 프리·애프터마켓에는 값이 바뀌지 않는다.
    수집 주기와 무관하게 시간표로만 정한다. 그날 종가는 CLOSE_PRICE_AT에 stock_closes로 따로 기록한다.
    """
    return settings.ignore_market_hours or stock.nxt_tradable or OPEN <= now.time() <= CLOSE


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
