"""가격을 수집할 기본 종목과 통화 — 이미 있는 행은 건드리지 않는다 (is_active 등 운영 변경 유지)."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from .models import FxRate, Stock

# 시장 → 거래 통화
MARKET_CURRENCY = {"KOSPI": "KRW", "KOSDAQ": "KRW", "NASDAQ": "USD", "NYSE": "USD"}
# 시장 → 국가 (PRICE_COUNTRIES로 수집 대상을 고른다)
MARKET_COUNTRY = {"KOSPI": "KR", "KOSDAQ": "KR", "NASDAQ": "US", "NYSE": "US"}
# 환율을 수집할 통화 — KRW(기준, 1)는 SCHEMA_PATCHES에서 넣는다
CURRENCIES = ["USD"]

# (종목코드, 이름, 시장[, 종류]) — 종류를 생략하면 개별 종목(stock)
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
    # 나스닥 빅테크
    ("AAPL", "애플", "NASDAQ"),
    ("MSFT", "마이크로소프트", "NASDAQ"),
    ("NVDA", "엔비디아", "NASDAQ"),
    ("AMZN", "아마존", "NASDAQ"),
    ("GOOGL", "알파벳", "NASDAQ"),
    ("META", "메타", "NASDAQ"),
    ("TSLA", "테슬라", "NASDAQ"),
    ("AVGO", "브로드컴", "NASDAQ"),
    ("NFLX", "넷플릭스", "NASDAQ"),
    ("AMD", "AMD", "NASDAQ"),
    # KODEX 대표 ETF — 유가증권시장 상장
    ("069500", "KODEX 200", "KOSPI", "etf"),
    ("229200", "KODEX 코스닥150", "KOSPI", "etf"),
    ("379800", "KODEX 미국S&P500", "KOSPI", "etf"),
    ("379810", "KODEX 미국나스닥100", "KOSPI", "etf"),
    ("091160", "KODEX 반도체", "KOSPI", "etf"),
    ("305720", "KODEX 2차전지산업", "KOSPI", "etf"),
]


async def seed_stocks(conn: AsyncConnection) -> None:
    await conn.execute(insert(FxRate).values([{"currency": c} for c in CURRENCIES]).on_conflict_do_nothing())
    # 없는 종목만 넣는다 — 충돌로 버려지는 INSERT도 id 시퀀스를 소모해 재시작마다 번호가 비기 때문
    existing = set(await conn.scalars(select(Stock.symbol)))
    rows = [
        {"symbol": symbol, "name": name, "market": market, "kind": kind[0] if kind else "stock",
         "currency": MARKET_CURRENCY[market], "display_order": i}
        for i, (symbol, name, market, *kind) in enumerate(STOCKS)
        if symbol not in existing
    ]
    if rows:
        await conn.execute(insert(Stock).values(rows).on_conflict_do_nothing(index_elements=["symbol"]))
