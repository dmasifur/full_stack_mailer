from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from server.models.base import BaseModel


class CampaignRecipient(BaseModel):
    __tablename__ = "campaign_recipients"

    __table_args__ = (
        UniqueConstraint(
            "campaign_id",
            "email",
            name="uq_campaign_recipients_campaign_email",
        ),
        # The send worker's hot path filters on exactly this pair.
        Index(
            "ix_campaign_recipients_campaign_id_status",
            "campaign_id",
            "status",
        ),
    )

    campaign_id: Mapped[str] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"),
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
    # NULL means "not yet validated".
    dns_valid: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=True,
    )

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

    campaign = relationship("Campaign", back_populates="recipients")
