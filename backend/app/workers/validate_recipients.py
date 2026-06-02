from __future__ import annotations

import logging

import dns.exception
import dns.resolver
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.campaign_recipient import CampaignRecipient
from app.workers.celery import celery_app

logger = logging.getLogger(__name__)

BATCH_SIZE = 200


@celery_app.task(
    name="validate_recipients_task",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
)
def validate_recipients_task(self, campaign_id: str) -> None:

    db: Session = SessionLocal()

    try:
        offset = 0

        while True:
            recipients = (
                db.query(CampaignRecipient)
                .filter(
                    CampaignRecipient.campaign_id == campaign_id,
                    CampaignRecipient.status == "pending_validation",
                )
                .order_by(CampaignRecipient.created_at)
                .offset(offset)
                .limit(BATCH_SIZE)
                .all()
            )

            if not recipients:
                break

            for recipient in recipients:
                domain = recipient.email.split("@")[-1]
                dns_valid, reason = _check_mx(domain)

                recipient.dns_valid = dns_valid
                recipient.status = "pending" if dns_valid else "invalid"
                if not dns_valid:
                    recipient.failure_reason = reason

            db.commit()

            if len(recipients) < BATCH_SIZE:
                break

            offset += BATCH_SIZE

        logger.info("DNS validation completed for campaign=%s", campaign_id)

    except Exception as exc:
        db.rollback()
        logger.exception("DNS validation task failed. campaign=%s", campaign_id)
        raise self.retry(exc=exc) from exc

    finally:
        db.close()


def _check_mx(domain: str) -> tuple[bool, str | None]:

    try:
        dns.resolver.resolve(domain, "MX")
        return True, None
    except dns.resolver.NXDOMAIN:
        return False, "domain_not_found"
    except dns.resolver.NoAnswer:
        return False, "missing_mx_record"
    except dns.exception.Timeout:
        return False, "dns_timeout"
    except Exception as exc:
        return False, f"dns_error:{exc!s}"
