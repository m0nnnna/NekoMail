import uuid
from datetime import datetime, timezone

from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    result = await db.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


_DUMMY_HASH = pwd_context.hash("dummy-timing-placeholder")


async def authenticate_user(db: AsyncSession, username: str, password: str) -> User | None:
    user = await get_user_by_username(db, username)
    # Always run verify_password to prevent timing-based username enumeration.
    hash_to_check = user.password_hash if user else _DUMMY_HASH
    if not verify_password(password, hash_to_check) or not user:
        return None
    user.last_login_at = datetime.now(timezone.utc)
    return user


async def create_user(db: AsyncSession, username: str, password: str, display_name: str | None = None, is_admin: bool = False) -> User:
    user = User(
        id=uuid.uuid4(),
        username=username,
        password_hash=hash_password(password),
        display_name=display_name,
        is_admin=is_admin,
    )
    db.add(user)
    await db.flush()
    return user
