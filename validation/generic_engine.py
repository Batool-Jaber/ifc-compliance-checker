"""
validation/generic_engine.py
==============================
Generic validation for any condition beyond the 3 original hardcoded
ones (check_room_area, check_window_ratio, check_sill_height -- which
are NEVER touched or reimplemented here, per the agreed design).

Handles conditions of type "minimum" or "range", checked against a
single field_path looked up via field_paths.resolve_field_path().

DESIGN NOTE (Dependency Injection / isolation): this module has ZERO
knowledge of Flask, SQLAlchemy, or the admin.models.Condition class.
It accepts plain dicts. The caller (validation/deterministic_checks.py,
via run_all_checks()) is responsible for converting DB Condition rows
into these dicts before calling evaluate_condition(). This keeps this
file testable with plain fixtures, no database required -- same
principle as the room/window dicts already used throughout this
project.

Expected shape of a `condition` dict passed in:
    {
        "id": str,               # slug, e.g. "min_door_width"
        "title": str,            # e.g. "Minimum Door Width"
        "type": "minimum" | "range",
        "field_path": str,       # one of field_paths.KNOWN_FIELD_PATHS
        "threshold": float | None,   # used when type == "minimum"
        "min_value": float | None,   # used when type == "range"
        "max_value": float | None,   # used when type == "range"
        "unit": str,
    }
"""

from validation.field_paths import resolve_field_path


def evaluate_condition(condition: dict, room: dict | None, window: dict | None) -> dict:
    """
    Evaluates ONE generic condition against already-extracted room/
    window data. Returns the same result shape used everywhere else
    in this project: condition, status, calculated_value,
    required_value, explanation.
    """
    title = condition["title"]
    field_path = condition["field_path"]
    condition_type = condition["type"]
    unit = condition.get("unit", "")

    value = resolve_field_path(field_path, room, window)

    required_value = _format_required_value(condition, unit)

    if value is None:
        return {
            "condition": title,
            "status": "CANNOT_BE_EVALUATED",
            "calculated_value": None,
            "required_value": required_value,
            "explanation": f"'{field_path}' could not be extracted from the IFC model.",
        }

    if condition_type == "minimum":
        threshold = condition["threshold"]
        passed = value >= threshold
        return {
            "condition": title,
            "status": "PASS" if passed else "FAIL",
            "calculated_value": f"{value:.2f} {unit}".strip(),
            "required_value": required_value,
            "explanation": (
                f"{title} is {value:.2f} {unit}, which "
                f"{'meets' if passed else 'does not meet'} the {threshold} {unit} minimum."
            ),
        }

    elif condition_type == "range":
        min_value = condition["min_value"]
        max_value = condition["max_value"]
        passed = min_value <= value <= max_value
        return {
            "condition": title,
            "status": "PASS" if passed else "FAIL",
            "calculated_value": f"{value:.2f} {unit}".strip(),
            "required_value": required_value,
            "explanation": (
                f"{title} is {value:.2f} {unit}, which "
                f"{'is within' if passed else 'is outside'} the "
                f"{min_value}{unit}-{max_value}{unit} allowed range."
            ),
        }

    # Should never happen -- ConditionType has a DB-level CheckConstraint
    # limiting it to 'minimum'/'range' -- but never crash on bad data.
    return {
        "condition": title,
        "status": "CANNOT_BE_EVALUATED",
        "calculated_value": f"{value:.2f} {unit}".strip(),
        "required_value": required_value,
        "explanation": f"Unknown condition type '{condition_type}'.",
    }


def _format_required_value(condition: dict, unit: str) -> str:
    if condition["type"] == "minimum":
        return f">= {condition['threshold']} {unit}".strip()
    elif condition["type"] == "range":
        return f"{condition['min_value']}{unit} - {condition['max_value']}{unit}"
    return "—"