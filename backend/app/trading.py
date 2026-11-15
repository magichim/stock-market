"""계좌 조회와 체결. 오더북이 없어 주문은 그 시점 최신가로 즉시 전량 체결된다 (DB_DESIGN.md "체결 규칙")."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .market import is_market_open, now_kst
from .models import Account, Event, Holding, PriceTick, Stock, Trade


def _initial_cash(event: Event | None) -> Decimal:
    return event.initial_cash if event else Decimal(settings.initial_cash)


def _find_account(user_id: int, event: Event | None):
    return select(Account).where(
        Account.user_id == user_id,
        Account.event_id == event.id if event else Account.event_id.is_(None),
    )


async def account_summary(session: AsyncSession, user_id: int, event: Event | None) -> dict:
    """계좌가 아직 없으면(첫 매수 전) 시작 자금만 있는 빈 계좌로 응답한다."""
    account = await session.scalar(_find_account(user_id, event))
    initial = account.initial_cash if account else _initial_cash(event)
    cash = account.cash if account else initial
    rows = (
        (await session.execute(
            select(Holding, Stock).join(Stock, Stock.id == Holding.stock_id)
            .where(Holding.account_id == account.id).order_by(Stock.display_order, Stock.symbol)
        )).all()
        if account
        else []
    )
    holdings = [
        {
            "symbol": s.symbol,
            "name": s.name,
            "quantity": h.quantity,
            "avg_price": float(h.avg_price),
            "price": float(s.last_price),
            "value": float(h.quantity * s.last_price),
            "pnl": float(h.quantity * (s.last_price - h.avg_price)),
        }
        for h, s in rows
    ]
    total = float(cash) + sum(h["value"] for h in holdings)
    return {
        "event": event.slug if event else None,
        "initial_cash": float(initial),
        "cash": float(cash),
        "holdings": holdings,
        "total_value": total,
        "return_rate": total / float(initial) - 1,
    }


async def execute_trade(
    session: AsyncSession, user_id: int, event: Event | None, symbol: str, side: Literal["buy", "sell"], quantity: int
) -> Trade:
    now = now_kst()
    if not is_market_open(now):
        raise HTTPException(409, "장 운영 시간이 아닙니다.")
    if event and not (event.start_date <= now.date() <= event.end_date):
        raise HTTPException(409, "이벤트 기간이 아닙니다.")
    stock = await session.scalar(select(Stock).where(Stock.symbol == symbol, Stock.is_active))
    if stock is None:
        raise HTTPException(404, "종목을 찾을 수 없습니다.")
    stale_after = timedelta(seconds=settings.price_interval_seconds * 3)
    if stock.last_price is None or stock.last_price_at < datetime.now(timezone.utc) - stale_after:
        raise HTTPException(409, "최신 가격이 없어 체결할 수 없습니다.")

    # 첫 거래면 계좌를 만든다 — 동시 첫 주문은 ON CONFLICT로 하나만 생성
    if side == "buy":
        initial = _initial_cash(event)
        await session.execute(
            insert(Account)
            .values(user_id=user_id, event_id=event.id if event else None, initial_cash=initial, cash=initial)
            .on_conflict_do_nothing()
        )
    # 계좌 행 잠금 — 같은 계좌의 동시 주문을 직렬화해 현금 음수·초과 매도를 막는다
    account = await session.scalar(_find_account(user_id, event).with_for_update())
    holding = account and await session.get(Holding, (account.id, stock.id))
    price = stock.last_price
    amount = price * quantity
    realized = None

    if side == "buy":
        if account.cash < amount:
            raise HTTPException(409, "현금이 부족합니다.")
        account.cash -= amount
        if holding:
            new_qty = holding.quantity + quantity
            holding.avg_price = ((holding.avg_price * holding.quantity + amount) / new_qty).quantize(Decimal("0.0001"))
            holding.quantity = new_qty
        else:
            session.add(Holding(account_id=account.id, stock_id=stock.id, quantity=quantity, avg_price=price))
    else:
        if not holding or holding.quantity < quantity:
            raise HTTPException(409, "보유 수량이 부족합니다.")
        account.cash += amount
        realized = ((price - holding.avg_price) * quantity).quantize(Decimal("0.01"))
        holding.quantity -= quantity
        if holding.quantity == 0:
            await session.delete(holding)

    tick_id = await session.scalar(
        select(PriceTick.id).where(PriceTick.stock_id == stock.id).order_by(PriceTick.collected_at.desc()).limit(1)
    )
    trade = Trade(
        account_id=account.id, stock_id=stock.id, tick_id=tick_id, side=side,
        quantity=quantity, price=price, amount=amount, realized_pnl=realized,
    )
    session.add(trade)
    await session.commit()
    return trade
