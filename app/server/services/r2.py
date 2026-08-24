from __future__ import annotations

from typing import TYPE_CHECKING

import boto3

if TYPE_CHECKING:
    # boto3-stubs is a dev-only dependency — never import it at runtime.
    from mypy_boto3_s3.client import S3Client

from server.core.config import settings


def get_client() -> S3Client:
    """
    An S3 client pointed at the R2 bucket.

    Shared by every storage service so the credential and endpoint wiring lives
    in one place.
    """
    return boto3.client(
        "s3",
        endpoint_url=settings.R2_ENDPOINT_URL,
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )
