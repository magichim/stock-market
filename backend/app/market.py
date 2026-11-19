"""장 운영 시간 (KRX, KST 평일 09:00–15:30). 공휴일은 아직 반영하지 않는다."""

from datetime import datetime, time, timedelta, timezone

from .config import settings

# 시각은 항상 UTC로 얻고, 국내 시장 판단만 KST(UTC+9 고정, 서머타임 없음)로 바꾼다 — 서버의 시스템 시간대·tzdata에 의존하지 않는다
KST = timezone(timedelta(hours=9), "KST")
OPEN, CLOSE = time(9, 0), time(15, 30)
# 국내 종목 시세 수집 시간 — NXT(넥스트레이드) 프리마켓 08:00부터 애프터마켓 20:00까지. 거래 가능 시간(OPEN–CLOSE)과는 별개
KR_QUOTE_OPEN, KR_QUOTE_CLOSE = time(8, 0), time(20, 0)


def now_kst() -> datetime:
    return datetime.now(timezone.utc).astimezone(KST)


def is_market_open(now: datetime) -> bool:
    if settings.ignore_market_hours:
        return True
    return now.weekday() < 5 and OPEN <= now.time() < CLOSE


def is_kr_quote_time(now: datetime) -> bool:
    """국내 종목 시세를 수집할 시간인지 (평일 08:00–20:00, NXT 포함). 휴장일은 KIS 게이트웨이가 거른다."""
    if settings.ignore_market_hours:
        return True
    return now.weekday() < 5 and KR_QUOTE_OPEN <= now.time() < KR_QUOTE_CLOSE


def is_after_close(now: datetime) -> bool:
    """장 마감 스냅샷 시점 — ignore_market_hours와 무관하게 실제 마감 기준."""
    return now.weekday() < 5 and now.time() >= CLOSE
