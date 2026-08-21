import ssl

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "full_stack_mailer",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.workers.send_campaign",
        "app.workers.reconcile_campaigns",
        "app.workers.validate_recipients",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    broker_use_ssl={
        "ssl_cert_reqs": ssl.CERT_NONE,
    },
    redis_backend_use_ssl={
        "ssl_cert_reqs": ssl.CERT_NONE,
    },
    # The Procfile runs a beat process; without a schedule it does nothing.
    # The reconciler is what makes scheduling durable — an apply_async(eta=...)
    # task lives only in the broker and is lost if Redis is flushed.
    beat_schedule={
        "reconcile-campaigns": {
            "task": "reconcile_campaigns_task",
            "schedule": 60.0,
        },
    },
)
