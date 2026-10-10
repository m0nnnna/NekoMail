from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from dependencies import CallerContext, get_caller, get_serializer, require_auth
from models.user import User
from schemas.auth import LoginRequest, UserOut
from services import local_auth
from services.auth_service import authenticate_user
from services.rate_limiter import clear_failures, is_locked_out, record_failure

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.post("/login", response_model=UserOut)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    ip = _client_ip(request)

    if await is_locked_out(ip):
        raise HTTPException(status_code=429, detail="Too many failed attempts. Please try again in 15 minutes.")

    user = await authenticate_user(db, body.username, body.password)
    if not user:
        count = await record_failure(ip)
        remaining = max(0, 10 - count)
        detail = "Invalid username or password."
        if 0 < remaining <= 3:
            detail += f" {remaining} attempt{'s' if remaining != 1 else ''} remaining before lockout."
        raise HTTPException(status_code=401, detail=detail)

    await clear_failures(ip)

    _set_session_cookie(response, user)
    return user


def _set_session_cookie(response: Response, user: User) -> None:
    s = get_serializer()
    response.set_cookie(
        key="session",
        value=s.dumps(str(user.id)),
        httponly=True,
        samesite="lax",
        max_age=86400 * 7,
        secure=settings.cookie_secure,
    )


# --- Local auto-login for the native window (desktop mode only) ---
# See services/local_auth.py for the design.

def _require_local(request: Request) -> None:
    if not local_auth.enabled() or not local_auth.request_is_local(request):
        raise HTTPException(status_code=404, detail="Not found")


@router.post("/local/ticket")
async def local_ticket(request: Request):
    _require_local(request)
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer ") or not local_auth.check_token(header[7:].strip()):
        raise HTTPException(status_code=403, detail="Forbidden")
    return {"ticket": local_auth.issue_ticket()}


@router.get("/local/session")
async def local_session(request: Request, ticket: str, db: Annotated[AsyncSession, Depends(get_db)]):
    _require_local(request)
    if not local_auth.redeem_ticket(ticket):
        raise HTTPException(status_code=403, detail="Forbidden")
    user = (await db.execute(select(User).where(User.is_admin.is_(True)).order_by(User.created_at))).scalars().first()
    if user is None:
        raise HTTPException(status_code=503, detail="No user yet")
    redirect = RedirectResponse("/", status_code=303)
    _set_session_cookie(redirect, user)
    return redirect


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("session", samesite="lax", httponly=True)
    return {"status": "ok"}


@router.get("/me", response_model=UserOut)
async def me(user: Annotated[User, Depends(require_auth)]):
    return user
