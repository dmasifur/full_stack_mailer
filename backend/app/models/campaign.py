from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, DateTime

from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel



class Campaign(BaseModel):

    __tablename__ = "campaigns"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"),
        nullable=False
    )

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )

    subject: Mapped[str] = mapped_column(
        String(500),
        nullable=False
    )

    template_body: Mapped[str] = mapped_column(
        Text,
        nullable=False
    )

    status: Mapped[str] = mapped_column(
        String(50),
        default="draft", # draft /scheduled /running /paused /completed /failed
        nullable=False,
        index=True
    )

    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )

    user = relationship("User")