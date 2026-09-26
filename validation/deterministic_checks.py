"""
deterministic_checks.py
========================
Pure Python, deterministic compliance checks. No LLM involved in any
calculation or PASS/FAIL decision -- the LLM/RAG layer only supplies
the human-readable rule text; these functions do the actual math.

Each check function returns a dict with:
  status: "PASS" | "FAIL" | "CANNOT_BE_EVALUATED"
  calculated_value, required_value, explanation

The 3 original hardcoded checks below (check_room_area,
check_window_ratio, check_sill_height) are STILL NOT reimplemented or
restructured -- their explanation wording is exactly what
tests/test_*.py assert against, and that wording is fully preserved.

CHANGED (live-threshold fix): each check now accepts its threshold(s)
as an OPTIONAL parameter, defaulting to the original module-level
constant. This closes a real gap: previously, an admin-approved edit
to one of these 3 conditions' threshold/min/max updated the Condition
row's description text (and therefore RAG citation) but NEVER actually
changed what the deterministic check enforced -- the check silently
kept using the hardcoded constant forever. Every EXISTING call site
(including all 15 current tests, which call these functions/
run_all_checks() with the same positional arguments as before) is
UNAFFECTED: when the new parameter isn't passed, the default equals
the original constant, so the calculated status AND the explanation
string text are byte-identical to before.

run_all_checks() accepts an optional `extra_conditions` list (plain
dicts, see validation/generic_engine.py) evaluated via the generic
engine and appended AFTER the 3 original results -- unchanged from
before. It ALSO now accepts optional keyword-only live-threshold
overrides for the 3 original checks; these are populated by
main.py::run_pipeline() ONLY on the live DB-driven path
(conditions=[...]), never on the conditions=None/CLI path -- see
main.py's own docstring for that distinction.
"""

from validation.generic_engine import evaluate_condition

MIN_ROOM_AREA_M2 = 12.0
MIN_WINDOW_RATIO_PERCENT = 10.0
SILL_HEIGHT_MIN_M = 0.80
SILL_HEIGHT_MAX_M = 1.10


def check_room_area(room_data: dict | None, min_area: float = MIN_ROOM_AREA_M2) -> dict:
    if room_data is None or room_data.get("floor_area_m2") is None:
        return {
            "condition": "Minimum Room Area",
            "status": "CANNOT_BE_EVALUATED",
            "calculated_value": None,
            "required_value": f">= {min_area} m²",
            "explanation": "Room floor area could not be extracted from the IFC model.",
        }

    area = room_data["floor_area_m2"]
    passed = area >= min_area
    return {
        "condition": "Minimum Room Area",
        "status": "PASS" if passed else "FAIL",
        "calculated_value": f"{area:.2f} m²",
        "required_value": f">= {min_area} m²",
        "explanation": (
            f"Room area is {area:.2f} m², which "
            f"{'meets' if passed else 'does not meet'} the {min_area} m² minimum."
        ),
    }


def check_window_ratio(
    room_data: dict | None, window_data: dict | None, min_ratio_percent: float = MIN_WINDOW_RATIO_PERCENT
) -> dict:
    if room_data is None or window_data is None:
        return {
            "condition": "Minimum Window Area",
            "status": "CANNOT_BE_EVALUATED",
            "calculated_value": None,
            "required_value": f">= {min_ratio_percent}%",
            "explanation": "Room or window data could not be extracted from the IFC model.",
        }

    room_area = room_data.get("floor_area_m2")
    window_area = window_data.get("area_m2")

    if room_area is None or window_area is None or room_area == 0:
        return {
            "condition": "Minimum Window Area",
            "status": "CANNOT_BE_EVALUATED",
            "calculated_value": None,
            "required_value": f">= {min_ratio_percent}%",
            "explanation": "Room area or window area is missing or invalid.",
        }

    ratio_percent = (window_area / room_area) * 100
    passed = ratio_percent >= min_ratio_percent
    return {
        "condition": "Minimum Window Area",
        "status": "PASS" if passed else "FAIL",
        "calculated_value": f"{ratio_percent:.2f}%",
        "required_value": f">= {min_ratio_percent}%",
        "explanation": (
            f"Window area is {ratio_percent:.2f}% of room area, which "
            f"{'meets' if passed else 'does not meet'} the {min_ratio_percent}% minimum."
        ),
    }


def check_sill_height(
    window_data: dict | None, min_sill: float = SILL_HEIGHT_MIN_M, max_sill: float = SILL_HEIGHT_MAX_M
) -> dict:
    if window_data is None or window_data.get("sill_height_m") is None:
        return {
            "condition": "Window Sill Height",
            "status": "CANNOT_BE_EVALUATED",
            "calculated_value": None,
            "required_value": f"{min_sill}m - {max_sill}m",
            "explanation": "Window sill height could not be extracted from the IFC model.",
        }

    sill = window_data["sill_height_m"]
    passed = min_sill <= sill <= max_sill
    return {
        "condition": "Window Sill Height",
        "status": "PASS" if passed else "FAIL",
        "calculated_value": f"{sill:.2f} m",
        "required_value": f"{min_sill}m - {max_sill}m",
        "explanation": (
            f"Sill height is {sill:.2f} m, which "
            f"{'is within' if passed else 'is outside'} the "
            f"{min_sill}m-{max_sill}m allowed range."
        ),
    }


def run_all_checks(
    room_data: dict | None,
    window_data: dict | None,
    extra_conditions: list[dict] | None = None,
    *,
    room_area_min: float | None = None,
    window_ratio_min: float | None = None,
    sill_height_min: float | None = None,
    sill_height_max: float | None = None,
) -> list[dict]:
    """
    Runs the 3 original checks, then evaluates any extra_conditions via
    the generic engine, and returns everything in one combined list.

    extra_conditions defaults to None (treated as empty). The 4 new
    keyword-only live-threshold overrides ALSO default to None, in
    which case each check falls back to its own original hardcoded
    constant -- so every existing caller, including all current tests
    (which call this with exactly 2 or 3 positional arguments), keeps
    working with byte-identical output.
    """
    results = [
        check_room_area(
            room_data,
            min_area=room_area_min if room_area_min is not None else MIN_ROOM_AREA_M2,
        ),
        check_window_ratio(
            room_data, window_data,
            min_ratio_percent=window_ratio_min if window_ratio_min is not None else MIN_WINDOW_RATIO_PERCENT,
        ),
        check_sill_height(
            window_data,
            min_sill=sill_height_min if sill_height_min is not None else SILL_HEIGHT_MIN_M,
            max_sill=sill_height_max if sill_height_max is not None else SILL_HEIGHT_MAX_M,
        ),
    ]

    for condition in extra_conditions or []:
        results.append(evaluate_condition(condition, room_data, window_data))

    return results


if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.append(str(Path(__file__).parent.parent))
    from extract_ifc_data import extract_all, DEFAULT_PATH

    data = extract_all(DEFAULT_PATH)
    results = run_all_checks(data["room"], data["window"])

    for r in results:
        print(f"[{r['status']}] {r['condition']}")
        print(f"  Calculated: {r['calculated_value']}  |  Required: {r['required_value']}")
        print(f"  {r['explanation']}\n")