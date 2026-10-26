from app.main import app


def test_contract_has_p0_endpoints():
    paths = app.openapi()["paths"]
    for path in (
        "/api/v1/auth/register",
        "/api/v1/auth/login",
        "/api/v1/auth/telegram",
        "/api/v1/me",
        "/api/v1/courses",
        "/api/v1/lectures/link",
        "/api/v1/lectures/{lecture_id}/status",
        "/api/v1/lectures/{lecture_id}/export.pdf",
        "/api/v1/search",
        "/api/v1/billing/quota",
        "/api/v1/public/{token}",
        "/api/v1/legal/{slug}",
    ):
        assert path in paths


async def test_not_ready_endpoint_returns_501(client):
    response = await client.get("/api/v1/legal")
    assert response.status_code == 501
