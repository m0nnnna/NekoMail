"""Outlook OAuth2 account linking (Phase 7). MSAL's PublicClientApplication
does the authorization-code-with-PKCE dance -- no client secret, since this
is a public client. See NEXT_STEPS.md for the exact Azure App Registration
shape this requires: redirect URI registered under the **Web** platform
(not Mobile/desktop) with "Allow public client flows" enabled -- that
combination is what lets a no-secret PKCE exchange land on a real
server-side callback URL instead of a native-app loopback/custom-scheme one.

MSAL is a synchronous, blocking-HTTP library -- every call here is meant to
be run through asyncio.to_thread by the caller so it doesn't stall the
event loop.
"""

import msal

from config import settings

CALLBACK_PATH = "/api/accounts/oauth/outlook/callback"

# Legacy Outlook protocol-auth scopes -- still required for XOAUTH2 over
# IMAP/SMTP (Graph API scopes don't cover this). offline_access is a
# reserved scope MSAL appends to every public-client request automatically --
# passing it explicitly here raises "cannot use a reserved scope".
SCOPES = [
    "https://outlook.office.com/IMAP.AccessAsUser.All",
    "https://outlook.office.com/SMTP.Send",
]


def redirect_uri() -> str:
    return settings.public_base_url.rstrip("/") + CALLBACK_PATH


def _app() -> msal.PublicClientApplication:
    return msal.PublicClientApplication(client_id=settings.azure_client_id, authority=settings.azure_authority)


def start_flow() -> dict:
    """Returns a dict with (at least) `auth_uri` to send the user's browser
    to, and `state` -- the caller must hold onto the whole dict server-side
    (it also carries the PKCE code_verifier) and pass it to complete_flow."""
    return _app().initiate_auth_code_flow(scopes=SCOPES, redirect_uri=redirect_uri())


def complete_flow(flow: dict, auth_response: dict) -> dict:
    """`auth_response` is the callback's raw query params. Returns the MSAL
    token result dict (access_token, refresh_token, expires_in,
    id_token_claims, ...) or raises on failure."""
    result = _app().acquire_token_by_auth_code_flow(flow, auth_response, scopes=SCOPES)
    if "error" in result:
        raise RuntimeError(f"{result['error']}: {result.get('error_description', '')}")
    return result


def refresh(refresh_token: str) -> dict:
    result = _app().acquire_token_by_refresh_token(refresh_token, scopes=SCOPES)
    if "error" in result:
        raise RuntimeError(f"{result['error']}: {result.get('error_description', '')}")
    return result
