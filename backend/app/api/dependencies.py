from collections.abc import Generator

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.user import User
from app.services.auth.jwt import (
    TokenExpiredError,
    TokenInvalidError,
    decode_access_token,
)


def get_db() -> Generator[Session]:
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    token = request.cookies.get("access_token")

    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.removeprefix("Bearer ").strip()

    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated.")

    try:
        user_id = decode_access_token(token)
    except TokenExpiredError as exc:
        raise HTTPException(
            status_code=401, detail="Session expired. Please log in again."
        ) from exc
    except TokenInvalidError as exc:
        raise HTTPException(status_code=401, detail="Invalid token.") from exc

    user = db.get(User, user_id)

    if not user:
        raise HTTPException(status_code=401, detail="User not found.")

    return user
