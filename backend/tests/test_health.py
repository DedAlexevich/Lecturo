from app.core.config import get_settings


async def test_health(client):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_health_head(client):
    response = await client.head("/api/v1/health")
    assert response.status_code == 200


async def test_health_reports_unavailable_redis(client, monkeypatch):
    settings = get_settings().model_copy(update={"redis_url": "redis://127.0.0.1:1/0"})
    monkeypatch.setattr("app.api.health.get_settings", lambda: settings)
    response = await client.get("/api/v1/health")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "ok", "redis": "error"}
