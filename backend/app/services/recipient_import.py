import csv
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.campaign_recipient import CampaignRecipient
from app.services.email_validation import validate_email_address

logger = logging.getLogger(__name__)

COMMIT_BATCH_SIZE = 100


class ImportSummary:
    def __init__(self) -> None:
        self.total_rows = 0
        self.imported = 0
        self.invalid = 0


def import_recipients_from_csv(
    db: Session,
    campaign_id: str,
    file_path: Path,
) -> ImportSummary:
    summary = ImportSummary()

    pending_objects: list[CampaignRecipient] = []

    with file_path.open("r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)

        required_columns = {"email"}

        if not required_columns.issubset(reader.fieldnames or set()):
            raise ValueError("CSV must contain at least an 'email' column")

        for row in reader:
            summary.total_rows += 1
            email = (row.get("email") or "").strip()

            if not email:
                logger.warning("Skipping row with empty email")
                summary.invalid += 1
                continue

            validation_result = validate_email_address(email)

            recipient = CampaignRecipient(
                campaign_id=campaign_id,
                first_name=(row.get("first_name") or "").strip() or None,
                last_name=(row.get("last_name") or "").strip() or None,
                email=email,
                dns_valid=validation_result.is_valid,
                status=("pending" if validation_result.is_valid else "invalid"),
                failure_reason=validation_result.reason,
            )

            pending_objects.append(recipient)

            if validation_result.is_valid:
                summary.imported += 1
            else:
                summary.invalid += 1

            if len(pending_objects) >= COMMIT_BATCH_SIZE:
                _commit_batch(db=db, objects=pending_objects)
                pending_objects.clear()
        if pending_objects:
            _commit_batch(db=db, objects=pending_objects)

        logger.info(
            "Recipient import completed. total=%s imported=%s invalid=%s",
            summary.total_rows,
            summary.imported,
            summary.invalid,
        )

        return summary


def _commit_batch(db: Session, objects: list[CampaignRecipient]) -> None:
    try:
        db.add_all(objects)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to commit recipient batch")
        raise
