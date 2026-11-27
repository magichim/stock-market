from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, or_, select

from ..db import SessionLocal
from ..market import is_tradable, kr_session, now_kst
from ..models import PriceTick, Stock, StockClose

router = APIRouter(prefix="/api/stocks")


@router.get("/domestic")
async def domestic_stocks() -> dict:
    """국내 종목(KRW) 목록."""
    return await list_stocks(Stock.currency == "KRW")


@router.get("/overseas")
async def overseas_stocks() -> dict:
    """해외 종목(KRW 외 통화) 목록."""
    return await list_stocks(Stock.currency != "KRW")


async def list_stocks(region) -> dict:
    async with SessionLocal() as session:
        # 등락률 기준 — 최신가가 찍힌 날(KST)보다 앞선 마지막 종가. 그날 15:30:00에 기록되는 당일 종가는 애프터마켓에도 쓰지 않는다
        close_price = (
            select(StockClose.price)
            .where(
                StockClose.stock_id == Stock.id,
                StockClose.close_date < func.date(func.timezone("Asia/Seoul", Stock.last_price_at)),
            )
            .order_by(StockClose.close_date.desc())
            .limit(1)
            .scalar_subquery()
        )
        rows = (
            await session.execute(
                select(Stock, close_price).where(Stock.is_active, region).order_by(Stock.display_order, Stock.symbol)
            )
        ).all()
        now = now_kst()
        kr = await kr_session(now)
        return {
            "session": kr,  # 국내 장 구간 — regular | nxt | null(닫힘)
            "stocks": [
                {
                    "symbol": s.symbol,
                    "name": s.name,
                    "market": s.market,
                    "kind": s.kind,
                    "currency": s.currency,
                    "price": float(s.last_price) if s.last_price is not None else None,
                    "close_price": float(close) if close is not None else None,  # 전 거래일 종가 — 없으면 등락률 없음
                    "price_at": s.last_price_at,
                    "tradable": is_tradable(s, now, kr),  # 지금 주문할 수 있는지
                }
                for s, close in rows
            ],
        }


@router.get("/search")
async def search(q: str = Query(min_length=1, max_length=50), limit: int = Query(10, ge=1, le=30)) -> list[dict]:
    """종목 검색 — 종목코드 앞부분 또는 이름 일부. 코드 완전 일치 → 이름 앞부분 일치 → 표시 순서."""
    q = q.strip()
    if not q:
        return []
    like = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    async with SessionLocal() as session:
        stocks = await session.scalars(
            select(Stock)
            .where(
                Stock.is_active,
                or_(Stock.symbol.ilike(f"{like}%", escape="\\"), Stock.name.ilike(f"%{like}%", escape="\\")),
            )
            .order_by(
                func.upper(Stock.symbol) != q.upper(),
                ~Stock.name.ilike(f"{like}%", escape="\\"),
                Stock.display_order,
                Stock.symbol,
            )
            .limit(limit)
        )
        return [
            {
                "symbol": s.symbol,
                "name": s.name,
                "market": s.market,
                "kind": s.kind,
                "currency": s.currency,
                "price": float(s.last_price) if s.last_price is not None else None,
            }
            for s in stocks
        ]


@router.get("/{symbol}/ticks")
async def ticks(symbol: str, hours: int = Query(24, ge=1, le=24 * 30)) -> list[dict]:
    """차트용 가격 시계열 — 최근 hours시간."""
    async with SessionLocal() as session:
        stock_id = await session.scalar(select(Stock.id).where(Stock.symbol == symbol))
        if stock_id is None:
            raise HTTPException(404, "종목을 찾을 수 없습니다.")
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        rows = await session.execute(
            select(PriceTick.collected_at, PriceTick.price)
            .where(PriceTick.stock_id == stock_id, PriceTick.collected_at >= since)
            .order_by(PriceTick.collected_at)
        )
        return [{"t": t, "price": float(p)} for t, p in rows]
