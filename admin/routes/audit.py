"""
admin/routes/audit.py
=======================
Read-only history of every change that was actually approved and
applied to a `Condition`. Rows are written automatically by
services/proposal_service.py::approve_proposal() -- this module never
writes to AuditLog itself, only reads from it.

Visible to admin + engineer. Viewer is blocked (403) -- role_required
enforces that the same way it does everywhere else.
"""

from flask import render_template

from admin import admin_bp
from admin.decorators import role_required
from admin.models import AuditLog, Role

_PAGE_SIZE = 50


@admin_bp.route("/audit-log")
@role_required(Role.ADMIN.value, Role.ENGINEER.value)
def audit_log():
    entries = (
        AuditLog.query.order_by(AuditLog.timestamp.desc())
        .limit(_PAGE_SIZE)
        .all()
    )
    return render_template("admin/audit_log.html", entries=entries, page_size=_PAGE_SIZE)