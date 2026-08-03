import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

SecurityMode = Literal["ssl", "starttls", "none"]


class AccountCreate(BaseModel):
    label: str = Field(min_length=1, max_length=128)
    email_address: str = Field(min_length=3, max_length=320)

    imap_host: str = Field(min_length=1, max_length=256)
    imap_port: int = 993
    imap_security: SecurityMode = "ssl"
    imap_username: str = Field(min_length=1, max_length=256)
    imap_password: str = Field(min_length=1)

    smtp_host: str = Field(min_length=1, max_length=256)
    smtp_port: int = 587
    smtp_security: SecurityMode = "starttls"
    smtp_username: str = Field(min_length=1, max_length=256)
    smtp_password: str = Field(min_length=1)

    verify_ssl: bool = True
    auto_saves_sent: bool = False


class AccountUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=128)
    email_address: str | None = Field(default=None, min_length=3, max_length=320)

    imap_host: str | None = Field(default=None, min_length=1, max_length=256)
    imap_port: int | None = None
    imap_security: SecurityMode | None = None
    imap_username: str | None = Field(default=None, min_length=1, max_length=256)
    imap_password: str | None = Field(default=None, min_length=1)

    smtp_host: str | None = Field(default=None, min_length=1, max_length=256)
    smtp_port: int | None = None
    smtp_security: SecurityMode | None = None
    smtp_username: str | None = Field(default=None, min_length=1, max_length=256)
    smtp_password: str | None = Field(default=None, min_length=1)

    verify_ssl: bool | None = None
    auto_saves_sent: bool | None = None
    is_active: bool | None = None


class AccountOut(BaseModel):
    id: uuid.UUID
    label: str
    email_address: str

    imap_host: str
    imap_port: int
    imap_security: SecurityMode
    imap_username: str

    smtp_host: str
    smtp_port: int
    smtp_security: SecurityMode
    smtp_username: str

    verify_ssl: bool
    auto_saves_sent: bool
    auth_type: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ConnectionCheckResult(BaseModel):
    ok: bool
    detail: str


class TestConnectResult(BaseModel):
    imap: ConnectionCheckResult
    smtp: ConnectionCheckResult


class FolderOut(BaseModel):
    id: uuid.UUID
    name: str
    delimiter: str | None
    special_use: str | None
    is_selectable: bool

    class Config:
        from_attributes = True
