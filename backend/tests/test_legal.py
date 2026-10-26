from app.api.legal import SLUGS


async def test_list_documents(client):
    response = await client.get("/api/v1/legal")
    assert response.status_code == 200
    assert [doc["slug"] for doc in response.json()] == list(SLUGS)
    assert all(doc["title"] for doc in response.json())


async def test_get_document(client):
    response = await client.get("/api/v1/legal/terms")
    assert response.status_code == 200
    body = response.json()
    assert body["slug"] == "terms"
    assert body["title"] == "Пользовательское соглашение"
    assert body["revision_date"] == "2026-10-26"
    assert body["content_md"].startswith("# Пользовательское соглашение")


async def test_unknown_document_returns_404(client):
    response = await client.get("/api/v1/legal/unknown")
    assert response.status_code == 404
