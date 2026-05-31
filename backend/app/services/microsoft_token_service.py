import logging

import requests
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.user import User
from app.services.token_encryption import decrypt_token, encrypt_token

logger = logging.getLogger(__name__)

TOKEN_URL = (
    f"https://login.microsoftonline.com/"
    f"{settings.MICROSOFT_TENANT_ID}"
    f"/oauth2/v2.0/token"
)


class TokenRefreshError(Exception):
    pass


def refresh_access_token(*, db: Session, user: User) -> None:
    if not user.refresh_token:
        raise TokenRefreshError("Missing refresh token.")

    try:
        plaintext_refresh_token = decrypt_token(user.refresh_token)
    except Exception as exc:
        raise TokenRefreshError("Could not decrypt stored refresh token.") from exc

    response = requests.post(
        TOKEN_URL,
        data={
            "client_id": settings.MICROSOFT_CLIENT_ID,
            "client_secret": settings.MICROSOFT_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": plaintext_refresh_token,
        },
        timeout=30,
    )

    if response.status_code != 200:
        logger.error(
            "Token refresh failed. status=%s response=%s",
            response.status_code,
            response.text,
        )
        raise TokenRefreshError("Microsoft token refresh failed.")

    token_data = response.json()

    user.access_token = encrypt_token(token_data["access_token"])

    new_refresh_token = token_data.get("refresh_token")
    if new_refresh_token:
        user.refresh_token = encrypt_token(new_refresh_token)

    db.commit()

    logger.info("Microsoft token refreshed successfully. user=%s", user.email)
