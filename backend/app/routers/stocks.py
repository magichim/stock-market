from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from ..db import SessionLocal
from ..market import is_market_open, now_kst
from ..models import PriceTick, Stock

router = APIRouter(prefix="/api/stocks")


@router.get("")
async def list_stocks() -> dict:
    async with SessionLocal() as session:
        stocks = await session.scalars(select(Stock).where(Stock.is_active).order_by(Stock.display_order, Stock.symbol))
        return {
            "market_open": is_market_open(now_kst()),
            "stocks": [
                {
                    "symbol": s.symbol,
                    "name": s.name,
                    "market": s.market,
                    "price": float(s.last_price) if s.last_price is not None else None,
                    "prev_close": float(s.prev_close) if s.prev_close is not None else None,
                    "price_at": s.last_price_at,
                }
                for s in stocks
            ],
        }


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
