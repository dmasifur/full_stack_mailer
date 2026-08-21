from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class SenderAddress(BaseModel):
    __tablename__ = "sender_addresses"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )

    # Display label e.g. "Marketing", "Support"
    label: Mapped[str] = mapped_column(String(255), nullable=False)

    email: Mapped[str] = mapped_column(String(255), nullable=False)

    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    user = relationship("User")
