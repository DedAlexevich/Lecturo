from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
KNOWN_SECRET_KEYS = {"dev-secret-change-me-before-production", "change-me-to-a-long-random-string"}
MIN_SECRET_KEY_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    public_url: str = "http://localhost"
    secret_key: str = "dev-secret-change-me-before-production"
    access_token_ttl_minutes: int = 60 * 24 * 30

    database_url: str = "postgresql+asyncpg://lecturo:lecturo@db:5432/lecturo"
    redis_url: str = "redis://redis:6379/0"
    storage_dir: Path = Path("/data/storage")
    youtube_proxy: str = ""
    youtube_cookies: Path | None = None

    log_dir: Path | None = None
    log_service: str = "app"
    log_max_mb: int = 10
    log_backup_count: int = 5
    log_stream_limit: int = 3

    backup_dir: Path = Path("/backups")
    backup_max_upload_mb: int = 2048
    zoomer_max_upload_mb: int = 30
    zoomer_max_duration_sec: int = 180
    restore_idle_wait_seconds: int = 300

    stt_provider: str = "stub"
    yandex_speechkit_api_key: str = ""
    yandex_folder_id: str = ""
    yandex_storage_bucket: str = ""
    yandex_storage_access_key: str = ""
    yandex_storage_secret_key: str = ""
    stt_retry_attempts: int = 5
    stt_retry_base_seconds: float = 2.0
    stt_retry_factor: float = 3.0
    stt_retry_max_seconds: float = 60.0
    stt_poll_seconds: float = 3.0
    stt_expected_ratio: float = 0.3
    stt_expected_min_seconds: float = 45.0
    stt_chunk_threshold_seconds: float = 720.0
    stt_chunk_target_seconds: float = 420.0
    stt_parallel_parts: int = 3
    eta_download_ratio: float = 0.1
    eta_audio_ratio: float = 0.01
    eta_summarize_ratio: float = 0.05
    eta_embed_ratio: float = 0.01
    upload_stale_hours: int = 24
    upload_max_pending: int = 5
    worker_max_jobs: int = 4

    llm_provider: str = "stub"
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    llm_timeout: float = 600.0
    llm_max_tokens: int = 8192

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
    complaints_email: str = ""

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
    local_max_total_chars: int = 1_000_000
    local_timecode_tolerance_sec: float = 1.0
    local_results_rate_limit: int = 10
    local_results_rate_window_seconds: int = 60
    regenerate_summary_rate_window_seconds: int = 300
    exam_sheet_rate_window_seconds: int = 300
    exam_sheet_failure_ttl_seconds: int = 7 * 24 * 3600
    link_rate_limit: int = 10
    link_rate_window_seconds: int = 60
    link_inspect_timeout_seconds: float = 90.0
    complaints_rate_limit: int = 5
    complaints_rate_window_seconds: int = 3600
    promo_rate_limit: int = 10
    promo_rate_window_seconds: int = 3600
    public_copy_daily_limit: int = 20
    public_export_rate_limit: int = 30
    public_export_rate_window_seconds: int = 3600
    lecture_chat_rate_limit: int = 40
    search_rate_limit: int = 30
    search_rate_window_seconds: int = 60
    pdf_export_rate_limit: int = 10
    pdf_export_rate_window_seconds: int = 60
    pdf_render_concurrency: int = 2
    lecture_chat_rate_window_seconds: int = 60
    auth_mail_rate_limit: int = 3
    auth_mail_ip_rate_limit: int = 20
    auth_mail_address_rate_limit: int = 10
    auth_mail_rate_window_seconds: int = 3600
    account_delete_rate_limit: int = 5
    account_delete_rate_window_seconds: int = 3600
    password_change_rate_limit: int = 10
    password_change_rate_window_seconds: int = 3600
    login_rate_limit: int = 10
    login_ip_rate_limit: int = 50
    login_rate_window_seconds: int = 900
    register_rate_limit: int = 10
    register_rate_window_seconds: int = 3600

    initial_admins: str = ""

    @property
    def is_local(self) -> bool:
        parts = urlsplit(self.public_url)
        host = parts.hostname or ""
        is_local_host = host in LOCAL_HOSTS or host.endswith(".localhost")
        return is_local_host and parts.scheme != "https"

    @model_validator(mode="after")
    def check_secret_key(self) -> "Settings":
        if self.is_local:
            return self
        if self.secret_key in KNOWN_SECRET_KEYS or len(self.secret_key) < MIN_SECRET_KEY_LENGTH:
            raise ValueError(
                f"SECRET_KEY must be a unique random string of at least {MIN_SECRET_KEY_LENGTH} "
                "characters when PUBLIC_URL is not localhost, generate it with openssl rand -hex 32"
            )
        return self

    @property
    def yandex_oauth_enabled(self) -> bool:
        return bool(self.yandex_oauth_client_id and self.yandex_oauth_redirect_uri)

    @property
    def vk_enabled(self) -> bool:
        return bool(self.vk_client_id and self.vk_redirect_uri)


@lru_cache
def get_settings() -> Settings:
    return Settings()
