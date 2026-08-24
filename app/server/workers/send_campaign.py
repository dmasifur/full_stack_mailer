from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
import time

from celery import Task
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from server.db.session import SessionLocal
from server.models.campaign import Campaign
from server.models.campaign_cc_recipient import CampaignCcRecipient
from server.models.campaign_recipient import CampaignRecipient
from server.models.email_log import EmailLog
from server.models.user import User
from server.services.campaign_state import transition
from server.services.email_sender import (
    EmailAuthError,
    PermanentEmailError,
    RetryableEmailError,
    send_email_via_graph_api,
)
from server.services.merge_fields import render_merge_fields
from server.services.microsoft_token_service import (
    TokenRefreshError,
    refresh_access_token,
)
from server.workers.celery import celery_app

logger = logging.getLogger(__name__)

BATCH_SIZE = 10
EMAIL_DELAY_SECONDS = 5
MAX_RETRIES = 3

# How long a recipient may sit at "sending" before another run reclaims it.
# Only a crashed worker leaves rows in that state.
STALE_SENDING_AFTER = timedelta(minutes=30)

# Anything outside this set means the task is stale and must be dropped.
STARTABLE_STATUSES = frozenset({"draft", "scheduled", "running"})


@celery_app.task(
    # Explicit, like the other two tasks: an auto-derived name is the module
    # path, which would tie the queue's contents to a directory name.
    name="send_campaign_task",
    bind=True,
    autoretry_for=(RetryableEmailError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": MAX_RETRIES},
)
def send_campaign_task(self: Task[..., None], campaign_id: str) -> None:

    db: Session = SessionLocal()

    try:
        campaign = db.get(Campaign, campaign_id)

        if not campaign:
            logger.error("Campaign not found: %s", campaign_id)
            return

        user = db.get(User, campaign.user_id)

        if not user:
            logger.error("User not found for campaign.")
            return

        # The only place a stale task can be stopped: the pause check inside the
        # loop below runs after the transition, too late to help.
        if campaign.status not in STARTABLE_STATUSES:
            logger.info(
                "Dropping stale send task; campaign is not startable. id=%s status=%s",
                campaign_id,
                campaign.status,
            )
            return

        if campaign.status != "running":
            transition(campaign, "running")
            db.commit()

        logger.info("Campaign started: %s", campaign_id)

        # A worker killed mid-send leaves rows at "sending", matching neither
        # the pending filter nor "sent".
        _release_stale_sending(db=db, campaign_id=campaign_id)

        cc_emails = _get_cc_emails(db=db, campaign_id=campaign_id)

        while True:
            db.expire_all()

            latest_campaign = db.get(Campaign, campaign_id)

            if not latest_campaign:
                logger.error("Campaign disappeared during send: %s", campaign_id)
                return

            if latest_campaign.status == "paused":
                logger.info("Campaign paused: %s", campaign_id)
                return

            recipients = _get_pending_recipients(db=db, campaign_id=campaign_id)

            if not recipients:
                logger.info("No pending recipients left. campaign=%s", campaign_id)
                break

            logger.info(
                "Processing batch. campaign=%s batch_size=%s",
                campaign_id,
                len(recipients),
            )

            for recipient in recipients:
                try:
                    _send_single_recipient(
                        db=db,
                        campaign=campaign,
                        user=user,
                        recipient=recipient,
                        cc_emails=cc_emails,
                    )
                    time.sleep(EMAIL_DELAY_SECONDS)

                except EmailAuthError:
                    logger.exception("Auth failure. Campaign paused.")
                    transition(campaign, "paused")
                    db.commit()
                    return

                except RetryableEmailError:
                    logger.exception("Retryable send error. recipient=%s", recipient.id)
                    raise

                # A permanent failure belongs to one recipient, not the campaign.
                except PermanentEmailError:
                    logger.warning(
                        "Permanent send failure — skipping recipient. recipient=%s",
                        recipient.id,
                        exc_info=True,
                    )
                    continue

                except Exception:
                    logger.exception(
                        "Unexpected recipient failure. recipient=%s", recipient.id
                    )
                    raise

        db.refresh(campaign)

        if campaign.status != "paused":
            transition(campaign, "completed")
            db.commit()

    # Retryable errors must not fail the campaign — autoretry resumes it. Except
    # on the last attempt, after which no task remains to resume it.
    except RetryableEmailError:
        db.rollback()

        if self.request.retries >= MAX_RETRIES:
            logger.error(
                "Retries exhausted; marking campaign failed. campaign=%s",
                campaign_id,
                exc_info=True,
            )
            _mark_failed(db=db, campaign_id=campaign_id)
        else:
            logger.warning(
                "Campaign send interrupted by a retryable error. campaign=%s",
                campaign_id,
                exc_info=True,
            )
        raise

    except Exception:
        db.rollback()
        logger.exception("Campaign send task failed. campaign=%s", campaign_id)
        _mark_failed(db=db, campaign_id=campaign_id)
        raise

    finally:
        db.close()


def _mark_failed(*, db: Session, campaign_id: str) -> None:
    """
    Move a campaign to 'failed' after an unrecoverable error.

    Without this the row stays at 'running' forever: 'running' has no transition
    back to 'draft' or 'scheduled', so the campaign would be unrecoverable via
    the API. Never let a bookkeeping failure mask the original exception.
    """
    try:
        campaign = db.get(Campaign, campaign_id)

        if not campaign:
            return

        # Release rows left at "sending" so /retry can resend them.
        released = (
            db.query(CampaignRecipient)
            .filter(
                CampaignRecipient.campaign_id == campaign_id,
                CampaignRecipient.status == "sending",
            )
            .update({CampaignRecipient.status: "pending"}, synchronize_session=False)
        )

        transition(campaign, "failed")
        db.commit()
        logger.info(
            "Campaign marked failed. id=%s released_recipients=%s",
            campaign_id,
            released,
        )

    except Exception:
        db.rollback()
        logger.exception("Could not mark campaign as failed. campaign=%s", campaign_id)


def _send_single_recipient(
    *,
    db: Session,
    campaign: Campaign,
    user: User,
    recipient: CampaignRecipient,
    cc_emails: list[str],
) -> None:
    existing_log = (
        db.query(EmailLog)
        .filter(
            EmailLog.campaign_id == campaign.id,
            EmailLog.recipient_email == recipient.email,
            EmailLog.status == "sent",
        )
        .first()
    )

    if existing_log:
        logger.info("Skipping already sent recipient. id=%s", recipient.id)
        recipient.status = "sent"
        db.commit()
        return

    # No "sending" write here: the claim in _get_pending_recipients set it, which
    # is what makes the claim survive the commits below.

    body = render_merge_fields(campaign.template_body, recipient)

    try:
        try:
            send_email_via_graph_api(
                user=user,
                recipient_email=recipient.email,
                subject=campaign.subject,
                html_body=body,
                from_address=campaign.from_address,
                cc_emails=cc_emails or None,
            )

        except EmailAuthError:
            logger.warning("Access token expired. Attempting refresh.")

            try:
                refresh_access_token(db=db, user=user)
            except TokenRefreshError as exc:
                logger.exception("Token refresh failed.")
                raise EmailAuthError("Unable to refresh token.") from exc

            db.refresh(user)
            logger.info("Token refreshed successfully. Retrying email send.")

            send_email_via_graph_api(
                user=user,
                recipient_email=recipient.email,
                subject=campaign.subject,
                html_body=body,
                from_address=campaign.from_address,
                cc_emails=cc_emails or None,
            )

        recipient.status = "sent"

        email_log = EmailLog(
            campaign_id=campaign.id,
            recipient_email=recipient.email,
            status="sent",
        )
        db.add(email_log)
        db.commit()

        logger.info("Email sent successfully. recipient=%s", recipient.id)

    # Campaign-level problems, not recipient-level: the address is fine, the
    # transport or token is not. Re-raise without blaming the recipient.
    except RetryableEmailError, EmailAuthError:
        raise

    except PermanentEmailError as exc:
        db.rollback()
        db.refresh(recipient)

        recipient.status = "failed"
        recipient.retry_count += 1
        recipient.failure_reason = str(exc)

        email_log = EmailLog(
            campaign_id=campaign.id,
            recipient_email=recipient.email,
            status="failed",
            error_message=str(exc),
        )
        db.add(email_log)
        db.commit()

        logger.exception("Email send failed. recipient=%s", recipient.id)
        raise


def _get_cc_emails(*, db: Session, campaign_id: str) -> list[str]:
    rows = (
        db.query(CampaignCcRecipient)
        .filter(CampaignCcRecipient.campaign_id == campaign_id)
        .all()
    )
    return [row.email for row in rows]


def _release_stale_sending(*, db: Session, campaign_id: str) -> None:
    """Return recipients abandoned at 'sending' by a crashed worker to 'pending'."""
    cutoff = datetime.now(tz=UTC) - STALE_SENDING_AFTER

    released = (
        db.query(CampaignRecipient)
        .filter(
            CampaignRecipient.campaign_id == campaign_id,
            CampaignRecipient.status == "sending",
            CampaignRecipient.updated_at < cutoff,
        )
        .update({CampaignRecipient.status: "pending"}, synchronize_session=False)
    )

    if released:
        db.commit()
        logger.warning(
            "Released %s recipient(s) stranded at 'sending'. campaign=%s",
            released,
            campaign_id,
        )


def _get_pending_recipients(
    *,
    db: Session,
    campaign_id: str,
) -> list[CampaignRecipient]:
    """
    Claim up to BATCH_SIZE recipients, atomically.

    Must be a single UPDATE, not SELECT ... FOR UPDATE followed by writes: those
    locks are released by the first commit inside the send loop, freeing the rest
    of the batch for a second worker. See docs/architecture.md.
    """
    claimable = (
        select(CampaignRecipient.id)
        .where(
            CampaignRecipient.campaign_id == campaign_id,
            CampaignRecipient.status == "pending",
            CampaignRecipient.dns_valid.is_(True),
        )
        .order_by(CampaignRecipient.created_at)
        .limit(BATCH_SIZE)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )

    claim = (
        update(CampaignRecipient)
        .where(CampaignRecipient.id.in_(claimable))
        .values(status="sending")
        .returning(CampaignRecipient)
    )

    recipients = list(
        db.execute(claim, execution_options={"synchronize_session": False})
        .scalars()
        .all()
    )
    db.commit()

    return recipients
