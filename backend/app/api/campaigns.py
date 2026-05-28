import logging
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile


from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.models.campaign import Campaign
from app.services.recipient_import import import_recipients_from_csv
from app.workers.send_campaign import send_campaign_task


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/campaigns", tags=["campaigns"])

UPLOAD_DIR = Path("uploads")

UPLOAD_DIR.mkdir(exist_ok=True)


@router.post("/{campaign_id}/recipients/upload")
def upload_recipients_csv(
    campaign_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)
) -> dict:
    campaign = db.get(Campaign, campaign_id)

    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")

    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are supported.")

    unique_filename = f"{uuid4()}.csv"

    save_file_path = UPLOAD_DIR / unique_filename

    try:
        with save_file_path.open("wb") as output:
            while chunk := file.file.read(1024 * 1024):
                output.write(chunk)
        summary = import_recipients_from_csv(
            db=db, campaign_id=campaign_id, file_path=save_file_path
        )

        return {
            "message": "Recipients imported successfully",
            "summary": {
                "total_rows": summary.total_rows,
                "imported": summary.imported,
                "invalid": summary.invalid,
            },
        }

    except Exception:
        logger.exception("Failed to upload recipient CSV")

        raise HTTPException(status_code=500, detail="Failed to process CSV upload.")

    finally:
        if save_file_path.exists():
            save_file_path.unlink(missing_ok=True)


@router.post("/{campaign_id}/start")
def start_campaign(campaign_id: str, db: Session = Depends(get_db)) -> dict:

    campaign = db.get(Campaign, campaign_id)

    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")

    if campaign.status not in ["draft", "scheduled"]:
        raise HTTPException(status_code=400, detail="Campaign cannot be started because the campaign status did not match.")

    campaign.status = "scheduled"

    db.commit()

    send_campaign_task.delay(campaign_id)

    return {"message": "Campaigned queued successfully."}
