"""Mail filter rules (Phase 8): CRUD plus the condition-matching/action-
execution engine. Only ever invoked against `FolderSyncResult.new_message_ids`
(services/mail/sync.py) -- genuinely new incoming mail, never a folder's
initial-sync batch or backfilled history. See models/rule.py for the exact
condition/action shapes.

Deliberately called by the sync callers (scheduler.py, routers/accounts.py)
*after* sync_folder/sync_account has returned, not from inside sync.py
itself -- sync_folder holds `lock_for_folder` for the whole pass, and
move/archive/trash actions re-acquire that same (non-reentrant) lock via
actions.py, which would deadlock if invoked while still inside the sync.
"""

import logging
import re
import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.account import Account
from models.message import Message
from models.rule import Rule
from schemas.rule import RuleCreate, RuleUpdate
from services.mail import actions

logger = logging.getLogger(__name__)


# --- CRUD ---

async def list_rules(db: AsyncSession, user_id: uuid.UUID) -> list[Rule]:
    result = await db.execute(select(Rule).where(Rule.user_id == user_id).order_by(Rule.priority, Rule.created_at))
    return list(result.scalars())


async def get_rule(db: AsyncSession, user_id: uuid.UUID, rule_id: uuid.UUID) -> Rule | None:
    result = await db.execute(select(Rule).where(Rule.id == rule_id, Rule.user_id == user_id))
    return result.scalar_one_or_none()


async def create_rule(db: AsyncSession, user_id: uuid.UUID, data: RuleCreate) -> Rule:
    rule = Rule(
        user_id=user_id, name=data.name, account_id=data.account_id,
        is_active=data.is_active, priority=data.priority,
        conditions=[c.model_dump() for c in data.conditions],
        actions=[a.model_dump() for a in data.actions],
    )
    db.add(rule)
    await db.flush()
    return rule


async def update_rule(db: AsyncSession, rule: Rule, data: RuleUpdate) -> Rule:
    changes = data.model_dump(exclude_unset=True)
    if "conditions" in changes:
        changes["conditions"] = [c if isinstance(c, dict) else c.model_dump() for c in changes["conditions"]]
    if "actions" in changes:
        changes["actions"] = [a if isinstance(a, dict) else a.model_dump() for a in changes["actions"]]
    for field, value in changes.items():
        setattr(rule, field, value)
    await db.flush()
    await db.refresh(rule)  # same onupdate=func.now() SQLite gotcha as Account.updated_at
    return rule


async def delete_rule(db: AsyncSession, rule: Rule) -> None:
    await db.delete(rule)
    await db.flush()


# --- Matching ---

def _addr_haystack(addrs: list[dict]) -> str:
    return " ".join(f"{a.get('name') or ''} {a.get('email') or ''}" for a in (addrs or []))


def _field_value(message: Message, field: str) -> str:
    if field == "subject":
        return message.subject or ""
    if field == "body":
        return message.body_text or ""
    if field == "from":
        return _addr_haystack(message.from_addrs)
    if field == "to":
        return _addr_haystack(message.to_addrs)
    if field == "cc":
        return _addr_haystack(message.cc_addrs)
    return ""


def _condition_matches(message: Message, condition: dict) -> bool:
    field = condition.get("field")
    operator = condition.get("operator")
    value = condition.get("value") or ""

    if field == "has_attachment":
        return message.has_attachments if operator == "is_true" else not message.has_attachments

    haystack = _field_value(message, field).lower()
    needle = value.lower()
    if operator == "contains":
        return needle in haystack
    if operator == "not_contains":
        return needle not in haystack
    if operator == "equals":
        return haystack == needle
    if operator == "starts_with":
        return haystack.startswith(needle)
    if operator == "ends_with":
        return haystack.endswith(needle)
    if operator == "matches_regex":
        try:
            return re.search(value, haystack, re.IGNORECASE) is not None
        except re.error:
            return False
    return False


def rule_matches(message: Message, rule: Rule) -> bool:
    conditions = rule.conditions or []
    if not conditions:
        return False  # no conditions = matches nothing, never "matches everything"
    return all(_condition_matches(message, c) for c in conditions)


# --- Execution ---

async def _apply_action(db: AsyncSession, user_id: uuid.UUID, message_ids: list[int], action: dict) -> None:
    action_type = action.get("type")
    if action_type == "mark_read":
        await actions.set_flags(db, user_id, message_ids, ["\\Seen"], [])
    elif action_type == "mark_unread":
        await actions.set_flags(db, user_id, message_ids, [], ["\\Seen"])
    elif action_type == "star":
        await actions.set_flags(db, user_id, message_ids, ["\\Flagged"], [])
    elif action_type == "unstar":
        await actions.set_flags(db, user_id, message_ids, [], ["\\Flagged"])
    elif action_type == "archive":
        await actions.archive_messages(db, user_id, message_ids)
    elif action_type == "trash":
        await actions.trash_messages(db, user_id, message_ids)
    elif action_type == "move_to_folder":
        folder_id = (action.get("params") or {}).get("folder_id")
        if folder_id:
            await actions.move_messages(db, user_id, message_ids, uuid.UUID(str(folder_id)))
    else:
        logger.warning("Unknown rule action type %r, skipping", action_type)


async def apply_rules_to_new_messages(db: AsyncSession, account: Account, message_ids: list[int]) -> None:
    if not message_ids:
        return

    result = await db.execute(
        select(Rule).where(
            Rule.user_id == account.user_id,
            Rule.is_active.is_(True),
            or_(Rule.account_id.is_(None), Rule.account_id == account.id),
        ).order_by(Rule.priority, Rule.created_at)
    )
    rules = list(result.scalars())
    if not rules:
        return

    result = await db.execute(select(Message).where(Message.id.in_(message_ids)))
    messages = {m.id: m for m in result.scalars()}
    if not messages:
        return

    for rule in rules:
        matched_ids = [mid for mid, m in messages.items() if rule_matches(m, rule)]
        if not matched_ids:
            continue
        for action in rule.actions or []:
            try:
                await _apply_action(db, account.user_id, matched_ids, action)
            except Exception:
                # A message a prior action in this same pass already moved
                # (deleted-and-recreated under a new id, see models/rule.py)
                # makes the next action on it a harmless not-found no-op via
                # actions.py's own per-message error reporting -- this catch
                # is for anything less expected, so one bad rule/action
                # can't take the rest of the sync pass down with it.
                logger.exception("Rule %s action %r failed for messages %s", rule.id, action, matched_ids)
