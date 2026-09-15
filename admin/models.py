"""
admin/models.py
================
SQLAlchemy models for the admin / role-management system.

Design notes
------------
- `Condition.title` is intentionally the ONLY title-like column -- no
  parallel "display title". It is treated as immutable once a condition
  exists. Enforcement is deliberately two-layered:
    1. UI layer:      the edit form never renders it as an <input>.
    2. Server layer:  services/validation.py::reject_title_change()
                       rejects any request payload that tries to change
                       it, even a hand-crafted one.
  See routes/conditions.py for where both layers are wired in.

- Proposed changes NEVER touch `Condition` directly. An engineer's
  edit or new-condition request lives in `ConditionProposal` with
  status="pending" until an admin acts on it. The one and only place
  in the codebase allowed to write approved values into `Condition`
  is services/proposal_service.py::approve_proposal() -- keeping that
  logic in one spot is what makes "old value stays live until approved"
  safe to reason about.

- `AuditLog.user_id` records the ADMIN whose approval made a change
  live (the person who caused the write). To see WHO ORIGINALLY
  PROPOSED it -- e.g. to answer "which engineers touched this rule and
  when" -- join through `AuditLog.proposal_id -> ConditionProposal.
  submitted_by`. `Condition.proposals` also gives the full proposal
  history (approved, rejected, and pending) for a given condition on
  its own, without needing the audit log at all.
"""

from datetime import datetime, timezone
from enum import Enum

from admin.extensions import db


def _utcnow() -> datetime:
    """Timezone-aware UTC 'now', used as the default for every timestamp
    column so audit ordering is never ambiguous across DST/local time."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------
# Enums (kept as plain str-Enums, NOT separate DB tables -- there are
# exactly 3 roles / 2 condition types / 2 proposal types / 3 statuses,
# all fixed by the agreed design. A CheckConstraint on each column
# enforces the same set of values at the database level too, so an
# invalid value can't sneak in even via a raw query.)
# ---------------------------------------------------------------------

class Role(str, Enum):
    ADMIN = "admin"
    ENGINEER = "engineer"
    VIEWER = "viewer"

    @classmethod
    def values(cls) -> list[str]:
        return [r.value for r in cls]


class ConditionType(str, Enum):
    MINIMUM = "minimum"
    RANGE = "range"

    @classmethod
    def values(cls) -> list[str]:
        return [t.value for t in cls]


class ProposalType(str, Enum):
    NEW = "new"
    EDIT = "edit"

    @classmethod
    def values(cls) -> list[str]:
        return [t.value for t in cls]


class ProposalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

    @classmethod
    def values(cls) -> list[str]:
        return [s.value for s in cls]


# ---------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------

class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)

    proposals_submitted = db.relationship(
        "ConditionProposal",
        foreign_keys="ConditionProposal.submitted_by",
        backref="submitter",
        lazy="dynamic",
    )
    proposals_reviewed = db.relationship(
        "ConditionProposal",
        foreign_keys="ConditionProposal.reviewed_by",
        backref="reviewer",
        lazy="dynamic",
    )

    __table_args__ = (
        db.CheckConstraint(
            "role IN ('admin', 'engineer', 'viewer')", name="ck_users_role_valid"
        ),
    )

    def __repr__(self) -> str:
        return f"<User {self.username} ({self.role})>"


class Condition(db.Model):
    __tablename__ = "conditions"

    # String PK (e.g. "room_area") rather than an auto-increment int --
    # matches the existing app's convention of referring to conditions
    # by a short slug, and keeps ids stable/readable in the audit log.
    id = db.Column(db.String(64), primary_key=True)

    # PROTECTED -- see module docstring. Exactly one column, no legacy/
    # display-title duplicate.
    title = db.Column(db.String(200), unique=True, nullable=False)

    description = db.Column(db.Text, nullable=False)
    type = db.Column(db.String(20), nullable=False)  # "minimum" | "range"

    threshold = db.Column(db.Float, nullable=True)   # used when type == "minimum"
    min_value = db.Column(db.Float, nullable=True)   # used when type == "range"
    max_value = db.Column(db.Float, nullable=True)   # used when type == "range"
    unit = db.Column(db.String(20), nullable=False)

    updated_at = db.Column(db.DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    updater = db.relationship("User", foreign_keys=[updated_by])
    proposals = db.relationship(
        "ConditionProposal",
        back_populates="condition",
        lazy="dynamic",
        order_by="ConditionProposal.submitted_at.desc()",
    )

    __table_args__ = (
        db.CheckConstraint("type IN ('minimum', 'range')", name="ck_conditions_type_valid"),
    )

    def __repr__(self) -> str:
        return f"<Condition {self.id}: {self.title}>"


class ConditionProposal(db.Model):
    """
    An engineer's request to create a new condition or change an
    existing one. Nothing here is "live" until an admin approves it.
    """

    __tablename__ = "condition_proposals"

    id = db.Column(db.Integer, primary_key=True)

    # Nullable: a "new condition" proposal has no existing condition to
    # point to yet.
    condition_id = db.Column(db.String(64), db.ForeignKey("conditions.id"), nullable=True)
    proposal_type = db.Column(db.String(10), nullable=False)  # "new" | "edit"

    # Proposed values. For "edit" the form pre-fills these with the
    # condition's current values so the diff is explicit; for "new",
    # all of these except proposed_title are effectively required
    # (enforced in services/validation.py, not at the DB level, since
    # which fields are required depends on proposed_type: "minimum" vs
    # "range").
    proposed_title = db.Column(db.String(200), nullable=True)  # only used for "new"
    proposed_description = db.Column(db.Text, nullable=True)
    proposed_type = db.Column(db.String(20), nullable=True)
    proposed_threshold = db.Column(db.Float, nullable=True)
    proposed_min = db.Column(db.Float, nullable=True)
    proposed_max = db.Column(db.Float, nullable=True)
    proposed_unit = db.Column(db.String(20), nullable=True)

    status = db.Column(db.String(10), nullable=False, default=ProposalStatus.PENDING.value)

    submitted_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    submitted_at = db.Column(db.DateTime, nullable=False, default=_utcnow)

    reviewed_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    review_note = db.Column(db.Text, nullable=True)

    condition = db.relationship("Condition", back_populates="proposals")

    __table_args__ = (
        db.CheckConstraint("proposal_type IN ('new', 'edit')", name="ck_proposals_type_valid"),
        db.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')", name="ck_proposals_status_valid"
        ),
    )

    def __repr__(self) -> str:
        return f"<ConditionProposal #{self.id} ({self.proposal_type}, {self.status})>"


class AuditLog(db.Model):
    __tablename__ = "audit_log"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    condition_id = db.Column(db.String(64), db.ForeignKey("conditions.id"), nullable=False)

    # Traceability back to the proposal that produced this row -- lets
    # the audit log page show "proposed by X on <date>, approved by Y
    # on <date>" in one query instead of guessing.
    proposal_id = db.Column(
        db.Integer, db.ForeignKey("condition_proposals.id"), nullable=True
    )

    field_changed = db.Column(db.String(50), nullable=False)
    old_value = db.Column(db.Text, nullable=True)
    new_value = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, nullable=False, default=_utcnow)

    user = db.relationship("User", foreign_keys=[user_id])
    condition = db.relationship("Condition", foreign_keys=[condition_id])
    proposal = db.relationship("ConditionProposal", foreign_keys=[proposal_id])

    def __repr__(self) -> str:
        return f"<AuditLog #{self.id} {self.field_changed}: {self.old_value} -> {self.new_value}>"