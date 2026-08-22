"""The campaign status machine — every legal and illegal edge."""

from __future__ import annotations

import pytest

from app.services.campaign_state import (
    VALID_CAMPAIGN_STATUSES,
    VALID_TRANSITIONS,
    CampaignTransitionError,
    transition,
)


class FakeCampaign:
    """Stand-in for a Campaign row; transition() only touches .status."""

    def __init__(self, status: str) -> None:
        self.status = status


LEGAL_EDGES = sorted(
    (source, target)
    for source, targets in VALID_TRANSITIONS.items()
    for target in targets
)

ILLEGAL_EDGES = sorted(
    (source, target)
    for source in VALID_TRANSITIONS
    for target in VALID_CAMPAIGN_STATUSES
    if target not in VALID_TRANSITIONS[source]
)


@pytest.mark.parametrize(("source", "target"), LEGAL_EDGES)
def test_legal_transition_is_applied(source, target):
    campaign = FakeCampaign(source)
    transition(campaign, target)
    assert campaign.status == target


@pytest.mark.parametrize(("source", "target"), ILLEGAL_EDGES)
def test_illegal_transition_is_rejected(source, target):
    campaign = FakeCampaign(source)

    with pytest.raises(CampaignTransitionError):
        transition(campaign, target)

    assert campaign.status == source, "a rejected transition must not mutate the row"


def test_unknown_status_is_rejected():
    campaign = FakeCampaign("draft")

    with pytest.raises(CampaignTransitionError, match="not a recognised"):
        transition(campaign, "banana")

    assert campaign.status == "draft"


# --- regressions -----------------------------------------------------------
# These four edges are the ones the blocker fixes turned on or depend upon.
# Spelled out separately so a future edit to VALID_TRANSITIONS that removes one
# fails here with an obvious name, not just inside the parametrized sweep.


def test_draft_can_start_directly():
    """POST /campaigns/{id}/start moved draft -> running and always 409'd."""
    campaign = FakeCampaign("draft")
    transition(campaign, "running")
    assert campaign.status == "running"


def test_running_can_fail():
    """Nothing could reach 'failed', so crashed sends stranded at 'running'."""
    campaign = FakeCampaign("running")
    transition(campaign, "failed")
    assert campaign.status == "failed"


def test_failed_can_be_retried():
    campaign = FakeCampaign("failed")
    transition(campaign, "running")
    assert campaign.status == "running"


def test_completed_is_terminal():
    campaign = FakeCampaign("completed")

    for target in sorted(VALID_CAMPAIGN_STATUSES):
        with pytest.raises(CampaignTransitionError):
            transition(campaign, target)

    assert campaign.status == "completed"
