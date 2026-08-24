"""
Regressions for the two leaks /health used to carry.

It is unauthenticated and polled continuously, which made both worse: driver
error strings name the host, port, database and user, and a session that was
never returned to the pool accumulated fastest exactly when the database was
already struggling.
"""

from __future__ import annotations

from typing import cast

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool

import server.api.health as health
from server.db.session import engine

BOOM = text("SELECT this_function_does_not_exist()")


@pytest.fixture
def failing_query(monkeypatch):
    """
    Make the health query fail *after* a connection is checked out.

    Raising earlier would not exercise the leak at all — the pool never hands
    out a connection, so there is nothing to strand.
    """
    real_execute = Session.execute

    def execute(self, statement, *args, **kwargs):
        if "SELECT 1" in str(statement):
            statement = BOOM
        return real_execute(self, statement, *args, **kwargs)

    monkeypatch.setattr(Session, "execute", execute)


def test_reports_the_database_as_healthy(anonymous_client):
    """
    Asserts the database leg only. Redis is checked against the real configured
    instance, whose reachability varies by machine and network — making the
    overall 200 an assertion about the environment rather than about the code.
    """
    response = anonymous_client.get("/health")

    assert response.json()["checks"]["database"]["status"] == "ok"


def test_a_failed_check_returns_503(anonymous_client, failing_query):
    response = anonymous_client.get("/health")

    assert response.status_code == 503
    assert response.json()["checks"]["database"]["status"] == "error"


def test_production_hides_the_driver_error(
    anonymous_client, failing_query, monkeypatch
):
    monkeypatch.setattr(health.settings, "APP_ENV", "production")

    body = anonymous_client.get("/health").text

    assert "detail" not in body
    for secret in (engine.url.host or "", engine.url.database or "", "psycopg2"):
        if secret:
            assert secret not in body, f"{secret!r} disclosed to an anonymous caller"


def test_development_keeps_the_detail_for_operators(
    anonymous_client, failing_query, monkeypatch
):
    monkeypatch.setattr(health.settings, "APP_ENV", "development")

    body = anonymous_client.get("/health").json()

    assert "detail" in body["checks"]["database"]


def test_failed_checks_do_not_leak_sessions(anonymous_client, failing_query):
    """
    The original closed the session inside the try block, so a failing query
    skipped it. Measured before the fix: the pool exhausted on the 16th call.
    """
    # engine.pool is typed as the abstract Pool; the concrete pool here is a
    # QueuePool, which is what carries the sizing attributes.
    pool = cast(QueuePool, engine.pool)
    for _ in range(pool.size() + pool._max_overflow + 5):
        anonymous_client.get("/health")

    assert pool.checkedout() == 0
