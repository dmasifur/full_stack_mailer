"""Harden the send path: duplicate-send backstop, sender uniqueness, hot index

Revision ID: c7d1f4a83b62
Revises: a1c4e7b9d2f0
Create Date: 2026-08-22

Three schema changes, all supporting fixes in the same pass:

1. A partial unique index on email_logs (campaign_id, recipient_email) for rows
   at status 'sent'. The worker's idempotency check reads before it writes, so
   two concurrent workers could both conclude "not sent yet" and both send. The
   index turns a duplicate delivery into an IntegrityError instead of a second
   email. Partial, because 'failed' rows are legitimately written more than once
   for the same address across retries.

2. A unique constraint on sender_addresses (user_id, email). Registration
   accepted the same address repeatedly, and the ownership check resolved the
   duplicates with .first().

3. A composite index on campaign_recipients (campaign_id, status) — the filter
   the send worker runs once per batch for the entire life of a campaign.

Pre-existing duplicates would make (1) and (2) fail to build, so both are
de-duplicated first. That is deliberately destructive in a narrow way: it keeps
the oldest row of each group, which is the one that reflects what actually
happened first.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c7d1f4a83b62"
down_revision: str | Sequence[str] | None = "a1c4e7b9d2f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SENT_LOG_INDEX = "uq_email_logs_campaign_recipient_sent"
_SENDER_UNIQUE = "uq_sender_addresses_user_email"
_RECIPIENT_STATUS_INDEX = "ix_campaign_recipients_campaign_id_status"


def upgrade() -> None:
    # Collapse any duplicate 'sent' logs before the unique index is built —
    # historical duplicates are exactly the bug this index exists to prevent.
    op.execute(
        """
        DELETE FROM email_logs a
        USING email_logs b
        WHERE a.status = 'sent'
          AND b.status = 'sent'
          AND a.campaign_id = b.campaign_id
          AND a.recipient_email = b.recipient_email
          AND a.created_at > b.created_at
        """
    )

    op.create_index(
        _SENT_LOG_INDEX,
        "email_logs",
        ["campaign_id", "recipient_email"],
        unique=True,
        postgresql_where=sa.text("status = 'sent'"),
    )

    # Same treatment for sender addresses: keep the earliest registration.
    op.execute(
        """
        DELETE FROM sender_addresses a
        USING sender_addresses b
        WHERE a.user_id = b.user_id
          AND a.email = b.email
          AND a.created_at > b.created_at
        """
    )

    op.create_unique_constraint(
        _SENDER_UNIQUE,
        "sender_addresses",
        ["user_id", "email"],
    )

    op.create_index(
        _RECIPIENT_STATUS_INDEX,
        "campaign_recipients",
        ["campaign_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(_RECIPIENT_STATUS_INDEX, table_name="campaign_recipients")
    op.drop_constraint(_SENDER_UNIQUE, "sender_addresses", type_="unique")
    op.drop_index(_SENT_LOG_INDEX, table_name="email_logs")
