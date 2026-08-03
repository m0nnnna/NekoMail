import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ConditionField = Literal["from", "to", "cc", "subject", "body", "has_attachment"]
ConditionOperator = Literal["contains", "not_contains", "equals", "starts_with", "ends_with", "matches_regex", "is_true", "is_false"]
ActionType = Literal["mark_read", "mark_unread", "star", "unstar", "archive", "trash", "move_to_folder"]


class RuleCondition(BaseModel):
    field: ConditionField
    operator: ConditionOperator
    value: str = ""


class RuleAction(BaseModel):
    type: ActionType
    params: dict = Field(default_factory=dict)


class RuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    account_id: uuid.UUID | None = None
    is_active: bool = True
    priority: int = 0
    conditions: list[RuleCondition] = Field(min_length=1)
    actions: list[RuleAction] = Field(min_length=1)


class RuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    account_id: uuid.UUID | None = None
    is_active: bool | None = None
    priority: int | None = None
    conditions: list[RuleCondition] | None = None
    actions: list[RuleAction] | None = None


class RuleOut(BaseModel):
    id: uuid.UUID
    name: str
    account_id: uuid.UUID | None
    is_active: bool
    priority: int
    conditions: list[RuleCondition]
    actions: list[RuleAction]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
