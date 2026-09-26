"""
admin/routes/proposals.py
===========================
admin:    /admin/proposals      -- review every pending proposal, approve/reject
engineer: /admin/my-proposals   -- track the status of proposals they submitted

The actual "apply values to Condition + write AuditLog" logic lives in
services/proposal_service.py -- this module only handles HTTP concerns
(load the row, check it's still pending, call the service, flash + redirect).

REOPEN WORKFLOW: reopening creates a brand-new proposal row rather
than editing the rejected one in place. Editing a reopened proposal's
VALUES is only ever allowed through edit_reopened_proposal_route()
below, which re-checks ownership + status server-side even though the
template only shows the "Edit" link when appropriate.

SAFE TESTER: test_proposal_route() is READ-ONLY -- it never calls
db.session.commit(), never touches `proposal.status` or any
`Condition` row. It generates a sample IFC model into its OWN separate
temp path (TEST_IFC_OUTPUT_PATH), never into
data/generated/compliant_model.ifc/violation_model.ifc/
missing_data_model.ifc -- so testing a proposal can never corrupt the
file the main Compliance Checker tool is using for a real check
happening at the same time.

BUILDING CODE ADVISORY (NEW): check_building_code_route() is ALSO
READ-ONLY and purely informational -- it queries the unified Chroma
store (rag/vector_db.py) for building_code articles related to this
proposal, and returns raw article text (never LLM-rephrased -- a
regulation's literal wording is the authoritative reference). This
NEVER blocks, influences, or auto-decides Approve/Reject in any way;
the frontend must visually label it "Advisory only".
"""

from flask import flash, jsonify, redirect, render_template, request, url_for

from admin import admin_bp
from admin.decorators import get_current_user, role_required
from admin.extensions import db
from admin.models import Condition, ConditionProposal, ConditionType, ProposalStatus, ProposalType, Role
from admin.services import proposal_service
from admin.services.validation import ValidationError, parse_optional_float
from validation.field_paths import KNOWN_FIELD_PATHS
from extract_ifc_data import extract_all
from generate_ifc import generate_model
from validation.deterministic_checks import run_all_checks
from main import CONDITION_TO_QUERY  # only used to identify "one of the original 3" by title -- no other coupling
from rag.vector_db import search as unified_search

# Mirrors app.py::SCENARIO_PARAMS exactly. Duplicated here (not
# imported from app.py) to avoid a circular import: app.py imports
# `admin`, which imports THIS module at package-init time, before
# app.py's own SCENARIO_PARAMS has been defined yet.
TEST_SCENARIO_PARAMS = {
    "compliant": {},
    "violation": {"room_width": 3.0, "room_length": 3.0},
    "missing_data": {"missing_data": True},
}

# A dedicated path, separate from the 3 canonical scenario files the
# main Compliance Checker tool reads/writes -- see module docstring.
TEST_IFC_OUTPUT_PATH = "data/generated/_proposal_test_tmp.ifc"

# NOTE: this threshold is a PLACEHOLDER, UNTESTED against real
# condition<->article pairs -- unlike help.py's CONFIDENCE_THRESHOLD
# (tuned on 12 real questions), this value has had ZERO real
# calibration yet. It is deliberately LOWER than 0.52 as a starting
# guess (regulatory article text vs. a condition's title+description
# is a different matching scenario than free-form engineer questions
# vs. a help guide).
#
# CAVEAT (2nd tier, more serious than the Help Assistant's own
# threshold caveat): a confirmed RANKING-QUALITY gap exists, not just
# a threshold-tuning gap. Real test case: query "Wheelchair Turning
# Space Near Doors... open floor space on both sides of an entry point
# for someone using a mobility device" -- Article 8.2 (the genuinely
# correct match, containing near-identical wording about manoeuvring
# space on both sides of an accessible door) scored 0.4319 and ranked
# #3, BELOW Article 8.5 (about lifts -- topically related but NOT the
# right answer) at 0.5031, rank #1. Raising the threshold alone cannot
# fix this: it would suppress the wrong (8.5) result for this specific
# query, but the CORRECT result (8.2) is itself below threshold, so
# the admin would see NOTHING instead of the right article -- silent
# omission, not silent error, but still a real gap for a compliance
# tool. This is the same class of semantic-similarity confusion
# documented for help.py's CONFIDENCE_THRESHOLD (the "known retrieval-
# quality limitation" there), surfacing here in a different context.
#
# PRE-COMMERCIAL-USE REQUIREMENT (not a "nice to have" future
# improvement -- a hard blocker before this feature is used for any
# real paid compliance decision, not just a portfolio/demo context):
# before this tool is used to inform an actual building-compliance
# decision for a real client, EITHER (a) switch this feature to show
# ALL top-N results unfiltered with visible scores -- no silent
# hiding, the admin judges relevance themselves -- OR (b) implement
# and validate a real retrieval-quality fix (hybrid search /
# re-ranking, tracked separately under this project's "RAG
# differentiation" backlog item). In ADDITION to either fix, mandatory
# human legal/engineering review is required regardless of what this
# tool surfaces -- no RAG system, however accurate, should be the sole
# reference for a real building-compliance decision. This threshold
# value (0.45) and this feature's current filtered-display design are
# acceptable ONLY for a portfolio/demo context, not for production use
# with real compliance stakes.
BUILDING_CODE_ADVISORY_THRESHOLD = 0.45


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


@admin_bp.route("/proposals/<int:proposal_id>/test", methods=["POST"])
@role_required(Role.ADMIN.value)
def test_proposal_route(proposal_id):
    """
    READ-ONLY preview: "what would happen to every condition's PASS/
    FAIL/CANNOT_BE_EVALUATED if this proposal were approved?" -- run
    against a sample IFC model the admin picks (same 3 scenarios as
    the main Compliance Checker tool).

    GUARANTEED READ-ONLY, explicitly:
    - No db.session.add()/commit() anywhere in this function or in
      proposal_service.build_test_condition_set().
    - proposal.status and every Condition row are left completely
      untouched.
    - The generated IFC model is written to TEST_IFC_OUTPUT_PATH, a
      path SEPARATE from the 3 canonical scenario files -- see module
      docstring.
    """
    proposal = ConditionProposal.query.get_or_404(proposal_id)
    scenario = request.form.get("scenario", "compliant")

    if scenario not in TEST_SCENARIO_PARAMS:
        return jsonify({"error": f"Unknown scenario '{scenario}'"}), 400

    try:
        generate_model(output_path=TEST_IFC_OUTPUT_PATH, **TEST_SCENARIO_PARAMS[scenario])
        extracted = extract_all(TEST_IFC_OUTPUT_PATH)
    except Exception as e:
        return jsonify({"error": f"Failed to generate/extract test model: {e}"}), 500

    hypothetical_conditions = proposal_service.build_test_condition_set(proposal)

    extra_conditions = [
        c for c in hypothetical_conditions
        if c.get("field_path") and c["title"] not in CONDITION_TO_QUERY
    ]
    by_title = {c["title"]: c for c in hypothetical_conditions}
    room_area_cond = by_title.get("Minimum Room Area")
    window_area_cond = by_title.get("Minimum Window Area")
    sill_height_cond = by_title.get("Window Sill Height")

    results = run_all_checks(
        extracted["room"], extracted["window"], extra_conditions,
        room_area_min=room_area_cond["threshold"] if room_area_cond else None,
        window_ratio_min=window_area_cond["threshold"] if window_area_cond else None,
        sill_height_min=sill_height_cond["min_value"] if sill_height_cond else None,
        sill_height_max=sill_height_cond["max_value"] if sill_height_cond else None,
    )

    overall = "PASS"
    statuses = [r["status"] for r in results]
    if "FAIL" in statuses:
        overall = "FAIL"
    elif "CANNOT_BE_EVALUATED" in statuses:
        overall = "CANNOT_BE_EVALUATED"

    return jsonify({"scenario": scenario, "results": results, "overall_result": overall})


@admin_bp.route("/proposals/<int:proposal_id>/check-code", methods=["POST"])
@role_required(Role.ADMIN.value)
def check_building_code_route(proposal_id):
    """
    READ-ONLY, purely advisory: searches the unified Chroma store
    (audience_role="admin" -- building_code content only, per its
    schema restriction) for regulation articles related to this
    proposal's title+description. Returns raw article text, NEVER an
    LLM-rephrased version -- a compliance-regulation's literal wording
    is the authoritative reference; rephrasing risks silently altering
    a precise legal qualifier (an exception clause, a specific number).

    This NEVER blocks or influences Approve/Reject in any way -- it's
    purely informational for the admin's own judgment, same as the
    Safe Tester above it. The frontend must visually label this
    "Advisory only" -- never presented as a compliance verdict.
    """
    proposal = ConditionProposal.query.get_or_404(proposal_id)

    if proposal.proposal_type == ProposalType.NEW.value:
        title = proposal.proposed_title
    else:
        title = proposal.condition.title
    description = proposal.proposed_description or ""

    query = f"{title}. {description}".strip()

    results = unified_search(query, top_k=3, audience_role="admin")
    # audience_role="admin" also returns "all"-scoped content (per
    # rag/vector_db.py's own $in filter) -- filter down to building_code
    # specifically here, since this feature is about regulations, not
    # building_conditions data that happens to also be admin-visible.
    matches = [r for r in results if r["metadata"].get("source") == "building_code"]
    matches = [r for r in matches if r["score"] >= BUILDING_CODE_ADVISORY_THRESHOLD]

    return jsonify({
        "matches": [
            {
                "article_number": m["metadata"].get("article_number"),
                "chapter_title": m["metadata"].get("chapter_title"),
                "title": m["title"],
                "text": m["text"],
                "score": round(m["score"], 4),
            }
            for m in matches
        ]
    })


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