"""Resolves a valid OAuth access token for an Account, refreshing it via
MSAL's refresh-token grant if the cached one is missing/expired. Every IMAP/
SMTP connection for an oauth-authenticated account goes through this first
(see account_conn.py) instead of reading a stored password directly.
"""

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from models.account import Account
from services.mail import outlook_oauth

_EXPIRY_MARGIN = timedelta(minutes=2)


async def get_access_token(db: AsyncSession, account: Account) -> str:
    now = datetime.now(timezone.utc)
    # SQLite has no native timezone type -- SQLAlchemy round-trips DateTime
    # columns through it as naive, so a freshly-loaded account's
    # oauth_token_expires_at comes back tz-naive even though it was written
    # tz-aware. Only the in-memory-since-creation case is already aware.
    expires_at = account.oauth_token_expires_at
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if account.oauth_access_token and expires_at and expires_at > now + _EXPIRY_MARGIN:
        return account.oauth_access_token

    if not account.oauth_refresh_token:
        raise RuntimeError("No OAuth refresh token stored for this account -- re-link it under Accounts")

    if account.oauth_provider == "outlook":
        result = await asyncio.to_thread(outlook_oauth.refresh, account.oauth_refresh_token)
    else:
        raise RuntimeError(f"Unknown OAuth provider {account.oauth_provider!r}")

    account.oauth_access_token = result["access_token"]
    account.oauth_token_expires_at = now + timedelta(seconds=result.get("expires_in", 3600))
    # Microsoft sometimes rotates the refresh token on use -- persist the new
    # one if given, otherwise keep using the one we already have.
    if result.get("refresh_token"):
        account.oauth_refresh_token = result["refresh_token"]
    await db.flush()
    return account.oauth_access_token
