from urllib.parse import urlencode

from app.core.config import settings

MICROSOFT_AUTHORIZATION_URL = (
    f"https://login.microsoftonline.com/"
    f"{settings.MICROSOFT_TENANT_ID}/oauth2/v2.0/authorize"
)

MICROSOFT_TOKEN_URL = (
    f"https://login.microsoftonline.com/"
    f"{settings.MICROSOFT_TENANT_ID}/oauth2/v2.0/token"
)

SCOPES = [
    "offline_access",
    "openid",
    "profile",
    "email",
    "Mail.Send"
    "User.Read"
]

def build_authorization_url(state: str) -> str:
    
    params = {
        "client_id":settings.MICROSOFT_CLIENT_ID,
        "response_type":"code",
        "redirect_uri":settings.MICROSOFT_REDIRECT_URI,
        "response_mode":"query",
        "scope":" ".join(SCOPES),
        "state":state
    }
    
    return (
        f"{MICROSOFT_AUTHORIZATION_URL}?"
        f"{urlencode(params)}"
    )

