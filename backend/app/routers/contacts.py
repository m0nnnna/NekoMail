import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import require_auth
from models.user import User
from schemas.mail import ContactCreate, ContactOut, ContactUpdate
from services import contact_service

router = APIRouter(prefix="/api/contacts", tags=["contacts"])


@router.get("", response_model=list[ContactOut])
async def search_contacts(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_auth)],
    q: Annotated[str, Query()] = "",
    limit: Annotated[int, Query(ge=1, le=20)] = 8,
):
    return await contact_service.search_contacts(db, user.id, q, limit)


@router.get("/lookup", response_model=ContactOut)
async def lookup_contact(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_auth)],
    email: Annotated[str, Query(min_length=3)],
):
    contact = await contact_service.get_by_email(db, user.id, email)
    if contact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found")
    return contact


@router.post("", response_model=ContactOut, status_code=status.HTTP_201_CREATED)
async def create_contact(
    data: ContactCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_auth)],
):
    try:
        return await contact_service.create_contact(db, user.id, data)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/{contact_id}", response_model=ContactOut)
async def update_contact(
    contact_id: uuid.UUID,
    data: ContactUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_auth)],
):
    contact = await contact_service.get_contact(db, user.id, contact_id)
    if contact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found")
    return await contact_service.update_contact(db, contact, data)
