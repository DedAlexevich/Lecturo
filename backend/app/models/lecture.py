import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAt, UUIDPk


class SourceType(enum.StrEnum):
    upload = "upload"
    link = "link"
    local = "local"


class LectureStatus(enum.StrEnum):
    queued = "queued"
    waiting_quota = "waiting_quota"
    processing = "processing"
    ready = "ready"
    failed = "failed"


class StepName(enum.StrEnum):
    download = "download"
    audio = "audio"
    video = "video"
    transcribe = "transcribe"
    summarize = "summarize"
    embed = "embed"
    quiz = "quiz"


class StepStatus(enum.StrEnum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"


class Lecture(UUIDPk, CreatedAt, Base):
    __tablename__ = "lectures"
    __table_args__ = (
        Index(
            "uq_lectures_owner_copied_from",
            "owner_id",
            "copied_from_id",
            unique=True,
            postgresql_where=text("copied_from_id IS NOT NULL"),
        ),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(300))
    source_type: Mapped[SourceType] = mapped_column(Enum(SourceType, name="source_type"))
    source_url: Mapped[str | None] = mapped_column(Text)
    embed_url: Mapped[str | None] = mapped_column(Text)
    duration_sec: Mapped[float | None] = mapped_column(Float)
    language: Mapped[str] = mapped_column(String(8), default="ru")
    status: Mapped[LectureStatus] = mapped_column(
        Enum(LectureStatus, name="lecture_status"), default=LectureStatus.queued
    )
    queue_position: Mapped[int | None] = mapped_column(Integer)
    video_path: Mapped[str | None] = mapped_column(Text)
    audio_path: Mapped[str | None] = mapped_column(Text)
    video_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_locally: Mapped[bool] = mapped_column(Boolean, default=False)
    copied_from_id: Mapped[uuid.UUID | None] = mapped_column()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    steps: Mapped[list["ProcessingStep"]] = relationship(
        cascade="all, delete-orphan", order_by="ProcessingStep.created_at"
    )
    segments: Mapped[list["TranscriptSegment"]] = relationship(
        cascade="all, delete-orphan", order_by="TranscriptSegment.idx"
    )
    chapters: Mapped[list["Chapter"]] = relationship(
        cascade="all, delete-orphan", order_by="Chapter.idx"
    )
    summary: Mapped["Summary | None"] = relationship(cascade="all, delete-orphan")


class ProcessingStep(UUIDPk, CreatedAt, Base):
    __tablename__ = "processing_steps"
    __table_args__ = (UniqueConstraint("lecture_id", "step"),)

    lecture_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lectures.id", ondelete="CASCADE"))
    step: Mapped[StepName] = mapped_column(Enum(StepName, name="step_name"))
    status: Mapped[StepStatus] = mapped_column(
        Enum(StepStatus, name="step_status"), default=StepStatus.pending
    )
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    stage: Mapped[str | None] = mapped_column(String(32))
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"

    id: Mapped[int] = mapped_column(primary_key=True)
    lecture_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lectures.id", ondelete="CASCADE"), index=True
    )
    idx: Mapped[int] = mapped_column(Integer)
    start: Mapped[float] = mapped_column(Float)
    end: Mapped[float] = mapped_column(Float)
    text: Mapped[str] = mapped_column(Text)


class Chapter(Base):
    __tablename__ = "chapters"

    id: Mapped[int] = mapped_column(primary_key=True)
    lecture_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lectures.id", ondelete="CASCADE"), index=True
    )
    idx: Mapped[int] = mapped_column(Integer)
    start: Mapped[float] = mapped_column(Float)
    end: Mapped[float] = mapped_column(Float)
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str] = mapped_column(Text, default="")


class Summary(CreatedAt, Base):
    __tablename__ = "summaries"

    lecture_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lectures.id", ondelete="CASCADE"), primary_key=True
    )
    content_md: Mapped[str] = mapped_column(Text)


class Quiz(UUIDPk, CreatedAt, Base):
    __tablename__ = "quizzes"

    lecture_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lectures.id", ondelete="CASCADE"), unique=True
    )
    questions: Mapped[list] = mapped_column(JSONB)


class ExamSheet(UUIDPk, CreatedAt, Base):
    __tablename__ = "exam_sheets"

    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), unique=True
    )
    content: Mapped[dict] = mapped_column(JSONB)
