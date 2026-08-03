import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class Address(BaseModel):
    name: str | None
    email: str


class SyncResult(BaseModel):
    folder_name: str
    new_count: int
    backfilled_count: int
    reconciled: bool


class AttachmentOut(BaseModel):
    id: int
    filename: str | None
    mime_type: str
    size: int | None
    content_id: str | None
    is_inline: bool

    class Config:
        from_attributes = True


class MessageOut(BaseModel):
    id: int
    account_id: uuid.UUID
    folder_id: uuid.UUID
    uid: int
    thread_id: str

    subject: str | None
    from_addrs: list[Address]
    to_addrs: list[Address]
    cc_addrs: list[Address]
    date: datetime | None
    snippet: str | None
    flags: list[str]
    has_attachments: bool
    is_encrypted: bool

    class Config:
        from_attributes = True


class MessageDetail(MessageOut):
    bcc_addrs: list[Address]
    body_text: str | None
    attachments: list[AttachmentOut]

    class Config:
        from_attributes = True


class HtmlBodyOut(BaseModel):
    html: str | None


class PgpCiphertextOut(BaseModel):
    ciphertext: str | None


class FlagUpdate(BaseModel):
    message_ids: list[int] = Field(min_length=1)
    add: list[str] = Field(default_factory=list)
    remove: list[str] = Field(default_factory=list)


class BulkActionRequest(BaseModel):
    message_ids: list[int] = Field(min_length=1)


class MoveRequest(BaseModel):
    message_ids: list[int] = Field(min_length=1)
    target_folder_id: uuid.UUID


class BulkActionError(BaseModel):
    message_id: int
    error: str


class BulkActionResult(BaseModel):
    succeeded_ids: list[int]
    failed: list[BulkActionError]


class SendResult(BaseModel):
    sent: bool
    sent_message: MessageOut | None


class ContactOut(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str | None
    pgp_public_key: str | None

    class Config:
        from_attributes = True


class ContactCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    display_name: str | None = None
    pgp_public_key: str | None = None


class ContactUpdate(BaseModel):
    display_name: str | None = None
    pgp_public_key: str | None = None
