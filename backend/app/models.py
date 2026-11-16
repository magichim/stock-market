"""DB_DESIGN.md의 스키마 (이 서비스 전용 DB). users는 predict-market DB에 있어 FK 없이 id만 저장한다."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

def _pk() -> Mapped[int]:
    return mapped_column(BigInteger, Identity(always=True), primary_key=True)


def _now() -> Mapped[datetime]:
    return mapped_column(TIMESTAMP(timezone=True), server_default=func.now())


class Stock(Base):
    __tablename__ = "stocks"

    id: Mapped[int] = _pk()
    symbol: Mapped[str] = mapped_column(String(12), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    market: Mapped[str] = mapped_column(String(10))
    currency: Mapped[str] = mapped_column(String(3), server_default="KRW")  # 거래 통화 — 가격·평단·체결 금액의 단위
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    display_order: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    last_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    last_price_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    prev_close: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    created_at: Mapped[datetime] = _now()


class PriceTick(Base):
    __tablename__ = "price_ticks"
    __table_args__ = (
        UniqueConstraint("stock_id", "collected_at"),
        CheckConstraint("price > 0"),
    )

    id: Mapped[int] = _pk()
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id", ondelete="CASCADE"))
    price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    collected_at: Mapped[datetime] = _now()


class FxRate(Base):
    """통화별 최신 환율 (기준 통화 KRW). KRW는 1로 고정, 나머지는 수집기가 갱신한다."""

    __tablename__ = "fx_rates"
    __table_args__ = (CheckConstraint("rate > 0"),)

    currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    rate: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))  # 1 통화 단위 = rate KRW
    rate_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (CheckConstraint("initial_cash > 0"), CheckConstraint("start_date <= end_date"))

    id: Mapped[int] = _pk()
    slug: Mapped[str] = mapped_column(String(40), unique=True)
    title: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, server_default="")
    initial_cash: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    start_date: Mapped[date] = mapped_column(Date)  # KST
    end_date: Mapped[date] = mapped_column(Date)  # KST, 포함
    published: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[datetime] = _now()


class Account(Base):
    """사용자 × (기본 | 이벤트)당 1개. event_id가 NULL이면 기본 계좌."""

    __tablename__ = "accounts"
    __table_args__ = (UniqueConstraint("user_id", "event_id", postgresql_nulls_not_distinct=True),)

    id: Mapped[int] = _pk()
    user_id: Mapped[int] = mapped_column(BigInteger)  # predict-market users.id — 다른 DB라 FK 없음 (탈퇴 정리는 users.py)
    event_id: Mapped[int | None] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"))
    initial_cash: Mapped[Decimal] = mapped_column(Numeric(18, 2))  # KRW
    created_at: Mapped[datetime] = _now()


class AccountBalance(Base):
    """계좌 × 통화별 현금. 계좌 생성 시 KRW 시작 자금, 다른 통화는 환전·매도로 생긴다. 0이 돼도 행은 남긴다."""

    __tablename__ = "account_balances"
    __table_args__ = (CheckConstraint("amount >= 0"),)

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    currency: Mapped[str] = mapped_column(ForeignKey("fx_rates.currency"), primary_key=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))


class Exchange(Base):
    """append-only 환전 내역 — 그 시점 최신 환율로 즉시 체결된다."""

    __tablename__ = "exchanges"
    __table_args__ = (
        CheckConstraint("from_currency <> to_currency"),
        CheckConstraint("from_amount > 0"),
        CheckConstraint("to_amount > 0"),
        Index("idx_exchanges_account_time", "account_id", "executed_at"),
    )

    id: Mapped[int] = _pk()
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    from_currency: Mapped[str] = mapped_column(ForeignKey("fx_rates.currency"))
    to_currency: Mapped[str] = mapped_column(ForeignKey("fx_rates.currency"))
    from_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    to_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 8))  # from 1단위당 to 수량
    executed_at: Mapped[datetime] = _now()


class Holding(Base):
    __tablename__ = "holdings"
    __table_args__ = (CheckConstraint("quantity > 0"),)

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"), primary_key=True)
    quantity: Mapped[int] = mapped_column(BigInteger)
    avg_price: Mapped[Decimal] = mapped_column(Numeric(16, 4))  # 이동평균 매입가 (종목 통화)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())


class Trade(Base):
    """append-only 체결 내역 — 주문은 최신가로 즉시 전량 체결되므로 주문 = 체결."""

    __tablename__ = "trades"
    __table_args__ = (
        CheckConstraint("side IN ('buy', 'sell')"),
        CheckConstraint("quantity > 0"),
        Index("idx_trades_account_time", "account_id", "executed_at"),
    )

    id: Mapped[int] = _pk()
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"))
    tick_id: Mapped[int | None] = mapped_column(ForeignKey("price_ticks.id"))
    side: Mapped[str] = mapped_column(String(4))
    quantity: Mapped[int] = mapped_column(BigInteger)
    price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))  # 가격·금액·손익은 종목 통화
    realized_pnl: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    executed_at: Mapped[datetime] = _now()


class EquitySnapshot(Base):
    """장 마감 후 계좌 평가액 — 월간·연간·이벤트 수익률의 기준점."""

    __tablename__ = "equity_snapshots"

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    snapshot_date: Mapped[date] = mapped_column(Date, primary_key=True)  # KST 거래일
    total_value: Mapped[Decimal] = mapped_column(Numeric(18, 2))  # KRW 환산

