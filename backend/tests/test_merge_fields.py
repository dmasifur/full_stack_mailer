"""
Merge-field substitution.

The escaping tests are the point of this file: names arrive from an uploaded
CSV and are interpolated into a document that gets emailed out.
"""

from __future__ import annotations

import pytest

from app.models.campaign_recipient import CampaignRecipient
from app.services.merge_fields import render_merge_fields


def recipient(
    *,
    email: str = "ada@example.com",
    first_name: str | None = "Ada",
    last_name: str | None = "Lovelace",
) -> CampaignRecipient:
    return CampaignRecipient(
        email=email,
        first_name=first_name,
        last_name=last_name,
        status="pending",
        dns_valid=True,
    )


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        ("Hi {{first_name}}", "Hi Ada"),
        ("Hi {{last_name}}", "Hi Lovelace"),
        ("Hi {{email}}", "Hi ada@example.com"),
        ("{{first_name}} {{last_name}}", "Ada Lovelace"),
        ("<p>Dear {{first_name}},</p>", "<p>Dear Ada,</p>"),
    ],
)
def test_supported_tokens_resolve(template, expected):
    assert render_merge_fields(template, recipient()) == expected


def test_whitespace_inside_the_braces_is_tolerated():
    assert render_merge_fields("Hi {{ first_name }}", recipient()) == "Hi Ada"


def test_body_without_tokens_is_returned_unchanged():
    body = "<table><tr><td>Newsletter</td></tr></table>"

    assert render_merge_fields(body, recipient()) == body


def test_unknown_token_is_left_in_place():
    """A visible mistake beats a silently blank space in a recipient's inbox."""
    assert render_merge_fields("Hi {{nickname}}", recipient()) == "Hi {{nickname}}"


@pytest.mark.parametrize("missing", [None, "", "   "])
def test_missing_value_uses_the_fallback(missing):
    result = render_merge_fields(
        "Hi {{first_name|there}}", recipient(first_name=missing)
    )

    assert result == "Hi there"


def test_present_value_wins_over_the_fallback():
    assert render_merge_fields("Hi {{first_name|there}}", recipient()) == "Hi Ada"


def test_missing_value_without_a_fallback_collapses_to_nothing():
    result = render_merge_fields("Hi {{first_name}}!", recipient(first_name=None))

    assert result == "Hi !"


def test_fallback_whitespace_is_trimmed():
    result = render_merge_fields(
        "Hi {{ first_name | Friend }}", recipient(first_name=None)
    )

    assert result == "Hi Friend"


def test_value_is_html_escaped():
    result = render_merge_fields(
        "<p>Hi {{first_name}}</p>", recipient(first_name="<script>alert(1)</script>")
    )

    assert "<script>" not in result
    assert result == "<p>Hi &lt;script&gt;alert(1)&lt;/script&gt;</p>"


def test_fallback_is_html_escaped_too():
    result = render_merge_fields(
        "Hi {{first_name|<b>friend</b>}}", recipient(first_name=None)
    )

    assert result == "Hi &lt;b&gt;friend&lt;/b&gt;"


def test_ampersand_in_a_name_is_escaped():
    result = render_merge_fields("{{last_name}}", recipient(last_name="Barnes & Noble"))

    assert result == "Barnes &amp; Noble"


def test_an_unbalanced_brace_does_not_swallow_markup():
    """
    The token pattern only matches word characters, so a stray brace in
    hand-written HTML cannot consume the span of markup that follows it.
    """
    body = "{{ <p>a paragraph</p> {{first_name}}"

    assert render_merge_fields(body, recipient()) == "{{ <p>a paragraph</p> Ada"
