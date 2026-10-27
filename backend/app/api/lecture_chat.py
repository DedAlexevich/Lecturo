import uuid

from fastapi import APIRouter, HTTPException, status
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.deps import CurrentUser, SessionDep
from app.models import Lecture, LectureStatus, SearchChunk
from app.providers import get_llm
from app.providers.openai_compat import OpenAICompatibleError
from app.schemas.lecture_chat import (
    LectureChatIn,
    LectureChatOut,
    LectureChatSource,
)
from app.services.consents import require_ai_transfer_consent
from app.services.lecture_chat import ChatReply, InvalidChatReply, answer_question, select_sources
from app.services.quota import has_subscription
from app.services.rate_limit import enforce_rate_limit
from app.services.search import embed_query, semantic_search

router = APIRouter(prefix="/lectures", tags=["lectures"])


@router.post("/{lecture_id}/chat", response_model=LectureChatOut)
async def chat_about_lecture(
    lecture_id: uuid.UUID,
    body: LectureChatIn,
    user: CurrentUser,
    session: SessionDep,
) -> LectureChatOut:
    lecture = await session.scalar(
        select(Lecture)
        .where(Lecture.id == lecture_id, Lecture.owner_id == user.id)
        .options(selectinload(Lecture.chapters), selectinload(Lecture.summary))
    )
    if lecture is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Лекция не найдена")
    if lecture.status != LectureStatus.ready:
        raise HTTPException(status.HTTP_409_CONFLICT, "Лекция ещё обрабатывается")
    require_ai_transfer_consent(user)
    if not await has_subscription(session, user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            {"code": "subscription_required", "message": "Чат доступен только с подпиской"},
        )

    settings = get_settings()
    await enforce_rate_limit(
        settings.redis_url,
        f"lecture-chat:{user.id}",
        settings.lecture_chat_rate_limit,
        settings.lecture_chat_rate_window_seconds,
    )

    try:
        vector = await embed_query(body.question)
        hits = await semantic_search(
            session,
            SearchChunk.lecture_id == lecture.id,
            body.question,
            vector,
        )
        if select_sources(lecture.id, hits):
            reply = await answer_question(
                get_llm(),
                lecture_id=lecture.id,
                title=lecture.title,
                question=body.question,
                history=[message.model_dump() for message in body.history],
                summary=lecture.summary.content_md if lecture.summary else "",
                chapters=[
                    {"title": chapter.title, "summary": chapter.summary}
                    for chapter in lecture.chapters
                ],
                hits=hits,
            )
        else:
            reply = ChatReply(
                "not_found", "В материалах лекции не найден ответ на этот вопрос.", None, []
            )
    except (
        OpenAICompatibleError,
        InvalidChatReply,
        SQLAlchemyError,
        RedisError,
        ValueError,
    ) as error:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Чат временно недоступен, попробуйте позже",
        ) from error

    return LectureChatOut(
        status=reply.status,
        answer=reply.answer,
        extra=reply.extra,
        sources=[
            LectureChatSource(
                kind=source.kind.value,
                start=source.start,
                end=source.end,
                text=source.text,
            )
            for source in reply.sources
        ],
    )
