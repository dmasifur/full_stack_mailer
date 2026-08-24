from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging

from sqlalchemy.orm import Session

from server.db.session import SessionLocal
from server.models.campaign import Campaign
from server.models.campaign_recipient import CampaignRecipient
from server.services.campaign_state import CampaignTransitionError, transition
from server.workers.celery import celery_app

logger = logging.getLogger(__name__)

# Grace period before assuming a validation task was lost rather than still
# running.
VALIDATION_STALE_AFTER = timedelta(minutes=10)


@celery_app.task(name="reconcile_campaigns_task")
def reconcile_campaigns_task() -> None:
    """
    Periodic sweeper for campaigns the broker may have dropped.

    apply_async(eta=...) parks the task inside Redis, where a flush or restart
    loses it silently. This makes the database, not the broker, the source of
    truth for what still needs sending.
    """
    db: Session = SessionLocal()

    try:
        _requeue_overdue_campaigns(db)
        _requeue_stalled_validation(db)

    except Exception:
        db.rollback()
        logger.exception("Campaign reconciliation failed.")
        raise

    finally:
        db.close()


def _requeue_overdue_campaigns(db: Session) -> None:
    due = (
        db.query(Campaign)
        .filter(
            Campaign.status == "scheduled",
            Campaign.scheduled_at.isnot(None),
            Campaign.scheduled_at <= datetime.now(tz=UTC),
        )
        .all()
    )

    if not due:
        return

    # Imported here: a top-level import would make the worker graph circular.
    from server.workers.send_campaign import send_campaign_task

    for campaign in due:
        try:
            transition(campaign, "running")
        except CampaignTransitionError:
            logger.exception(
                "Skipping overdue campaign in unexpected state. id=%s status=%s",
                campaign.id,
                campaign.status,
            )
            continue

        db.commit()
        send_campaign_task.delay(str(campaign.id))
        logger.info(
            "Re-queued overdue scheduled campaign. id=%s scheduled_at=%s",
            campaign.id,
            campaign.scheduled_at,
        )


def _requeue_stalled_validation(db: Session) -> None:
    """
    Re-queue DNS validation for imports whose task never ran.

    Validation is enqueued once, from inside the upload request. If the broker
    was down then, the rows stay at 'pending_validation' forever and the send
    worker ignores them. This is the safety net.
    """
    cutoff = datetime.now(tz=UTC) - VALIDATION_STALE_AFTER

    stalled = [
        row[0]
        for row in db.query(CampaignRecipient.campaign_id)
        .filter(
            CampaignRecipient.status == "pending_validation",
            CampaignRecipient.created_at < cutoff,
        )
        .distinct()
        .all()
    ]

    if not stalled:
        return

    from server.workers.validate_recipients import validate_recipients_task

    for campaign_id in stalled:
        validate_recipients_task.delay(str(campaign_id))
        logger.info("Re-queued stalled DNS validation. campaign=%s", campaign_id)
