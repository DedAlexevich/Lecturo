import enum
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UUIDPk


class ZoomerVideoStatus(enum.StrEnum):
    processing = "processing"
    ready = "ready"
    failed = "failed"


class ZoomerVideo(UUIDPk, CreatedAt, Base):
    __tablename__ = "zoomer_videos"
    __table_args__ = (
        CheckConstraint("status IN ('processing', 'ready', 'failed')", name="status"),
    )

    title: Mapped[str] = mapped_column(String(120))
    source: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(16), default=ZoomerVideoStatus.processing)
    error: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    duration_sec: Mapped[float | None] = mapped_column(Float)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
