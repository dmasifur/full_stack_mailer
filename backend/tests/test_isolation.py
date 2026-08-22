"""
Authentication boundary and cross-tenant isolation.

Every campaign and sender-address route is owned by exactly one user. These
tests are the regression net for that: an endpoint added without an ownership
filter should fail here rather than in production.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.usefixtures("no_broker")

PROTECTED_ROUTES = [
    ("get", "/campaigns"),
    ("post", "/campaigns"),
    ("get", "/templates"),
    ("post", "/templates"),
    ("get", "/sender-addresses"),
    ("post", "/sender-addresses"),
    ("get", "/auth/me"),
]


@pytest.mark.parametrize(("method", "path"), PROTECTED_ROUTES)
def test_anonymous_requests_are_rejected(anonymous_client, method, path):
    response = getattr(anonymous_client, method)(path)

    assert response.status_code == 401


def test_health_is_public(anonymous_client):
    assert anonymous_client.get("/health").status_code in (200, 503)


def test_a_garbage_token_is_rejected(anonymous_client):
    anonymous_client.cookies.set("access_token", "not-a-real-token")

    assert anonymous_client.get("/campaigns").status_code == 401


def test_me_identifies_the_caller(client, alice):
    response = client.get("/auth/me")

    assert response.status_code == 200
    assert response.json()["email"] == alice.email


# --- OAuth state binding ---------------------------------------------------
#
# The signature on the state parameter only proves the server minted it. Without
# binding it to the browser, an attacker could mint a state, pair it with their
# own authorization code, and have a victim's browser complete the exchange —
# logging the victim into the attacker's account.


def _signed_state(raw: str) -> str:
    from app.api.auth import _STATE_SALT, _state_serializer

    return _state_serializer().dumps(raw, salt=_STATE_SALT)


def test_login_issues_a_state_cookie(anonymous_client):
    from app.api.auth import _STATE_COOKIE

    response = anonymous_client.get("/auth/microsoft/login", follow_redirects=False)

    assert response.status_code == 307
    assert _STATE_COOKIE in response.cookies


def test_callback_without_the_state_cookie_is_rejected(anonymous_client):
    response = anonymous_client.get(
        "/auth/microsoft/callback",
        params={"code": "attacker-code", "state": _signed_state("attacker-state")},
    )

    assert response.status_code == 400
    assert "state cookie" in response.json()["detail"]


def test_callback_with_a_mismatched_state_cookie_is_rejected(anonymous_client):
    """The attack this binding exists to stop."""
    from app.api.auth import _STATE_COOKIE

    anonymous_client.cookies.set(_STATE_COOKIE, "the-victims-own-state")

    response = anonymous_client.get(
        "/auth/microsoft/callback",
        params={"code": "attacker-code", "state": _signed_state("attacker-state")},
    )

    assert response.status_code == 400
    assert "CSRF" in response.json()["detail"]


def test_callback_rejects_an_unsigned_state(anonymous_client):
    from app.api.auth import _STATE_COOKIE

    anonymous_client.cookies.set(_STATE_COOKIE, "raw-state")

    response = anonymous_client.get(
        "/auth/microsoft/callback",
        params={"code": "c", "state": "raw-state"},
    )

    assert response.status_code == 400


# --- cross-user access -----------------------------------------------------


@pytest.fixture
def alices_campaign(client, alice, bob, make_campaign):
    """A campaign owned by Alice, with the client switched to Bob."""
    campaign = make_campaign(
        alice, recipients=["r@example.com"], cc_emails=["cc@example.com"]
    )
    client.login_as(bob)
    return campaign


# Each route carries a body that would be *valid* if the caller owned the
# campaign. Sending an invalid one instead would get a 422 from body validation
# before the ownership check ran, so the test would pass without proving
# anything about isolation.
CAMPAIGN_ROUTES = [
    ("get", "", None),
    ("patch", "", {"name": "renamed"}),
    ("delete", "", None),
    ("post", "/start", None),
    ("post", "/pause", None),
    ("post", "/resume", None),
    ("post", "/retry", None),
    ("get", "/cc-recipients", None),
    ("post", "/cc-recipients", {"emails": ["intruder@example.com"]}),
]


@pytest.mark.parametrize(("method", "suffix", "body"), CAMPAIGN_ROUTES)
def test_another_user_cannot_touch_a_campaign(
    client, alices_campaign, method, suffix, body
):
    path = f"/campaigns/{alices_campaign.id}{suffix}"
    kwargs = {"json": body} if body is not None else {}

    response = getattr(client, method)(path, **kwargs)

    assert response.status_code == 404, f"{method.upper()} {path} leaked"


def test_another_user_cannot_upload_recipients(client, alices_campaign):
    response = client.post(
        f"/campaigns/{alices_campaign.id}/recipients/upload",
        files={"file": ("r.csv", b"email\nx@example.com\n", "text/csv")},
    )

    assert response.status_code == 404


def test_campaign_list_is_scoped_to_the_owner(client, alices_campaign):
    body = client.get("/campaigns").json()

    assert body["total"] == 0
    assert body["items"] == []


def test_sender_addresses_are_scoped_to_the_owner(client, db, alice, bob):
    from app.models import SenderAddress

    alices = db.query(SenderAddress).filter_by(user_id=alice.id).one()
    client.login_as(bob)

    assert all(
        row["id"] != str(alices.id) for row in client.get("/sender-addresses").json()
    )
    assert (
        client.patch(f"/sender-addresses/{alices.id}", json={"label": "x"}).status_code
        == 404
    )
    assert client.delete(f"/sender-addresses/{alices.id}").status_code == 404


def test_a_user_cannot_send_as_another_users_address(client, alice, bob):
    client.login_as(bob)

    response = client.post(
        "/campaigns",
        json={
            "name": "Impersonation",
            "subject": "Hi",
            "template_body": "<p>x</p>",
            "from_address": "alice-send@example.com",
        },
    )

    assert response.status_code == 400
