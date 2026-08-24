"""
Serving the built frontend alongside the API.

The mount is exercised against a throwaway app so the tests do not depend on a
frontend build existing in the checkout.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

import app.spa as spa
from app.spa import mount_spa

SHELL = "<!doctype html><title>Mailer</title><div id=root></div>"


def _api_app() -> FastAPI:
    """A stand-in for the real app: one API route, then the SPA mount."""
    application = FastAPI()

    @application.get("/campaigns")
    def campaigns() -> dict[str, str]:
        return {"resource": "campaigns"}

    return application


@pytest.fixture
def built(tmp_path, monkeypatch):
    """A directory shaped like a finished Vite build."""
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text(SHELL)
    (static / "assets" / "index-abc123.js").write_text("console.log(1)")
    (static / "favicon.svg").write_text("<svg/>")

    monkeypatch.setattr(spa, "STATIC_DIR", static)
    return static


@pytest.fixture
def spa_client(built):
    application = _api_app()
    mount_spa(application)
    return TestClient(application)


@pytest.mark.parametrize(
    "path",
    ["/app", "/app/campaigns", "/app/campaigns/9f8e/recipients", "/app/settings"],
)
def test_client_side_routes_serve_the_shell(spa_client, path):
    response = spa_client.get(path)

    assert response.status_code == 200
    assert response.text == SHELL


def test_the_root_redirects_into_the_spa(spa_client):
    response = spa_client.get("/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/app"


def test_the_api_still_answers_on_its_own_paths(spa_client):
    """
    The collision this prefix exists to avoid: /campaigns is the API's, and the
    campaign list page is /app/campaigns.
    """
    response = spa_client.get("/campaigns")

    assert response.status_code == 200
    assert response.json() == {"resource": "campaigns"}


@pytest.mark.parametrize(
    "path",
    ["/campaigns/9f8e/stats", "/auth/me", "/templates", "/sender-addresses", "/typo"],
)
def test_unmatched_paths_are_404_not_the_shell(spa_client, path):
    """
    A mistyped endpoint must fail as a missing endpoint. Answering 200 with
    HTML would make a client try to parse the shell as JSON.
    """
    response = spa_client.get(path)

    assert response.status_code == 404
    assert response.text != SHELL


def test_hashed_bundle_files_are_served(spa_client):
    assert spa_client.get("/static/assets/index-abc123.js").text == "console.log(1)"


def test_other_build_files_are_served(spa_client):
    assert spa_client.get("/static/favicon.svg").text == "<svg/>"


def test_a_traversal_attempt_does_not_read_outside_the_build(spa_client, tmp_path):
    (tmp_path / "secret.txt").write_text("credentials")

    response = spa_client.get("/static/../secret.txt")

    assert "credentials" not in response.text


def test_a_missing_build_leaves_the_api_alone(monkeypatch, tmp_path):
    """A backend-only checkout must still start and serve the API."""
    monkeypatch.setattr(spa, "STATIC_DIR", tmp_path / "absent")

    application = _api_app()
    mount_spa(application)
    client = TestClient(application)

    assert client.get("/campaigns").json() == {"resource": "campaigns"}
    assert client.get("/app").status_code == 404
