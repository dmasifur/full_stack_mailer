from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class Campaign(BaseModel):
    __tablename__ = "campaigns"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)

    name: Mapped[str] = mapped_column(String(255), nullable=False)

    subject: Mapped[str] = mapped_column(String(500), nullable=False)

    template_body: Mapped[str] = mapped_column(Text, nullable=False)
    template_id: Mapped[str | None] = mapped_column(
        ForeignKey("templates.id"), nullable=True
    )
    # Sender address. None means send from the authenticated user's own mailbox.
    from_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(50),
        default="draft",  # draft /scheduled /running /paused /completed /failed
        nullable=False,
        index=True,
    )

    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user = relationship("User")
    source_template = relationship("Template")
    cc_recipients = relationship("CampaignCcRecipient", cascade="all, delete-orphan")
