"""Outlook account linking via OAuth2/XOAUTH2 (Phase 7). Two-step browser
redirect flow: /start (auth-gated, initiated by an in-app "Link Outlook
Account" full-page navigation) redirects to Microsoft; /callback
(unauthenticated -- Microsoft's redirect is a fresh top-level navigation
that may not carry our session cookie in every browser/config) exchanges
the code and creates the Account under whichever user actually initiated
the flow, tracked server-side by `state` rather than by cookie.

The in-process `_pending_flows` dict mirrors the same single-worker
assumption services/mail/scheduler.py's `_idle_tasks` already documents --
this app must run under `uvicorn --workers 1`.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from dependencies import require_auth
from models.user import User
from services import account_service
from services.mail import outlook_oauth

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/accounts/oauth/outlook", tags=["oauth"])

_PENDING_FLOW_TTL = timedelta(minutes=15)
_pending_flows: dict[str, dict] = {}


def _error_redirect(message: str) -> RedirectResponse:
    return RedirectResponse(url=f"/accounts?outlook_error={quote(message)}")


def _prune_stale_flows() -> None:
    cutoff = datetime.now(timezone.utc) - _PENDING_FLOW_TTL
    for state in [s for s, v in _pending_flows.items() if v["created_at"] < cutoff]:
        _pending_flows.pop(state, None)


@router.get("/start")
async def start(user: Annotated[User, Depends(require_auth)]):
    if not settings.azure_client_id:
        return _error_redirect("Outlook linking isn't configured on this server (AZURE_CLIENT_ID is unset).")

    _prune_stale_flows()
    try:
        flow = await asyncio.to_thread(outlook_oauth.start_flow)
    except Exception as exc:
        logger.exception("Failed to start Outlook OAuth flow")
        return _error_redirect(f"Couldn't start Microsoft sign-in: {exc}")

    _pending_flows[flow["state"]] = {"flow": flow, "user_id": user.id, "created_at": datetime.now(timezone.utc)}
    return RedirectResponse(url=flow["auth_uri"])


@router.get("/callback")
async def callback(request: Request, db: Annotated[AsyncSession, Depends(get_db)]):
    params = dict(request.query_params)
    state = params.get("state")
    pending = _pending_flows.pop(state, None) if state else None
    if pending is None:
        return _error_redirect("Login session expired or was already used -- try linking again.")

    try:
        result = await asyncio.to_thread(outlook_oauth.complete_flow, pending["flow"], params)
    except Exception as exc:
        logger.exception("Outlook OAuth token exchange failed")
        return _error_redirect(f"Microsoft sign-in failed: {exc}")

    claims = result.get("id_token_claims") or {}
    email = claims.get("preferred_username") or claims.get("email")
    if not email:
        return _error_redirect("Microsoft didn't return an email address for this account.")

    refresh_token = result.get("refresh_token")
    if not refresh_token:
        return _error_redirect(
            "Microsoft didn't grant offline access -- check the app registration's API permissions include offline_access."
        )

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=result.get("expires_in", 3600))

    try:
        account = await account_service.create_oauth_outlook_account(
            db, pending["user_id"], email=email, label=claims.get("name") or email,
            access_token=result["access_token"], refresh_token=refresh_token, expires_at=expires_at,
        )
    except ValueError as exc:
        return _error_redirect(str(exc))

    return RedirectResponse(url=f"/accounts?outlook_linked={account.id}")
