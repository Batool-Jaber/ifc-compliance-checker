"""
admin/services/proposal_service.py
====================================
All proposal-related business logic lives here -- not in the route
handlers -- so routes/conditions.py and routes/proposals.py stay thin
HTTP layers: parse the request, call one of these functions, flash +
redirect.

`approve_proposal()` is the ONLY function in the whole codebase allowed
to write into `Condition`. Both the "new condition" path and the "edit
existing condition" path funnel through it, and both log every changed
field to `AuditLog` via the same helper -- so the two flows can never
produce a differently-shaped audit trail.

REOPEN WORKFLOW (NEW -- see admin/models.py's module docstring for the
full design rationale):
  - reopen_proposal() NEVER edits a rejected proposal in place. It
    creates a brand new ConditionProposal row, copying the proposed
    values, status back to "pending". The original rejected row is
    never touched again.
  - edit_reopened_proposal() is the ONLY way an engineer can edit a
    proposal's proposed values directly -- and ONLY for a proposal
    that is both still "pending" AND was itself created via
    reopen_proposal() (reopened_from_id is not None). This is a
    deliberate restriction: editing an ordinary first-time "pending"
    proposal is NOT allowed, to avoid a race condition where an
    engineer changes values while an admin is actively reviewing or
    testing the original submission. Both conditions are re-checked
    here, server-side -- never trust that the UI only shows the edit
    option when appropriate.
  - edit_review_note() is unrelated to the above -- it edits the
    review_note on an ALREADY-DECIDED proposal (approved or rejected),
    and logs the edit to ProposalNoteEditLog (a small, separate table
    from AuditLog -- see admin/models.py's docstring for why).
"""

import re
from datetime import datetime, timezone

from admin.extensions import db
from admin.models import (
    AuditLog,
    Condition,
    ConditionProposal,
    ProposalNoteEditLog,
    ProposalStatus,
    ProposalType,
    User,
)
from admin.services.validation import validate_condition_values

# field_path added -- tracked/audited exactly like the other fields
# (description, type, threshold, etc.)
_TRACKED_FIELDS = ("description", "type", "threshold", "min_value", "max_value", "unit", "field_path")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------
# Creating proposals
# ---------------------------------------------------------------------

def create_edit_proposal(
    *,
    condition: Condition,
    submitted_by: User,
    description: str,
    condition_type: str,
    threshold: float | None,
    min_value: float | None,
    max_value: float | None,
    unit: str,
    field_path: str | None = None,
) -> ConditionProposal:
    """`condition_type` is passed in as the condition's EXISTING type --
    this flow doesn't let an engineer change minimum<->range, only the
    numeric values/description/unit/field_path of the existing type."""
    validate_condition_values(
        condition_type,
        threshold=threshold,
        min_value=min_value,
        max_value=max_value,
        unit=unit,
        description=description,
        field_path=field_path,
    )

    proposal = ConditionProposal(
        condition_id=condition.id,
        proposal_type=ProposalType.EDIT.value,
        proposed_description=description,
        proposed_type=condition_type,
        proposed_threshold=threshold,
        proposed_min=min_value,
        proposed_max=max_value,
        proposed_unit=unit,
        proposed_field_path=field_path,
        submitted_by=submitted_by.id,
    )
    db.session.add(proposal)
    db.session.commit()
    return proposal


def create_new_proposal(
    *,
    submitted_by: User,
    title: str,
    description: str,
    condition_type: str,
    threshold: float | None,
    min_value: float | None,
    max_value: float | None,
    unit: str,
    field_path: str,
) -> ConditionProposal:
    validate_condition_values(
        condition_type,
        threshold=threshold,
        min_value=min_value,
        max_value=max_value,
        unit=unit,
        description=description,
        field_path=field_path,
    )

    proposal = ConditionProposal(
        condition_id=None,  # no existing condition yet -- this IS the new one
        proposal_type=ProposalType.NEW.value,
        proposed_title=title,
        proposed_description=description,
        proposed_type=condition_type,
        proposed_threshold=threshold,
        proposed_min=min_value,
        proposed_max=max_value,
        proposed_unit=unit,
        proposed_field_path=field_path,
        submitted_by=submitted_by.id,
    )
    db.session.add(proposal)
    db.session.commit()
    return proposal


# ---------------------------------------------------------------------
# Approving / rejecting a pending proposal
# ---------------------------------------------------------------------

def approve_proposal(
    *, proposal: ConditionProposal, reviewed_by: User, review_note: str | None = None
) -> Condition:
    if proposal.status != ProposalStatus.PENDING.value:
        raise ValueError("Only a pending proposal can be approved.")

    if proposal.proposal_type == ProposalType.NEW.value:
        condition = _create_condition_from_proposal(proposal)
        old_values = {field: None for field in _TRACKED_FIELDS}
    else:
        condition = proposal.condition
        old_values = _condition_field_values(condition)
        _apply_proposed_values(condition, proposal, reviewed_by)

    _log_field_changes(
        condition,
        old_values=old_values,
        new_values=_condition_field_values(condition),
        reviewed_by=reviewed_by,
        proposal=proposal,
    )

    proposal.status = ProposalStatus.APPROVED.value
    proposal.reviewed_by = reviewed_by.id
    proposal.reviewed_at = _utcnow()
    proposal.review_note = review_note

    db.session.commit()
    return condition


def reject_proposal(
    *, proposal: ConditionProposal, reviewed_by: User, review_note: str | None = None
) -> None:
    if proposal.status != ProposalStatus.PENDING.value:
        raise ValueError("Only a pending proposal can be rejected.")

    proposal.status = ProposalStatus.REJECTED.value
    proposal.reviewed_by = reviewed_by.id
    proposal.reviewed_at = _utcnow()
    proposal.review_note = review_note
    db.session.commit()


# ---------------------------------------------------------------------
# Editing a review note AFTER a final decision (NEW)
# ---------------------------------------------------------------------

def edit_review_note(
    *, proposal: ConditionProposal, edited_by: User, new_note: str | None
) -> None:
    """
    Edits review_note on a proposal that already has a FINAL decision
    (approved or rejected). Logs the change to ProposalNoteEditLog --
    a separate, small table from AuditLog (see admin/models.py's
    docstring for why).
    """
    if proposal.status == ProposalStatus.PENDING.value:
        raise ValueError("This proposal hasn't been reviewed yet -- there's no decision note to edit.")

    old_note = proposal.review_note
    if old_note == new_note:
        return  # nothing actually changed -- don't write a no-op log entry

    db.session.add(
        ProposalNoteEditLog(
            proposal_id=proposal.id,
            edited_by=edited_by.id,
            old_note=old_note,
            new_note=new_note,
        )
    )
    proposal.review_note = new_note
    db.session.commit()


# ---------------------------------------------------------------------
# Reopening a rejected proposal (NEW)
# ---------------------------------------------------------------------

def reopen_proposal(*, proposal: ConditionProposal, reopened_by: User) -> ConditionProposal:
    """
    Creates a BRAND NEW ConditionProposal row, copying every proposed
    value from `proposal`, with status reset to "pending". The
    original `proposal` (must be "rejected") is NEVER modified --
    it stays a permanent, unaltered historical record. See
    admin/models.py's docstring for the full rationale.
    """
    if proposal.status != ProposalStatus.REJECTED.value:
        raise ValueError("Only a rejected proposal can be reopened.")

    new_proposal = ConditionProposal(
        condition_id=proposal.condition_id,
        proposal_type=proposal.proposal_type,
        proposed_title=proposal.proposed_title,
        proposed_description=proposal.proposed_description,
        proposed_type=proposal.proposed_type,
        proposed_threshold=proposal.proposed_threshold,
        proposed_min=proposal.proposed_min,
        proposed_max=proposal.proposed_max,
        proposed_unit=proposal.proposed_unit,
        proposed_field_path=proposal.proposed_field_path,
        status=ProposalStatus.PENDING.value,
        submitted_by=proposal.submitted_by,  # same engineer, unchanged
        reopened_from_id=proposal.id,
        reopened_by=reopened_by.id,
        reopened_at=_utcnow(),
        engineer_notified_of_reopen=True,
    )
    db.session.add(new_proposal)
    db.session.commit()
    return new_proposal


def edit_reopened_proposal(
    *,
    proposal: ConditionProposal,
    submitted_by: User,
    description: str,
    condition_type: str,
    threshold: float | None,
    min_value: float | None,
    max_value: float | None,
    unit: str,
    field_path: str | None,
    title: str | None = None,
) -> None:
    """
    Lets an engineer edit the proposed values of a proposal IN PLACE --
    but ONLY when ALL of these hold, re-checked here server-side
    (never trust that the UI only shows the edit option when
    appropriate):
      - proposal.reopened_from_id is not None (it was created via
        reopen_proposal(), not an ordinary first-time proposal), AND
      - proposal.status == "pending" (no decision has been made on
        THIS reopened attempt yet), AND
      - proposal.submitted_by == submitted_by.id (only the engineer
        who owns this proposal can edit it).

    This is deliberately NOT allowed for an ordinary first-time pending
    proposal -- see module docstring's "REOPEN WORKFLOW" note for why
    (race condition with an admin actively reviewing/testing it).

    No audit/log entry is written here -- this is still a draft under
    review, not an audited final decision (contrast with
    edit_review_note(), which IS logged).
    """
    if proposal.reopened_from_id is None:
        raise ValueError("Only a reopened proposal can be edited directly -- not an ordinary pending proposal.")
    if proposal.status != ProposalStatus.PENDING.value:
        raise ValueError("This proposal has already received a new decision and can no longer be edited.")
    if proposal.submitted_by != submitted_by.id:
        raise ValueError("You can only edit your own proposals.")

    validate_condition_values(
        condition_type,
        threshold=threshold,
        min_value=min_value,
        max_value=max_value,
        unit=unit,
        description=description,
        field_path=field_path,
    )

    if proposal.proposal_type == ProposalType.NEW.value and title is not None:
        proposal.proposed_title = title
    proposal.proposed_description = description
    proposal.proposed_type = condition_type
    proposal.proposed_threshold = threshold
    proposal.proposed_min = min_value
    proposal.proposed_max = max_value
    proposal.proposed_unit = unit
    proposal.proposed_field_path = field_path

    db.session.commit()


# ---------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------

def _condition_field_values(condition: Condition) -> dict:
    return {field: getattr(condition, field) for field in _TRACKED_FIELDS}


def _apply_proposed_values(condition: Condition, proposal: ConditionProposal, reviewed_by: User) -> None:
    condition.description = proposal.proposed_description
    condition.type = proposal.proposed_type
    condition.threshold = proposal.proposed_threshold
    condition.min_value = proposal.proposed_min
    condition.max_value = proposal.proposed_max
    condition.unit = proposal.proposed_unit
    condition.field_path = proposal.proposed_field_path
    condition.updated_at = _utcnow()
    condition.updated_by = reviewed_by.id


def _create_condition_from_proposal(proposal: ConditionProposal) -> Condition:
    condition = Condition(
        id=_unique_condition_id(proposal.proposed_title),
        title=proposal.proposed_title,
        description=proposal.proposed_description,
        type=proposal.proposed_type,
        threshold=proposal.proposed_threshold,
        min_value=proposal.proposed_min,
        max_value=proposal.proposed_max,
        unit=proposal.proposed_unit,
        field_path=proposal.proposed_field_path,
    )
    db.session.add(condition)
    db.session.flush()  # confirms condition.id before we link the proposal to it
    proposal.condition_id = condition.id
    return condition


def _log_field_changes(
    condition: Condition,
    *,
    old_values: dict,
    new_values: dict,
    reviewed_by: User,
    proposal: ConditionProposal,
) -> None:
    """Writes one AuditLog row per field that actually changed -- used
    for both "new" (old values all None) and "edit" proposals, so both
    produce the same audit trail shape."""
    for field in _TRACKED_FIELDS:
        old, new = old_values.get(field), new_values.get(field)
        if old == new:
            continue
        db.session.add(
            AuditLog(
                user_id=reviewed_by.id,
                condition_id=condition.id,
                proposal_id=proposal.id,
                field_changed=field,
                old_value=None if old is None else str(old),
                new_value=None if new is None else str(new),
            )
        )


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", title.strip().lower()).strip("_")
    return slug or "condition"


def _unique_condition_id(title: str) -> str:
    """Guards against two approved 'new condition' proposals producing
    the same slug (e.g. two titles that only differ by punctuation)."""
    base = _slugify(title)
    candidate = base
    suffix = 2
    while Condition.query.get(candidate) is not None:
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate