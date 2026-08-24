from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from server.api.assets import router as assets_router
from server.api.auth import router as auth_router
from server.api.campaigns import router as campaigns_router
from server.api.health import router as health_router
from server.api.sender_addresses import router as sender_addresses_router
from server.api.templates import router as templates_router
from server.core.config import settings
from server.core.logging import setup_logging
from server.core.rate_limit import limiter
from server.spa import mount_spa

setup_logging()

app = FastAPI(title=settings.APP_NAME)

app.state.limiter = limiter
# Starlette types the handler as taking a bare Exception; slowapi's is
# narrower (RateLimitExceeded). Correct at runtime — Starlette only ever
# invokes it for the exception class it was registered against.
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
app.add_middleware(SlowAPIMiddleware)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(campaigns_router)
app.include_router(templates_router)
app.include_router(sender_addresses_router)
app.include_router(assets_router)

# Last: its catch-all route would otherwise shadow every router above it.
mount_spa(app)
