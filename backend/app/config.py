from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # backend/.env — cwd와 무관하게 항상 backend 디렉터리의 .env를 읽는다
    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parent.parent / ".env", extra="ignore")

    # agisaja.com 백엔드와 같은 JWT 서명 키 (필수)
    jwt_secret: str
    # agisaja.com이 COOKIE_DOMAIN으로 발급하는 access 쿠키 이름 (로컬 COOKIE_SECURE=false면 "at")
    access_cookie: str = "__Secure-at"


settings = Settings()
