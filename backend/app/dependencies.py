from dataclasses import dataclass
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from models.user import User


def get_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key)


@dataclass
class CallerContext:
    user: User | None = None

    @property
    def is_authenticated(self) -> bool:
        return self.user is not None


async def get_caller(
    db: Annotated[AsyncSession, Depends(get_db)],
    session: Annotated[str | None, Cookie(alias="session")] = None,
) -> CallerContext:
    if session:
        try:
            s = get_serializer()
            user_id = s.loads(session, max_age=86400 * 7)  # 7 days
            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if user:
                return CallerContext(user=user)
        except (BadSignature, SignatureExpired):
            pass

    return CallerContext()


async def require_auth(caller: Annotated[CallerContext, Depends(get_caller)]) -> User:
    if not caller.is_authenticated:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return caller.user
