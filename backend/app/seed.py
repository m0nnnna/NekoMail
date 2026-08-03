"""Seed the database with the initial admin user if none exists."""
import asyncio

from sqlalchemy import select

from config import settings
from database import AsyncSessionLocal
from models.user import User
from services.auth_service import create_user, pwd_context


async def seed():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.username == settings.admin_username))
        admin = result.scalar_one_or_none()
        if admin is None:
            print(f"Creating admin user: {settings.admin_username}")
            await create_user(
                db,
                username=settings.admin_username,
                password=settings.admin_password,
                display_name="Admin",
                is_admin=True,
            )
            await db.commit()
            print("Admin user created.")
        else:
            # Always re-hash and sync password from .env on startup
            admin.password_hash = pwd_context.hash(settings.admin_password)
            await db.commit()
            print("Admin password synced from .env.")


if __name__ == "__main__":
    asyncio.run(seed())
