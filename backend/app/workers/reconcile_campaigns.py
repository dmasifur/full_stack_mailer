from __future__ import annotations

from datetime import UTC, datetime
import logging

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.campaign import Campaign
from app.services.campaign_state import CampaignTransitionError, transition
from app.workers.celery import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="reconcile_campaigns_task")
def reconcile_campaigns_task() -> None:
    """
    Periodic sweeper for campaigns the broker may have dropped.

    /schedule enqueues with apply_async(eta=...), which parks the task inside
    Redis. A flush, a purge, or a broker restart loses it silently and the
    campaign sits at 'scheduled' past its time with nothing to run it. This
    re-queues any such campaign, so the database — not the broker — is the
    source of truth for what still needs to be sent.
    """
    db: Session = SessionLocal()

    try:
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

        # Imported here rather than at module scope: send_campaign imports
        # campaign_state, and a top-level import in both directions would make
        # the worker module graph circular.
        from app.workers.send_campaign import send_campaign_task

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

    except Exception:
        db.rollback()
        logger.exception("Campaign reconciliation failed.")
        raise

    finally:
        db.close()
