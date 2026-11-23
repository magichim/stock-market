"""가격 수집기 — 장 운영 중 PRICE_INTERVAL_SECONDS마다 활성 종목의 현재가와 환율을 적재하고,
장 마감 후 탈퇴 사용자 정리와 평가액 스냅샷을 하루 한 번 한다.

워커가 여러 개여도 Redis 락으로 한 주기에 한 워커만 수집한다.
"""

import asyncio
import logging
import random
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Protocol

import httpx
from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import SessionLocal
from .leaderboard import ACCOUNT_VALUES, refresh_realtime
from .market import (
    is_after_close,
    is_kr_quote_time,
    is_kr_stock_quote_time,
    is_market_open,
    is_nxt_refresh_time,
    now_kst,
)
from .models import FxRate, PriceTick, Stock
from .seed import MARKET_COUNTRY, MARKET_CURRENCY
from .users import purge_deleted_users

log = logging.getLogger(__name__)


class PriceProvider(Protocol):
    async def fetch(self, stocks: list[Stock]) -> dict[str, Decimal]:
        """종목코드 → 현재가. 받지 못한 종목은 빼고 반환한다."""
        ...

    async def fetch_fx(self, rates: list[FxRate]) -> dict[str, Decimal]:
        """통화 → 1단위당 KRW. 받지 못한 통화는 빼고 반환한다."""
        ...

    async def fetch_nxt(self, stocks: list[Stock]) -> dict[str, bool]:
        """국내 종목코드 → NXT 거래 종목 여부. 확인하지 못한 종목은 빼고 반환한다."""
        ...


class MockProvider:
    """랜덤 워크 — 직전가에서 ±1% 안에서 움직인다. 실 거래소 API 연동 전 개발용."""

    async def fetch(self, stocks: list[Stock]) -> dict[str, Decimal]:
        return {
            s.symbol: max(Decimal(1), ((s.last_price or Decimal(50_000 if s.currency == "KRW" else 100)) * Decimal(1 + random.uniform(-0.01, 0.01))).quantize(Decimal(1)))
            for s in stocks
        }

    async def fetch_fx(self, rates: list[FxRate]) -> dict[str, Decimal]:
        return {
            r.currency: ((r.rate or Decimal(1400)) * Decimal(1 + random.uniform(-0.002, 0.002))).quantize(Decimal("0.0001"))
            for r in rates
        }

    async def fetch_nxt(self, stocks: list[Stock]) -> dict[str, bool]:
        return {}  # mock은 NXT 거래 여부를 모른다 — 기존 값을 그대로 둔다


class KisProvider:
    """KIS 게이트웨이(kis/)의 묶음 조회 — 받지 못한 종목·통화는 응답에서 빠져 있다."""

    async def _prices(self, path: str, **params: str) -> dict[str, Decimal]:
        async with httpx.AsyncClient(base_url=settings.kis_api_url, timeout=120) as client:
            res = await client.get(path, params=params)
        res.raise_for_status()
        body = res.json()
        if body["errors"]:
            log.warning("kis %s: %s", path, body["errors"])
        return {code: Decimal(value) for code, value in body["prices"].items()}

    async def fetch(self, stocks: list[Stock]) -> dict[str, Decimal]:
        return await self._prices("/quotes/stocks", items=",".join(f"{s.symbol}:{s.market}" for s in stocks))

    async def fetch_fx(self, rates: list[FxRate]) -> dict[str, Decimal]:
        return await self._prices("/quotes/fx", currencies=",".join(r.currency for r in rates))

    async def fetch_nxt(self, stocks: list[Stock]) -> dict[str, bool]:
        async with httpx.AsyncClient(base_url=settings.kis_api_url, timeout=120) as client:
            res = await client.get("/quotes/nxt", params={"symbols": ",".join(s.symbol for s in stocks)})
        res.raise_for_status()
        body = res.json()
        if body["errors"]:
            log.warning("kis /quotes/nxt: %s", body["errors"])
        return body["tradable"]


# 수집 대상 — PRICE_COUNTRIES에 적힌 국가의 시장과 그 통화만
MARKETS = [m for m, c in MARKET_COUNTRY.items() if c in settings.price_countries.split(",")]
CURRENCIES = {MARKET_CURRENCY[m] for m in MARKETS}

PROVIDERS: dict[str, type[PriceProvider]] = {"mock": MockProvider, "kis": KisProvider}
provider: PriceProvider = PROVIDERS[settings.price_provider]()


async def collect_prices(session: AsyncSession) -> None:
    # 국내 종목은 NXT 포함 08:00–20:00(NXT 미거래 종목은 정규장 + 마감 뒤 한 번), 그 밖(미국)은 기존 장 시간에만 수집한다
    kst = now_kst()
    is_open = {"KR": is_kr_quote_time(kst), "US": is_market_open(kst)}
    markets = [m for m in MARKETS if is_open[MARKET_COUNTRY[m]]]
    stocks = [
        s
        for s in await session.scalars(select(Stock).where(Stock.is_active, Stock.market.in_(markets)))
        if MARKET_COUNTRY[s.market] != "KR" or is_kr_stock_quote_time(s, kst)
    ]
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


async def collect_fx(session: AsyncSession) -> None:
    """KRW(기준, 1 고정)를 뺀 통화의 최신 환율을 갱신한다."""
    rates = list(await session.scalars(select(FxRate).where(FxRate.currency != "KRW", FxRate.currency.in_(CURRENCIES))))
    if not rates:
        return
    fetched = await provider.fetch_fx(rates)
    now = datetime.now(timezone.utc)
    for r in rates:
        if r.currency in fetched:
            r.rate, r.rate_at = fetched[r.currency], now
    await session.commit()


async def refresh_nxt(session: AsyncSession) -> None:
    """국내 종목의 NXT 거래 여부(stocks.nxt_tradable)를 갱신한다 — 확인된 종목만 바꾼다."""
    kr = [m for m, c in MARKET_COUNTRY.items() if c == "KR"]
    stocks = list(await session.scalars(select(Stock).where(Stock.is_active, Stock.market.in_(kr))))
    if not stocks:
        return
    tradable = await provider.fetch_nxt(stocks)
    for s in stocks:
        if s.symbol in tradable:
            s.nxt_tradable = tradable[s.symbol]
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
            if is_nxt_refresh_time(now):  # 06:00부터, 수집보다 먼저 — 수집 대상이 NXT 거래 여부로 갈린다
                await _once_per_day(redis, "nxt", now.date(), refresh_nxt)
            if is_kr_quote_time(now) and await redis.set("stock:lock:collect", "1", nx=True, ex=max(interval - 1, 1)):
                async with SessionLocal() as session:
                    await collect_fx(session)
                    await collect_prices(session)
                    await refresh_realtime(session, redis)
            if is_after_close(now):
                await _once_per_day(redis, "purge", now.date(), purge_deleted_users)
                await _once_per_day(redis, "snapshot", now.date(), lambda s: snapshot_equity(s, now.date()))
        except Exception:
            log.exception("price collector failed")
        await asyncio.sleep(interval)
