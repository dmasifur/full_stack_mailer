from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from server.models.base import BaseModel


class Template(BaseModel):
    __tablename__ = "templates"

    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # R2 object key — used to fetch the HTML from storage
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)

    # Original filename for display purposes
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)

    uploaded_by: Mapped[str] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )

    uploader = relationship("User")
