from __future__ import annotations

import logging
import uuid

from botocore.exceptions import BotoCoreError, ClientError

from server.core.config import settings
from server.services.r2 import get_client

logger = logging.getLogger(__name__)


class TemplateStorageError(Exception):
    pass


def upload_template(html_bytes: bytes, original_filename: str) -> str:
    """
    Upload HTML bytes to R2. Returns the storage key.
    The key is a UUID so filenames never collide regardless of uploader.
    """
    key = f"templates/{uuid.uuid4()}.html"

    try:
        client = get_client()
        client.put_object(
            Bucket=settings.R2_BUCKET_NAME,
            Key=key,
            Body=html_bytes,
            ContentType="text/html; charset=utf-8",
        )
        logger.info(
            "Template uploaded to R2. key=%s original=%s", key, original_filename
        )
        return key

    except (BotoCoreError, ClientError) as exc:
        logger.exception("R2 upload failed. original=%s", original_filename)
        raise TemplateStorageError(f"Failed to upload template: {exc}") from exc


def fetch_template(storage_key: str) -> str:
    """
    Fetch template HTML from R2 by storage key. Returns HTML string.
    """
    try:
        client = get_client()
        response = client.get_object(
            Bucket=settings.R2_BUCKET_NAME,
            Key=storage_key,
        )
        body: bytes = response["Body"].read()
        return body.decode("utf-8")

    except (BotoCoreError, ClientError) as exc:
        logger.exception("R2 fetch failed. key=%s", storage_key)
        raise TemplateStorageError(f"Failed to fetch template: {exc}") from exc


def delete_template(storage_key: str) -> None:
    """
    Delete a template from R2 by storage key.
    """
    try:
        client = get_client()
        client.delete_object(
            Bucket=settings.R2_BUCKET_NAME,
            Key=storage_key,
        )
        logger.info("Template deleted from R2. key=%s", storage_key)

    except (BotoCoreError, ClientError) as exc:
        logger.exception("R2 delete failed. key=%s", storage_key)
        raise TemplateStorageError(f"Failed to delete template: {exc}") from exc
