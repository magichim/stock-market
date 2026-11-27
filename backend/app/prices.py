"""가격 수집기 — 장 운영 중 PRICE_INTERVAL_SECONDS마다 활성 종목의 현재가와 환율을 적재하고,
장 마감 후 탈퇴 사용자 정리와 평가액 스냅샷을 하루 한 번 한다.

워커가 여러 개여도 Redis 락으로 한 주기에 한 워커만 수집한다.
"""

import asyncio
import logging
import random
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Protocol

import httpx
from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import SessionLocal
from .leaderboard import ACCOUNT_VALUES, refresh_realtime
from .market import (
    KST,
    CLOSE_PRICE_AT,
    SCHEDULE_DELAY,
    is_after_close,
    is_collect_tick,
    is_kr_collect_day,
    is_kr_prepare_time,
    is_kr_quote_time,
    is_kr_stock_quote_time,
    is_market_open,
    next_collect_at,
    now_kst,
)
from .models import FxRate, PriceTick, Stock, StockClose
from .seed import MARKET_COUNTRY, MARKET_CURRENCY
from .users import purge_deleted_users

log = logging.getLogger(__name__)


class PriceProvider(Protocol):
    async def fetch(self, stocks: list[Stock]) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
        """(종목코드 → 현재가, 국내 종목코드 → 전일 확정 종가). 받지 못한 종목은 빼고 반환한다."""
        ...

    async def fetch_fx(self, rates: list[FxRate]) -> dict[str, Decimal]:
        """통화 → 1단위당 KRW. 받지 못한 통화는 빼고 반환한다."""
        ...

    async def fetch_nxt(self, stocks: list[Stock]) -> tuple[dict[str, bool], dict[str, bool]]:
        """(국내 종목코드 → NXT 거래 종목 여부, 국내 종목코드 → 거래정지 여부). 확인하지 못한 종목은 빼고 반환한다."""
        ...


class MockProvider:
    """랜덤 워크 — 직전가에서 ±1% 안에서 움직인다. 실 거래소 API 연동 전 개발용."""

    async def fetch(self, stocks: list[Stock]) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
        prices = {
            s.symbol: max(Decimal(1), ((s.last_price or Decimal(50_000 if s.currency == "KRW" else 100)) * Decimal(1 + random.uniform(-0.01, 0.01))).quantize(Decimal(1)))
            for s in stocks
        }
        return prices, {}  # mock은 전일 종가를 모른다

    async def fetch_fx(self, rates: list[FxRate]) -> dict[str, Decimal]:
        return {
            r.currency: ((r.rate or Decimal(1400)) * Decimal(1 + random.uniform(-0.002, 0.002))).quantize(Decimal("0.0001"))
            for r in rates
        }

    async def fetch_nxt(self, stocks: list[Stock]) -> tuple[dict[str, bool], dict[str, bool]]:
        return {}, {}  # mock은 NXT 거래 여부·거래정지를 모른다 — 기존 값을 그대로 둔다


class KisProvider:
    """KIS 게이트웨이(kis/)의 묶음 조회 — 받지 못한 종목·통화는 응답에서 빠져 있다."""

    async def _get(self, path: str, **params: str) -> dict:
        async with httpx.AsyncClient(base_url=settings.kis_api_url, timeout=120) as client:
            res = await client.get(path, params=params)
        res.raise_for_status()
        body = res.json()
        if body["errors"]:
            log.warning("kis %s: %s", path, body["errors"])
        return body

    async def fetch(self, stocks: list[Stock]) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
        body = await self._get("/quotes/stocks", items=",".join(f"{s.symbol}:{s.market}" for s in stocks))
        prev_closes = body.get("prev_closes", {})  # prev_closes가 없는 이전 게이트웨이도 받는다
        return {c: Decimal(v) for c, v in body["prices"].items()}, {c: Decimal(v) for c, v in prev_closes.items()}

    async def fetch_fx(self, rates: list[FxRate]) -> dict[str, Decimal]:
        body = await self._get("/quotes/fx", currencies=",".join(r.currency for r in rates))
        return {code: Decimal(value) for code, value in body["prices"].items()}

    async def fetch_nxt(self, stocks: list[Stock]) -> tuple[dict[str, bool], dict[str, bool]]:
        body = await self._get("/quotes/nxt", symbols=",".join(s.symbol for s in stocks))
        return body["tradable"], body.get("halted", {})  # halted가 없는 이전 게이트웨이도 받는다


# 수집 대상 — PRICE_COUNTRIES에 적힌 국가의 시장과 그 통화만
MARKETS = [m for m, c in MARKET_COUNTRY.items() if c in settings.price_countries.split(",")]
CURRENCIES = {MARKET_CURRENCY[m] for m in MARKETS}

PROVIDERS: dict[str, type[PriceProvider]] = {"mock": MockProvider, "kis": KisProvider}
provider: PriceProvider = PROVIDERS[settings.price_provider]()


async def collect_prices(session: AsyncSession, kst: datetime, all_kr: bool = False) -> dict[Stock, Decimal]:
    """수집한 {종목: 가격}을 돌려준다.

    kst는 수집 회차 시각. 국내 종목은 개장일의 NXT 포함 08:00–20:00(NXT 미거래 종목은 정규장 09:00–15:30만), 그 밖(미국)은 기존 장 시간에만 수집한다.
    all_kr이면 수집 시간 안의 국내 종목을 NXT 거래 여부와 무관하게 모두 수집한다 (종가를 남길 회차).

    국내 종목은 그날 첫 수집 때 KIS가 준 전일 확정 종가로 stock_closes를 바로잡는다 (_correct_closes).
    """
    is_open = {"KR": is_kr_quote_time(kst) and await is_kr_collect_day(kst), "US": is_market_open(kst)}
    markets = [m for m in MARKETS if is_open[MARKET_COUNTRY[m]]]
    stocks = [
        s
        for s in await session.scalars(select(Stock).where(Stock.is_active, Stock.market.in_(markets)))
        if MARKET_COUNTRY[s.market] != "KR" or all_kr or is_kr_stock_quote_time(s, kst)
    ]
    if not stocks:
        return {}
    prices, prev_closes = await provider.fetch(stocks)
    await _correct_closes(session, stocks, prev_closes, kst.date())  # last_price_at을 바꾸기 전에
    now = datetime.now(timezone.utc)
    collected = {s: prices[s.symbol] for s in stocks if s.symbol in prices}
    for s, price in collected.items():
        s.last_price, s.last_price_at = price, now
        session.add(PriceTick(stock_id=s.id, price=price, collected_at=now))
    await session.commit()
    return collected


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


NXT_BATCH = 200  # /quotes/nxt 한 번에 넘기는 종목 수 — 게이트웨이가 종목마다 KIS를 불러(0.1초 간격) 대기 시간(120초) 안에 끝나게


async def refresh_nxt(session: AsyncSession) -> None:
    """국내 종목의 NXT 거래 여부(stocks.nxt_tradable)와 거래정지 여부(stocks.trading_halted)를 갱신한다 — 확인된 종목만 바꾼다.

    NXT_BATCH개씩 나눠 요청하고 묶음마다 저장한다. 실패한 묶음이 있으면 나머지를 마친 뒤 예외를 내 다음 회차에 다시 시도한다.
    """
    kr = [m for m, c in MARKET_COUNTRY.items() if c == "KR"]
    stocks = list(await session.scalars(select(Stock).where(Stock.is_active, Stock.market.in_(kr))))
    failed = 0
    for i in range(0, len(stocks), NXT_BATCH):
        batch = stocks[i:i + NXT_BATCH]
        try:
            tradable, halted = await provider.fetch_nxt(batch)
        except Exception:
            log.exception("NXT 갱신 묶음 실패 (%d–%d번째 종목)", i + 1, i + len(batch))
            failed += 1
            continue
        for s in batch:
            if s.symbol in tradable:
                s.nxt_tradable = tradable[s.symbol]
            if s.symbol in halted:
                if s.trading_halted != halted[s.symbol]:
                    log.info("거래정지 %s: %s %s", "지정" if halted[s.symbol] else "해제", s.symbol, s.name)
                s.trading_halted = halted[s.symbol]
        await session.commit()
    if failed:
        raise RuntimeError(f"NXT 갱신 묶음 {failed}개 실패 — 다음 회차에 다시 시도한다")


async def record_close(session: AsyncSession) -> None:
    """국내 종목의 오늘(KST) 종가를 지금 조회한 가격으로 stock_closes에 넣는다 — 받은 종목만. stocks·price_ticks는 건드리지 않는다."""
    kr = [m for m in MARKETS if MARKET_COUNTRY[m] == "KR"]
    stocks = list(await session.scalars(select(Stock).where(Stock.is_active, Stock.market.in_(kr))))
    if not stocks:
        return
    prices, _ = await provider.fetch(stocks)
    await save_closes(session, {s: prices[s.symbol] for s in stocks if s.symbol in prices}, now_kst().date())


async def save_closes(session: AsyncSession, prices: dict[Stock, Decimal], day: date) -> bool:
    """국내 종목의 day(KST) 종가를 stock_closes에 넣는다 — 같은 날 행이 있으면 덮어쓴다. 국내 종목만 넣고, 넣은 행이 있으면 True."""
    rows = [{"stock_id": s.id, "close_date": day, "price": p} for s, p in prices.items() if MARKET_COUNTRY[s.market] == "KR"]
    if rows:
        await _upsert_closes(session, rows)
        await session.commit()
    return bool(rows)


async def _upsert_closes(session: AsyncSession, rows: list[dict]) -> None:
    """stock_closes에 (stock_id, close_date, price) 행을 넣는다 — 같은 날 행이 있고 값이 다를 때만 바꾼다."""
    stmt = insert(StockClose).values(rows)
    await session.execute(stmt.on_conflict_do_update(
        index_elements=["stock_id", "close_date"], set_={"price": stmt.excluded.price}, where=StockClose.price != stmt.excluded.price,
    ))


async def _correct_closes(session: AsyncSession, stocks: list[Stock], prev_closes: dict[str, Decimal], today: date) -> None:
    """KIS가 준 전일 확정 종가로 마지막 수집일의 stock_closes를 바로잡는다 — 그날 행이 없으면 넣고, 다르면 바꾼다.

    15:30:00 기록(run_close_recorder)은 종가 단일가 체결 전 값일 수 있고, 기록이 빠진 날도 있다.
    KIS 응답에는 "전일"이 며칠인지 없으므로, 그날 첫 수집 직전의 last_price_at(KST 날짜)을 전 거래일로 본다.
    그래서 같은 날 두 번째 수집부터는 건너뛴다. 마지막 수집일이 7일보다 오래되면(서버가 전 거래일에 꺼져 있었을 수 있음) 쓰지 않는다.
    """
    rows = []
    for s in stocks:
        if MARKET_COUNTRY[s.market] != "KR" or s.symbol not in prev_closes or s.last_price_at is None:
            continue
        last_day = s.last_price_at.astimezone(KST).date()
        if today - timedelta(days=7) <= last_day < today:
            rows.append({"stock_id": s.id, "close_date": last_day, "price": prev_closes[s.symbol]})
    if rows:
        await _upsert_closes(session, rows)


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
    close_on_tick = is_collect_tick(CLOSE_PRICE_AT, interval)  # 그러면 종가도 이 루프가 남긴다 (run_close_recorder는 쉰다)
    tick = now_kst()
    while True:
        # KST 자정부터 interval 간격의 회차(예: 매시 00·20·40분)에 깨어난다 — 시작·재시작 시각, 수집 소요 시간과 무관.
        # 실제 실행은 SCHEDULE_DELAY 뒤 (dev 30초)
        tick = next_collect_at(max(tick, now_kst() - SCHEDULE_DELAY), interval)
        await asyncio.sleep((tick + SCHEDULE_DELAY - now_kst()).total_seconds())
        now = tick  # 판단은 회차 시각으로 — 늦게 깨도(dev 지연 포함) 20:00 회차는 20:00으로 본다
        try:
            # 04:00부터, 수집보다 먼저 — 그날 개장일인지 확인하고(휴장일이면 국내 수집 없음) NXT 거래 여부를 갱신한다
            if is_kr_prepare_time(now) and await is_kr_collect_day(now):
                await _once_per_day(redis, "nxt", now.date(), refresh_nxt)
            if is_kr_quote_time(now) and await redis.set("stock:lock:collect", "1", nx=True, ex=max(interval - 1, 1)):
                # 종가는 CLOSE_PRICE_AT 회차에 남긴다. 그 회차가 실패하거나 건너뛰면 그날 다음에 성공한 회차가
                # (마감 뒤라 수집하지 않는 NXT 미거래 종목까지 함께 수집해) 남긴다. 남겼는지는 stock:lock:close:{날짜}로 본다
                close_key = f"stock:lock:close:{now.date()}"
                close_due = close_on_tick and now.time() >= CLOSE_PRICE_AT and not await redis.exists(close_key)
                async with SessionLocal() as session:
                    await collect_fx(session)
                    collected = await collect_prices(session, now, all_kr=close_due)
                    if close_due and await save_closes(session, collected, now.date()):
                        await redis.set(close_key, "1", ex=2 * 86400)
                    await refresh_realtime(session, redis)
            if is_after_close(now):
                await _once_per_day(redis, "purge", now.date(), purge_deleted_users)
                await _once_per_day(redis, "snapshot", now.date(), lambda s: snapshot_equity(s, now.date()))
        except Exception:
            log.exception("price collector failed")


async def run_close_recorder(redis: Redis) -> None:
    """개장일마다 CLOSE_PRICE_AT(KST 15:30:00)에 국내 종목의 종가(stock_closes)를 기록한다 — 수집 루프(run_collector)와 별개.

    실제 실행은 SCHEDULE_DELAY 뒤 (dev 15:30:30).
    CLOSE_PRICE_AT이 수집 회차와 겹치면(주기 600·120초 등) 수집 루프가 그 회차 값으로 기록하므로 이 태스크는 바로 끝난다.
    """
    if is_collect_tick(CLOSE_PRICE_AT, settings.price_interval_seconds):
        log.info("종가 기록 시각 %s이 수집 회차와 겹쳐 수집 루프가 기록한다", CLOSE_PRICE_AT)
        return
    while True:
        now = now_kst() - SCHEDULE_DELAY
        target = datetime.combine(now.date(), CLOSE_PRICE_AT, KST)
        if now >= target:
            target += timedelta(days=1)
        await asyncio.sleep((target + SCHEDULE_DELAY - now_kst()).total_seconds())
        try:
            now = now_kst() - SCHEDULE_DELAY
            if now >= target and await is_kr_collect_day(now):
                await _once_per_day(redis, "close", now.date(), record_close)
        except Exception:
            log.exception("close recorder failed")
