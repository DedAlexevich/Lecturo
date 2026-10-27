import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    token: str
    public_url: str
    database_url: str
    redis_url: str
    free_weekly_seconds: int
    subscription_weekly_seconds: int


def load_settings() -> Settings:
    database_url = os.environ.get("DATABASE_URL", "")
    return Settings(
        token=os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(),
        public_url=os.environ.get("PUBLIC_URL", "").strip().rstrip("/"),
        database_url=database_url.replace("postgresql+asyncpg://", "postgresql://", 1),
        redis_url=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
        free_weekly_seconds=int(os.environ.get("FREE_WEEKLY_SECONDS", 7200)),
        subscription_weekly_seconds=int(os.environ.get("SUBSCRIPTION_WEEKLY_SECONDS", 36000)),
    )
