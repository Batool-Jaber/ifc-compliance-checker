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

- `field_path`: which extracted IFC value (see
  validation/field_paths.py::KNOWN_FIELD_PATHS) this condition is
  checked against by the generic engine (validation/generic_engine.py).
  Nullable because the 3 ORIGINAL conditions don't use it -- they're
  evaluated by their own permanently-hardcoded functions in
  validation/deterministic_checks.py (check_room_area, etc.), not the
  generic engine. Every condition proposed through the admin panel
  going forward (routes/conditions.py::propose_new_condition) requires
  it -- enforced in services/validation.py, not at the DB level, since
  "required" depends on which condition this is, not a fixed rule.

- REOPEN WORKFLOW: a rejected proposal is NEVER edited in place.
  Reopening it (admin/services/proposal_service.py::reopen_proposal())
  creates a BRAND NEW ConditionProposal row, copying the proposed
  values, with status="pending" again. The original rejected row is
  never touched again -- it stays a permanent, immutable historical
  record. The new row links back via `reopened_from_id`, so the full
  chain (rejected #1 -> reopened as #2 -> approved/rejected) is always
  reconstructable without ever deleting or overwriting anything.
  `engineer_notified_of_reopen` is a simple "unseen" flag: set True
  when reopened, cleared to False the next time the submitting
  engineer's admin.routes.proposals::my_proposals() page loads -- no
  separate notifications system needed for this.

  A reopened proposal (status still "pending", reopened_from_id set)
  is the ONLY kind of proposal an engineer is allowed to edit directly
  in place (admin/services/proposal_service.py::edit_reopened_proposal())
  -- this is deliberately NOT allowed for an ordinary first-time
  "pending" proposal, to avoid a race condition where an engineer edits
  values while an admin is actively reviewing/testing the original
  submission.

- `ProposalNoteEditLog`: tracks edits to `review_note` made AFTER a
  proposal has already been approved or rejected (i.e. after a final
  decision). This is intentionally a SEPARATE, small table from
  `AuditLog` -- AuditLog tracks changes to a LIVE Condition's fields;
  this tracks changes to a review comment on a proposal, which may not
  even have an associated Condition (e.g. a rejected "new condition"
  proposal). Edits to a proposal's PROPOSED values before a decision
  is made (via edit_reopened_proposal(), reopened case only) are NOT
  logged here -- those are still a draft under review, not a final,
  audited decision.

- `UploadedDocument` (NEW): tracks every markdown knowledge-base file
  uploaded dynamically through the admin panel
  (rag/knowledge_upload.py), as opposed to the 4 original sources
  (building_conditions, engineer_guide, building_code,
  materials_register), each of which has its own hand-written
  sync_*() function in rag/migrate_to_chroma.py. This row is the ONLY
  durable record of "what dynamic sources exist" -- same "zero silent
  data loss" principle as AuditLog/ProposalNoteEditLog.
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

    id = db.Column(db.String(64), primary_key=True)
    title = db.Column(db.String(200), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=False)
    type = db.Column(db.String(20), nullable=False)  # "minimum" | "range"

    threshold = db.Column(db.Float, nullable=True)   # used when type == "minimum"
    min_value = db.Column(db.Float, nullable=True)   # used when type == "range"
    max_value = db.Column(db.Float, nullable=True)   # used when type == "range"
    unit = db.Column(db.String(20), nullable=False)

    field_path = db.Column(db.String(100), nullable=True)

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

    See module docstring's "REOPEN WORKFLOW" note for reopened_from_id /
    reopened_by / reopened_at / engineer_notified_of_reopen.
    """

    __tablename__ = "condition_proposals"

    id = db.Column(db.Integer, primary_key=True)

    condition_id = db.Column(db.String(64), db.ForeignKey("conditions.id"), nullable=True)
    proposal_type = db.Column(db.String(10), nullable=False)  # "new" | "edit"

    proposed_title = db.Column(db.String(200), nullable=True)  # only used for "new"
    proposed_description = db.Column(db.Text, nullable=True)
    proposed_type = db.Column(db.String(20), nullable=True)
    proposed_threshold = db.Column(db.Float, nullable=True)
    proposed_min = db.Column(db.Float, nullable=True)
    proposed_max = db.Column(db.Float, nullable=True)
    proposed_unit = db.Column(db.String(20), nullable=True)
    proposed_field_path = db.Column(db.String(100), nullable=True)

    status = db.Column(db.String(10), nullable=False, default=ProposalStatus.PENDING.value)

    submitted_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    submitted_at = db.Column(db.DateTime, nullable=False, default=_utcnow)

    reviewed_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    review_note = db.Column(db.Text, nullable=True)

    reopened_from_id = db.Column(
        db.Integer, db.ForeignKey("condition_proposals.id"), nullable=True
    )
    reopened_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    reopened_at = db.Column(db.DateTime, nullable=True)
    engineer_notified_of_reopen = db.Column(db.Boolean, nullable=False, default=False)

    condition = db.relationship("Condition", back_populates="proposals")
    reopened_from = db.relationship(
        "ConditionProposal", remote_side=[id], foreign_keys=[reopened_from_id]
    )

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


class ProposalNoteEditLog(db.Model):
    """
    Tracks edits made to a proposal's `review_note` AFTER a final
    decision (approved/rejected) has already been recorded -- see
    module docstring for why this is separate from AuditLog.

    Does NOT track edits to a reopened proposal's proposed VALUES
    (title/threshold/etc.) before a decision -- that's still a draft
    under review, not an audited final decision (see
    proposal_service.py::edit_reopened_proposal()).
    """

    __tablename__ = "proposal_note_edit_log"

    id = db.Column(db.Integer, primary_key=True)
    proposal_id = db.Column(
        db.Integer, db.ForeignKey("condition_proposals.id"), nullable=False
    )
    edited_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    edited_at = db.Column(db.DateTime, nullable=False, default=_utcnow)

    old_note = db.Column(db.Text, nullable=True)
    new_note = db.Column(db.Text, nullable=True)

    proposal = db.relationship("ConditionProposal", foreign_keys=[proposal_id])
    editor = db.relationship("User", foreign_keys=[edited_by])

    def __repr__(self) -> str:
        return f"<ProposalNoteEditLog #{self.id} on proposal #{self.proposal_id}>"


class UploadedDocument(db.Model):
    """
    Tracks every markdown knowledge-base file uploaded dynamically
    through the admin panel (rag/knowledge_upload.py), as opposed to
    the 4 original sources (building_conditions, engineer_guide,
    building_code, materials_register), each of which has its own
    hand-written sync_*() function in rag/migrate_to_chroma.py.

    This row is the ONLY durable record of "what dynamic sources exist"
    -- without it, a full re-sync of the unified Chroma collection
    (if it were ever rebuilt from scratch) would silently lose any
    admin-uploaded source, since there'd be no fixed function anywhere
    in the codebase that knows to re-read it. Same "zero silent data
    loss" principle as AuditLog/ProposalNoteEditLog.

    `file_path` points to the raw .md file saved to disk (see
    rag/knowledge_upload.py) -- the uploaded file itself is kept
    permanently, not just its chunked/embedded form in Chroma, for the
    same re-sync-from-scratch reason above.

    `split_mode` and `audience_role` are the two choices the admin
    makes at upload time (see rag/knowledge_upload.py) -- stored here
    so a future re-sync knows exactly how to re-chunk this file without
    the admin re-entering that choice.
    """

    __tablename__ = "uploaded_documents"

    id = db.Column(db.Integer, primary_key=True)

    source_name = db.Column(db.String(100), unique=True, nullable=False)

    original_filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)

    split_mode = db.Column(db.String(20), nullable=False)  # "single_level" | "two_level"
    audience_role = db.Column(db.String(20), nullable=False)  # "engineer" | "admin" | "all"

    chunk_count = db.Column(db.Integer, nullable=False)

    uploaded_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    uploaded_at = db.Column(db.DateTime, nullable=False, default=_utcnow)

    uploader = db.relationship("User", foreign_keys=[uploaded_by])

    __table_args__ = (
        db.CheckConstraint(
            "split_mode IN ('single_level', 'two_level')", name="ck_uploaded_docs_split_mode_valid"
        ),
        db.CheckConstraint(
            "audience_role IN ('engineer', 'admin', 'all')", name="ck_uploaded_docs_audience_role_valid"
        ),
    )

    def __repr__(self) -> str:
        return f"<UploadedDocument {self.source_name} ({self.chunk_count} chunks)>"