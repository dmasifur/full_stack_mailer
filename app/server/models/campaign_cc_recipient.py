from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from server.models.base import BaseModel


class CampaignCcRecipient(BaseModel):
    __tablename__ = "campaign_cc_recipients"

    campaign_id: Mapped[str] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True
    )

    email: Mapped[str] = mapped_column(String(255), nullable=False)

    campaign = relationship("Campaign", back_populates="cc_recipients")
