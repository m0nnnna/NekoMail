import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.contact import Contact
from schemas.mail import ContactCreate, ContactUpdate


async def search_contacts(db: AsyncSession, user_id: uuid.UUID, q: str, limit: int) -> list[Contact]:
    query = select(Contact).where(Contact.user_id == user_id).order_by(Contact.last_seen_at.desc()).limit(limit)
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.where(or_(Contact.email.ilike(like), Contact.display_name.ilike(like)))
    result = await db.execute(query)
    return list(result.scalars())


async def get_by_email(db: AsyncSession, user_id: uuid.UUID, email: str) -> Contact | None:
    result = await db.execute(select(Contact).where(Contact.user_id == user_id, Contact.email == email.strip().lower()))
    return result.scalar_one_or_none()


async def get_contact(db: AsyncSession, user_id: uuid.UUID, contact_id: uuid.UUID) -> Contact | None:
    result = await db.execute(select(Contact).where(Contact.id == contact_id, Contact.user_id == user_id))
    return result.scalar_one_or_none()


async def create_contact(db: AsyncSession, user_id: uuid.UUID, data: ContactCreate) -> Contact:
    email = data.email.strip().lower()
    existing = await get_by_email(db, user_id, email)
    if existing is not None:
        raise ValueError(f"A contact for {email} already exists")
    contact = Contact(user_id=user_id, email=email, display_name=data.display_name, pgp_public_key=data.pgp_public_key)
    db.add(contact)
    await db.flush()
    return contact


async def update_contact(db: AsyncSession, contact: Contact, data: ContactUpdate) -> Contact:
    changes = data.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(contact, field, value)
    await db.flush()
    await db.refresh(contact)
    return contact
