"""
admin/services/validation.py
==============================
All field-level validation for condition values, in one place, shared
by both "propose an edit" and "propose a new condition" -- so the
rules (positive numbers, min < max, etc.) can never drift between the
two flows.
"""

from admin.models import ConditionType, Role

MIN_PASSWORD_LENGTH = 6


class ValidationError(Exception):
    """Carries a list of user-facing error messages (there can be more
    than one problem with a single submission -- report all of them at
    once instead of stopping at the first)."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def parse_optional_float(raw: str | None) -> float | None:
    """Converts a form field to float, or None if left blank. Raises
    ValidationError (not a bare ValueError) so routes only need to
    catch one exception type from user input."""
    if raw is None or raw.strip() == "":
        return None
    try:
        return float(raw)
    except ValueError:
        raise ValidationError([f"'{raw}' is not a valid number."])


def validate_condition_values(
    condition_type: str,
    *,
    threshold: float | None,
    min_value: float | None,
    max_value: float | None,
    unit: str,
    description: str,
) -> None:
    """Raises ValidationError if anything is wrong; returns None (does
    nothing) if the values are valid. Collects ALL problems found, not
    just the first one, so the user fixes everything in one pass."""
    errors: list[str] = []

    if condition_type not in ConditionType.values():
        # Can't meaningfully check anything else without a valid type.
        raise ValidationError(
            [f"Type must be one of: {', '.join(ConditionType.values())}."]
        )

    if not description or not description.strip():
        errors.append("Description cannot be empty.")

    if not unit or not unit.strip():
        errors.append("Unit cannot be empty.")

    if condition_type == ConditionType.MINIMUM.value:
        if threshold is None:
            errors.append("Threshold is required for a 'minimum' condition.")
        elif threshold <= 0:
            errors.append("Threshold must be a positive number.")
        if min_value is not None or max_value is not None:
            errors.append("A 'minimum' condition should not have min/max values.")

    elif condition_type == ConditionType.RANGE.value:
        if min_value is None or max_value is None:
            errors.append("Both a min and a max value are required for a 'range' condition.")
        else:
            if min_value <= 0 or max_value <= 0:
                errors.append("Min and max must both be positive numbers.")
            elif min_value >= max_value:
                errors.append("Min must be less than max.")
        if threshold is not None:
            errors.append("A 'range' condition should not have a threshold value.")

    if errors:
        raise ValidationError(errors)


def validate_registration(username: str, password: str, confirm_password: str, role: str) -> None:
    """Shared by routes/auth.py::register(). Self-registration is only
    ever for 'engineer' or 'viewer' -- the single 'admin' account is
    seeded by the programmer (see admin/seed.py), never created here."""
    errors: list[str] = []

    if not username or len(username.strip()) < 3:
        errors.append("Username must be at least 3 characters.")

    if role not in (Role.ENGINEER.value, Role.VIEWER.value):
        errors.append("Role must be 'Engineer' or 'Viewer'.")

    if len(password) < MIN_PASSWORD_LENGTH:
        errors.append(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    elif password != confirm_password:
        errors.append("Passwords do not match.")

    if errors:
        raise ValidationError(errors)