"""
admin/seed.py
=============
First-run seeding: creates the initial admin user and the 3 existing
building conditions, so the panel is usable immediately without any
manual data entry.

Idempotent by design -- safe to call on every app startup (see
admin/__init__.py). It only inserts rows when the relevant table is
empty, so restarting the app never duplicates seed data or raises a
UNIQUE-constraint error on the second run.
"""

import os

from werkzeug.security import generate_password_hash

from admin.extensions import db
from admin.models import Condition, ConditionType, Role, User

# These 3 conditions -- and their EXACT `title` strings -- are copied
# verbatim from the existing knowledge_base/building_conditions.md and
# validation/deterministic_checks.py. deterministic_checks.py matches
# conditions by this exact title string (e.g. "condition": "Minimum
# Room Area"), so changing so much as one character here will silently
# break the existing compliance-checking pipeline.
_SEED_CONDITIONS = [
    {
        "id": "room_area",
        "title": "Minimum Room Area",
        "description": (
            "The internal floor area of a room must be at least 12 square "
            "meters (m²). This ensures adequate living space and complies "
            "with basic habitability standards for enclosed rooms."
        ),
        "type": ConditionType.MINIMUM.value,
        "threshold": 12.0,
        "min_value": None,
        "max_value": None,
        "unit": "m²",
    },
    {
        "id": "window_area_ratio",
        "title": "Minimum Window Area",
        "description": (
            "The window area must be at least 10% of the room's internal "
            "floor area. This is calculated as: (Window Area / Room Area) "
            "× 100 ≥ 10%. Adequate window area ensures sufficient natural "
            "light and ventilation."
        ),
        # NOTE: this is a ratio, but per the agreed design it is still
        # type "minimum" -- the unit ("%") is what distinguishes it from
        # an absolute measurement, not a 3rd DB-level type.
        "type": ConditionType.MINIMUM.value,
        "threshold": 10.0,
        "min_value": None,
        "max_value": None,
        "unit": "%",
    },
    {
        "id": "sill_height",
        "title": "Window Sill Height",
        "description": (
            "The vertical distance between the finished floor level and "
            "the bottom of the window opening (sill height) must be "
            "between 0.80 meters and 1.10 meters. This range ensures the "
            "window is safely positioned — not too low (fall risk) and "
            "not too high (usability/visibility)."
        ),
        "type": ConditionType.RANGE.value,
        "threshold": None,
        "min_value": 0.80,
        "max_value": 1.10,
        "unit": "m",
    },
]


def seed_database(app) -> None:
    """Call once at startup, right after db.create_all() (see
    admin/__init__.py). Wrapped in its own app_context so it can also be
    called from a standalone script/shell if ever needed."""
    with app.app_context():
        _seed_admin_user(app)
        _seed_conditions()
        db.session.commit()


def _seed_admin_user(app) -> None:
    if User.query.filter_by(role=Role.ADMIN.value).first() is not None:
        return  # an admin already exists -- never touch existing accounts

    username = os.environ.get("ADMIN_USERNAME", "admin")
    password = os.environ.get("ADMIN_PASSWORD", "changeme-local-dev-only")

    db.session.add(
        User(
            username=username,
            password_hash=generate_password_hash(password),
            role=Role.ADMIN.value,
            is_active=True,
        )
    )

    if password == "changeme-local-dev-only":
        app.logger.warning(
            "ADMIN_PASSWORD is not set -- using the insecure local-dev "
            "default. Set ADMIN_USERNAME / ADMIN_PASSWORD as environment "
            "variables before using this outside of local testing."
        )


def _seed_conditions() -> None:
    if Condition.query.count() > 0:
        return  # already seeded -- never overwrite live/edited data on restart

    for data in _SEED_CONDITIONS:
        db.session.add(Condition(**data))