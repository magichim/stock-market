"""계좌 조회와 체결·환전. 오더북이 없어 주문은 그 시점 최신가로 즉시 전량 체결된다 (DB_DESIGN.md "체결 규칙").

현금은 통화별(account_balances)로 두고, 종목은 그 종목 통화의 현금으로만 사고판다. 평가액·수익률은 KRW 환산.
"""

from datetime import datetime, timedelta, timezone
from decimal import ROUND_DOWN, Decimal
from typing import Literal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .market import is_market_open, now_kst
from .models import Account, AccountBalance, Event, Exchange, FxRate, Holding, PriceTick, Stock, Trade

BASE_CURRENCY = "KRW"


def _initial_cash(event: Event | None) -> Decimal:
    return event.initial_cash if event else Decimal(settings.initial_cash)


def _find_account(user_id: int, event: Event | None):
    return select(Account).where(
        Account.user_id == user_id,
        Account.event_id == event.id if event else Account.event_id.is_(None),
    )


async def account_summary(session: AsyncSession, user_id: int, event: Event | None) -> dict:
    """계좌가 아직 없으면(첫 거래 전) KRW 시작 자금만 있는 빈 계좌로 응답한다."""
    account = await session.scalar(_find_account(user_id, event))
    initial = account.initial_cash if account else _initial_cash(event)
    # 환율이 아직 없는 통화는 0으로 환산한다 (수집 전에는 그 통화 잔액·보유가 생길 수 없다)
    rates = {c: r for c, r in await session.execute(select(FxRate.currency, FxRate.rate)) if r is not None}
    if account:
        cash = dict(
            (await session.execute(
                select(AccountBalance.currency, AccountBalance.amount).where(AccountBalance.account_id == account.id)
            )).all()
        )
        rows = (await session.execute(
            select(Holding, Stock).join(Stock, Stock.id == Holding.stock_id)
            .where(Holding.account_id == account.id).order_by(Stock.display_order, Stock.symbol)
        )).all()
    else:
        cash, rows = {BASE_CURRENCY: initial}, []
    balances = [
        {"currency": c, "amount": float(a), "rate": float(rates.get(c, 0)), "value": float(a * rates.get(c, 0))}
        for c, a in sorted(cash.items(), key=lambda x: x[0] != BASE_CURRENCY)
    ]
    holdings = [
        {
            "symbol": s.symbol,
            "name": s.name,
            "currency": s.currency,
            "quantity": h.quantity,
            "avg_price": float(h.avg_price),
            "price": float(s.last_price),
            "value": float(h.quantity * s.last_price),
            "pnl": float(h.quantity * (s.last_price - h.avg_price)),
            "value_krw": float(h.quantity * s.last_price * rates.get(s.currency, 0)),
        }
        for h, s in rows
    ]
    total = sum(b["value"] for b in balances) + sum(h["value_krw"] for h in holdings)
    return {
        "event": event.slug if event else None,
        "initial_cash": float(initial),
        "balances": balances,
        "holdings": holdings,
        "total_value": total,
        "return_rate": total / float(initial) - 1,
    }


def _check_tradable(event: Event | None) -> None:
    now = now_kst()
    if not is_market_open(now):
        raise HTTPException(409, "장 운영 시간이 아닙니다.")
    if event and not (event.start_date <= now.date() <= event.end_date):
        raise HTTPException(409, "이벤트 기간이 아닙니다.")


def _is_stale(at: datetime | None) -> bool:
    return at is None or at < datetime.now(timezone.utc) - timedelta(seconds=settings.price_interval_seconds * 3)


async def _lock_account(session: AsyncSession, user_id: int, event: Event | None, create: bool) -> Account | None:
    """계좌 행 잠금 — 같은 계좌의 동시 주문·환전을 직렬화해 잔액 음수·초과 매도를 막는다.

    create면 첫 거래 때 계좌와 KRW 시작 자금을 만든다 — 동시 첫 주문은 ON CONFLICT로 하나만 생성.
    """
    if create:
        initial = _initial_cash(event)
        new_id = await session.scalar(
            insert(Account)
            .values(user_id=user_id, event_id=event.id if event else None, initial_cash=initial)
            .on_conflict_do_nothing()
            .returning(Account.id)
        )
        if new_id:
            session.add(AccountBalance(account_id=new_id, currency=BASE_CURRENCY, amount=initial))
            await session.flush()
    return await session.scalar(_find_account(user_id, event).with_for_update())


async def _balance(session: AsyncSession, account_id: int, currency: str) -> AccountBalance:
    """통화 잔액 행 — 없으면 0으로 만든다."""
    balance = await session.get(AccountBalance, (account_id, currency))
    if balance is None:
        balance = AccountBalance(account_id=account_id, currency=currency, amount=Decimal(0))
        session.add(balance)
    return balance


async def execute_trade(
    session: AsyncSession, user_id: int, event: Event | None, symbol: str, side: Literal["buy", "sell"], quantity: int
) -> Trade:
    _check_tradable(event)
    stock = await session.scalar(select(Stock).where(Stock.symbol == symbol, Stock.is_active))
    if stock is None:
        raise HTTPException(404, "종목을 찾을 수 없습니다.")
    if stock.last_price is None or _is_stale(stock.last_price_at):
        raise HTTPException(409, "최신 가격이 없어 체결할 수 없습니다.")

    account = await _lock_account(session, user_id, event, create=side == "buy")
    holding = account and await session.get(Holding, (account.id, stock.id))
    price = stock.last_price
    amount = price * quantity
    realized = None

    if side == "buy":
        balance = await _balance(session, account.id, stock.currency)
        if balance.amount < amount:
            raise HTTPException(409, f"{stock.currency} 잔액이 부족합니다.")
        balance.amount -= amount
        if holding:
            new_qty = holding.quantity + quantity
            holding.avg_price = ((holding.avg_price * holding.quantity + amount) / new_qty).quantize(Decimal("0.0001"))
            holding.quantity = new_qty
        else:
            session.add(Holding(account_id=account.id, stock_id=stock.id, quantity=quantity, avg_price=price))
    else:
        if not holding or holding.quantity < quantity:
            raise HTTPException(409, "보유 수량이 부족합니다.")
        (await _balance(session, account.id, stock.currency)).amount += amount
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


async def execute_exchange(
    session: AsyncSession, user_id: int, event: Event | None, from_currency: str, to_currency: str, amount: Decimal
) -> Exchange:
    """from 통화 amount를 최신 환율로 to 통화로 바꾼다. 받는 금액은 0.01 단위 내림."""
    _check_tradable(event)
    if from_currency == to_currency:
        raise HTTPException(422, "같은 통화로는 환전할 수 없습니다.")
    rates = {r.currency: r for r in await session.scalars(select(FxRate).where(FxRate.currency.in_([from_currency, to_currency])))}
    for c in (from_currency, to_currency):
        r = rates.get(c)
        if r is None:
            raise HTTPException(404, f"지원하지 않는 통화입니다: {c}")
        if r.rate is None or (c != BASE_CURRENCY and _is_stale(r.rate_at)):
            raise HTTPException(409, "최신 환율이 없어 환전할 수 없습니다.")
    rate = rates[from_currency].rate / rates[to_currency].rate
    received = (amount * rate).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    if received <= 0:
        raise HTTPException(422, "환전 금액이 너무 작습니다.")

    account = await _lock_account(session, user_id, event, create=True)
    source = await _balance(session, account.id, from_currency)
    if source.amount < amount:
        raise HTTPException(409, f"{from_currency} 잔액이 부족합니다.")
    source.amount -= amount
    (await _balance(session, account.id, to_currency)).amount += received
    exchange = Exchange(
        account_id=account.id, from_currency=from_currency, to_currency=to_currency,
        from_amount=amount, to_amount=received, rate=rate.quantize(Decimal("0.00000001")),
    )
    session.add(exchange)
    await session.commit()
    return exchange
