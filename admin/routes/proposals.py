"""
admin/routes/proposals.py
===========================
admin:    /admin/proposals      -- review every pending proposal, approve/reject
engineer: /admin/my-proposals   -- track the status of proposals they submitted

The actual "apply values to Condition + write AuditLog" logic lives in
services/proposal_service.py -- this module only handles HTTP concerns
(load the row, check it's still pending, call the service, flash + redirect).
"""

from flask import flash, redirect, render_template, request, url_for

from admin import admin_bp
from admin.decorators import get_current_user, role_required
from admin.models import ConditionProposal, ProposalStatus, Role
from admin.services import proposal_service


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


@admin_bp.route("/my-proposals")
@role_required(Role.ENGINEER.value)
def my_proposals():
    current = get_current_user()
    proposals = (
        ConditionProposal.query.filter_by(submitted_by=current.id)
        .order_by(ConditionProposal.submitted_at.desc())
        .all()
    )
    return render_template("admin/my_proposals.html", proposals=proposals)