from pathlib import Path

from app.models import EMBEDDING_DIM
from app.providers import get_embeddings, get_llm, get_speech_to_text


async def test_stub_providers():
    segments = await get_speech_to_text().transcribe(Path("lecture.opus"))
    assert segments
    assert all(a.end <= b.start for a, b in zip(segments, segments[1:], strict=False))

    assert await get_llm().complete("system", "текст")

    vectors = await get_embeddings().embed_documents(["один", "два"])
    assert len(vectors) == 2
    assert all(len(v) == EMBEDDING_DIM for v in vectors)
