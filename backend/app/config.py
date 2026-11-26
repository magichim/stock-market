from pathlib import Path
from typing import Literal

from pydantic import field_validator
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

    # 실행 환경. dev는 수집·종가 기록을 정해진 시각보다 30초 늦게 실행한다 — 같은 KIS 앱키를 쓰는 운영과 호출 시각이 겹쳐 초당 호출 한도에 걸리지 않게
    app_env: Literal["prod", "dev"] = "prod"

    # 이 서비스 전용 DB (DB_DESIGN.md)
    database_url: str = "postgresql+asyncpg://dev@localhost:5432/stock_market"
    # predict-market과 같은 Redis를 써도 된다 — 키는 모두 stock: 접두어
    redis_url: str = "redis://localhost:6379/0"

    # 가격 공급자. mock은 랜덤 워크(개발용), kis는 KIS 게이트웨이(kis/)에서 받는다
    price_provider: Literal["mock", "kis"] = "mock"
    kis_api_url: str = "http://localhost:8200"
    # 시세를 수집할 국가 — KR(KOSPI·KOSDAQ), US(NASDAQ·NYSE)를 쉼표로. 빠진 국가의 종목·환율은 갱신하지 않는다
    price_countries: str = "KR,US"
    # 가격 수집 주기(초)
    price_interval_seconds: int = 3600  # 수집 주기 (1시간)
    # 장 운영 시간 검사를 끈다 — 로컬 개발에서 밤·주말에도 수집·거래하려면 true
    ignore_market_hours: bool = False
    # 기본 계좌 시작 자금 (원)
    initial_cash: int = 10_000_000

    @field_validator("price_countries")
    @classmethod
    def _countries(cls, v: str) -> str:
        codes = {c.strip().upper() for c in v.split(",") if c.strip()}
        if not codes or codes - {"KR", "US"}:
            raise ValueError("PRICE_COUNTRIES는 KR, US 중 하나 이상을 쉼표로 적는다")
        return ",".join(sorted(codes))


settings = Settings()
