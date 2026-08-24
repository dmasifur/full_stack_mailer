"""cascade delete campaign children and index email_logs.campaign_id

Revision ID: a1c4e7b9d2f0
Revises: 3500d062e26c
Create Date: 2026-08-21

Deleting a campaign previously raised a foreign-key IntegrityError as soon as it
had recipients or send logs: only cc_recipients had an ORM cascade, and no FK
carried ON DELETE CASCADE. This recreates the three campaign-referencing FKs with
ondelete="CASCADE".

Also indexes email_logs.campaign_id — the send worker filters
(campaign_id, recipient_email, status) for its idempotency check before every
single send, which was a sequential scan.

The existing constraint names are looked up rather than hardcoded. Databases
migrated before app.db.base.NAMING_CONVENTION was introduced carry PostgreSQL's
default names (campaign_recipients_campaign_id_fkey); ones built afterwards carry
convention names (fk_campaign_recipients_campaign_id_campaigns). Both must work.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a1c4e7b9d2f0"
down_revision: str | Sequence[str] | None = "3500d062e26c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Tables holding a campaign_id FK, paired with the name the constraint will carry
# after this migration (matching NAMING_CONVENTION, so it is stable from here on).
_CAMPAIGN_FK_TABLES = [
    ("campaign_recipients", "fk_campaign_recipients_campaign_id_campaigns"),
    ("email_logs", "fk_email_logs_campaign_id_campaigns"),
    ("campaign_cc_recipients", "fk_campaign_cc_recipients_campaign_id_campaigns"),
]


def _existing_campaign_fk(table: str) -> str | None:
    """Find whatever the campaign_id → campaigns FK is currently called."""
    inspector = sa.inspect(op.get_bind())

    for fk in inspector.get_foreign_keys(table):
        if fk["referred_table"] == "campaigns" and fk["constrained_columns"] == [
            "campaign_id"
        ]:
            return fk["name"]

    return None


def _recreate_campaign_fk(table: str, new_name: str, *, ondelete: str | None) -> None:
    current = _existing_campaign_fk(table)

    if current:
        op.drop_constraint(current, table, type_="foreignkey")

    op.create_foreign_key(
        new_name,
        table,
        "campaigns",
        ["campaign_id"],
        ["id"],
        ondelete=ondelete,
    )


def upgrade() -> None:
    """Upgrade schema."""
    for table, name in _CAMPAIGN_FK_TABLES:
        _recreate_campaign_fk(table, name, ondelete="CASCADE")

    op.create_index(
        op.f("ix_email_logs_campaign_id"),
        "email_logs",
        ["campaign_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_email_logs_campaign_id"), table_name="email_logs")

    for table, name in _CAMPAIGN_FK_TABLES:
        _recreate_campaign_fk(table, name, ondelete=None)
