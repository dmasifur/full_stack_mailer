from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class User(BaseModel):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )

    full_name: Mapped[str] = mapped_column(String(255), nullable=True)

    microsoft_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True
    )

    access_token: Mapped[str | None] = mapped_column(nullable=True)

    refresh_token: Mapped[str | None] = mapped_column(nullable=True)
