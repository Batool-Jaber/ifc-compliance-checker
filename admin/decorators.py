"""
admin/decorators.py
====================
Two small, dependency-free decorators for route protection. Rolled by
hand (no Flask-Login) per the agreed design -- 3 fixed roles and
simple session-based auth don't need a full library for this.

Both decorators share one helper (`_require_active_user`) so the
"who's logged in, and are they still active" check lives in exactly
one place -- role_required doesn't duplicate login_required's logic,
it builds on top of it.
"""

from functools import wraps

from flask import abort, flash, redirect, session, url_for

from admin.models import User


def get_current_user() -> User | None:
    """Loads the logged-in user fresh from the DB on every call (never
    cached in the session itself) so a deactivation by an admin takes
    effect on the deactivated user's very next request, not just after
    their next login."""
    user_id = session.get("user_id")
    if user_id is None:
        return None
    return User.query.get(user_id)


def _require_active_user() -> User | None:
    """Returns the current active User, or None (and clears a stale/
    invalid session as a side effect) if the caller should be sent to
    the login page."""
    user = get_current_user()
    if user is None or not user.is_active:
        session.clear()
        return None
    return user


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if _require_active_user() is None:
            flash("Please log in to continue.", "error")
            return redirect(url_for("admin.login"))
        return view(*args, **kwargs)
    return wrapped


def role_required(*allowed_roles: str):
    """Usage:  @role_required(Role.ADMIN.value, Role.ENGINEER.value)"""
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = _require_active_user()
            if user is None:
                flash("Please log in to continue.", "error")
                return redirect(url_for("admin.login"))
            if user.role not in allowed_roles:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator