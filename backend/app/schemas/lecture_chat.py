from typing import Literal

from pydantic import Field, field_validator

from app.schemas.common import Schema


class ChatMessage(Schema):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)

    @field_validator("content")
    @classmethod
    def trim_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Сообщение не может быть пустым")
        return value


class LectureChatIn(Schema):
    question: str = Field(min_length=1, max_length=1000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=10)

    @field_validator("question", mode="before")
    @classmethod
    def trim_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Вопрос не может быть пустым")
        return value


class LectureChatSource(Schema):
    kind: Literal["transcript", "chapter"]
    start: float
    end: float
    text: str


class LectureChatOut(Schema):
    status: Literal["answered", "not_found", "off_topic"]
    answer: str
    extra: str | None
    sources: list[LectureChatSource]
