from datetime import UTC, datetime
import logging

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.core.config import settings

logger = logging.getLogger(__name__)

_SALT = "access-token"


def _get_serializer() -> URLSafeTimedSerializer:
    secret = settings.SECRET_KEY

    if not secret:
        raise RuntimeError(
            "SECRET_KEY is not set. "
            'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
        )

    return URLSafeTimedSerializer(secret)


def create_access_token(user_id: str) -> str:
    serializer = _get_serializer()
    payload = {"sub": user_id, "iat": datetime.now(tz=UTC).isoformat()}
    return serializer.dumps(payload, salt=_SALT)


def decode_access_token(token: str) -> str:
    serializer = _get_serializer()

    try:
        payload = serializer.loads(
            token,
            salt=_SALT,
            max_age=settings.ACCESS_TOKEN_TTL_SECONDS,
        )
        return str(payload["sub"])
    except SignatureExpired as exc:
        raise TokenExpiredError("Access token has expired.") from exc
    except (BadSignature, KeyError) as exc:
        raise TokenInvalidError("Access token is invalid or tampered.") from exc


class TokenExpiredError(Exception):
    pass


class TokenInvalidError(Exception):
    pass
