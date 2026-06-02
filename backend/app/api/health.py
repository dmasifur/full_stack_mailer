from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
import redis
from sqlalchemy import text

from app.core.config import settings
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


def _check_database() -> dict:
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        return {"status": "ok"}
    except Exception as exc:
        logger.error("Database health check failed: %s", exc)
        return {"status": "error", "detail": str(exc)}


def _check_redis() -> dict:
    try:
        client = redis.Redis.from_url(
            settings.REDIS_URL, ssl_cert_reqs=None, socket_connect_timeout=2
        )
        client.ping()
        return {"status": "ok"}
    except Exception as exc:
        logger.error("Redis health check failed: %s", exc)
        return {"status": "error", "detail": str(exc)}


@router.get("/health")
def health_check() -> JSONResponse:
    checks = {
        "database": _check_database(),
        "redis": _check_redis(),
    }

    all_ok = all(c["status"] == "ok" for c in checks.values())

    status_code = 200 if all_ok else 503

    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ok" if all_ok else "degraded",
            "checks": checks,
        },
    )
