import logging
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.campaign import Campaign
from app.models.campaign_cc_recipient import CampaignCcRecipient
from app.models.campaign_recipient import CampaignRecipient
from app.models.email_log import EmailLog
from app.models.user import User
from app.services.campaign_state import transition
from app.services.email_sender import (
    EmailAuthError,
    EmailSendError,
    RetryableEmailError,
    send_email_via_graph_api,
)
from app.services.microsoft_token_service import TokenRefreshError, refresh_access_token
from app.workers.celery import celery_app

logger = logging.getLogger(__name__)

BATCH_SIZE = 10
EMAIL_DELAY_SECONDS = 5


@celery_app.task(
    autoretry_for=(RetryableEmailError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def send_campaign_task(campaign_id: str) -> None:

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

        if campaign.status != "running":
            transition(campaign, "running")
            db.commit()

        logger.info("Campaign started: %s", campaign_id)

        # Fetch CC list once — it's the same for every recipient in the campaign.
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
                    logger.exception(
                        "Retryable send error. recipient=%s", recipient.email
                    )
                    raise

                except EmailSendError:
                    logger.exception(
                        "Permanent send failure. recipient=%s", recipient.email
                    )
                    raise

                except Exception:
                    logger.exception(
                        "Unexpected recipient failure. recipient=%s", recipient.email
                    )
                    raise

        db.refresh(campaign)

        if campaign.status != "paused":
            transition(campaign, "completed")
            db.commit()

    except Exception:
        db.rollback()
        logger.exception("Campaign send task failed. campaign=%s", campaign_id)
        raise

    finally:
        db.close()


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
        logger.info("Skipping already sent recipient: %s", recipient.email)
        recipient.status = "sent"
        db.commit()
        return

    recipient.status = "sending"
    db.commit()

    try:
        try:
            send_email_via_graph_api(
                user=user,
                recipient_email=recipient.email,
                subject=campaign.subject,
                html_body=campaign.template_body,
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
                html_body=campaign.template_body,
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

        logger.info("Email sent successfully: %s", recipient.email)

    # Re-raise retryable errors BEFORE the EmailSendError catch so Celery's
    # autoretry_for can intercept them. EmailSendError is the parent class of
    # RetryableEmailError; catching the parent first would swallow the subtype.
    except RetryableEmailError:
        raise

    except EmailSendError as exc:
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

        logger.exception("Email send failed: %s", recipient.email)
        raise


def _get_cc_emails(*, db: Session, campaign_id: str) -> list[str]:
    rows = (
        db.query(CampaignCcRecipient)
        .filter(CampaignCcRecipient.campaign_id == campaign_id)
        .all()
    )
    return [row.email for row in rows]


def _get_pending_recipients(
    *,
    db: Session,
    campaign_id: str,
) -> list[CampaignRecipient]:
    query_statement = (
        select(CampaignRecipient)
        .where(
            CampaignRecipient.campaign_id == campaign_id,
            CampaignRecipient.status == "pending",
            CampaignRecipient.dns_valid.is_(True),
        )
        .limit(BATCH_SIZE)
        .with_for_update(skip_locked=True)
    )
    return db.execute(query_statement).scalars().all()
