from sqlalchemy import ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class EmailLog(BaseModel):
    __tablename__ = "email_logs"

    __table_args__ = (
        # Makes a duplicate delivery a database error rather than a silent
        # second email. Partial: 'failed' rows repeat legitimately.
        Index(
            "uq_email_logs_campaign_recipient_sent",
            "campaign_id",
            "recipient_email",
            unique=True,
            postgresql_where=text("status = 'sent'"),
        ),
    )

    campaign_id: Mapped[str] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    recipient_email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    provider_message_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    campaign = relationship("Campaign", back_populates="email_logs")
