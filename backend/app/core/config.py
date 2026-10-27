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

    log_dir: Path | None = None
    log_service: str = "app"
    log_max_mb: int = 10
    log_backup_count: int = 5

    stt_provider: str = "stub"
    yandex_speechkit_api_key: str = ""
    yandex_folder_id: str = ""
    yandex_storage_bucket: str = ""
    yandex_storage_access_key: str = ""
    yandex_storage_secret_key: str = ""

    llm_provider: str = "stub"
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"

    embeddings_provider: str = "stub"
    embeddings_base_url: str = ""
    embeddings_api_key: str = ""
    embeddings_model: str = ""
    yandex_embeddings_base_url: str = "https://ai.api.cloud.yandex.net"
    yandex_embeddings_api_key: str = ""
    yandex_embeddings_folder_id: str = ""

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""

    telegram_bot_token: str = ""
    telegram_bot_username: str = ""

    vk_client_id: str = ""
    vk_redirect_uri: str = ""
    vk_authorize_url: str = "https://id.vk.com/authorize"
    vk_token_url: str = "https://id.vk.com/oauth2/auth"
    vk_user_info_url: str = "https://id.vk.com/oauth2/user_info"
    vk_start_rate_limit: int = 30
    vk_start_rate_window_seconds: int = 3600

    yandex_oauth_client_id: str = ""
    yandex_oauth_redirect_uri: str = ""
    yandex_oauth_client_secret: str = ""
    yandex_oauth_authorize_url: str = "https://oauth.yandex.ru/authorize"
    yandex_oauth_token_url: str = "https://oauth.yandex.ru/token"
    yandex_oauth_user_info_url: str = "https://login.yandex.ru/info"
    yandex_oauth_start_rate_limit: int = 30
    yandex_oauth_start_rate_window_seconds: int = 3600

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
    regenerate_summary_rate_window_seconds: int = 300
    complaints_rate_limit: int = 5
    complaints_rate_window_seconds: int = 3600
    auth_mail_rate_limit: int = 3
    auth_mail_ip_rate_limit: int = 20
    auth_mail_address_rate_limit: int = 10
    auth_mail_rate_window_seconds: int = 3600
    account_delete_rate_limit: int = 5
    account_delete_rate_window_seconds: int = 3600
    password_change_rate_limit: int = 10
    password_change_rate_window_seconds: int = 3600

    @property
    def yandex_oauth_enabled(self) -> bool:
        return bool(self.yandex_oauth_client_id and self.yandex_oauth_redirect_uri)

    @property
    def vk_enabled(self) -> bool:
        return bool(self.vk_client_id and self.vk_redirect_uri)


@lru_cache
def get_settings() -> Settings:
    return Settings()
