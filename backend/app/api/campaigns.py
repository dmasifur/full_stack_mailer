from __future__ import annotations

from datetime import datetime
import logging
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db
from app.models.campaign import Campaign
from app.models.campaign_cc_recipient import CampaignCcRecipient
from app.models.template import Template
from app.models.user import User
from app.schemas.campaign import (
    CampaignCreate,
    CampaignListResponse,
    CampaignResponse,
    CampaignUpdate,
    CcRecipientAdd,
    CcRecipientResponse,
    RecipientUploadResponse,
)
from app.services.campaign_state import CampaignTransitionError, transition
from app.services.recipient_import import import_recipients_from_csv
from app.services.template_storage import TemplateStorageError, fetch_template
from app.workers.send_campaign import send_campaign_task

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/campaigns", tags=["campaigns"])

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)


def _get_campaign_or_404(
    campaign_id: str,
    db: Session,
    current_user: User,
) -> Campaign:
    campaign = (
        db.query(Campaign)
        .filter(Campaign.id == campaign_id, Campaign.user_id == current_user.id)
        .first()
    )
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    return campaign


def _resolve_template_body(
    *,
    db: Session,
    template_id: str | None,
    template_body: str,
) -> str:
    """
    If a template_id is provided, fetch the HTML from R2 and return it.
    The caller-supplied template_body is used as fallback (plain text path).
    """
    if not template_id:
        return template_body

    template = db.get(Template, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found.")

    try:
        return fetch_template(template.storage_key)
    except TemplateStorageError as exc:
        logger.exception("Failed to fetch template from storage. id=%s", template_id)
        raise HTTPException(
            status_code=500, detail="Failed to retrieve template content."
        ) from exc


def _sync_cc_recipients(
    *,
    db: Session,
    campaign: Campaign,
    cc_emails: list[str],
) -> None:
    """Replace the campaign's CC list with the provided addresses."""
    db.query(CampaignCcRecipient).filter(
        CampaignCcRecipient.campaign_id == str(campaign.id)
    ).delete()

    for email in cc_emails:
        db.add(CampaignCcRecipient(campaign_id=str(campaign.id), email=email))


@router.post("", status_code=201, response_model=CampaignResponse)
def create_campaign(
    body: CampaignCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Campaign:
    resolved_body = _resolve_template_body(
        db=db,
        template_id=str(body.template_id) if body.template_id else None,
        template_body=body.template_body,
    )

    campaign = Campaign(
        user_id=current_user.id,
        name=body.name,
        subject=body.subject,
        template_body=resolved_body,
        template_id=str(body.template_id) if body.template_id else None,
        from_address=str(body.from_address) if body.from_address else None,
        status="draft",
    )
    db.add(campaign)
    db.flush()  # get campaign.id before CC insert

    if body.cc_emails:
        _sync_cc_recipients(
            db=db,
            campaign=campaign,
            cc_emails=[str(e) for e in body.cc_emails],
        )

    db.commit()
    db.refresh(campaign)

    logger.info("Campaign created. id=%s user=%s", campaign.id, current_user.email)
    return campaign


@router.get("", response_model=CampaignListResponse)
def list_campaigns(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CampaignListResponse:
    base_query = db.query(Campaign).filter(Campaign.user_id == current_user.id)
    total = base_query.count()
    items = (
        base_query.order_by(Campaign.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return CampaignListResponse(
        items=[CampaignResponse.model_validate(c) for c in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{campaign_id}", response_model=CampaignResponse)
def get_campaign(
    campaign_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Campaign:
    return _get_campaign_or_404(campaign_id, db, current_user)


@router.patch("/{campaign_id}", response_model=CampaignResponse)
def update_campaign(
    campaign_id: str,
    body: CampaignUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Campaign:
    campaign = _get_campaign_or_404(campaign_id, db, current_user)

    if campaign.status != "draft":
        raise HTTPException(
            status_code=409,
            detail="Only draft campaigns can be edited.",
        )

    if body.name is not None:
        campaign.name = body.name
    if body.subject is not None:
        campaign.subject = body.subject
    if body.template_body is not None:
        campaign.template_body = body.template_body
    if body.from_address is not None:
        campaign.from_address = str(body.from_address)
    if body.cc_emails is not None:
        _sync_cc_recipients(
            db=db,
            campaign=campaign,
            cc_emails=[str(e) for e in body.cc_emails],
        )

    db.commit()
    db.refresh(campaign)

    logger.info("Campaign updated. id=%s", campaign_id)
    return campaign


@router.delete("/{campaign_id}", status_code=204)
def delete_campaign(
    campaign_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    campaign = _get_campaign_or_404(campaign_id, db, current_user)

    if campaign.status != "draft":
        raise HTTPException(
            status_code=409,
            detail="Only draft campaigns can be deleted.",
        )

    db.delete(campaign)
    db.commit()
    logger.info("Campaign deleted. id=%s", campaign_id)


@router.get("/{campaign_id}/cc-recipients", response_model=list[CcRecipientResponse])
def list_cc_recipients(
    campaign_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[CampaignCcRecipient]:
    _get_campaign_or_404(campaign_id, db, current_user)
    return (
        db.query(CampaignCcRecipient)
        .filter(CampaignCcRecipient.campaign_id == campaign_id)
        .all()
    )


@router.post(
    "/{campaign_id}/cc-recipients",
    status_code=201,
    response_model=list[CcRecipientResponse],
)
def add_cc_recipients(
    campaign_id: str,
    body: CcRecipientAdd,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[CampaignCcRecipient]:
    """
    Replace the campaign's CC list with the provided addresses.
    Only allowed while the campaign is in draft status.
    """
    campaign = _get_campaign_or_404(campaign_id, db, current_user)

    if campaign.status != "draft":
        raise HTTPException(
            status_code=409,
            detail="CC recipients can only be updated on draft campaigns.",
        )

    _sync_cc_recipients(
        db=db,
        campaign=campaign,
        cc_emails=[str(e) for e in body.emails],
    )
    db.commit()

    return (
        db.query(CampaignCcRecipient)
        .filter(CampaignCcRecipient.campaign_id == campaign_id)
        .all()
    )


@router.delete("/{campaign_id}/cc-recipients/{cc_id}", status_code=204)
def remove_cc_recipient(
    campaign_id: str,
    cc_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    campaign = _get_campaign_or_404(campaign_id, db, current_user)

    if campaign.status != "draft":
        raise HTTPException(
            status_code=409,
            detail="CC recipients can only be updated on draft campaigns.",
        )

    cc = (
        db.query(CampaignCcRecipient)
        .filter(
            CampaignCcRecipient.id == cc_id,
            CampaignCcRecipient.campaign_id == campaign_id,
        )
        .first()
    )
    if not cc:
        raise HTTPException(status_code=404, detail="CC recipient not found.")

    db.delete(cc)
    db.commit()


@router.post(
    "/{campaign_id}/recipients/upload",
    response_model=RecipientUploadResponse,
)
def upload_recipients_csv(
    campaign_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RecipientUploadResponse:
    campaign = _get_campaign_or_404(campaign_id, db, current_user)

    if not (file.filename or "").endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are supported.")

    unique_filename = f"{uuid4()}.csv"
    save_file_path = UPLOAD_DIR / unique_filename

    try:
        with save_file_path.open("wb") as output:
            while chunk := file.file.read(1024 * 1024):
                output.write(chunk)

        summary = import_recipients_from_csv(
            db=db, campaign_id=str(campaign.id), file_path=save_file_path
        )

        return RecipientUploadResponse(
            message="Recipients imported successfully.",
            summary={
                "total_rows": summary.total_rows,
                "imported": summary.imported,
                "invalid": summary.invalid,
            },
        )

    except Exception as exc:
        logger.exception("Failed to upload recipient CSV")
        raise HTTPException(
            status_code=500, detail="Failed to process CSV upload."
        ) from exc

    finally:
        if save_file_path.exists():
            save_file_path.unlink(missing_ok=True)


@router.post("/{campaign_id}/start", response_model=dict)
def start_campaign(
    campaign_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    campaign = _get_campaign_or_404(campaign_id, db, current_user)

    try:
        transition(campaign, "running")
    except CampaignTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    db.commit()
    send_campaign_task.delay(str(campaign.id))
    return {"message": "Campaign queued successfully."}


@router.post("/{campaign_id}/schedule", response_model=dict)
def schedule_campaign(
    campaign_id: str,
    scheduled_at: datetime,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    campaign = _get_campaign_or_404(campaign_id, db, current_user)

    try:
        transition(campaign, "scheduled")
    except CampaignTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    campaign.scheduled_at = scheduled_at
    db.commit()

    send_campaign_task.apply_async(
        args=[str(campaign.id)],
        eta=scheduled_at,
    )

    logger.info("Campaign scheduled. id=%s eta=%s", campaign_id, scheduled_at)
    return {"message": "Campaign scheduled successfully."}


@router.post("/{campaign_id}/pause", response_model=dict)
def pause_campaign(
    campaign_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    campaign = _get_campaign_or_404(campaign_id, db, current_user)

    try:
        transition(campaign, "paused")
    except CampaignTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    db.commit()
    logger.info("Campaign paused. id=%s", campaign_id)
    return {"message": "Campaign paused successfully."}


@router.post("/{campaign_id}/resume", response_model=dict)
def resume_campaign(
    campaign_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    campaign = _get_campaign_or_404(campaign_id, db, current_user)

    try:
        transition(campaign, "scheduled")
    except CampaignTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    db.commit()
    send_campaign_task.delay(str(campaign.id))
    logger.info("Campaign resumed. id=%s", campaign_id)
    return {"message": "Campaign resumed successfully."}
