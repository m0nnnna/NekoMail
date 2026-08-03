import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import require_auth
from models.message import Message
from models.user import User
from schemas.mail import MessageOut, SendResult
from services import account_service, message_service
from services.mail import compose
from services.mail.compose import ComposeAttachment

router = APIRouter(prefix="/api/messages", tags=["compose"])


async def _load_attachments(files: list[UploadFile]) -> list[ComposeAttachment]:
    loaded = []
    for f in files:
        data = await f.read()
        loaded.append(ComposeAttachment(filename=f.filename or "attachment", mime_type=f.content_type or "application/octet-stream", data=data))
    return loaded


async def _threading_headers(db: AsyncSession, user_id: uuid.UUID, in_reply_to_message_id: int | None) -> tuple[str | None, str | None]:
    if in_reply_to_message_id is None:
        return None, None
    original = await message_service.get_message(db, user_id, in_reply_to_message_id)
    if original is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Original message not found")
    in_reply_to = original.message_id_header
    refs = original.references.split() if original.references else []
    if original.message_id_header and original.message_id_header not in refs:
        refs.append(original.message_id_header)
    return in_reply_to, (" ".join(refs) if refs else None)


async def _get_draft(db: AsyncSession, user_id: uuid.UUID, account_id: uuid.UUID, draft_id: int | None) -> Message | None:
    if draft_id is None:
        return None
    draft = await message_service.get_message(db, user_id, draft_id)
    if draft is not None and draft.account_id != account_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Draft belongs to a different account")
    return draft


@router.post("/send", response_model=SendResult)
async def send_message(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_auth)],
    account_id: Annotated[uuid.UUID, Form()],
    to: Annotated[str, Form()] = "",
    cc: Annotated[str, Form()] = "",
    bcc: Annotated[str, Form()] = "",
    subject: Annotated[str, Form()] = "",
    body_text: Annotated[str, Form()] = "",
    in_reply_to_message_id: Annotated[int | None, Form()] = None,
    draft_id: Annotated[int | None, Form()] = None,
    attachments: list[UploadFile] = File(default=[]),
    # Phase 9: a fully-formed PGP/MIME message the browser already built and
    # encrypted with openpgp.js. When present, `attachments`/`body_text`/
    # `subject` above are ignored -- the backend never sees the plaintext.
    raw_mime: Annotated[str | None, Form()] = None,
):
    account = await account_service.get_account(db, user.id, account_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    in_reply_to, references = await _threading_headers(db, user.id, in_reply_to_message_id)
    draft_message = await _get_draft(db, user.id, account_id, draft_id)
    loaded_attachments = [] if raw_mime else await _load_attachments(attachments)

    try:
        sent_message = await compose.send_mail(
            db, account,
            to=to, cc=cc, bcc=bcc, subject=subject, body_text=body_text,
            in_reply_to=in_reply_to, references=references,
            attachments=loaded_attachments,
            draft_message=draft_message,
            raw_mime=raw_mime.encode("utf-8") if raw_mime else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Send failed: {exc}") from exc

    return {"sent": True, "sent_message": sent_message}


@router.post("/draft", response_model=MessageOut)
async def save_draft(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_auth)],
    account_id: Annotated[uuid.UUID, Form()],
    to: Annotated[str, Form()] = "",
    cc: Annotated[str, Form()] = "",
    bcc: Annotated[str, Form()] = "",
    subject: Annotated[str, Form()] = "",
    body_text: Annotated[str, Form()] = "",
    in_reply_to_message_id: Annotated[int | None, Form()] = None,
    draft_id: Annotated[int | None, Form()] = None,
    attachments: list[UploadFile] = File(default=[]),
    raw_mime: Annotated[str | None, Form()] = None,
):
    account = await account_service.get_account(db, user.id, account_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    in_reply_to, references = await _threading_headers(db, user.id, in_reply_to_message_id)
    replace_message = await _get_draft(db, user.id, account_id, draft_id)
    loaded_attachments = [] if raw_mime else await _load_attachments(attachments)

    try:
        return await compose.save_draft(
            db, account,
            to=to, cc=cc, bcc=bcc, subject=subject, body_text=body_text,
            in_reply_to=in_reply_to, references=references,
            attachments=loaded_attachments,
            replace_message=replace_message,
            raw_mime=raw_mime.encode("utf-8") if raw_mime else None,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Draft save failed: {exc}") from exc
