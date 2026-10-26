from app.config import load_settings
from app.handlers import open_app_markup


def test_button_only_for_https_url():
    assert open_app_markup("") is None
    assert open_app_markup("http://localhost") is None
    markup = open_app_markup("https://lecturo.example")
    assert markup.inline_keyboard[0][0].web_app.url == "https://lecturo.example"


def test_settings_strip_driver_and_slash(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@db:5432/x")
    monkeypatch.setenv("PUBLIC_URL", "https://lecturo.example/")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    settings = load_settings()
    assert settings.database_url == "postgresql://u:p@db:5432/x"
    assert settings.public_url == "https://lecturo.example"
    assert settings.token == ""
