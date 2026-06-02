from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db
from app.models.sender_address import SenderAddress
from app.models.user import User
from app.schemas.campaign import (
    SenderAddressCreate,
    SenderAddressResponse,
    SenderAddressUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sender-addresses", tags=["sender-addresses"])


@router.post("", status_code=201, response_model=SenderAddressResponse)
def create_sender_address(
    body: SenderAddressCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SenderAddress:
    """
    Save a sender address (own mailbox or shared mailbox) for use in campaigns.
    If is_default=True, any existing default for this user is cleared first.
    """
    if body.is_default:
        _clear_default(db=db, user_id=str(current_user.id))

    sender = SenderAddress(
        user_id=str(current_user.id),
        label=body.label,
        email=str(body.email),
        is_default=body.is_default,
    )
    db.add(sender)
    db.commit()
    db.refresh(sender)

    logger.info(
        "Sender address saved. id=%s email=%s user=%s",
        sender.id,
        sender.email,
        current_user.email,
    )
    return sender


@router.get("", response_model=list[SenderAddressResponse])
def list_sender_addresses(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[SenderAddress]:
    """List all saved sender addresses for the current user."""
    return (
        db.query(SenderAddress)
        .filter(SenderAddress.user_id == str(current_user.id))
        .order_by(SenderAddress.is_default.desc(), SenderAddress.created_at)
        .all()
    )


@router.patch("/{address_id}", response_model=SenderAddressResponse)
def update_sender_address(
    address_id: str,
    body: SenderAddressUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SenderAddress:
    sender = _get_or_404(db=db, address_id=address_id, user_id=str(current_user.id))

    if body.label is not None:
        sender.label = body.label

    if body.is_default is True:
        _clear_default(db=db, user_id=str(current_user.id))
        sender.is_default = True
    elif body.is_default is False:
        sender.is_default = False

    db.commit()
    db.refresh(sender)
    return sender


@router.delete("/{address_id}", status_code=204)
def delete_sender_address(
    address_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    sender = _get_or_404(db=db, address_id=address_id, user_id=str(current_user.id))
    db.delete(sender)
    db.commit()
    logger.info("Sender address deleted. id=%s user=%s", address_id, current_user.email)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_or_404(*, db: Session, address_id: str, user_id: str) -> SenderAddress:
    sender = (
        db.query(SenderAddress)
        .filter(
            SenderAddress.id == address_id,
            SenderAddress.user_id == user_id,
        )
        .first()
    )
    if not sender:
        raise HTTPException(status_code=404, detail="Sender address not found.")
    return sender


def _clear_default(*, db: Session, user_id: str) -> None:
    """Remove is_default from all addresses for this user."""
    db.query(SenderAddress).filter(
        SenderAddress.user_id == user_id,
        SenderAddress.is_default.is_(True),
    ).update({"is_default": False})
