import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class Rule(Base):
    """A mail filter rule (Phase 8): if all `conditions` match a newly
    synced message, all `actions` fire, in the order listed -- not
    first-match-wins, every active matching rule runs. Rules only ever see
    genuinely new incoming mail (services/mail/sync.py's forward-sync path),
    never a folder's initial-sync batch or backfilled history -- see
    services/mail/rules.py for where this actually gets invoked.

    `account_id` NULL means the rule applies across every account under
    this user; set means it's scoped to just that one account (required if
    any action is "move_to_folder", since a target folder only exists in
    one specific account).

    `conditions`: list of {"field": "from"|"to"|"cc"|"subject"|"body"|
    "has_attachment", "operator": "contains"|"not_contains"|"equals"|
    "starts_with"|"ends_with"|"matches_regex"|"is_true"|"is_false",
    "value": str}. ANDed together -- a rule with zero conditions matches
    nothing (never "matches everything") to avoid an accidental blanket rule.

    `actions`: list of {"type": "mark_read"|"mark_unread"|"star"|"unstar"|
    "archive"|"trash"|"move_to_folder", "params": {"folder_id": "..."} for
    move_to_folder, else {}}.
    """

    __tablename__ = "rules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Lower runs first. Matters mainly when two rules' actions could
    # conflict (e.g. both move the same message) -- only the first one to
    # actually execute has effect, since a message can only be in one
    # folder at a time and a move deletes+recreates its row under a new id.
    priority: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    conditions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    actions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
