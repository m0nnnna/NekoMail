import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import require_auth
from models.account import Account
from models.user import User
from schemas.account import AccountCreate, AccountOut, AccountUpdate, FolderOut, TestConnectResult
from schemas.mail import SyncResult
from services import account_service, message_service
from services.mail import rules as rules_service
from services.mail import sync as sync_service

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


async def _get_account_or_404(db: AsyncSession, user: User, account_id: uuid.UUID) -> Account:
    account = await account_service.get_account(db, user.id, account_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    return account


@router.get("", response_model=list[AccountOut])
async def list_accounts(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_auth)],
):
    return await account_service.list_accounts(db, user.id)


@router.post("", response_model=AccountOut, status_code=status.HTTP_201_CREATED)
async def create_account(
    data: AccountCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_auth)],
):
    try:
        return await account_service.create_account(db, user.id, data)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{account_id}", response_model=AccountOut)
async def get_account(
    account_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_auth)],
):
    return await _get_account_or_404(db, user, account_id)


@router.patch("/{account_id}", response_model=AccountOut)
async def update_account(
    account_id: uuid.UUID,
    data: AccountUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_auth)],
):
    account = await _get_account_or_404(db, user, account_id)
    try:
        return await account_service.update_account(db, account, data)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    account_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_auth)],
):
    account = await _get_account_or_404(db, user, account_id)
    await account_service.delete_account(db, account)


@router.post("/{account_id}/test-connect", response_model=TestConnectResult)
async def test_connect(
    account_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_auth)],
):
    account = await _get_account_or_404(db, user, account_id)
    return await account_service.test_connect(db, account)


@router.post("/{account_id}/folders/refresh", response_model=list[FolderOut])
async def refresh_folders(
    account_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_auth)],
):
    account = await _get_account_or_404(db, user, account_id)
    try:
        return await account_service.refresh_folders(db, account)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Folder discovery failed: {exc}") from exc


@router.get("/{account_id}/folders", response_model=list[FolderOut])
async def list_folders(
    account_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_auth)],
):
    account = await _get_account_or_404(db, user, account_id)
    return await account_service.list_folders(db, account)


@router.get("/{account_id}/unread-counts", response_model=dict[uuid.UUID, int])
async def unread_counts(
    account_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_auth)],
):
    account = await _get_account_or_404(db, user, account_id)
    return await message_service.get_unread_counts(db, account.id)


@router.post("/{account_id}/sync", response_model=list[SyncResult])
async def sync_account(
    account_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_auth)],
):
    account = await _get_account_or_404(db, user, account_id)
    try:
        results = await sync_service.sync_account(db, account)
        for r in results:
            if r.new_message_ids:
                await rules_service.apply_rules_to_new_messages(db, account, r.new_message_ids)
        return results
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Sync failed: {exc}") from exc
