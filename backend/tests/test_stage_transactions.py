from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionLocal
from app.models import Lecture
from app.pipeline import embed, exam, quiz, stages, summarize
from app.providers.base import Segment
from app.providers.stub import StubEmbeddings
from tests.test_exam_sheet import ScriptedLLM as ExamLLM
from tests.test_exam_sheet import create_course
from tests.test_quiz import ScriptedLLM as QuizLLM
from tests.test_quiz import answer, create_ready_lecture, make_question
from tests.test_summarize import ScriptedLLM as SummaryLLM


class Watch:
    def __init__(self) -> None:
        self.session: AsyncSession | None = None
        self.open: list[bool] = []

    def check(self) -> None:
        assert self.session is not None
        self.open.append(self.session.in_transaction())


async def report(progress: float, stage: str | None = None) -> None:
    pass


async def run_stage(stage, lecture_id, watch: Watch) -> None:
    async with SessionLocal() as session:
        watch.session = session
        lecture = await session.get(Lecture, lecture_id)
        await stage(session, lecture, report)
        await session.commit()


class WatchedLLM:
    def __init__(self, llm, watch: Watch) -> None:
        self.llm = llm
        self.watch = watch

    async def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
        self.watch.check()
        return await self.llm.complete(system, user, json_mode=json_mode)


async def test_transcribe_has_no_transaction_during_recognition(user, monkeypatch):
    lecture = await create_ready_lecture(user)
    watch = Watch()

    class Recognizer:
        async def transcribe(self, path: Path, language: str, **kwargs) -> list[Segment]:
            watch.check()
            return [Segment(start=0.0, end=5.0, text="фраза")]

        async def discard(self, object_keys: list[str]) -> None:
            pass

    monkeypatch.setattr(stages, "get_speech_to_text", Recognizer)

    await run_stage(stages.transcribe, lecture.id, watch)

    assert watch.open == [False]


async def test_summarize_has_no_transaction_during_llm_calls(user, monkeypatch):
    lecture = await create_ready_lecture(user)
    watch = Watch()
    monkeypatch.setattr(summarize, "get_llm", lambda: WatchedLLM(SummaryLLM(), watch))

    await run_stage(summarize.summarize, lecture.id, watch)

    assert watch.open
    assert not any(watch.open)


async def test_quiz_has_no_transaction_during_llm_call(user, monkeypatch):
    lecture = await create_ready_lecture(user)
    watch = Watch()
    questions = [make_question(number) for number in range(8)]
    monkeypatch.setattr(quiz, "get_llm", lambda: WatchedLLM(QuizLLM(answer(questions)), watch))

    await run_stage(quiz.build_quiz, lecture.id, watch)

    assert watch.open == [False]


async def test_embed_has_no_transaction_during_embedding(user, monkeypatch):
    lecture = await create_ready_lecture(user)
    watch = Watch()

    class Embeddings(StubEmbeddings):
        async def embed_documents(self, texts: list[str]) -> list[list[float]]:
            watch.check()
            return await super().embed_documents(texts)

    monkeypatch.setattr(embed, "get_embeddings", Embeddings)

    await run_stage(embed.embed, lecture.id, watch)

    assert watch.open
    assert not any(watch.open)


async def test_exam_sheet_has_no_transaction_during_llm_calls(user, monkeypatch):
    course_id = await create_course(user)
    watch = Watch()

    def tracked_session():
        watch.session = SessionLocal()
        return watch.session

    monkeypatch.setattr(exam, "SessionLocal", tracked_session)
    monkeypatch.setattr(exam, "get_llm", lambda: WatchedLLM(ExamLLM(), watch))

    assert await exam.build_exam_sheet({}, str(course_id)) == "ready"

    assert watch.open
    assert not any(watch.open)
