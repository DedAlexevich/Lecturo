import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UUIDPk


class ShareLink(UUIDPk, CreatedAt, Base):
    __tablename__ = "share_links"
    __table_args__ = (
        CheckConstraint("(lecture_id IS NULL) <> (course_id IS NULL)", name="one_target"),
    )

    token: Mapped[str] = mapped_column(String(64), unique=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    lecture_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("lectures.id", ondelete="CASCADE")
    )
    course_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Complaint(UUIDPk, CreatedAt, Base):
    __tablename__ = "complaints"

    lecture_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lectures.id", ondelete="CASCADE"))
    reporter_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reason: Mapped[str] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
