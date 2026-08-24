from __future__ import annotations

from pydantic import BaseModel


class AssetUploadResponse(BaseModel):
    """The public URL of a stored inline image, ready to use as an <img src>."""

    url: str
