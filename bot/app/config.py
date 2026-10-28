import os
from dataclasses import dataclass
from datetime import timedelta


@dataclass(frozen=True)
class Settings:
    token: str
    public_url: str
    database_url: str
    bot_redis_url: str
    free_weekly_seconds: int
    subscription_weekly_seconds: int
    admin_alert_interval: timedelta


def load_settings() -> Settings:
    database_url = os.environ.get("DATABASE_URL", "")
    return Settings(
        token=os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(),
        public_url=os.environ.get("PUBLIC_URL", "").strip().rstrip("/"),
        database_url=database_url.replace("postgresql+asyncpg://", "postgresql://", 1),
        bot_redis_url=os.environ.get("BOT_REDIS_URL", "redis://localhost:6379/0"),
        free_weekly_seconds=int(os.environ.get("FREE_WEEKLY_SECONDS", 7200)),
        subscription_weekly_seconds=int(os.environ.get("SUBSCRIPTION_WEEKLY_SECONDS", 36000)),
        admin_alert_interval=timedelta(
            minutes=max(1, int(os.environ.get("ADMIN_ALERT_INTERVAL_MINUTES", 15)))
        ),
    )
