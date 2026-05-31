import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, RedirectResponse
import httpx
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.core.config import settings
from app.models.user import User
from app.services.auth.jwt import create_access_token
from app.services.auth.microsoft_oauth import (
    MICROSOFT_TOKEN_URL,
    build_authorization_url,
)
from app.services.token_encryption import encrypt_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

_STATE_SALT = "oauth-state"
_STATE_MAX_AGE = 300


def _state_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.SECRET_KEY)


@router.get("/microsoft/login")
def microsoft_login() -> RedirectResponse:
    raw_state = secrets.token_urlsafe(32)

    signed_state = _state_serializer().dumps(raw_state, salt=_STATE_SALT)

    authorization_url = build_authorization_url(state=signed_state)

    return RedirectResponse(authorization_url)


@router.get("/microsoft/callback")
async def microsoft_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> JSONResponse:
    if not state:
        raise HTTPException(status_code=400, detail="Missing OAuth state parameter.")

    try:
        _state_serializer().loads(state, salt=_STATE_SALT, max_age=_STATE_MAX_AGE)
    except SignatureExpired:
        raise HTTPException(status_code=400, detail="OAuth state expired. Please log in again.") from SignatureExpired
    except BadSignature:
        raise HTTPException(status_code=400, detail="Invalid OAuth state. Possible CSRF attempt.") from BadSignature

    if not code:
        raise HTTPException(
            status_code=400,
            detail="Missing authorization code. Start login from '/auth/microsoft/login'.",
        )

    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            MICROSOFT_TOKEN_URL,
            data={
                "client_id": settings.MICROSOFT_CLIENT_ID,
                "client_secret": settings.MICROSOFT_CLIENT_SECRET,
                "code": code,
                "redirect_uri": settings.MICROSOFT_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )

        if token_response.status_code != 200:
            logger.error("Failed to obtain Microsoft token: %s", token_response.text)
            raise HTTPException(status_code=400, detail="Microsoft token exchange failed.")

        token_data = token_response.json()
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")

        profile_response = await client.get(
            "https://graph.microsoft.com/v1.0/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        if profile_response.status_code != 200:
            logger.error("Failed to fetch Microsoft profile: %s", profile_response.text)
            raise HTTPException(status_code=400, detail="Failed to fetch Microsoft profile.")

    profile = profile_response.json()
    user_email = profile.get("mail") or profile.get("userPrincipalName")

    if not user_email:
        raise HTTPException(status_code=400, detail="Microsoft account has no accessible email.")

    encrypted_access_token = encrypt_token(access_token)
    encrypted_refresh_token = encrypt_token(refresh_token) if refresh_token else None

    try:
        existing_user = db.query(User).filter(User.email == user_email).first()

        if existing_user:
            existing_user.access_token = encrypted_access_token
            if encrypted_refresh_token:
                existing_user.refresh_token = encrypted_refresh_token
            user = existing_user
        else:
            user = User(
                email=user_email,
                full_name=profile.get("displayName"),
                microsoft_id=profile["id"],
                access_token=encrypted_access_token,
                refresh_token=encrypted_refresh_token,
            )
            db.add(user)

        db.commit()
        db.refresh(user)

    except Exception:
        db.rollback()
        logger.exception("Failed to persist Microsoft user.")
        raise

    session_token = create_access_token(str(user.id))

    response = JSONResponse(
        content={
            "message": "Microsoft login successful.",
            "user_id": str(user.id),
            "email": user.email,
        }
    )

    response.set_cookie(
        key="access_token",
        value=session_token,
        httponly=True,
        secure=settings.APP_ENV != "development",
        samesite="lax",
        max_age=60 * 60 * 8,
    )

    return response


@router.post("/logout")
def logout() -> JSONResponse:
    response = JSONResponse(content={"message": "Logged out successfully."})
    response.delete_cookie("access_token")
    return response
