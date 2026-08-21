import logging
from urllib.parse import quote

import requests

from app.models.user import User
from app.services.token_encryption import decrypt_token

logger = logging.getLogger(__name__)

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
GRAPH_SENDMAIL_URL = f"{GRAPH_BASE_URL}/me/sendMail"


def _sendmail_url(from_address: str | None) -> str:
    """
    Pick the Graph endpoint for the mailbox being sent from.

    /me/sendMail always sends as the authenticated user — Graph ignores a "from"
    field there unless the account holds SendAs rights, which silently defeats
    shared-mailbox sending. Addressing the mailbox directly via
    /users/{address}/sendMail is the supported route, and is what the
    Mail.Send.Shared scope grants.
    """
    if not from_address:
        return GRAPH_SENDMAIL_URL

    return f"{GRAPH_BASE_URL}/users/{quote(from_address)}/sendMail"


class EmailSendError(Exception):
    """
    Base email send exception.
    """


class RetryableEmailError(EmailSendError):
    """
    Temporary/transient send failure.
    """


class PermanentEmailError(EmailSendError):
    """
    Non-retryable send failure.
    """


class EmailAuthError(EmailSendError):
    """
    Access token invalid/expired.
    """


def send_email_via_graph_api(
    *,
    user: User,
    recipient_email: str,
    subject: str,
    html_body: str,
    from_address: str | None = None,
    cc_emails: list[str] | None = None,
) -> None:
    """
    Send an email via the Microsoft Graph API.

    from_address: if provided, sends from this address (requires Mail.Send.Shared
    permission in Azure for shared mailboxes). If None, sends from the
    authenticated user's own mailbox.

    cc_emails: optional list of CC recipient addresses.
    """
    plaintext_token = decrypt_token(user.access_token)

    headers = {
        "Authorization": f"Bearer {plaintext_token}",
        "Content-Type": "application/json",
    }

    message: dict = {
        "subject": subject,
        "body": {"ContentType": "HTML", "content": html_body},
        "toRecipients": [{"emailAddress": {"address": recipient_email}}],
    }

    # The endpoint (below) is what actually selects the mailbox; "from" makes the
    # intent explicit and is required by Graph when sending on behalf of another.
    if from_address:
        message["from"] = {"emailAddress": {"address": from_address}}

    # CC recipients — only include the key if there are addresses to send to.
    if cc_emails:
        message["ccRecipients"] = [
            {"emailAddress": {"address": addr}} for addr in cc_emails
        ]

    payload = {
        "message": message,
        "saveToSentItems": True,
    }

    response = requests.post(
        _sendmail_url(from_address), headers=headers, json=payload, timeout=30
    )

    if response.status_code == 401:
        raise EmailAuthError("Microsoft access token expired.")

    if response.status_code == 429:
        raise RetryableEmailError("Microsoft Graph rate limit hit.")

    if response.status_code >= 500:
        raise RetryableEmailError(f"Microsoft server error: {response.status_code}")

    if response.status_code >= 400:
        logger.error(
            "Graph API send failed. status=%s response=%s",
            response.status_code,
            response.text,
        )
        raise PermanentEmailError(
            f"Permanent Graph API send failed: {response.status_code}"
        )
