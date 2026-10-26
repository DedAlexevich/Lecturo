from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    public_url: str = "http://localhost"
    secret_key: str = "dev-secret-change-me-before-production"
    access_token_ttl_minutes: int = 60 * 24 * 30

    database_url: str = "postgresql+asyncpg://lecturo:lecturo@db:5432/lecturo"
    redis_url: str = "redis://redis:6379/0"
    storage_dir: Path = Path("/data/storage")

    stt_provider: str = "stub"
    yandex_speechkit_api_key: str = ""
    yandex_folder_id: str = ""
    yandex_storage_bucket: str = ""
    yandex_storage_access_key: str = ""
    yandex_storage_secret_key: str = ""
    salute_auth_key: str = ""

    llm_provider: str = "stub"
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"

    embeddings_provider: str = "stub"
    embeddings_base_url: str = ""
    embeddings_api_key: str = ""
    embeddings_model: str = ""

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""

    telegram_bot_token: str = ""
    telegram_bot_username: str = ""

    yookassa_shop_id: str = ""
    yookassa_secret_key: str = ""
    yookassa_api_url: str = "https://api.yookassa.ru/v3"
    yookassa_receipt: bool = False

    free_weekly_seconds: int = 2 * 3600
    subscription_weekly_seconds: int = 10 * 3600
    subscription_price_rub: int = 299
    subscription_days: int = 30
    hour_packages: dict[int, int] = {5: 199, 10: 349}
    free_video_retention_days: int = 3
    subscription_video_retention_days: int = 30
    local_embeddings_weekly_seconds: int = 10 * 3600
    local_lectures_weekly_count: int = 20
    local_min_chars_per_minute: float = 100.0
    local_max_chars_per_minute: float = 3000.0
    local_max_segments: int = 20000
    local_max_chapters: int = 500
    local_max_text_chars: int = 5000
    local_timecode_tolerance_sec: float = 1.0
    local_results_rate_limit: int = 10
    local_results_rate_window_seconds: int = 60


@lru_cache
def get_settings() -> Settings:
    return Settings()
