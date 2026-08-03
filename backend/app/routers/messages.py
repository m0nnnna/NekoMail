import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import require_auth
from models.user import User
from schemas.mail import (
    BulkActionRequest,
    BulkActionResult,
    FlagUpdate,
    HtmlBodyOut,
    MessageDetail,
    MessageOut,
    MoveRequest,
    PgpCiphertextOut,
)
from services import message_service
from services.mail import actions
from services.mail.parser import extract_attachment_payload, extract_html_body, extract_pgp_ciphertext

router = APIRouter(prefix="/api/messages", tags=["messages"])


@router.get("", response_model=list[MessageOut])
async def list_messages(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_auth)],
    account_id: uuid.UUID | None = None,
    folder_id: uuid.UUID | None = None,
    special_use: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    return await message_service.list_messages(
        db, user.id, account_id=account_id, folder_id=folder_id, special_use=special_use, limit=limit, offset=offset,
    )


@router.patch("/flags", response_model=BulkActionResult)
async def update_flags(
    data: FlagUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_auth)],
):
    return await actions.set_flags(db, user.id, data.message_ids, data.add, data.remove)


@router.post("/archive", response_model=BulkActionResult)
async def archive_messages(
    data: BulkActionRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_auth)],
):
    return await actions.archive_messages(db, user.id, data.message_ids)


@router.post("/trash", response_model=BulkActionResult)
async def trash_messages(
    data: BulkActionRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_auth)],
):
    return await actions.trash_messages(db, user.id, data.message_ids)


@router.post("/move", response_model=BulkActionResult)
async def move_messages(
    data: MoveRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_auth)],
):
    return await actions.move_messages(db, user.id, data.message_ids, data.target_folder_id)


@router.get("/{message_id}", response_model=MessageDetail)
async def get_message(
    message_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_auth)],
):
    message = await message_service.get_message(db, user.id, message_id)
    if message is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    return message


@router.get("/{message_id}/html", response_model=HtmlBodyOut)
async def get_message_html(
    message_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_auth)],
):
    message = await message_service.get_message(db, user.id, message_id)
    if message is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    raw = message_service.read_eml_bytes(message)
    return {"html": extract_html_body(raw)}


@router.get("/{message_id}/pgp", response_model=PgpCiphertextOut)
async def get_message_pgp(
    message_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_auth)],
):
    message = await message_service.get_message(db, user.id, message_id)
    if message is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    raw = message_service.read_eml_bytes(message)
    return {"ciphertext": extract_pgp_ciphertext(raw)}


@router.get("/{message_id}/attachments/{attachment_id}")
async def get_message_attachment(
    message_id: int,
    attachment_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_auth)],
):
    message = await message_service.get_message(db, user.id, message_id)
    if message is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")

    ordered = sorted(message.attachments, key=lambda a: a.id)
    ordinal = next((i for i, a in enumerate(ordered) if a.id == attachment_id), None)
    if ordinal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")

    raw = message_service.read_eml_bytes(message)
    extracted = extract_attachment_payload(raw, ordinal)
    if extracted is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")

    payload, mime_type, _filename = extracted
    attachment = ordered[ordinal]
    filename = (attachment.filename or _filename or "attachment").replace('"', "")
    return Response(
        content=payload,
        media_type=attachment.mime_type or mime_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
