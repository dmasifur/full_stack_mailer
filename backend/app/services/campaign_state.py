from __future__ import annotations

from typing import Protocol


class HasStatus(Protocol):
    """
    Narrower than Campaign on purpose: the state machine has no business
    touching the ORM.
    """

    status: str


VALID_CAMPAIGN_STATUSES = {
    "draft",
    "scheduled",
    "running",
    "paused",
    "completed",
    "failed",
}

VALID_TRANSITIONS: dict[str, set[str]] = {
    # draft → running is a manual start; draft → scheduled defers it.
    "draft": {"scheduled", "running"},
    "scheduled": {"running", "draft"},  # allow un-scheduling back to draft
    "running": {"paused", "completed", "failed"},
    "paused": {"running", "scheduled", "failed"},  # resume → scheduled (re-queues)
    "completed": set(),
    "failed": {"running"},  # retry re-queues the remaining recipients
}


class CampaignTransitionError(Exception):
    """Raised when a requested status transition is not permitted."""


def transition(campaign: HasStatus, to_status: str) -> None:

    if to_status not in VALID_CAMPAIGN_STATUSES:
        raise CampaignTransitionError(
            f"'{to_status}' is not a recognised campaign status."
        )

    allowed = VALID_TRANSITIONS.get(campaign.status, set())

    if to_status not in allowed:
        raise CampaignTransitionError(
            f"Cannot move campaign from '{campaign.status}' to '{to_status}'. "
            f"Allowed transitions: {sorted(allowed) or 'none (terminal state)'}."
        )

    campaign.status = to_status
