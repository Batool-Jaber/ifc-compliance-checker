"""
deterministic_checks.py
========================
Pure Python, deterministic compliance checks. No LLM involved in any
calculation or PASS/FAIL decision — the LLM/RAG layer only supplies
the human-readable rule text; these functions do the actual math.

Each check function returns a dict with:
  status: "PASS" | "FAIL" | "CANNOT_BE_EVALUATED"
  calculated_value, required_value, explanation
"""

MIN_ROOM_AREA_M2 = 12.0
MIN_WINDOW_RATIO_PERCENT = 10.0
SILL_HEIGHT_MIN_M = 0.80
SILL_HEIGHT_MAX_M = 1.10


def check_room_area(room_data: dict | None) -> dict:
    if room_data is None or room_data.get("floor_area_m2") is None:
        return {
            "condition": "Minimum Room Area",
            "status": "CANNOT_BE_EVALUATED",
            "calculated_value": None,
            "required_value": f">= {MIN_ROOM_AREA_M2} m²",
            "explanation": "Room floor area could not be extracted from the IFC model.",
        }

    area = room_data["floor_area_m2"]
    passed = area >= MIN_ROOM_AREA_M2
    return {
        "condition": "Minimum Room Area",
        "status": "PASS" if passed else "FAIL",
        "calculated_value": f"{area:.2f} m²",
        "required_value": f">= {MIN_ROOM_AREA_M2} m²",
        "explanation": (
            f"Room area is {area:.2f} m², which "
            f"{'meets' if passed else 'does not meet'} the {MIN_ROOM_AREA_M2} m² minimum."
        ),
    }


def check_window_ratio(room_data: dict | None, window_data: dict | None) -> dict:
    if room_data is None or window_data is None:
        return {
            "condition": "Minimum Window Area",
            "status": "CANNOT_BE_EVALUATED",
            "calculated_value": None,
            "required_value": f">= {MIN_WINDOW_RATIO_PERCENT}%",
            "explanation": "Room or window data could not be extracted from the IFC model.",
        }

    room_area = room_data.get("floor_area_m2")
    window_area = window_data.get("area_m2")

    if room_area is None or window_area is None or room_area == 0:
        return {
            "condition": "Minimum Window Area",
            "status": "CANNOT_BE_EVALUATED",
            "calculated_value": None,
            "required_value": f">= {MIN_WINDOW_RATIO_PERCENT}%",
            "explanation": "Room area or window area is missing or invalid.",
        }

    ratio_percent = (window_area / room_area) * 100
    passed = ratio_percent >= MIN_WINDOW_RATIO_PERCENT
    return {
        "condition": "Minimum Window Area",
        "status": "PASS" if passed else "FAIL",
        "calculated_value": f"{ratio_percent:.2f}%",
        "required_value": f">= {MIN_WINDOW_RATIO_PERCENT}%",
        "explanation": (
            f"Window area is {ratio_percent:.2f}% of room area, which "
            f"{'meets' if passed else 'does not meet'} the {MIN_WINDOW_RATIO_PERCENT}% minimum."
        ),
    }


def check_sill_height(window_data: dict | None) -> dict:
    if window_data is None or window_data.get("sill_height_m") is None:
        return {
            "condition": "Window Sill Height",
            "status": "CANNOT_BE_EVALUATED",
            "calculated_value": None,
            "required_value": f"{SILL_HEIGHT_MIN_M}m - {SILL_HEIGHT_MAX_M}m",
            "explanation": "Window sill height could not be extracted from the IFC model.",
        }

    sill = window_data["sill_height_m"]
    passed = SILL_HEIGHT_MIN_M <= sill <= SILL_HEIGHT_MAX_M
    return {
        "condition": "Window Sill Height",
        "status": "PASS" if passed else "FAIL",
        "calculated_value": f"{sill:.2f} m",
        "required_value": f"{SILL_HEIGHT_MIN_M}m - {SILL_HEIGHT_MAX_M}m",
        "explanation": (
            f"Sill height is {sill:.2f} m, which "
            f"{'is within' if passed else 'is outside'} the "
            f"{SILL_HEIGHT_MIN_M}m-{SILL_HEIGHT_MAX_M}m allowed range."
        ),
    }


def run_all_checks(room_data: dict | None, window_data: dict | None) -> list[dict]:
    return [
        check_room_area(room_data),
        check_window_ratio(room_data, window_data),
        check_sill_height(window_data),
    ]


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