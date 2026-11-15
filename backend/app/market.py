"""장 운영 시간 (KRX, KST 평일 09:00–15:30). 공휴일은 아직 반영하지 않는다."""

from datetime import datetime, time
from zoneinfo import ZoneInfo

from .config import settings

KST = ZoneInfo("Asia/Seoul")
OPEN, CLOSE = time(9, 0), time(15, 30)


def now_kst() -> datetime:
    return datetime.now(KST)


def is_market_open(now: datetime) -> bool:
    if settings.ignore_market_hours:
        return True
    return now.weekday() < 5 and OPEN <= now.time() < CLOSE


def is_after_close(now: datetime) -> bool:
    """장 마감 스냅샷 시점 — ignore_market_hours와 무관하게 실제 마감 기준."""
    return now.weekday() < 5 and now.time() >= CLOSE
