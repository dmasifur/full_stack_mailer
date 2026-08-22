from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

# One shared instance: SlowAPI resolves limits through app.state.limiter, so a
# Limiter built inside a router is never consulted. See docs/architecture.md.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200/minute"],
    storage_uri=settings.REDIS_URL,
    # Degrade to per-process counters if Redis is down, rather than 500 on
    # every request.
    in_memory_fallback_enabled=True,
    in_memory_fallback=["200/minute"],
    swallow_errors=True,
)
