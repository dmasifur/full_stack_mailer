from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
import redis
from sqlalchemy import text

from server.core.config import settings
from server.db.session import SessionLocal

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


def _failure(component: str, exc: Exception) -> dict[str, str]:
    """
    Report a failed check without describing the infrastructure.

    /health is unauthenticated, and driver errors name the host, port, database
    and user — psycopg2 and redis-py both do. The operator gets the detail from
    the logs; outside development the caller only learns that something is down.
    """
    logger.error("%s health check failed: %s", component, exc)

    if settings.APP_ENV == "development":
        return {"status": "error", "detail": str(exc)}

    return {"status": "error"}


def _check_database() -> dict[str, str]:
    db = None
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as exc:
        return _failure("Database", exc)
    finally:
        # Must be in `finally`: a failing SELECT would otherwise skip the close
        # and leak the session, and health checks are polled continuously —
        # exactly when the database is flaky, which exhausts the pool.
        if db is not None:
            db.close()


def _check_redis() -> dict[str, str]:
    client = None
    try:
        # SSL options only apply to rediss:// URLs; passing them for a plain
        # redis:// connection is at best ignored and at worst an error.
        client = redis.Redis.from_url(
            settings.REDIS_URL,
            socket_connect_timeout=2,
            **(settings.redis_ssl_options or {}),
        )
        client.ping()
        return {"status": "ok"}
    except Exception as exc:
        return _failure("Redis", exc)
    finally:
        # from_url builds a fresh connection pool per call; without this every
        # health check leaks one.
        if client is not None:
            client.close()


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
