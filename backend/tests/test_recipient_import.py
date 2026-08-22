"""CSV recipient import."""

from __future__ import annotations

import pytest

from app.models import CampaignRecipient
from app.services.recipient_import import import_recipients_from_csv


@pytest.fixture
def csv_file(tmp_path):
    def _write(content: str, name: str = "recipients.csv"):
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        return path

    return _write


@pytest.fixture(autouse=True)
def _no_validation_task(monkeypatch):
    """The import queues DNS validation; there is no broker under test."""
    from unittest.mock import MagicMock

    import app.services.recipient_import as recipient_import

    task = MagicMock()
    monkeypatch.setattr(recipient_import, "validate_recipients_task", task)
    return task


def emails(db, campaign_id) -> set[str]:
    return {
        row.email
        for row in db.query(CampaignRecipient).filter_by(campaign_id=campaign_id)
    }


def test_imports_rows(db, alice, make_campaign, csv_file):
    campaign = make_campaign(alice)
    path = csv_file(
        "email,first_name,last_name\na@example.com,Ann,Lee\nb@example.com,Bo,Ray\n"
    )

    summary = import_recipients_from_csv(db, str(campaign.id), path)

    assert summary.total_rows == 2
    assert emails(db, campaign.id) == {"a@example.com", "b@example.com"}


def test_names_are_captured(db, alice, make_campaign, csv_file):
    campaign = make_campaign(alice)
    path = csv_file("email,first_name,last_name\na@example.com,Ann,Lee\n")

    import_recipients_from_csv(db, str(campaign.id), path)

    row = db.query(CampaignRecipient).filter_by(campaign_id=campaign.id).one()
    assert (row.first_name, row.last_name) == ("Ann", "Lee")


def test_addresses_are_lowercased_and_trimmed(db, alice, make_campaign, csv_file):
    campaign = make_campaign(alice)
    path = csv_file("email\n  MiXeD@Example.COM  \n")

    import_recipients_from_csv(db, str(campaign.id), path)

    assert emails(db, campaign.id) == {"mixed@example.com"}


def test_rows_without_an_email_are_counted_invalid(db, alice, make_campaign, csv_file):
    campaign = make_campaign(alice)
    path = csv_file("email,first_name\na@example.com,Ann\n,Nobody\n")

    summary = import_recipients_from_csv(db, str(campaign.id), path)

    assert summary.total_rows == 2
    assert summary.invalid == 1
    assert emails(db, campaign.id) == {"a@example.com"}


def test_duplicates_within_one_file_collapse(db, alice, make_campaign, csv_file):
    campaign = make_campaign(alice)
    path = csv_file("email\na@example.com\na@example.com\n")

    import_recipients_from_csv(db, str(campaign.id), path)

    assert db.query(CampaignRecipient).filter_by(campaign_id=campaign.id).count() == 1


def test_reimporting_does_not_duplicate(db, alice, make_campaign, csv_file):
    campaign = make_campaign(alice)
    path = csv_file("email\na@example.com\n")

    import_recipients_from_csv(db, str(campaign.id), path)
    import_recipients_from_csv(db, str(campaign.id), path)

    assert db.query(CampaignRecipient).filter_by(campaign_id=campaign.id).count() == 1


def test_imported_rows_await_validation(db, alice, make_campaign, csv_file):
    campaign = make_campaign(alice)
    path = csv_file("email\na@example.com\n")

    import_recipients_from_csv(db, str(campaign.id), path)

    row = db.query(CampaignRecipient).filter_by(campaign_id=campaign.id).one()
    assert row.status == "pending_validation"
    assert row.dns_valid is None


def test_validation_is_queued(db, alice, make_campaign, csv_file, _no_validation_task):
    campaign = make_campaign(alice)
    path = csv_file("email\na@example.com\n")

    import_recipients_from_csv(db, str(campaign.id), path)

    assert _no_validation_task.delay.called


def test_a_file_without_an_email_column_is_rejected(db, alice, make_campaign, csv_file):
    campaign = make_campaign(alice)
    path = csv_file("name,phone\nAnn,123\n")

    with pytest.raises(ValueError, match="email"):
        import_recipients_from_csv(db, str(campaign.id), path)


def test_recipients_are_scoped_to_their_campaign(db, alice, make_campaign, csv_file):
    first = make_campaign(alice)
    second = make_campaign(alice)
    path = csv_file("email\nshared@example.com\n")

    import_recipients_from_csv(db, str(first.id), path)
    import_recipients_from_csv(db, str(second.id), path)

    assert emails(db, first.id) == {"shared@example.com"}
    assert emails(db, second.id) == {"shared@example.com"}
