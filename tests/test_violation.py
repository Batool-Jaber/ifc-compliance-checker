"""
tests/test_violation.py
========================
Automated test: a model that violates at least one condition.

Deliberately shrinks the room to 3.0m x 3.0m = 9.0 m^2 (below the
12 m^2 minimum), while keeping the window/sill values at their
compliant defaults. This isolates the failure to Rule 1 only, and
confirms Rules 2/3 are evaluated independently and still PASS.
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from generate_ifc import generate_model
from extract_ifc_data import extract_all
from validation.deterministic_checks import run_all_checks

FIXTURE_PATH = str(Path(__file__).parent / "fixtures" / "test_violation.ifc")


def setup_module(module):
    """Generate the violation fixture: room area below the 12 m^2 minimum."""
    generate_model(
        output_path=FIXTURE_PATH,
        room_width=3.0,
        room_length=3.0,  # -> 9.0 m^2, fails Rule 1 (>= 12 m^2)
    )


def test_room_area_fails():
    data = extract_all(FIXTURE_PATH)
    results = run_all_checks(data["room"], data["window"])
    room_check = next(r for r in results if r["condition"] == "Minimum Room Area")
    assert room_check["status"] == "FAIL"
    assert room_check["calculated_value"] == "9.00 m²"


def test_window_ratio_still_passes():
    """Window/sill were left at compliant defaults -- only Rule 1 should fail."""
    data = extract_all(FIXTURE_PATH)
    results = run_all_checks(data["room"], data["window"])
    window_check = next(r for r in results if r["condition"] == "Minimum Window Area")
    assert window_check["status"] == "PASS"


def test_sill_height_still_passes():
    data = extract_all(FIXTURE_PATH)
    results = run_all_checks(data["room"], data["window"])
    sill_check = next(r for r in results if r["condition"] == "Window Sill Height")
    assert sill_check["status"] == "PASS"


def test_overall_result_has_at_least_one_failure():
    data = extract_all(FIXTURE_PATH)
    results = run_all_checks(data["room"], data["window"])
    statuses = [r["status"] for r in results]
    assert "FAIL" in statuses, f"Expected at least one FAIL, got: {statuses}"