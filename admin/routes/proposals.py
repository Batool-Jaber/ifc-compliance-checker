"""
admin/routes/proposals.py
===========================
admin:    /admin/proposals      -- review every pending proposal, approve/reject
engineer: /admin/my-proposals   -- track the status of proposals they submitted

The actual "apply values to Condition + write AuditLog" logic lives in
services/proposal_service.py -- this module only handles HTTP concerns
(load the row, check it's still pending, call the service, flash + redirect).

REOPEN WORKFLOW (NEW -- see admin/models.py and proposal_service.py for
the full design): reopening creates a brand-new proposal row rather
than editing the rejected one in place. Editing a reopened proposal's
VALUES is only ever allowed through edit_reopened_proposal_route()
below, which re-checks ownership + status server-side even though the
template only shows the "Edit" link when appropriate.
"""

from flask import flash, redirect, render_template, request, url_for

from admin import admin_bp
from admin.decorators import get_current_user, role_required
from admin.extensions import db
from admin.models import Condition, ConditionProposal, ConditionType, ProposalStatus, ProposalType, Role
from admin.services import proposal_service
from admin.services.validation import ValidationError, parse_optional_float
from validation.field_paths import KNOWN_FIELD_PATHS


@admin_bp.route("/proposals")
@role_required(Role.ADMIN.value)
def proposals_list():
    pending = (
        ConditionProposal.query.filter_by(status=ProposalStatus.PENDING.value)
        .order_by(ConditionProposal.submitted_at.asc())
        .all()
    )
    decided = (
        ConditionProposal.query.filter(ConditionProposal.status != ProposalStatus.PENDING.value)
        .order_by(ConditionProposal.reviewed_at.desc())
        .limit(20)
        .all()
    )
    return render_template("admin/proposals.html", pending=pending, decided=decided)


@admin_bp.route("/proposals/<int:proposal_id>/approve", methods=["POST"])
@role_required(Role.ADMIN.value)
def approve_proposal(proposal_id):
    proposal = ConditionProposal.query.get_or_404(proposal_id)
    if proposal.status != ProposalStatus.PENDING.value:
        flash("This proposal has already been reviewed.", "error")
        return redirect(url_for("admin.proposals_list"))

    note = request.form.get("review_note", "").strip() or None
    condition = proposal_service.approve_proposal(
        proposal=proposal, reviewed_by=get_current_user(), review_note=note
    )
    flash(f"Approved — '{condition.title}' is now live.", "success")
    return redirect(url_for("admin.proposals_list"))


@admin_bp.route("/proposals/<int:proposal_id>/reject", methods=["POST"])
@role_required(Role.ADMIN.value)
def reject_proposal(proposal_id):
    proposal = ConditionProposal.query.get_or_404(proposal_id)
    if proposal.status != ProposalStatus.PENDING.value:
        flash("This proposal has already been reviewed.", "error")
        return redirect(url_for("admin.proposals_list"))

    note = request.form.get("review_note", "").strip() or None
    proposal_service.reject_proposal(
        proposal=proposal, reviewed_by=get_current_user(), review_note=note
    )
    flash("Proposal rejected.", "success")
    return redirect(url_for("admin.proposals_list"))


@admin_bp.route("/proposals/<int:proposal_id>/edit-note", methods=["POST"])
@role_required(Role.ADMIN.value)
def edit_proposal_note(proposal_id):
    """Edit review_note on an already-decided (approved/rejected)
    proposal. Logged to ProposalNoteEditLog -- see proposal_service.py."""
    proposal = ConditionProposal.query.get_or_404(proposal_id)
    new_note = request.form.get("review_note", "").strip() or None

    try:
        proposal_service.edit_review_note(
            proposal=proposal, edited_by=get_current_user(), new_note=new_note
        )
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("admin.proposals_list"))

    flash("Note updated.", "success")
    return redirect(url_for("admin.proposals_list"))


@admin_bp.route("/proposals/<int:proposal_id>/reopen", methods=["POST"])
@role_required(Role.ADMIN.value)
def reopen_proposal_route(proposal_id):
    """Creates a brand-new pending proposal from a rejected one -- the
    original rejected row is never modified. See proposal_service.py."""
    proposal = ConditionProposal.query.get_or_404(proposal_id)

    try:
        new_proposal = proposal_service.reopen_proposal(
            proposal=proposal, reopened_by=get_current_user()
        )
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("admin.proposals_list"))

    flash(f"Reopened as proposal #{new_proposal.id} — the engineer can now edit and resubmit it.", "success")
    return redirect(url_for("admin.proposals_list"))


@admin_bp.route("/my-proposals")
@role_required(Role.ENGINEER.value)
def my_proposals():
    current = get_current_user()
    proposals = (
        ConditionProposal.query.filter_by(submitted_by=current.id)
        .order_by(ConditionProposal.submitted_at.desc())
        .all()
    )

    # Clear the "unseen reopen" flag now that the engineer is looking
    # at this page -- simple "seen it" marker, not a full notifications
    # system (see admin/models.py's docstring).
    unseen = [p for p in proposals if p.engineer_notified_of_reopen]
    if unseen:
        for p in unseen:
            p.engineer_notified_of_reopen = False
        db.session.commit()

    return render_template("admin/my_proposals.html", proposals=proposals)


@admin_bp.route("/my-proposals/<int:proposal_id>/edit", methods=["GET", "POST"])
@role_required(Role.ENGINEER.value)
def edit_reopened_proposal_route(proposal_id):
    """
    Lets the OWNING engineer edit a reopened proposal's proposed values
    directly, instead of resubmitting from scratch. Only ever valid for
    a proposal created via reopen_proposal() (reopened_from_id set)
    that is still "pending" and belongs to the current user -- all
    three re-checked server-side in proposal_service.py, not just
    gated here by which links the template happens to show.
    """
    proposal = ConditionProposal.query.get_or_404(proposal_id)
    current = get_current_user()

    # Defense-in-depth at the route layer too, before even rendering
    # the form -- the service layer re-checks this again on submit.
    if proposal.reopened_from_id is None or proposal.submitted_by != current.id:
        flash("You can't edit this proposal.", "error")
        return redirect(url_for("admin.my_proposals"))
    if proposal.status != ProposalStatus.PENDING.value:
        flash("This proposal has already received a new decision and can no longer be edited.", "error")
        return redirect(url_for("admin.my_proposals"))

    if request.method == "GET":
        return render_template(
            "admin/proposal_edit_reopened.html",
            proposal=proposal,
            ConditionType=ConditionType,
            field_paths=KNOWN_FIELD_PATHS,
        )

    try:
        title = request.form.get("title", "").strip() if proposal.proposal_type == ProposalType.NEW.value else None
        description = request.form.get("description", "").strip()
        condition_type = request.form.get("type", "").strip()
        unit = request.form.get("unit", "").strip()
        threshold = parse_optional_float(request.form.get("threshold"))
        min_value = parse_optional_float(request.form.get("min_value"))
        max_value = parse_optional_float(request.form.get("max_value"))
        field_path = request.form.get("field_path", "").strip() or None

        if field_path is not None and field_path not in KNOWN_FIELD_PATHS:
            raise ValidationError([f"'{field_path}' is not a recognized field to check against."])

        proposal_service.edit_reopened_proposal(
            proposal=proposal,
            submitted_by=current,
            title=title,
            description=description,
            condition_type=condition_type,
            threshold=threshold,
            min_value=min_value,
            max_value=max_value,
            unit=unit,
            field_path=field_path,
        )
    except (ValidationError, ValueError) as e:
        errors = e.errors if isinstance(e, ValidationError) else [str(e)]
        for msg in errors:
            flash(msg, "error")
        return render_template(
            "admin/proposal_edit_reopened.html",
            proposal=proposal,
            ConditionType=ConditionType,
            field_paths=KNOWN_FIELD_PATHS,
        ), 400

    flash("Proposal updated — it's ready for the admin to review again.", "success")
    return redirect(url_for("admin.my_proposals"))