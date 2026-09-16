"""
admin/routes/conditions.py
===========================
Viewing conditions (all 3 roles, read-only for viewer) and proposing
new/edited conditions (engineer only). A proposal never touches
`Condition` directly -- see admin/services/proposal_service.py.
"""

from flask import flash, redirect, render_template, request, url_for

from admin import admin_bp
from admin.decorators import get_current_user, login_required, role_required
from admin.models import Condition, ConditionType, Role
from admin.services import proposal_service
from admin.services.validation import ValidationError, parse_optional_float
from validation.field_paths import KNOWN_FIELD_PATHS


@admin_bp.route("/conditions")
@login_required
def conditions_list():
    conditions = Condition.query.order_by(Condition.title).all()
    return render_template(
        "admin/conditions.html", conditions=conditions, ConditionType=ConditionType
    )


@admin_bp.route("/conditions/<condition_id>/edit", methods=["GET", "POST"])
@role_required(Role.ENGINEER.value)
def propose_condition_edit(condition_id):
    condition = Condition.query.get_or_404(condition_id)

    if request.method == "GET":
        return render_template(
            "admin/condition_edit.html", condition=condition, ConditionType=ConditionType
        )

    # Defense-in-depth: the edit form never renders a `title` <input>,
    # but reject outright if one somehow arrives in the payload anyway.
    if "title" in request.form:
        flash("The condition title cannot be changed.", "error")
        return render_template(
            "admin/condition_edit.html", condition=condition, ConditionType=ConditionType
        ), 400

    try:
        description = request.form.get("description", "").strip()
        unit = request.form.get("unit", "").strip()
        threshold = parse_optional_float(request.form.get("threshold"))
        min_value = parse_optional_float(request.form.get("min_value"))
        max_value = parse_optional_float(request.form.get("max_value"))
        # field_path is NOT editable here -- the edit flow never lets an
        # engineer change minimum<->range OR what field a condition
        # checks; it stays whatever it already is on `condition`.

        proposal_service.create_edit_proposal(
            condition=condition,
            submitted_by=get_current_user(),
            description=description,
            condition_type=condition.type,  # this flow can't change minimum<->range
            threshold=threshold,
            min_value=min_value,
            max_value=max_value,
            unit=unit,
            field_path=condition.field_path,  # unchanged, carried forward as-is
        )
    except ValidationError as e:
        for msg in e.errors:
            flash(msg, "error")
        return render_template(
            "admin/condition_edit.html", condition=condition, ConditionType=ConditionType
        ), 400

    flash(f"Proposal submitted for '{condition.title}' — pending admin approval.", "success")
    return redirect(url_for("admin.conditions_list"))


@admin_bp.route("/conditions/new", methods=["GET", "POST"])
@role_required(Role.ENGINEER.value)
def propose_new_condition():
    if request.method == "GET":
        return render_template(
            "admin/condition_new.html",
            ConditionType=ConditionType,
            field_paths=KNOWN_FIELD_PATHS,
        )

    try:
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        condition_type = request.form.get("type", "").strip()
        unit = request.form.get("unit", "").strip()
        threshold = parse_optional_float(request.form.get("threshold"))
        min_value = parse_optional_float(request.form.get("min_value"))
        max_value = parse_optional_float(request.form.get("max_value"))
        field_path = request.form.get("field_path", "").strip()

        if not title:
            raise ValidationError(["Title is required for a new condition."])
        if Condition.query.filter_by(title=title).first() is not None:
            raise ValidationError([f"A condition titled '{title}' already exists."])
        if not field_path:
            raise ValidationError(["You must select which extracted value this condition checks."])
        # Server-side rejection regardless of what the client sent --
        # never trust the dropdown alone (see validation/field_paths.py).
        if field_path not in KNOWN_FIELD_PATHS:
            raise ValidationError([f"'{field_path}' is not a recognized field to check against."])

        proposal_service.create_new_proposal(
            submitted_by=get_current_user(),
            title=title,
            description=description,
            condition_type=condition_type,
            threshold=threshold,
            min_value=min_value,
            max_value=max_value,
            unit=unit,
            field_path=field_path,
        )
    except ValidationError as e:
        for msg in e.errors:
            flash(msg, "error")
        return render_template(
            "admin/condition_new.html",
            ConditionType=ConditionType,
            field_paths=KNOWN_FIELD_PATHS,
        ), 400

    flash(f"New condition '{title}' proposed — pending admin approval.", "success")
    return redirect(url_for("admin.conditions_list"))