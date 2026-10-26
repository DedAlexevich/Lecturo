import uuid

from app.core.db import SessionLocal
from app.models import Chapter, Lecture, SourceType, Summary, TranscriptSegment


async def test_lectures_require_auth(client):
    response = await client.get("/api/v1/lectures")
    assert response.status_code == 401


async def test_lecture_detail(client, user, auth_headers):
    async with SessionLocal() as session:
        lecture = Lecture(owner_id=user.id, title="Матанализ", source_type=SourceType.upload)
        session.add(lecture)
        await session.flush()
        session.add_all(
            [
                TranscriptSegment(lecture_id=lecture.id, idx=1, start=5.0, end=9.0, text="два"),
                TranscriptSegment(lecture_id=lecture.id, idx=0, start=0.0, end=4.0, text="раз"),
                Chapter(lecture_id=lecture.id, idx=0, start=0.0, end=9.0, title="Введение"),
                Summary(lecture_id=lecture.id, content_md="# Конспект"),
            ]
        )
        await session.commit()

    response = await client.get(f"/api/v1/lectures/{lecture.id}", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert [s["text"] for s in body["segments"]] == ["раз", "два"]
    assert body["chapters"][0]["title"] == "Введение"
    assert body["summary"]["content_md"] == "# Конспект"
    assert body["video_url"] is None

    listed = await client.get("/api/v1/lectures", headers=auth_headers)
    assert [item["id"] for item in listed.json()] == [str(lecture.id)]


async def test_foreign_lecture_hidden(client, auth_headers):
    response = await client.get(f"/api/v1/lectures/{uuid.uuid4()}", headers=auth_headers)
    assert response.status_code == 404
