"""가격 수집기 — 장 운영 중 PRICE_INTERVAL_SECONDS마다 활성 종목의 현재가를 적재하고,
장 마감 후 탈퇴 사용자 정리와 평가액 스냅샷을 하루 한 번 한다.

워커가 여러 개여도 Redis 락으로 한 주기에 한 워커만 수집한다.
"""

import asyncio
import logging
import random
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Protocol

from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import SessionLocal
from .leaderboard import ACCOUNT_VALUES, refresh_realtime
from .market import is_after_close, is_market_open, now_kst
from .models import PriceTick, Stock
from .users import purge_deleted_users

log = logging.getLogger(__name__)


class PriceProvider(Protocol):
    async def fetch(self, stocks: list[Stock]) -> dict[str, Decimal]:
        """종목코드 → 현재가. 받지 못한 종목은 빼고 반환한다."""
        ...


class MockProvider:
    """랜덤 워크 — 직전가에서 ±1% 안에서 움직인다. 실 거래소 API 연동 전 개발용."""

    async def fetch(self, stocks: list[Stock]) -> dict[str, Decimal]:
        return {
            s.symbol: max(Decimal(1), ((s.last_price or Decimal(50_000)) * Decimal(1 + random.uniform(-0.01, 0.01))).quantize(Decimal(1)))
            for s in stocks
        }


PROVIDERS: dict[str, type[PriceProvider]] = {"mock": MockProvider}
provider: PriceProvider = PROVIDERS[settings.price_provider]()


async def collect_prices(session: AsyncSession) -> None:
    stocks = list(await session.scalars(select(Stock).where(Stock.is_active)))
    if not stocks:
        return
    prices = await provider.fetch(stocks)
    now = datetime.now(timezone.utc)
    today_start = now_kst().replace(hour=0, minute=0, second=0, microsecond=0)
    for s in stocks:
        price = prices.get(s.symbol)
        if price is None:
            continue
        if s.last_price_at and s.last_price_at < today_start:  # 새 거래일 첫 틱 — 직전 최신가가 전일 종가
            s.prev_close = s.last_price
        s.last_price, s.last_price_at = price, now
        session.add(PriceTick(stock_id=s.id, price=price, collected_at=now))
    await session.commit()


async def snapshot_equity(session: AsyncSession, day: date) -> None:
    await session.execute(
        text(f"""
        WITH {ACCOUNT_VALUES}
        INSERT INTO equity_snapshots (account_id, snapshot_date, total_value)
        SELECT id, :day, value FROM account_values
        ON CONFLICT (account_id, snapshot_date) DO UPDATE SET total_value = EXCLUDED.total_value
        """),
        {"day": day},
    )
    await session.commit()


async def _once_per_day(redis: Redis, name: str, day: date, job) -> None:
    """여러 워커 중 하나만 하루 한 번. 실패하면 락을 풀어 다음 루프에서 다시 시도한다."""
    key = f"stock:lock:{name}:{day}"
    if not await redis.set(key, "1", nx=True, ex=2 * 86400):
        return
    try:
        async with SessionLocal() as session:
            await job(session)
    except Exception:
        await redis.delete(key)
        log.exception("daily job %s failed", name)


async def run_collector(redis: Redis) -> None:
    interval = settings.price_interval_seconds
    while True:
        now = now_kst()
        try:
            if is_market_open(now) and await redis.set("stock:lock:collect", "1", nx=True, ex=max(interval - 1, 1)):
                async with SessionLocal() as session:
                    await collect_prices(session)
                    await refresh_realtime(session, redis)
            if is_after_close(now):
                await _once_per_day(redis, "purge", now.date(), purge_deleted_users)
                await _once_per_day(redis, "snapshot", now.date(), lambda s: snapshot_equity(s, now.date()))
        except Exception:
            log.exception("price collector failed")
        await asyncio.sleep(interval)
