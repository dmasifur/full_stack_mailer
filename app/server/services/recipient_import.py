from __future__ import annotations

import csv
import logging
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from server.models.campaign_recipient import CampaignRecipient
from server.workers.validate_recipients import validate_recipients_task

logger = logging.getLogger(__name__)

COMMIT_BATCH_SIZE = 100


class ImportSummary:
    def __init__(self) -> None:
        self.total_rows = 0
        self.imported = 0
        self.invalid = 0  # malformed rows (missing/empty email), not DNS failures


def import_recipients_from_csv(
    db: Session,
    campaign_id: str,
    file_path: Path,
) -> ImportSummary:
    summary = ImportSummary()
    pending_rows: list[dict[str, object]] = []

    with file_path.open("r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)

        required_columns = {"email"}
        if not required_columns.issubset(reader.fieldnames or set()):
            raise ValueError("CSV must contain at least an 'email' column")

        for row in reader:
            summary.total_rows += 1
            email = (row.get("email") or "").strip().lower()

            if not email:
                logger.warning("Skipping row %s — empty email", summary.total_rows)
                summary.invalid += 1
                continue

            pending_rows.append(
                {
                    "campaign_id": campaign_id,
                    "email": email,
                    "first_name": (row.get("first_name") or "").strip() or None,
                    "last_name": (row.get("last_name") or "").strip() or None,
                    "dns_valid": None,
                    "status": "pending_validation",
                    "failure_reason": None,
                }
            )
            summary.imported += 1

            if len(pending_rows) >= COMMIT_BATCH_SIZE:
                _insert_batch(db=db, rows=pending_rows)
                pending_rows.clear()

        if pending_rows:
            _insert_batch(db=db, rows=pending_rows)

    logger.info(
        "Recipient import completed. total=%s queued=%s skipped=%s",
        summary.total_rows,
        summary.imported,
        summary.invalid,
    )

    # Rows are already committed, so a broker outage must not turn a successful
    # import into a 500. The reconciler sweeps anything left behind.
    try:
        validate_recipients_task.delay(campaign_id)
    except Exception:
        logger.exception(
            "Could not queue DNS validation; the reconciler will pick it up. "
            "campaign=%s",
            campaign_id,
        )

    return summary


def _insert_batch(db: Session, rows: list[dict[str, object]]) -> None:

    try:
        stmt = (
            insert(CampaignRecipient)
            .values(rows)
            .on_conflict_do_nothing(
                index_elements=["campaign_id", "email"],
            )
        )
        db.execute(stmt)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to commit recipient batch")
        raise
