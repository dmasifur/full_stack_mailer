"""
The beat reconciler.

/schedule enqueues with apply_async(eta=...), which parks the task inside Redis.
A flush or a purge loses it and the campaign sits at 'scheduled' past its time
with nothing left to run it. The reconciler makes the database, not the broker,
the record of what still has to be sent.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models import Campaign, CampaignRecipient
from app.workers.reconcile_campaigns import reconcile_campaigns_task

pytestmark = pytest.mark.usefixtures("no_broker")


def ago(**kwargs):
    return datetime.now(tz=UTC) - timedelta(**kwargs)


def ahead(**kwargs):
    return datetime.now(tz=UTC) + timedelta(**kwargs)


def test_an_overdue_campaign_is_requeued(db, alice, make_campaign, no_broker):
    campaign = make_campaign(alice, status="scheduled", scheduled_at=ago(minutes=5))

    reconcile_campaigns_task()

    db.expire_all()
    assert db.get(Campaign, campaign.id).status == "running"
    no_broker["send"].assert_called_once_with(str(campaign.id))


def test_a_future_campaign_is_left_alone(db, alice, make_campaign, no_broker):
    campaign = make_campaign(alice, status="scheduled", scheduled_at=ahead(hours=2))

    reconcile_campaigns_task()

    db.expire_all()
    assert db.get(Campaign, campaign.id).status == "scheduled"
    no_broker["send"].assert_not_called()


@pytest.mark.parametrize(
    "status", ["draft", "running", "paused", "completed", "failed"]
)
def test_only_scheduled_campaigns_are_considered(
    db, alice, make_campaign, no_broker, status
):
    campaign = make_campaign(alice, status=status, scheduled_at=ago(minutes=5))

    reconcile_campaigns_task()

    db.expire_all()
    assert db.get(Campaign, campaign.id).status == status
    no_broker["send"].assert_not_called()


def test_a_campaign_without_a_time_is_ignored(db, alice, make_campaign, no_broker):
    campaign = make_campaign(alice, status="scheduled", scheduled_at=None)

    reconcile_campaigns_task()

    db.expire_all()
    assert db.get(Campaign, campaign.id).status == "scheduled"
    no_broker["send"].assert_not_called()


def test_running_twice_does_not_double_queue(db, alice, make_campaign, no_broker):
    """The second pass sees 'running' and leaves it to the worker already on it."""
    make_campaign(alice, status="scheduled", scheduled_at=ago(minutes=5))

    reconcile_campaigns_task()
    reconcile_campaigns_task()

    assert no_broker["send"].call_count == 1


def test_several_overdue_campaigns_are_all_picked_up(
    db, alice, make_campaign, no_broker
):
    for _ in range(3):
        make_campaign(alice, status="scheduled", scheduled_at=ago(minutes=5))

    reconcile_campaigns_task()

    db.expire_all()
    assert no_broker["send"].call_count == 3
    assert db.query(Campaign).filter_by(status="running").count() == 3


def test_nothing_due_is_a_no_op(db, alice, make_campaign, no_broker):
    make_campaign(alice, status="draft")

    reconcile_campaigns_task()

    no_broker["send"].assert_not_called()


# --- stalled DNS validation ------------------------------------------------
#
# Validation is enqueued once, from inside the upload request. If the broker was
# down at that moment the rows sit at 'pending_validation' forever: the send
# worker ignores them, so the campaign silently has nothing to send.


def _stale_recipient(db, campaign, *, age_minutes: int) -> None:
    created = datetime.now(tz=UTC) - timedelta(minutes=age_minutes)
    db.add(
        CampaignRecipient(
            campaign_id=campaign.id,
            email="waiting@example.com",
            status="pending_validation",
            dns_valid=None,
            created_at=created,
        )
    )
    db.commit()


def test_stalled_validation_is_requeued(db, alice, make_campaign, no_broker):
    campaign = make_campaign(alice)
    _stale_recipient(db, campaign, age_minutes=30)

    reconcile_campaigns_task()

    no_broker["validate"].assert_called_once_with(str(campaign.id))


def test_recent_imports_are_left_to_finish(db, alice, make_campaign, no_broker):
    campaign = make_campaign(alice)
    _stale_recipient(db, campaign, age_minutes=1)

    reconcile_campaigns_task()

    assert not no_broker["validate"].called


def test_validated_recipients_are_not_requeued(db, alice, make_campaign, no_broker):
    make_campaign(alice, recipients=["done@example.com"])

    reconcile_campaigns_task()

    assert not no_broker["validate"].called
