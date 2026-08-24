from __future__ import annotations

from collections.abc import Callable
import logging
from pathlib import Path
import tempfile
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db
from app.core.config import settings
from app.models.campaign import Campaign
from app.models.campaign_cc_recipient import CampaignCcRecipient
from app.models.campaign_recipient import CampaignRecipient
from app.models.sender_address import SenderAddress
from app.models.template import Template
from app.models.user import User
from app.schemas.campaign import (
    CampaignCreate,
    CampaignListResponse,
    CampaignResponse,
    CampaignSchedule,
    CampaignStatsResponse,
    CampaignUpdate,
    CcRecipientAdd,
    CcRecipientResponse,
    ImportSummarySchema,
    RecipientListResponse,
    RecipientResponse,
    RecipientUploadResponse,
)
from app.services.campaign_state import CampaignTransitionError, transition
from app.services.recipient_import import import_recipients_from_csv
from app.services.template_storage import TemplateStorageError, fetch_template
from app.workers.send_campaign import send_campaign_task

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


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


def _validate_from_address(
    *,
    db: Session,
    user: User,
    from_address: str | None,
) -> str | None:
    """
    Ensure a campaign's from_address is one the caller actually owns.

    Without this check any authenticated user could send as any address — the
    value goes straight to Graph. None means "send from the user's own mailbox",
    which needs no verification.
    """
    if not from_address:
        return None

    owned = (
        db.query(SenderAddress)
        .filter(
            SenderAddress.user_id == str(user.id),
            SenderAddress.email == from_address,
        )
        .first()
    )

    if not owned:
        raise HTTPException(
            status_code=400,
            detail=(
                f"'{from_address}' is not one of your registered sender "
                "addresses. Add it under /sender-addresses first."
            ),
        )

    return from_address


def _assert_sendable(*, db: Session, campaign: Campaign) -> None:
    """
    Refuse to launch a campaign that cannot actually send.

    The worker only picks up recipients at 'pending' with dns_valid true. Without
    this check a campaign with none finds nothing to do and completes itself
    having sent nothing — and 'completed' is terminal.
    """
    counts: dict[str, int] = dict(
        db.query(CampaignRecipient.status, func.count())
        .filter(CampaignRecipient.campaign_id == str(campaign.id))
        .group_by(CampaignRecipient.status)
        .tuples()
        .all()
    )

    if not counts:
        raise HTTPException(
            status_code=409,
            detail="Campaign has no recipients. Upload a CSV before sending.",
        )

    awaiting = counts.get("pending_validation", 0)
    if awaiting:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{awaiting} recipient(s) are still awaiting DNS validation. "
                "Wait for validation to finish before sending."
            ),
        )

    if not counts.get("pending", 0) and not counts.get("sending", 0):
        raise HTTPException(
            status_code=409,
            detail=(
                "No sendable recipients remain — every address is already sent, "
                "failed, or invalid."
            ),
        )


def _transition_and_dispatch(
    *,
    db: Session,
    campaign: Campaign,
    to_status: str,
    dispatch: Callable[[], object],
) -> None:
    """
    Move a campaign to `to_status` and hand it to Celery, atomically enough.

    Reverting on dispatch failure keeps the database honest about what is
    actually queued: 'running' has no transition back to 'draft', so a campaign
    committed without a task behind it is stuck.
    """
    previous_status = campaign.status

    try:
        transition(campaign, to_status)
    except CampaignTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    db.commit()

    try:
        dispatch()
    except Exception as exc:
        logger.exception(
            "Broker dispatch failed; reverting campaign status. id=%s", campaign.id
        )
        campaign.status = previous_status
        db.commit()
        raise HTTPException(
            status_code=503,
            detail="Could not queue the campaign — the task broker is unavailable.",
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

    from_address = _validate_from_address(
        db=db,
        user=current_user,
        from_address=str(body.from_address) if body.from_address else None,
    )

    campaign = Campaign(
        user_id=current_user.id,
        name=body.name,
        subject=body.subject,
        template_body=resolved_body,
        template_id=str(body.template_id) if body.template_id else None,
        from_address=from_address,
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

    logger.info("Campaign created. id=%s user=%s", campaign.id, current_user.id)
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
    # model_fields_set, not a None check: for from_address, None is a
    # meaningful value — "send from my own mailbox" — and is the only way to
    # undo a shared sender. Testing for None would make that change
    # impossible to express.
    if "from_address" in body.model_fields_set:
        campaign.from_address = _validate_from_address(
            db=db,
            user=current_user,
            from_address=str(body.from_address) if body.from_address else None,
        )
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

    # An in-flight campaign has a worker or a queued ETA task pointing at it.
    # Everything else — including completed and failed — is safe to remove; the
    # recipients and send logs cascade with it.
    if campaign.status in {"running", "scheduled"}:
        raise HTTPException(
            status_code=409,
            detail=(
                f"A campaign that is '{campaign.status}' cannot be deleted. "
                "Pause it first."
            ),
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

    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are supported.")

    with tempfile.TemporaryDirectory(prefix="recipient-upload-") as staging:
        save_file_path = Path(staging) / f"{uuid4()}.csv"

        _stream_to_disk(file, save_file_path)

        try:
            summary = import_recipients_from_csv(
                db=db, campaign_id=str(campaign.id), file_path=save_file_path
            )

        # A file the caller got wrong is a 400, not a 500.
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except UnicodeDecodeError as exc:
            raise HTTPException(
                status_code=400,
                detail="CSV must be UTF-8 encoded.",
            ) from exc
        except Exception as exc:
            logger.exception("Failed to upload recipient CSV")
            raise HTTPException(
                status_code=500, detail="Failed to process CSV upload."
            ) from exc

    return RecipientUploadResponse(
        message="Recipients imported successfully.",
        summary=ImportSummarySchema(
            total_rows=summary.total_rows,
            imported=summary.imported,
            invalid=summary.invalid,
        ),
    )


def _stream_to_disk(file: UploadFile, destination: Path) -> None:
    """
    Write an upload to disk, refusing anything over MAX_UPLOAD_BYTES.

    Enforced while streaming: UploadFile does not know the length up front and
    Content-Length is caller-controlled.
    """
    written = 0

    with destination.open("wb") as output:
        while chunk := file.file.read(1024 * 1024):
            written += len(chunk)

            if written > settings.MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=(
                        "File exceeds maximum allowed size of "
                        f"{settings.MAX_UPLOAD_BYTES // 1024 // 1024} MB."
                    ),
                )

            output.write(chunk)


@router.get("/{campaign_id}/recipients", response_model=RecipientListResponse)
def list_recipients(
    campaign_id: str,
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RecipientListResponse:
    """List a campaign's recipients, optionally filtered by status."""
    _get_campaign_or_404(campaign_id, db, current_user)

    base_query = db.query(CampaignRecipient).filter(
        CampaignRecipient.campaign_id == campaign_id
    )

    if status:
        base_query = base_query.filter(CampaignRecipient.status == status)

    total = base_query.count()
    items = (
        base_query.order_by(CampaignRecipient.created_at)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return RecipientListResponse(
        items=[RecipientResponse.model_validate(r) for r in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{campaign_id}/stats", response_model=CampaignStatsResponse)
def campaign_stats(
    campaign_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CampaignStatsResponse:
    """Recipient counts per status — what a campaign actually did."""
    campaign = _get_campaign_or_404(campaign_id, db, current_user)

    by_status: dict[str, int] = dict(
        db.query(CampaignRecipient.status, func.count())
        .filter(CampaignRecipient.campaign_id == campaign_id)
        .group_by(CampaignRecipient.status)
        .tuples()
        .all()
    )

    return CampaignStatsResponse(
        campaign_id=campaign.id,
        status=campaign.status,
        total_recipients=sum(by_status.values()),
        by_status=by_status,
        sent=by_status.get("sent", 0),
        failed=by_status.get("failed", 0),
        pending=by_status.get("pending", 0),
        awaiting_validation=by_status.get("pending_validation", 0),
        invalid=by_status.get("invalid", 0),
    )


@router.post("/{campaign_id}/start", response_model=dict[str, str])
def start_campaign(
    campaign_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    campaign = _get_campaign_or_404(campaign_id, db, current_user)
    _assert_sendable(db=db, campaign=campaign)

    _transition_and_dispatch(
        db=db,
        campaign=campaign,
        to_status="running",
        dispatch=lambda: send_campaign_task.delay(str(campaign.id)),
    )

    logger.info("Campaign queued. id=%s", campaign_id)
    return {"message": "Campaign queued successfully."}


@router.post("/{campaign_id}/schedule", response_model=dict[str, str])
def schedule_campaign(
    campaign_id: str,
    body: CampaignSchedule,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    campaign = _get_campaign_or_404(campaign_id, db, current_user)
    _assert_sendable(db=db, campaign=campaign)

    campaign.scheduled_at = body.scheduled_at

    _transition_and_dispatch(
        db=db,
        campaign=campaign,
        to_status="scheduled",
        dispatch=lambda: send_campaign_task.apply_async(
            args=(str(campaign.id),),
            eta=body.scheduled_at,
        ),
    )

    logger.info("Campaign scheduled. id=%s eta=%s", campaign_id, body.scheduled_at)
    return {"message": "Campaign scheduled successfully."}


@router.post("/{campaign_id}/pause", response_model=dict[str, str])
def pause_campaign(
    campaign_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    campaign = _get_campaign_or_404(campaign_id, db, current_user)

    try:
        transition(campaign, "paused")
    except CampaignTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    db.commit()
    logger.info("Campaign paused. id=%s", campaign_id)
    return {"message": "Campaign paused successfully."}


@router.post("/{campaign_id}/resume", response_model=dict[str, str])
def resume_campaign(
    campaign_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    campaign = _get_campaign_or_404(campaign_id, db, current_user)

    # Cleared so the beat reconciler cannot match this campaign and dispatch a
    # second task alongside the one queued below.
    campaign.scheduled_at = None

    _transition_and_dispatch(
        db=db,
        campaign=campaign,
        to_status="running",
        dispatch=lambda: send_campaign_task.delay(str(campaign.id)),
    )

    logger.info("Campaign resumed. id=%s", campaign_id)
    return {"message": "Campaign resumed successfully."}


@router.post("/{campaign_id}/retry", response_model=dict[str, str])
def retry_campaign(
    campaign_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    """
    Re-queue a campaign that ended in 'failed'.

    Recipients already marked 'sent' are skipped by the worker's idempotency
    check, so this picks up the remaining ones rather than resending.
    """
    campaign = _get_campaign_or_404(campaign_id, db, current_user)
    campaign.scheduled_at = None

    _transition_and_dispatch(
        db=db,
        campaign=campaign,
        to_status="running",
        dispatch=lambda: send_campaign_task.delay(str(campaign.id)),
    )

    logger.info("Campaign retried. id=%s", campaign_id)
    return {"message": "Campaign re-queued successfully."}
