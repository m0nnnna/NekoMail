import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import require_auth
from models.user import User
from schemas.rule import RuleCreate, RuleOut, RuleUpdate
from services.mail import rules as rules_service

router = APIRouter(prefix="/api/rules", tags=["rules"])


async def _get_rule_or_404(db: AsyncSession, user: User, rule_id: uuid.UUID):
    rule = await rules_service.get_rule(db, user.id, rule_id)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    return rule


@router.get("", response_model=list[RuleOut])
async def list_rules(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_auth)],
):
    return await rules_service.list_rules(db, user.id)


@router.post("", response_model=RuleOut, status_code=status.HTTP_201_CREATED)
async def create_rule(
    data: RuleCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_auth)],
):
    return await rules_service.create_rule(db, user.id, data)


@router.patch("/{rule_id}", response_model=RuleOut)
async def update_rule(
    rule_id: uuid.UUID,
    data: RuleUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_auth)],
):
    rule = await _get_rule_or_404(db, user, rule_id)
    return await rules_service.update_rule(db, rule, data)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_auth)],
):
    rule = await _get_rule_or_404(db, user, rule_id)
    await rules_service.delete_rule(db, rule)
