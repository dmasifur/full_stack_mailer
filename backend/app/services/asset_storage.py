from __future__ import annotations

import logging
import uuid

from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings
from app.services.r2 import get_client

logger = logging.getLogger(__name__)

# One year. Keys are UUIDs and objects are never rewritten, so the content at a
# key can never change — there is nothing for a cache to go stale against.
_CACHE_CONTROL = "public, max-age=31536000, immutable"

_EXTENSIONS = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
}


class AssetStorageError(Exception):
    pass


class AssetStorageNotConfiguredError(AssetStorageError):
    """R2_PUBLIC_BASE_URL is unset, so no reachable URL can be produced."""


def upload_asset(*, image_bytes: bytes, content_type: str) -> str:
    """
    Upload an inline campaign image to R2 and return its public URL.

    The URL, not the key: an image in a sent email is fetched anonymously by the
    recipient's mail client, which has no session and cannot sign a request.

    Assets are never deleted. An email that has left the building keeps pointing
    at its images forever, so an object outlives the campaign that referenced it
    and the storage cost is the price of not breaking already-delivered mail.
    """
    if not settings.R2_PUBLIC_BASE_URL:
        raise AssetStorageNotConfiguredError(
            "R2_PUBLIC_BASE_URL is not set. Inline images would be uploaded to a "
            "bucket with no publicly reachable URL."
        )

    extension = _EXTENSIONS[content_type]
    key = f"assets/{uuid.uuid4()}.{extension}"

    try:
        client = get_client()
        client.put_object(
            Bucket=settings.R2_BUCKET_NAME,
            Key=key,
            Body=image_bytes,
            ContentType=content_type,
            CacheControl=_CACHE_CONTROL,
        )
    except (BotoCoreError, ClientError) as exc:
        logger.exception("R2 asset upload failed. key=%s", key)
        raise AssetStorageError(f"Failed to upload asset: {exc}") from exc

    logger.info("Asset uploaded to R2. key=%s bytes=%s", key, len(image_bytes))
    return f"{settings.R2_PUBLIC_BASE_URL}/{key}"
