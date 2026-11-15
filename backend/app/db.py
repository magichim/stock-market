import asyncpg
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
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
