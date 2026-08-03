import uuid

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str | None
    is_admin: bool

    class Config:
        from_attributes = True
