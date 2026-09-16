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
"""

import re
from datetime import datetime, timezone

from admin.extensions import db
from admin.models import (
    AuditLog,
    Condition,
    ConditionProposal,
    ProposalStatus,
    ProposalType,
    User,
)
from admin.services.validation import validate_condition_values

# NEW: field_path added -- tracked/audited exactly like the other
# fields (description, type, threshold, etc.)
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