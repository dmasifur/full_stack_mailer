import logging

import requests

from app.models.user import User

logger = logging.getLogger(__name__)

GRAPH_SENDMAIL_URL = "https://graph.microsoft.com/v1.0/me/sendMail"


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
    *, user: User, recipient_email: str, subject: str, html_body: str
) -> None:
    headers = {
        "Authorization": (f"Bearer {user.access_token}"),
        "Content-Type": "application/json",
    }

    payload = {
        "message": {
            "subject": subject,
            "body": {"ContentType": "HTML", "content": html_body},
            "toRecipients": [{"emailAddress": {"address": recipient_email}}],
        },
        "saveToSentItems": True,
    }

    response = requests.post(
        GRAPH_SENDMAIL_URL, headers=headers, json=payload, timeout=30
    )

    if response.status_code == 401:
        raise EmailAuthError("Microsoft access token expired.")

    if response.status_code == 429:
        raise RetryableEmailError(
            "Microsoft Graph rate limit hit."
        )

    if response.status_code >= 500:
        raise RetryableEmailError(
            f"Microsoft server error: "
            f"{response.status_code}"
        )

    if response.status_code >= 400:
        logger.error(
            "Graph API send failed. status=%s response=%s",
            response.status_code,
            response.text,
        )

        raise PermanentEmailError(
            f"Permanent Graph API send failed: "
            f"{response.status_code}"
        )
