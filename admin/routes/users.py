"""
admin/routes/users.py
=======================
Admin-only. Registration itself happens self-service via
routes/auth.py::register() -- this page is where the admin follows up:
activate a newly-registered engineer, deactivate someone, or fix a
role picked wrong at registration.

The single "admin" role can never be granted or revoked here -- it's
seeded once by the programmer (see admin/seed.py) and that's it.
"""

from flask import abort, flash, redirect, render_template, request, url_for

from admin import admin_bp
from admin.decorators import get_current_user, role_required
from admin.extensions import db
from admin.models import Role, User

_ASSIGNABLE_ROLES = (Role.ENGINEER.value, Role.VIEWER.value)


@admin_bp.route("/users")
@role_required(Role.ADMIN.value)
def users_list():
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template("admin/users.html", users=users, assignable_roles=_ASSIGNABLE_ROLES)


@admin_bp.route("/users/<int:user_id>/toggle-active", methods=["POST"])
@role_required(Role.ADMIN.value)
def toggle_user_active(user_id):
    user = User.query.get_or_404(user_id)

    if user.role == Role.ADMIN.value:
        abort(403)  # the seeded admin account can't be deactivated from the UI

    if user.id == get_current_user().id:
        abort(403)  # can't deactivate/reactivate your own session mid-use

    user.is_active = not user.is_active
    db.session.commit()

    flash(
        f"{user.username} is now {'active' if user.is_active else 'inactive'}.",
        "success",
    )
    return redirect(url_for("admin.users_list"))


@admin_bp.route("/users/<int:user_id>/role", methods=["POST"])
@role_required(Role.ADMIN.value)
def change_user_role(user_id):
    user = User.query.get_or_404(user_id)

    if user.role == Role.ADMIN.value:
        abort(403)  # the seeded admin account's role is fixed

    new_role = request.form.get("role", "").strip()
    if new_role not in _ASSIGNABLE_ROLES:
        flash("Role must be Engineer or Viewer.", "error")
        return redirect(url_for("admin.users_list"))

    user.role = new_role
    db.session.commit()

    flash(f"{user.username}'s role is now {new_role}.", "success")
    return redirect(url_for("admin.users_list"))