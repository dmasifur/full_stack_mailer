from celery import Celery

from server.core.config import settings

# Sent only for rediss:// — SSL options on a plain redis:// URL are silently
# ignored, which hides whether verification is actually in force.
_ssl_options = settings.redis_ssl_options

celery_app = Celery(
    "full_stack_mailer",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "server.workers.send_campaign",
        "server.workers.reconcile_campaigns",
        "server.workers.validate_recipients",
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
    broker_use_ssl=_ssl_options,
    redis_backend_use_ssl=_ssl_options,
    # The reconciler is what makes scheduling durable: an apply_async(eta=...)
    # task lives only in the broker and is lost if Redis is flushed.
    beat_schedule={
        "reconcile-campaigns": {
            "task": "reconcile_campaigns_task",
            "schedule": 60.0,
        },
    },
)
