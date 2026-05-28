import logging
import time

from celery import shared_task

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.campaign import Campaign

from app.models.campaign_recipient import CampaignRecipient

from app.models.email_log import EmailLog
from app.models.user import User

from app.services.email_sender import EmailSendError, send_email_via_graph_api


logger = logging.getLogger(__name__)

BATCH_SIZE = 10

EMAIL_DELAY_SECONDS = 1

@shared_task(
    bind=True,
    autoretry_for=(Exception),
    retry_backoff=True,
    retry_kwargs={"max_retries":3}
)
def send_campaign_task(
    self,
    campaign_id: str,
    
) -> None:
    
    db: Session = SessionLocal()
    
    try:
        
        campaign = db.get(Campaign,campaign_id)
        
        if not campaign:
            logger.error(
                "Campaign not found: %s",
                campaign_id
            )
            return
        
        user = db.get(User, campaign.user_id)
        
        if not user:
            logger.error(
                "User not found for campaign."
            )
            return
        
        campaign.status = "running"
        db.commit()
        
        while True:
            db.expire_all()
            
            latest_campaign = db.get(
                Campaign,
                campaign_id
            )
            
            if latest_campaign.status == "paused":
                logger.info(
                    "Campaign paused: %s",
                    campaign_id
                )
                return
            
            recipients = db.query(CampaignRecipient).filter(
                CampaignRecipient.campaign_id == campaign_id
            ).limit(BATCH_SIZE).all()
            
            if not recipients:
                break
            
            for recipient in recipients:
                try:
                    _send_single_recipient(
                        db=db,
                        campaign=campaign,
                        user=user,
                        recipient = recipient
                    )
                    
                    time.sleep(
                        EMAIL_DELAY_SECONDS
                    )
                    
                except Exception:
                    logger.exception(
                        "Recipient send failed. "
                        "recipient=%s",
                        recipient.email
                    )
        campaign.status = "completed"
        db.commit()
    
    except Exception:
        db.rollback()
        
        logger.exception(
            "Campaign send task failed."
        )
        
        raise
    
    finally:
        db.close()
        
        
def _send_single_recipient(*, db:Session, campaign: Campaign, user:User, recipient: CampaignRecipient) ->None:
    
    existing_log = db.query(EmailLog).filter(EmailLog.campaign_id == campaign.id, EmailLog.recipient_email == recipient.email, EmailLog.status == "sent").first()
    
    if existing_log:
        logger.info(
            "Skipping already sent recipient: %s",
            recipient.email
        )
        
        recipient.status="sent"
        db.commit()
        
        return
    
    recipient.status = "sending"
    db.commit()
    
    try:
        send_email_via_graph_api(
            user = user,
            recipient_email=recipient.email,
            subject=campaign.subject,
            html_body=campaign.template_body
        )
        
        recipient.status = "sent"
        
        email_log = EmailLog(
            campaign_id = campaign.id,
            recipient_email = recipient.email,
            status="sent"
        )
        
        db.add(email_log)
        
        db.commit()
        
        logger.info(
            "Email sent successfully: %s",
            recipient.email
        )
    
    except EmailSendError as exc:
        db.rollback()
        
        recipient.status = "failed"
        recipient.retry_count += 1
        recipient.failure_reason = str(exc)
        
        email_log = EmailLog(
            campaign_id = campaign.id,
            recipient_email = recipient.email,
            status="failed",
            error_message=str(exc)
        )
        
        db.add(email_log)
        
        db.commit()
        
        logger.exception(
            "Eail send failed: %s",
            recipient.email
        )