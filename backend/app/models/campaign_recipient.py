from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class CampaignRecipient(BaseModel):
    __tablename__ = "campaign_recipients"

    __table_args__ = (
        UniqueConstraint(
            "campaign_id",
            "email",
            name="uq_campaign_recipients_campaign_email",
        ),
    )

    campaign_id: Mapped[str] = mapped_column(
        ForeignKey("campaigns.id"),
        nullable=False,
        index=True,
    )

    first_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    last_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )
    # Nullable: set to True/False by the background DNS validation task.
    # NULL means "not yet validated".
    dns_valid: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=True,
    )

    # pending_validation → pending (dns ok) or invalid (dns failed)
    # pending → sending → sent / failed
    status: Mapped[str] = mapped_column(
        String(50),
        default="pending_validation",
        nullable=False,
        index=True,
    )

    retry_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    failure_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    campaign = relationship("Campaign")
