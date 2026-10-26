import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    token: str
    public_url: str
    database_url: str


def load_settings() -> Settings:
    database_url = os.environ.get("DATABASE_URL", "")
    return Settings(
        token=os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(),
        public_url=os.environ.get("PUBLIC_URL", "").strip().rstrip("/"),
        database_url=database_url.replace("postgresql+asyncpg://", "postgresql://", 1),
    )
