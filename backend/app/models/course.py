import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Table, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UUIDPk

course_lectures = Table(
    "course_lectures",
    Base.metadata,
    Column("course_id", ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True),
    Column("lecture_id", ForeignKey("lectures.id", ondelete="CASCADE"), primary_key=True),
    Column("position", Integer, nullable=False, server_default="0"),
    Column("added_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)


class Course(UUIDPk, CreatedAt, Base):
    __tablename__ = "courses"
    __table_args__ = (
        Index(
            "uq_courses_owner_copied_from",
            "owner_id",
            "copied_from_id",
            unique=True,
            postgresql_where=text("copied_from_id IS NOT NULL"),
        ),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    copied_from_id: Mapped[uuid.UUID | None] = mapped_column()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
