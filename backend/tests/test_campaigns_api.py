"""Campaign CRUD, lifecycle endpoints, and sender-address enforcement."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models import Campaign, CampaignRecipient, EmailLog

pytestmark = pytest.mark.usefixtures("no_broker")


def create_campaign(client, **overrides):
    body = {
        "name": "Launch",
        "subject": "Hello",
        "template_body": "<p>Hi</p>",
    } | overrides
    return client.post("/campaigns", json=body)


# --- creation --------------------------------------------------------------


def test_create_returns_a_draft(client):
    response = create_campaign(client)

    assert response.status_code == 201
    assert response.json()["status"] == "draft"


def test_create_accepts_an_owned_sender_address(client):
    response = create_campaign(client, from_address="alice-send@example.com")

    assert response.status_code == 201
    assert response.json()["from_address"] == "alice-send@example.com"


def test_create_rejects_an_unowned_sender_address(client):
    """Unchecked, this let any user send as any address."""
    response = create_campaign(client, from_address="ceo@somewhere-else.com")

    assert response.status_code == 400
    assert "registered sender" in response.json()["detail"]


def test_create_rejects_another_users_sender_address(client, bob):
    response = create_campaign(client, from_address="bob-send@example.com")

    assert response.status_code == 400


def test_omitting_from_address_is_allowed(client):
    """None means 'the authenticated user's own mailbox' and needs no check."""
    assert create_campaign(client).json()["from_address"] is None


# --- updates ---------------------------------------------------------------


def test_update_rejects_an_unowned_sender_address(client):
    campaign_id = create_campaign(client).json()["id"]

    response = client.patch(
        f"/campaigns/{campaign_id}", json={"from_address": "ceo@somewhere-else.com"}
    )

    assert response.status_code == 400


def test_only_drafts_are_editable(client, db, alice, make_campaign):
    campaign = make_campaign(alice, status="running")

    response = client.patch(f"/campaigns/{campaign.id}", json={"name": "new"})

    assert response.status_code == 409


# --- lifecycle -------------------------------------------------------------


def test_start_a_draft(client, db, alice, make_campaign, no_broker):
    """This 409'd for every campaign ever created."""
    campaign = make_campaign(alice, recipients=["a@example.com"])

    response = client.post(f"/campaigns/{campaign.id}/start")

    assert response.status_code == 200
    db.expire_all()
    assert db.get(Campaign, campaign.id).status == "running"
    no_broker["send"].assert_called_once_with(str(campaign.id))


def test_pause_and_resume(client, db, alice, make_campaign):
    campaign = make_campaign(alice, status="running")

    assert client.post(f"/campaigns/{campaign.id}/pause").status_code == 200
    db.expire_all()
    assert db.get(Campaign, campaign.id).status == "paused"

    assert client.post(f"/campaigns/{campaign.id}/resume").status_code == 200
    db.expire_all()
    resumed = db.get(Campaign, campaign.id)
    assert resumed.status == "running"
    # Left at "scheduled" with a past scheduled_at, the reconciler would have
    # dispatched a second task alongside the one resume just queued.
    assert resumed.scheduled_at is None


def test_retry_requeues_a_failed_campaign(client, db, alice, make_campaign, no_broker):
    campaign = make_campaign(alice, status="failed")

    response = client.post(f"/campaigns/{campaign.id}/retry")

    assert response.status_code == 200
    db.expire_all()
    assert db.get(Campaign, campaign.id).status == "running"
    no_broker["send"].assert_called_once_with(str(campaign.id))


def test_retry_rejects_a_completed_campaign(client, alice, make_campaign):
    campaign = make_campaign(alice, status="completed")

    assert client.post(f"/campaigns/{campaign.id}/retry").status_code == 409


def test_schedule_sets_the_time(client, db, alice, make_campaign):
    campaign = make_campaign(alice, recipients=["a@example.com"])
    when = datetime.now(tz=UTC) + timedelta(hours=1)

    response = client.post(
        f"/campaigns/{campaign.id}/schedule",
        json={"scheduled_at": when.isoformat()},
    )

    assert response.status_code == 200
    db.expire_all()
    assert db.get(Campaign, campaign.id).status == "scheduled"


# --- deletion --------------------------------------------------------------


def test_delete_a_draft(client, db, alice, make_campaign):
    campaign = make_campaign(alice)
    campaign_id = campaign.id

    assert client.delete(f"/campaigns/{campaign_id}").status_code == 204

    # expunge, not expire: the row is gone, and refreshing an expired instance
    # that no longer exists raises ObjectDeletedError instead of returning None.
    db.expunge_all()
    assert db.query(Campaign).filter_by(id=campaign_id).first() is None


def test_delete_cascades_to_children(client, db, alice, make_campaign):
    """This raised an uncaught FK IntegrityError once recipients existed."""
    campaign = make_campaign(alice, status="completed", recipients=["a@example.com"])
    db.add(
        EmailLog(
            campaign_id=campaign.id, recipient_email="a@example.com", status="sent"
        )
    )
    db.commit()
    campaign_id = campaign.id

    assert client.delete(f"/campaigns/{campaign_id}").status_code == 204

    db.expire_all()
    assert db.query(CampaignRecipient).filter_by(campaign_id=campaign_id).count() == 0
    assert db.query(EmailLog).filter_by(campaign_id=campaign_id).count() == 0


@pytest.mark.parametrize("status", ["completed", "failed", "paused"])
def test_terminal_campaigns_are_deletable(client, alice, make_campaign, status):
    campaign = make_campaign(alice, status=status)

    assert client.delete(f"/campaigns/{campaign.id}").status_code == 204


@pytest.mark.parametrize("status", ["running", "scheduled"])
def test_in_flight_campaigns_are_not_deletable(client, alice, make_campaign, status):
    campaign = make_campaign(alice, status=status)

    assert client.delete(f"/campaigns/{campaign.id}").status_code == 409


# --- listing ---------------------------------------------------------------


def test_list_is_paginated(client, alice, make_campaign):
    for _ in range(3):
        make_campaign(alice)

    body = client.get("/campaigns", params={"page": 1, "page_size": 2}).json()

    assert body["total"] == 3
    assert len(body["items"]) == 2
    assert body["page_size"] == 2


# --- send preconditions ----------------------------------------------------
#
# The worker only picks up recipients at 'pending' with dns_valid true. A
# campaign that has none finds nothing to do and transitions itself straight to
# 'completed' — a terminal state — having sent nothing at all.


def test_start_rejects_a_campaign_with_no_recipients(client, alice, make_campaign):
    campaign = make_campaign(alice)

    response = client.post(f"/campaigns/{campaign.id}/start")

    assert response.status_code == 409
    assert "no recipients" in response.json()["detail"].lower()


def test_start_rejects_recipients_still_awaiting_validation(
    client, db, alice, make_campaign
):
    campaign = make_campaign(alice, recipients=["a@example.com"])
    db.query(CampaignRecipient).filter_by(campaign_id=campaign.id).update(
        {"status": "pending_validation", "dns_valid": None}
    )
    db.commit()

    response = client.post(f"/campaigns/{campaign.id}/start")

    assert response.status_code == 409
    assert "validation" in response.json()["detail"].lower()
    db.expire_all()
    assert db.get(Campaign, campaign.id).status == "draft", "must not be consumed"


def test_start_rejects_a_campaign_with_nothing_left_to_send(
    client, db, alice, make_campaign
):
    campaign = make_campaign(alice, recipients=["a@example.com"])
    db.query(CampaignRecipient).filter_by(campaign_id=campaign.id).update(
        {"status": "sent"}
    )
    db.commit()

    response = client.post(f"/campaigns/{campaign.id}/start")

    assert response.status_code == 409


def test_schedule_rejects_a_past_time(client, alice, make_campaign):
    campaign = make_campaign(alice, recipients=["a@example.com"])
    when = datetime.now(tz=UTC) - timedelta(hours=1)

    response = client.post(
        f"/campaigns/{campaign.id}/schedule",
        json={"scheduled_at": when.isoformat()},
    )

    assert response.status_code == 422


def test_schedule_rejects_a_naive_datetime(client, alice, make_campaign):
    """Celery runs with enable_utc, so a naive value fires at the wrong moment."""
    campaign = make_campaign(alice, recipients=["a@example.com"])

    response = client.post(
        f"/campaigns/{campaign.id}/schedule",
        json={"scheduled_at": "2030-01-01T12:00:00"},
    )

    assert response.status_code == 422


# --- broker failures -------------------------------------------------------


def test_a_broker_failure_does_not_strand_a_campaign(
    client, db, alice, make_campaign, no_broker
):
    """
    'running' has no transition back to 'draft', so a campaign committed as
    running with no task behind it could only be recovered by pause-then-resume.
    """
    campaign = make_campaign(alice, recipients=["a@example.com"])
    no_broker["send"].side_effect = OSError("broker unreachable")

    response = client.post(f"/campaigns/{campaign.id}/start")

    assert response.status_code == 503
    db.expire_all()
    assert db.get(Campaign, campaign.id).status == "draft"


# --- upload limits ---------------------------------------------------------


def test_an_oversized_csv_is_rejected(client, alice, make_campaign, monkeypatch):
    import app.api.campaigns as campaigns_api

    monkeypatch.setattr(campaigns_api.settings, "MAX_UPLOAD_BYTES", 64)
    campaign = make_campaign(alice)

    oversized = ("email\n" + "a@example.com\n" * 100).encode()
    response = client.post(
        f"/campaigns/{campaign.id}/recipients/upload",
        files={"file": ("big.csv", oversized, "text/csv")},
    )

    assert response.status_code == 413


def test_a_csv_without_an_email_column_is_a_client_error(client, alice, make_campaign):
    """This used to surface as a 500, indistinguishable from a server fault."""
    campaign = make_campaign(alice)

    response = client.post(
        f"/campaigns/{campaign.id}/recipients/upload",
        files={"file": ("bad.csv", b"name,phone\nAnn,123\n", "text/csv")},
    )

    assert response.status_code == 400
    assert "email" in response.json()["detail"]


def test_a_non_utf8_csv_is_a_client_error(client, alice, make_campaign):
    campaign = make_campaign(alice)

    response = client.post(
        f"/campaigns/{campaign.id}/recipients/upload",
        files={"file": ("latin.csv", b"email\n\xff\xfe@example.com\n", "text/csv")},
    )

    assert response.status_code == 400


# --- visibility ------------------------------------------------------------


def test_recipients_are_listable(client, alice, make_campaign):
    campaign = make_campaign(alice, recipients=["a@example.com", "b@example.com"])

    response = client.get(f"/campaigns/{campaign.id}/recipients")

    assert response.status_code == 200
    assert response.json()["total"] == 2


def test_recipients_can_be_filtered_by_status(client, db, alice, make_campaign):
    campaign = make_campaign(alice, recipients=["a@example.com", "b@example.com"])
    db.query(CampaignRecipient).filter_by(email="a@example.com").update(
        {"status": "failed", "failure_reason": "550 no such mailbox"}
    )
    db.commit()

    response = client.get(
        f"/campaigns/{campaign.id}/recipients", params={"status": "failed"}
    )

    assert response.json()["total"] == 1
    assert response.json()["items"][0]["failure_reason"] == "550 no such mailbox"


def test_stats_explain_an_under_sending_campaign(client, db, alice, make_campaign):
    campaign = make_campaign(
        alice, recipients=["a@example.com", "b@example.com", "c@example.com"]
    )
    db.query(CampaignRecipient).filter_by(email="a@example.com").update(
        {"status": "sent"}
    )
    db.query(CampaignRecipient).filter_by(email="b@example.com").update(
        {"status": "invalid", "dns_valid": False}
    )
    db.commit()

    body = client.get(f"/campaigns/{campaign.id}/stats").json()

    assert body["total_recipients"] == 3
    assert body["sent"] == 1
    assert body["invalid"] == 1
    assert body["pending"] == 1


def test_patch_can_clear_from_address(client, alice, make_campaign):
    """
    An explicit null reverts to the user's own mailbox.

    None is a meaningful value for this field, so "not provided" and "set to
    null" have to mean different things — otherwise a campaign that once used a
    shared sender could never be moved back.
    """
    campaign = make_campaign(alice, from_address="alice-send@example.com")

    response = client.patch(f"/campaigns/{campaign.id}", json={"from_address": None})

    assert response.status_code == 200
    assert response.json()["from_address"] is None


def test_patch_without_from_address_leaves_it_alone(client, alice, make_campaign):
    campaign = make_campaign(alice, from_address="alice-send@example.com")

    response = client.patch(f"/campaigns/{campaign.id}", json={"name": "Renamed"})

    assert response.status_code == 200
    assert response.json()["from_address"] == "alice-send@example.com"
    assert response.json()["name"] == "Renamed"
