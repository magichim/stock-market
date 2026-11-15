from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # backend/.env — cwd와 무관하게 항상 backend 디렉터리의 .env를 읽는다
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parent.parent / ".env",
        extra="ignore",  # Settings에 없는 .env 키 허용
    )

    # agisaja.com 백엔드와 같은 JWT 서명 키 (필수)
    jwt_secret: str
    # agisaja.com이 COOKIE_DOMAIN으로 발급하는 access 쿠키 이름 (로컬 COOKIE_SECURE=false면 "at")
    access_cookie: str = "__Secure-at"
    # predict-market 백엔드 주소 — 사용자 프로필을 내부 API(/api/internal/users)로 조회한다 (AUTH.md). 로컬은 http://localhost:8000
    internal_predict_api_url: str = "https://agisaja.com"
    # 내부 API Bearer 토큰 — predict-market INTERNAL_API_TOKEN과 같은 값 (필수)
    internal_api_token: str
    # 이 서비스 주소 — CSRF Origin 검사에 쓴다
    site_url: str = "https://stock.agisaja.com"

    # 이 서비스 전용 DB (DB_DESIGN.md)
    database_url: str = "postgresql+asyncpg://dev@localhost:5432/stock_market"
    # predict-market과 같은 Redis를 써도 된다 — 키는 모두 stock: 접두어
    redis_url: str = "redis://localhost:6379/0"

    # 가격 공급자. mock은 랜덤 워크 (실 거래소 API 연동 전 개발용)
    price_provider: Literal["mock"] = "mock"
    # 가격 수집 주기(초)
    price_interval_seconds: int = 60
    # 장 운영 시간 검사를 끈다 — 로컬 개발에서 밤·주말에도 수집·거래하려면 true
    ignore_market_hours: bool = False
    # 기본 계좌 시작 자금 (원)
    initial_cash: int = 10_000_000


settings = Settings()
