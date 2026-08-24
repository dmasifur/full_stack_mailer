"""
Per-recipient substitution of ``{{token}}`` placeholders in a campaign body.

Syntax is ``{{token}}`` or ``{{token|fallback}}``. Whitespace inside the braces
is ignored, so ``{{ first_name | there }}`` is the same as
``{{first_name|there}}``.
"""

from __future__ import annotations

from collections.abc import Callable
import html
import re

from app.models.campaign_recipient import CampaignRecipient

# The token name is restricted to word characters so an unbalanced brace in
# hand-written HTML cannot make the pattern swallow a span of markup.
_TOKEN = re.compile(r"\{\{\s*(\w+)\s*(?:\|([^}]*))?\}\}")

_FIELDS: dict[str, Callable[[CampaignRecipient], str | None]] = {
    "first_name": lambda r: r.first_name,
    "last_name": lambda r: r.last_name,
    "email": lambda r: r.email,
}


def render_merge_fields(html_body: str, recipient: CampaignRecipient) -> str:
    """
    Resolve merge tokens in ``html_body`` for one recipient.

    Values are HTML-escaped. They come from an uploaded CSV and land inside a
    document that is emailed out, so an unescaped name containing markup would
    be interpolated into the message as markup.

    An unrecognised token is left in place rather than blanked. A literal
    ``{{foo}}`` arriving in an inbox is a visible mistake someone can correct;
    a silently empty space is one nobody notices.
    """

    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        fallback = match.group(2)

        accessor = _FIELDS.get(name)
        if accessor is None:
            return match.group(0)

        value = (accessor(recipient) or "").strip()

        if not value:
            value = (fallback or "").strip()

        return html.escape(value)

    return _TOKEN.sub(_replace, html_body)
