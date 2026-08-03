from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from dependencies import CallerContext, get_caller, get_serializer, require_auth
from models.user import User
from schemas.auth import LoginRequest, UserOut
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

    s = get_serializer()
    session_token = s.dumps(str(user.id))
    response.set_cookie(
        key="session",
        value=session_token,
        httponly=True,
        samesite="lax",
        max_age=86400 * 7,
        secure=settings.cookie_secure,
    )
    return user


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("session", samesite="lax", httponly=True)
    return {"status": "ok"}


@router.get("/me", response_model=UserOut)
async def me(user: Annotated[User, Depends(require_auth)]):
    return user
