from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "full_stack_mailer",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    
    task_acks_late=True,
    
    worker_prefetch_multipiler=1,
    task_track_started=True
)