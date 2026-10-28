import pytest
from pydantic import ValidationError

from app.core.config import Settings

STRONG_KEY = "a" * 64


@pytest.mark.parametrize(
    "public_url", ["http://localhost", "http://127.0.0.1:8080", "http://app.localhost"]
)
def test_local_url_allows_default_key(public_url: str) -> None:
    settings = Settings(public_url=public_url)

    assert settings.secret_key == "dev-secret-change-me-before-production"


@pytest.mark.parametrize(
    "secret_key",
    ["dev-secret-change-me-before-production", "change-me-to-a-long-random-string", "short"],
)
@pytest.mark.parametrize("public_url", ["https://lecturo.example", "https://localhost"])
def test_public_url_rejects_weak_key(public_url: str, secret_key: str) -> None:
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(public_url=public_url, secret_key=secret_key)


def test_public_url_rejects_default_key_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUBLIC_URL", "http://lecturo.example")
    monkeypatch.delenv("SECRET_KEY", raising=False)

    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings()


def test_public_url_accepts_strong_key() -> None:
    settings = Settings(public_url="https://lecturo.example", secret_key=STRONG_KEY)

    assert settings.secret_key == STRONG_KEY
