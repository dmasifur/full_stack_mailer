"""
Shared test fixtures.

Tests run against a dedicated database whose name is the application database's
plus a ``_test`` suffix (override wholesale with ``TEST_DATABASE_URL``). The
suffix is asserted before anything connects, so a misconfigured environment
fails loudly rather than truncating real campaigns.

The database is created and migrated once per session and dropped afterwards;
every test starts from empty tables.
"""

from __future__ import annotations

from collections.abc import Iterator
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import make_url

BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_DIR / ".env")


def _resolve_test_database_url() -> str:
    override = os.environ.get("TEST_DATABASE_URL")

    if override:
        url = make_url(override)
    else:
        base = os.environ.get("DATABASE_URL")
        if not base:
            raise RuntimeError(
                "Set DATABASE_URL (or TEST_DATABASE_URL) before running the tests."
            )
        url = make_url(base)
        url = url.set(database=f"{url.database}_test")

    # Neon's -pooler host is PgBouncer, tuned for short serverless connections.
    # It drops long-lived ones mid-statement ("SSL connection has been closed
    # unexpectedly"), which a suite doing CREATE DATABASE and TRUNCATE trips
    # constantly. The direct endpoint is stable for this workload.
    if url.host and "-pooler." in url.host:
        url = url.set(host=url.host.replace("-pooler.", ".", 1))

    if not (url.database or "").endswith("_test"):
        raise RuntimeError(
            f"Refusing to run: test database {url.database!r} must end with '_test'."
        )

    return url.render_as_string(hide_password=False)


TEST_DATABASE_URL = _resolve_test_database_url()

# Must happen before any app import: Settings reads the environment at
# construction and app.db.session binds its engine at import time.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi import Depends  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import main  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.api.dependencies import get_current_user, get_db  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.models import (  # noqa: E402
    Campaign,
    CampaignCcRecipient,
    CampaignRecipient,
    SenderAddress,
    User,
)


def _admin_engine():
    """Engine on the maintenance database, for CREATE/DROP DATABASE."""
    admin_url = make_url(TEST_DATABASE_URL).set(database="postgres")
    return create_engine(
        admin_url.render_as_string(hide_password=False),
        isolation_level="AUTOCOMMIT",
    )


def _drop_database(conn, name: str | None) -> None:
    conn.execute(
        text(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = :name AND pid <> pg_backend_pid()"
        ),
        {"name": name},
    )
    conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))


@pytest.fixture(scope="session", autouse=True)
def _test_database():
    name = make_url(TEST_DATABASE_URL).database
    admin = _admin_engine()

    with admin.connect() as conn:
        _drop_database(conn, name)
        conn.execute(text(f'CREATE DATABASE "{name}"'))

    try:
        config = Config(str(BACKEND_DIR / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
        # env.py reads settings.DATABASE_URL, which already points at the test
        # database because the environment was overridden above.
        command.upgrade(config, "head")
        yield
    finally:
        engine.dispose()
        with admin.connect() as conn:
            _drop_database(conn, name)
        admin.dispose()


@pytest.fixture(autouse=True)
def _clean_tables():
    """Empty every table between tests, leaving the schema in place."""
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture
def db() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def make_user(db):
    """Create a user, optionally with a registered sender address."""
    created = {"n": 0}

    def _make(email: str | None = None, sender_address: str | None = None) -> User:
        created["n"] += 1
        n = created["n"]
        user = User(
            email=email or f"user{n}@example.com",
            full_name=f"User {n}",
            microsoft_id=f"ms-{n}",
        )
        db.add(user)
        db.flush()

        if sender_address:
            db.add(
                SenderAddress(
                    user_id=user.id,
                    label=f"Label {n}",
                    email=sender_address,
                    is_default=True,
                )
            )

        db.commit()
        db.refresh(user)
        return user

    return _make


@pytest.fixture
def alice(make_user) -> User:
    user: User = make_user("alice@example.com", sender_address="alice-send@example.com")
    return user


@pytest.fixture
def bob(make_user) -> User:
    user: User = make_user("bob@example.com", sender_address="bob-send@example.com")
    return user


@pytest.fixture
def make_campaign(db):
    """
    Create a campaign with recipients already past DNS validation.

    Recipients default to 'pending'/dns_valid=True because the send worker only
    picks up rows in that state; tests that care about validation set it up
    themselves.
    """

    def _make(
        user: User,
        *,
        status: str = "draft",
        recipients: list[str] | None = None,
        cc_emails: list[str] | None = None,
        from_address: str | None = None,
        scheduled_at=None,
    ) -> Campaign:
        campaign = Campaign(
            user_id=user.id,
            name="Test campaign",
            subject="Test subject",
            template_body="<p>Hello</p>",
            from_address=from_address,
            status=status,
            scheduled_at=scheduled_at,
        )
        db.add(campaign)
        db.flush()

        for email in recipients or []:
            db.add(
                CampaignRecipient(
                    campaign_id=campaign.id,
                    email=email,
                    status="pending",
                    dns_valid=True,
                )
            )

        for email in cc_emails or []:
            db.add(CampaignCcRecipient(campaign_id=campaign.id, email=email))

        db.commit()
        db.refresh(campaign)
        return campaign

    return _make


@pytest.fixture
def client(alice):
    """
    TestClient authenticated as Alice by default.

    Call ``client.login_as(user)`` to switch. The override resolves the user
    through the same session the endpoint uses, so the instance stays attached.
    """
    active = {"user_id": alice.id}

    def _current_user(session: Session = Depends(get_db)) -> User:
        user = session.get(User, active["user_id"])
        assert user is not None, "the fixture user must exist in this session"
        return user

    main.app.dependency_overrides[get_current_user] = _current_user

    test_client = TestClient(main.app)
    # Attached dynamically so tests can switch identity mid-test.
    test_client.login_as = lambda user: active.update(user_id=user.id)  # type: ignore[attr-defined]

    try:
        yield test_client
    finally:
        main.app.dependency_overrides.clear()


@pytest.fixture
def anonymous_client():
    """TestClient with no authentication override — hits the real dependency."""
    main.app.dependency_overrides.clear()
    with TestClient(main.app) as test_client:
        yield test_client


@pytest.fixture
def no_broker(monkeypatch):
    """
    Stop tasks being handed to Celery.

    Returns the patched ``.delay`` mocks so tests can assert what was enqueued
    without a live Redis.
    """
    from unittest.mock import MagicMock

    import app.api.campaigns as campaigns_api
    import app.services.recipient_import as recipient_import
    import app.workers.send_campaign as send_campaign

    send = MagicMock()
    validate = MagicMock()

    monkeypatch.setattr(campaigns_api.send_campaign_task, "delay", send)
    monkeypatch.setattr(campaigns_api.send_campaign_task, "apply_async", MagicMock())
    monkeypatch.setattr(send_campaign.send_campaign_task, "delay", send)
    monkeypatch.setattr(recipient_import.validate_recipients_task, "delay", validate)

    return {"send": send, "validate": validate}


@pytest.fixture
def instant_send(monkeypatch):
    """Remove the inter-email throttle so worker tests don't sleep."""
    import app.workers.send_campaign as send_campaign

    monkeypatch.setattr(send_campaign, "EMAIL_DELAY_SECONDS", 0)
