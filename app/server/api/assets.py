from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from server.api.dependencies import get_current_user
from server.core.rate_limit import limiter
from server.models.user import User
from server.schemas.asset import AssetUploadResponse
from server.services.asset_storage import (
    AssetStorageError,
    AssetStorageNotConfiguredError,
    upload_asset,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/assets", tags=["assets"])

MAX_ASSET_BYTES = 2 * 1024 * 1024  # 2 MB — an inline email image, not a photo library


def _sniff(data: bytes) -> str | None:
    """
    Identify an image by its leading bytes.

    The filename and Content-Type are both supplied by the caller, so neither is
    evidence of anything. The magic bytes are the only part of the request the
    caller cannot lie about without changing the file.
    """
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"

    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"

    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"

    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"

    return None


@router.post("", status_code=201, response_model=AssetUploadResponse)
@limiter.limit("60/minute")
async def upload_inline_asset(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
) -> AssetUploadResponse:
    """
    Store an inline campaign image and return its public URL.

    Used by the campaign editor for pasted, dropped, and explicitly chosen
    images. The returned URL is what goes into the email's <img src>.
    """
    image_bytes = await file.read()

    if len(image_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    if len(image_bytes) > MAX_ASSET_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Image exceeds the maximum size of {MAX_ASSET_BYTES // 1024 // 1024} MB.",
        )

    content_type = _sniff(image_bytes)

    if content_type is None:
        raise HTTPException(
            status_code=400,
            detail="Unsupported image format. Accepted formats are PNG, JPEG, GIF, and WEBP.",
        )

    try:
        url = upload_asset(image_bytes=image_bytes, content_type=content_type)
    except AssetStorageNotConfiguredError as exc:
        logger.error("Asset upload attempted with no public R2 base URL configured.")
        raise HTTPException(
            status_code=503,
            detail=(
                "Image hosting is not configured. Set R2_PUBLIC_BASE_URL before "
                "adding images to a campaign."
            ),
        ) from exc
    except AssetStorageError as exc:
        logger.exception("Asset storage upload failed.")
        raise HTTPException(status_code=500, detail="Failed to store image.") from exc

    logger.info("Inline asset stored. user=%s type=%s", current_user.id, content_type)
    return AssetUploadResponse(url=url)
