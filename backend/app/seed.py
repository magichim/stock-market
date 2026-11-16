"""가격을 수집할 기본 종목과 통화 — 이미 있는 행은 건드리지 않는다 (is_active 등 운영 변경 유지)."""

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from .models import FxRate, Stock

# 시장 → 거래 통화
MARKET_CURRENCY = {"KOSPI": "KRW", "KOSDAQ": "KRW", "NASDAQ": "USD", "NYSE": "USD"}
# 환율을 수집할 통화 — KRW(기준, 1)는 SCHEMA_PATCHES에서 넣는다
CURRENCIES = ["USD"]

STOCKS = [
    ("005930", "삼성전자", "KOSPI"),
    ("000660", "SK하이닉스", "KOSPI"),
    ("373220", "LG에너지솔루션", "KOSPI"),
    ("207940", "삼성바이오로직스", "KOSPI"),
    ("005380", "현대차", "KOSPI"),
    ("000270", "기아", "KOSPI"),
    ("068270", "셀트리온", "KOSPI"),
    ("105560", "KB금융", "KOSPI"),
    ("035420", "NAVER", "KOSPI"),
    ("035720", "카카오", "KOSPI"),
]


async def seed_stocks(conn: AsyncConnection) -> None:
    await conn.execute(insert(FxRate).values([{"currency": c} for c in CURRENCIES]).on_conflict_do_nothing())
    rows = [
        {"symbol": symbol, "name": name, "market": market, "currency": MARKET_CURRENCY[market], "display_order": i}
        for i, (symbol, name, market) in enumerate(STOCKS)
    ]
    await conn.execute(insert(Stock).values(rows).on_conflict_do_nothing(index_elements=["symbol"]))
