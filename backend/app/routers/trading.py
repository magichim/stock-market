from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import CurrentUser, require_user
from ..db import SessionLocal
from ..models import Account, Event, Exchange, Stock, Trade
from ..trading import account_summary, execute_exchange, execute_trade

router = APIRouter(prefix="/api")


async def find_event(session: AsyncSession, slug: str | None) -> Event | None:
    """slug가 없으면 기본 계좌(None). 공개되지 않았거나 없는 이벤트는 404."""
    if slug is None:
        return None
    event = await session.scalar(select(Event).where(Event.slug == slug, Event.published))
    if event is None:
        raise HTTPException(404, "이벤트를 찾을 수 없습니다.")
    return event


@router.get("/events")
async def list_events() -> list[dict]:
    async with SessionLocal() as session:
        events = await session.scalars(select(Event).where(Event.published).order_by(Event.start_date.desc()))
        return [
            {
                "slug": e.slug,
                "title": e.title,
                "description": e.description,
                "initial_cash": float(e.initial_cash),
                "start_date": e.start_date,
                "end_date": e.end_date,
            }
            for e in events
        ]


@router.get("/account")
async def get_account(event: str | None = None, user: CurrentUser = Depends(require_user)) -> dict:
    async with SessionLocal() as session:
        return await account_summary(session, user.id, await find_event(session, event))


@router.get("/account/trades")
async def get_trades(
    event: str | None = None, limit: int = Query(50, ge=1, le=200), user: CurrentUser = Depends(require_user)
) -> list[dict]:
    async with SessionLocal() as session:
        ev = await find_event(session, event)
        rows = await session.execute(
            select(Trade, Stock)
            .join(Stock, Stock.id == Trade.stock_id)
            .join(Account, Account.id == Trade.account_id)
            .where(Account.user_id == user.id, Account.event_id == ev.id if ev else Account.event_id.is_(None))
            .order_by(Trade.executed_at.desc())
            .limit(limit)
        )
        return [_trade_out(t, s) for t, s in rows]


class TradeIn(BaseModel):
    symbol: str
    side: Literal["buy", "sell"]
    quantity: int = Field(gt=0, le=1_000_000)
    event: str | None = None


@router.post("/trades")
async def post_trade(body: TradeIn, user: CurrentUser = Depends(require_user)) -> dict:
    """시장가 주문 — 최신가로 즉시 전량 체결된다."""
    async with SessionLocal() as session:
        ev = await find_event(session, body.event)
        stock = await session.scalar(select(Stock).where(Stock.symbol == body.symbol))
        trade = await execute_trade(session, user.id, ev, body.symbol, body.side, body.quantity)
        return _trade_out(trade, stock)


class ExchangeIn(BaseModel):
    from_currency: str = Field(min_length=3, max_length=3)
    to_currency: str = Field(min_length=3, max_length=3)
    amount: Decimal = Field(gt=0, max_digits=16, decimal_places=2)  # 보내는 금액 (from 통화)
    event: str | None = None


@router.post("/exchanges")
async def post_exchange(body: ExchangeIn, user: CurrentUser = Depends(require_user)) -> dict:
    """환전 — 최신 환율로 즉시 체결된다."""
    async with SessionLocal() as session:
        ev = await find_event(session, body.event)
        e = await execute_exchange(
            session, user.id, ev, body.from_currency.upper(), body.to_currency.upper(), body.amount
        )
        return _exchange_out(e)


@router.get("/account/exchanges")
async def get_exchanges(
    event: str | None = None, limit: int = Query(50, ge=1, le=200), user: CurrentUser = Depends(require_user)
) -> list[dict]:
    async with SessionLocal() as session:
        ev = await find_event(session, event)
        rows = await session.scalars(
            select(Exchange)
            .join(Account, Account.id == Exchange.account_id)
            .where(Account.user_id == user.id, Account.event_id == ev.id if ev else Account.event_id.is_(None))
            .order_by(Exchange.executed_at.desc())
            .limit(limit)
        )
        return [_exchange_out(e) for e in rows]


def _exchange_out(e: Exchange) -> dict:
    return {
        "id": e.id,
        "from_currency": e.from_currency,
        "to_currency": e.to_currency,
        "from_amount": float(e.from_amount),
        "to_amount": float(e.to_amount),
        "rate": float(e.rate),
        "executed_at": e.executed_at,
    }


def _trade_out(t: Trade, s: Stock) -> dict:
    return {
        "id": t.id,
        "symbol": s.symbol,
        "name": s.name,
        "currency": s.currency,
        "side": t.side,
        "quantity": t.quantity,
        "price": float(t.price),
        "amount": float(t.amount),
        "realized_pnl": float(t.realized_pnl) if t.realized_pnl is not None else None,
        "executed_at": t.executed_at,
    }
