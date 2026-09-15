"""
admin/routes/auth.py
=====================
Login, logout, and self-registration.

Self-registration rules (agreed design):
  - Anyone can register as "viewer" or "engineer" -- never "admin"
    (the single admin account is seeded from environment variables by
    the programmer, see admin/seed.py; it can't be created here).
  - A new "viewer" account is active immediately and gets logged in
    on the spot.
  - A new "engineer" account starts INACTIVE (is_active=False) and
    needs an admin to activate it from /admin/users before its first
    login can succeed -- reuses the same `is_active` flag that also
    covers later deactivation, so there's no separate "approved" column.
"""

from flask import flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from admin import admin_bp
from admin.extensions import db
from admin.models import Role, User
from admin.services.validation import ValidationError, validate_registration


@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("admin/login.html")

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    user = User.query.filter_by(username=username).first()

    # Same generic message whether the username doesn't exist or the
    # password is wrong -- doesn't tell an attacker which one it was.
    if user is None or not check_password_hash(user.password_hash, password):
        flash("Invalid username or password.", "error")
        return render_template("admin/login.html"), 401

    if not user.is_active:
        flash(
            "This account isn't active yet -- either it's still waiting "
            "on admin approval, or it's been deactivated. Contact an admin.",
            "error",
        )
        return render_template("admin/login.html"), 403

    session.clear()
    session["user_id"] = user.id
    session["role"] = user.role

    return redirect(_landing_page_for(user.role))


@admin_bp.route("/logout")
def logout():
    session.clear()
    flash("You've been logged out.", "success")
    return redirect(url_for("admin.login"))


@admin_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("admin/register.html")

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    confirm_password = request.form.get("confirm_password", "")
    role = request.form.get("role", "").strip()

    try:
        validate_registration(username, password, confirm_password, role)
        if User.query.filter_by(username=username).first() is not None:
            raise ValidationError([f"Username '{username}' is already taken."])
    except ValidationError as e:
        for msg in e.errors:
            flash(msg, "error")
        return render_template("admin/register.html"), 400

    is_viewer = role == Role.VIEWER.value
    user = User(
        username=username,
        password_hash=generate_password_hash(password),
        role=role,
        is_active=is_viewer,  # viewer: active right away / engineer: needs admin approval
    )
    db.session.add(user)
    db.session.commit()

    if is_viewer:
        session.clear()
        session["user_id"] = user.id
        session["role"] = user.role
        flash("Account created — you're signed in.", "success")
        return redirect(_landing_page_for(user.role))

    flash(
        "Account created. An admin needs to activate it before you can log in.",
        "success",
    )
    return redirect(url_for("admin.login"))


def _landing_page_for(role: str) -> str:
    """admin -> pending approvals queue, engineer -> conditions list to
    propose from (both unchanged). viewer -> the main compliance-check
    tool itself (index.html) -- a viewer's whole purpose is running
    checks, not managing rules, so that's where they land."""
    if role == Role.ADMIN.value:
        return url_for("admin.proposals_list")
    if role == Role.ENGINEER.value:
        return url_for("admin.conditions_list")
    return url_for("index")  # viewer