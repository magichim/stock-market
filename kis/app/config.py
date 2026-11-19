from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # kis/.env — cwd와 무관하게 항상 kis 디렉터리의 .env를 읽는다
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    kis_env: Literal["demo", "real"] = "demo"
    kis_allow_order: bool = False

    kis_app_key: str = ""
    kis_app_secret: str = ""
    kis_paper_app_key: str = ""
    kis_paper_app_secret: str = ""
    kis_hts_id: str = ""
    kis_acct_stock: str = ""
    kis_acct_future: str = ""
    kis_paper_acct_stock: str = ""
    kis_paper_acct_future: str = ""
    kis_prod: str = "01"

    @property
    def svr(self) -> str:
        """kis_auth의 서버 구분 — prod: 실전, vps: 모의."""
        return "prod" if self.kis_env == "real" else "vps"

    @property
    def configured(self) -> bool:
        if self.kis_env == "real":
            return bool(self.kis_app_key and self.kis_app_secret)
        return bool(self.kis_paper_app_key and self.kis_paper_app_secret)


settings = Settings()
