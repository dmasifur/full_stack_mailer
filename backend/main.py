from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.auth import router as auth_router
from app.api.campaigns import router as campaigns_router
from app.api.health import router as health_router
from app.api.sender_addresses import router as sender_addresses_router
from app.api.templates import router as templates_router
from app.core.config import settings
from app.core.logging import setup_logging
from app.core.rate_limit import limiter

setup_logging()

app = FastAPI(title=settings.APP_NAME)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(campaigns_router)
app.include_router(templates_router)
app.include_router(sender_addresses_router)
