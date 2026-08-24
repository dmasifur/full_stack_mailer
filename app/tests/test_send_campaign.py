"""The send worker, with Microsoft Graph mocked out."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from server.db.session import SessionLocal
from server.models import Campaign, CampaignRecipient, EmailLog
from server.services.campaign_state import transition
from server.services.email_sender import (
    EmailAuthError,
    PermanentEmailError,
    RetryableEmailError,
)
import server.workers.send_campaign as send_campaign

pytestmark = pytest.mark.usefixtures("instant_send")

THREE = ["one@example.com", "two@example.com", "three@example.com"]


@pytest.fixture
def graph(monkeypatch):
    """
    Record every send and let a test decide which addresses fail.

    ``graph.fail['x@y'] = SomeError(...)`` makes that recipient raise.
    """

    class Graph:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []
            self.fail: dict[str, Exception] = {}

        def __call__(self, *, recipient_email, **kwargs):
            self.calls.append({"recipient_email": recipient_email, **kwargs})
            if recipient_email in self.fail:
                raise self.fail[recipient_email]

        @property
        def attempted(self) -> list[str]:
            return [str(c["recipient_email"]) for c in self.calls]

    stub = Graph()
    monkeypatch.setattr(send_campaign, "send_email_via_graph_api", stub)
    return stub


def statuses(db, campaign_id) -> dict[str, str]:
    return {
        row.email: row.status
        for row in db.query(CampaignRecipient).filter(
            CampaignRecipient.campaign_id == campaign_id
        )
    }


def test_sends_to_every_recipient_and_completes(db, alice, make_campaign, graph):
    campaign = make_campaign(alice, recipients=THREE)

    send_campaign.send_campaign_task(str(campaign.id))

    db.expire_all()
    assert sorted(graph.attempted) == sorted(THREE)
    assert db.get(Campaign, campaign.id).status == "completed"
    assert set(statuses(db, campaign.id).values()) == {"sent"}


def test_permanent_failure_skips_only_that_recipient(db, alice, make_campaign, graph):
    """A hard bounce used to abort the campaign, stranding everyone after it."""
    campaign = make_campaign(alice, recipients=THREE)
    graph.fail["one@example.com"] = PermanentEmailError("550 no such mailbox")

    send_campaign.send_campaign_task(str(campaign.id))

    db.expire_all()
    assert sorted(graph.attempted) == sorted(THREE), "all three must be attempted"
    assert db.get(Campaign, campaign.id).status == "completed"
    assert statuses(db, campaign.id) == {
        "one@example.com": "failed",
        "two@example.com": "sent",
        "three@example.com": "sent",
    }


def test_permanent_failure_records_the_reason(db, alice, make_campaign, graph):
    campaign = make_campaign(alice, recipients=["one@example.com"])
    graph.fail["one@example.com"] = PermanentEmailError("550 no such mailbox")

    send_campaign.send_campaign_task(str(campaign.id))

    db.expire_all()
    row = db.query(CampaignRecipient).filter_by(campaign_id=campaign.id).one()
    assert "550 no such mailbox" in row.failure_reason
    assert row.retry_count == 1

    log = db.query(EmailLog).filter_by(campaign_id=campaign.id).one()
    assert log.status == "failed"
    assert "550 no such mailbox" in log.error_message


def test_unexpected_error_marks_campaign_failed(db, alice, make_campaign, graph):
    """Without this the campaign stayed 'running' with no way out."""
    campaign = make_campaign(alice, recipients=THREE)
    graph.fail["one@example.com"] = RuntimeError("worker exploded")

    with pytest.raises(RuntimeError):
        send_campaign.send_campaign_task(str(campaign.id))

    db.expire_all()
    assert db.get(Campaign, campaign.id).status == "failed"


def test_failure_releases_recipients_left_sending(db, alice, make_campaign, graph):
    """
    A row is flipped to 'sending' before the call. Nothing queries that state,
    so a crash mid-send would hide it from any retry.
    """
    campaign = make_campaign(alice, recipients=THREE)
    graph.fail["one@example.com"] = RuntimeError("worker exploded")

    with pytest.raises(RuntimeError):
        send_campaign.send_campaign_task(str(campaign.id))

    db.expire_all()
    assert "sending" not in statuses(db, campaign.id).values()


def test_failed_campaign_can_be_resent(db, alice, make_campaign, graph):
    campaign = make_campaign(alice, recipients=THREE)
    graph.fail["one@example.com"] = RuntimeError("worker exploded")

    with pytest.raises(RuntimeError):
        send_campaign.send_campaign_task(str(campaign.id))

    graph.fail.clear()

    # Mirror POST /campaigns/{id}/retry, which moves the campaign back to
    # 'running' before dispatching. Calling the task straight at a 'failed'
    # campaign is not a path the API can produce.
    db.expire_all()
    transition(db.get(Campaign, campaign.id), "running")
    db.commit()

    send_campaign.send_campaign_task(str(campaign.id))

    db.expire_all()
    assert db.get(Campaign, campaign.id).status == "completed"
    assert set(statuses(db, campaign.id).values()) == {"sent"}


def test_retryable_error_propagates_without_failing_the_campaign(
    db, alice, make_campaign, graph
):
    """Celery retries these; marking the campaign failed would fight that."""
    campaign = make_campaign(alice, recipients=THREE)
    graph.fail["one@example.com"] = RetryableEmailError("429 throttled")

    with pytest.raises(RetryableEmailError):
        send_campaign.send_campaign_task(str(campaign.id))

    db.expire_all()
    assert db.get(Campaign, campaign.id).status == "running"


def test_auth_failure_pauses_the_campaign(db, alice, make_campaign, graph, monkeypatch):
    monkeypatch.setattr(
        send_campaign,
        "refresh_access_token",
        lambda **_: (_ for _ in ()).throw(
            send_campaign.TokenRefreshError("refresh rejected")
        ),
    )
    campaign = make_campaign(alice, recipients=THREE)
    graph.fail["one@example.com"] = EmailAuthError("401")

    send_campaign.send_campaign_task(str(campaign.id))

    db.expire_all()
    assert db.get(Campaign, campaign.id).status == "paused"


def test_auth_failure_does_not_blame_the_recipient(
    db, alice, make_campaign, graph, monkeypatch
):
    """The address was never actually tried — it must not be marked failed."""
    monkeypatch.setattr(
        send_campaign,
        "refresh_access_token",
        lambda **_: (_ for _ in ()).throw(
            send_campaign.TokenRefreshError("refresh rejected")
        ),
    )
    campaign = make_campaign(alice, recipients=["one@example.com"])
    graph.fail["one@example.com"] = EmailAuthError("401")

    send_campaign.send_campaign_task(str(campaign.id))

    db.expire_all()
    row = db.query(CampaignRecipient).filter_by(campaign_id=campaign.id).one()
    assert row.status != "failed"
    assert row.retry_count == 0
    assert db.query(EmailLog).filter_by(campaign_id=campaign.id).count() == 0


def test_already_sent_recipients_are_not_resent(db, alice, make_campaign, graph):
    """Idempotency: Celery may re-run the whole task after a retry."""
    campaign = make_campaign(alice, recipients=THREE)
    db.add(
        EmailLog(
            campaign_id=campaign.id, recipient_email="one@example.com", status="sent"
        )
    )
    db.commit()

    send_campaign.send_campaign_task(str(campaign.id))

    assert "one@example.com" not in graph.attempted
    assert sorted(graph.attempted) == ["three@example.com", "two@example.com"]


def test_a_pause_survives_a_pending_celery_retry(db, alice, make_campaign, graph):
    """
    The production sequence that defeated pause.

    Graph throttles, so the task raises and Celery queues an autoretry. The
    operator pauses while that retry is pending. When it fires it must not drag
    the campaign back into 'running' and resume sending.
    """
    campaign = make_campaign(alice, status="running", recipients=THREE)
    graph.fail["one@example.com"] = RetryableEmailError("429 throttled")

    with pytest.raises(RetryableEmailError):
        send_campaign.send_campaign_task(str(campaign.id))

    db.expire_all()
    transition(db.get(Campaign, campaign.id), "paused")
    db.commit()

    graph.fail.clear()
    graph.calls.clear()
    send_campaign.send_campaign_task(str(campaign.id))  # the retry fires

    db.expire_all()
    assert graph.attempted == [], "pause was overridden and email went out"
    assert db.get(Campaign, campaign.id).status == "paused"


@pytest.mark.parametrize("status", ["paused", "completed", "failed"])
def test_a_stale_task_does_not_restart_a_campaign(
    db, alice, make_campaign, graph, status
):
    """Duplicate ETA tasks and reconciler races land here too, not just retries."""
    campaign = make_campaign(alice, status=status, recipients=THREE)

    send_campaign.send_campaign_task(str(campaign.id))

    db.expire_all()
    assert graph.attempted == []
    assert db.get(Campaign, campaign.id).status == status


def test_paused_campaign_stops_before_the_next_batch(db, alice, make_campaign, graph):
    campaign = make_campaign(alice, status="paused", recipients=THREE)

    send_campaign.send_campaign_task(str(campaign.id))

    assert graph.attempted == []
    db.expire_all()
    assert db.get(Campaign, campaign.id).status == "paused"


def test_unvalidated_recipients_are_skipped(db, alice, make_campaign, graph):
    campaign = make_campaign(alice, recipients=THREE)
    db.query(CampaignRecipient).filter_by(email="one@example.com").update(
        {"dns_valid": None, "status": "pending_validation"}
    )
    db.commit()

    send_campaign.send_campaign_task(str(campaign.id))

    assert "one@example.com" not in graph.attempted


def test_cc_and_from_address_are_applied_to_every_send(db, alice, make_campaign, graph):
    campaign = make_campaign(
        alice,
        recipients=THREE,
        cc_emails=["cc1@example.com", "cc2@example.com"],
        from_address="alice-send@example.com",
    )

    send_campaign.send_campaign_task(str(campaign.id))

    assert len(graph.calls) == 3
    for call in graph.calls:
        assert sorted(call["cc_emails"]) == ["cc1@example.com", "cc2@example.com"]
        assert call["from_address"] == "alice-send@example.com"


def test_missing_campaign_is_a_no_op(graph):
    send_campaign.send_campaign_task("00000000-0000-0000-0000-000000000000")
    assert graph.calls == []


# --- concurrency -----------------------------------------------------------


def test_claiming_a_batch_excludes_a_second_worker(db, alice, make_campaign):
    """
    The duplicate-send guard.

    Claiming used to be SELECT ... FOR UPDATE SKIP LOCKED, whose locks are
    released by the first commit inside the send loop — freeing the rest of the
    batch for a second worker to claim and send again. The claim now flips the
    status as part of the same statement, so it outlives the transaction.
    """
    campaign = make_campaign(alice, recipients=THREE)

    first = send_campaign._get_pending_recipients(db=db, campaign_id=str(campaign.id))
    assert len(first) == 3

    # A second worker, on its own session, must find nothing left to claim.
    other = SessionLocal()
    try:
        second = send_campaign._get_pending_recipients(
            db=other, campaign_id=str(campaign.id)
        )
    finally:
        other.close()

    assert second == []


def test_claiming_marks_rows_sending(db, alice, make_campaign):
    campaign = make_campaign(alice, recipients=THREE)

    send_campaign._get_pending_recipients(db=db, campaign_id=str(campaign.id))

    db.expire_all()
    assert set(statuses(db, campaign.id).values()) == {"sending"}


def test_stale_sending_rows_are_released_on_restart(db, alice, make_campaign, graph):
    """
    A SIGKILLed worker leaves rows at 'sending'. They match neither the pending
    filter nor 'sent', so without this they are skipped forever.
    """
    campaign = make_campaign(alice, status="running", recipients=THREE)
    stale = (
        datetime.now(tz=UTC) - send_campaign.STALE_SENDING_AFTER - timedelta(minutes=1)
    )
    db.query(CampaignRecipient).filter_by(campaign_id=campaign.id).update(
        {"status": "sending", "updated_at": stale}
    )
    db.commit()

    send_campaign.send_campaign_task(str(campaign.id))

    db.expire_all()
    assert sorted(graph.attempted) == sorted(THREE)
    assert set(statuses(db, campaign.id).values()) == {"sent"}


def test_recently_sending_rows_are_left_alone(db, alice, make_campaign, graph):
    """Only abandoned rows are reclaimed — not ones a live worker is mid-send on."""
    campaign = make_campaign(alice, status="running", recipients=THREE)
    db.query(CampaignRecipient).filter_by(campaign_id=campaign.id).update(
        {"status": "sending"}
    )
    db.commit()

    send_campaign.send_campaign_task(str(campaign.id))

    assert graph.attempted == []


# --- retry exhaustion ------------------------------------------------------


def test_exhausted_retries_mark_the_campaign_failed(db, alice, make_campaign, graph):
    """
    Until the final attempt the campaign must stay 'running' so Celery can retry.
    On the last one the task is gone for good, and a campaign left at 'running'
    with no task behind it looks alive when it is not.
    """
    campaign = make_campaign(alice, status="running", recipients=THREE)
    graph.fail["one@example.com"] = RetryableEmailError("429 throttled")

    task = send_campaign.send_campaign_task

    with pytest.raises(RetryableEmailError):
        task.apply(
            args=(str(campaign.id),),
            retries=send_campaign.MAX_RETRIES,
            throw=True,
        ).get()

    db.expire_all()
    assert db.get(Campaign, campaign.id).status == "failed"


def test_merge_fields_are_resolved_per_recipient(db, alice, make_campaign, graph):
    """
    Each recipient must receive their own name, not the first one's. The
    substitution happens per send, inside the batch loop.
    """
    campaign = make_campaign(alice, recipients=["ada@example.com", "grace@example.com"])
    campaign.template_body = "<p>Hi {{first_name|there}},</p>"

    names = {"ada@example.com": "Ada", "grace@example.com": "Grace"}
    for row in db.query(CampaignRecipient).filter(
        CampaignRecipient.campaign_id == campaign.id
    ):
        row.first_name = names[row.email]
    db.commit()

    send_campaign.send_campaign_task(str(campaign.id))

    bodies = {str(c["recipient_email"]): str(c["html_body"]) for c in graph.calls}
    assert bodies["ada@example.com"] == "<p>Hi Ada,</p>"
    assert bodies["grace@example.com"] == "<p>Hi Grace,</p>"


def test_merge_field_falls_back_when_the_csv_had_no_name(
    db, alice, make_campaign, graph
):
    """make_campaign leaves first_name unset, which is the common CSV case."""
    campaign = make_campaign(alice, recipients=["anon@example.com"])
    campaign.template_body = "<p>Hi {{first_name|there}},</p>"
    db.commit()

    send_campaign.send_campaign_task(str(campaign.id))

    assert graph.calls[0]["html_body"] == "<p>Hi there,</p>"


def test_a_body_with_no_tokens_is_sent_verbatim(db, alice, make_campaign, graph):
    """A pasted table-based template must reach Graph byte for byte."""
    body = '<table role="presentation"><tr><td>Newsletter</td></tr></table>'
    campaign = make_campaign(alice, recipients=["ada@example.com"])
    campaign.template_body = body
    db.commit()

    send_campaign.send_campaign_task(str(campaign.id))

    assert graph.calls[0]["html_body"] == body
