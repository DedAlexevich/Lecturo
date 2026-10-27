from app.config import load_settings
from app.handlers import open_app_markup
from app.storage import CONFIRM_START, confirm_start, save_chat_id


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


class FakePool:
    def __init__(self, status):
        self.status = status
        self.calls = []
        self.queries = []

    async def execute(self, query, *args):
        self.calls.append(args)
        self.queries.append(query)
        return self.status


async def test_save_chat_id_reports_whether_user_found():
    pool = FakePool("UPDATE 1")
    assert await save_chat_id(pool, 42, 777) is True
    assert pool.calls == [(777, "42")]
    assert await save_chat_id(FakePool("UPDATE 0"), 43, 1) is False


async def test_start_confirms_bot_for_linked_telegram():
    pool = FakePool("UPDATE 1")
    assert await confirm_start(pool, 42) is True
    assert pool.queries == [CONFIRM_START]
    assert pool.calls == [("42",)]
    assert "bot_started_at = now()" in CONFIRM_START
    assert "bot_blocked_at = NULL" in CONFIRM_START
    assert await confirm_start(FakePool("UPDATE 0"), 43) is False
