import asyncpg
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings

# 이 서비스 전용 DB — 종목·가격·계좌·거래 (DB_DESIGN.md)
engine = create_async_engine(
    settings.database_url,
    pool_size=10,        # 상시 유지 커넥션 수 (단일 uvicorn 워커 기준)
    max_overflow=20,     # 순간 부하 시 추가 허용 커넥션 (유휴 시 즉시 반납)
    pool_timeout=30,     # 풀 고갈 시 대기 한도(초)
    pool_recycle=1800,   # 30분 지난 커넥션은 재생성 (서버/방화벽의 idle 종료 대비)
    pool_pre_ping=True,  # 체크아웃 시 살아있는지 확인, 끊긴 커넥션 자동 교체
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


# create_all은 없는 테이블만 만들고 기존 테이블은 바꾸지 않는다 — 기존 테이블의 컬럼·인덱스·제약 변경은
# models.py를 고치고 여기에 같은 변경을 멱등 SQL로 덧붙인다 (새 DB는 create_all, 기존 DB는 이 패치로 맞춰진다).
# - 여러 번 실행해도 안전해야 한다 (ADD COLUMN IF NOT EXISTS, CREATE INDEX IF NOT EXISTS, DO 블록 등)
# - 순서대로 실행된다. 모든 환경(로컬·운영)에 반영되기 전에는 지우지 않는다
SCHEMA_PATCHES: list[str] = [
    # 예: "ALTER TABLE trades ADD COLUMN IF NOT EXISTS fee NUMERIC(18,2) NOT NULL DEFAULT 0",
    # 다통화 — 종목 통화, 환율 기준 행(KRW = 1, 시드보다 먼저 필요한 FK 대상)
    "ALTER TABLE stocks ADD COLUMN IF NOT EXISTS currency VARCHAR(3) NOT NULL DEFAULT 'KRW'",
    "INSERT INTO fx_rates (currency, rate) VALUES ('KRW', 1) ON CONFLICT DO NOTHING",
    # accounts.cash → account_balances(KRW)로 옮기고, 원래 컬럼은 지우지 않고 legacy_cash로 남긴다 (모든 환경 반영 후 삭제)
    """DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema = current_schema() AND table_name = 'accounts' AND column_name = 'cash') THEN
            INSERT INTO account_balances (account_id, currency, amount)
                SELECT id, 'KRW', cash FROM accounts ON CONFLICT DO NOTHING;
            ALTER TABLE accounts RENAME COLUMN cash TO legacy_cash;
            ALTER TABLE accounts ALTER COLUMN legacy_cash DROP NOT NULL;
        END IF;
    END $$""",
    # 종목 종류 — 개별 종목(stock) | ETF. 컬럼이 생기기 전에 시드로 들어간 ETF 행을 맞춘다
    "ALTER TABLE stocks ADD COLUMN IF NOT EXISTS kind VARCHAR(10) NOT NULL DEFAULT 'stock' CHECK (kind IN ('stock', 'etf'))",
    # NXT(넥스트레이드) 거래 종목 여부 — 수집기가 하루 한 번 KIS로 확인해 채운다
    "ALTER TABLE stocks ADD COLUMN IF NOT EXISTS nxt_tradable BOOLEAN NOT NULL DEFAULT false",
    # 전일 종가는 stock_closes(날짜별 종가)에서 읽는다
    "ALTER TABLE stocks DROP COLUMN IF EXISTS prev_close",
    "UPDATE stocks SET kind = 'etf' WHERE kind = 'stock' AND symbol IN ('069500', '229200', '379800', '379810', '091160', '305720')",
]


async def apply_schema_patches(conn: AsyncConnection) -> None:
    for sql in SCHEMA_PATCHES:
        await conn.execute(text(sql))


async def ensure_database() -> None:
    """DATABASE_URL의 DB가 없으면 같은 계정으로 만든다 (계정에 CREATEDB 권한 필요). 있으면 아무것도 하지 않는다."""
    url = make_url(settings.database_url).set(drivername="postgresql")
    try:
        await (await asyncpg.connect(url.render_as_string(hide_password=False))).close()
        return
    except asyncpg.InvalidCatalogNameError:
        pass
    conn = await asyncpg.connect(url.set(database="postgres").render_as_string(hide_password=False))
    try:
        await conn.execute(f'CREATE DATABASE "{url.database.replace(chr(34), chr(34) * 2)}"')
    except asyncpg.DuplicateDatabaseError:
        pass  # 다른 워커가 먼저 만듦
    except asyncpg.InsufficientPrivilegeError as e:
        raise RuntimeError(
            f"DB '{url.database}'가 없고 '{url.username}'에 CREATEDB 권한이 없다 — "
            f"superuser로 `createdb -O {url.username} {url.database}`를 실행한다"
        ) from e
    finally:
        await conn.close()
