"""
tests/test_missing_data.py
============================
Automated test: a model with missing/invalid information.

Uses generate_model(..., missing_data=True) to create a window with
NO IfcOpeningElement relationship and NO quantity set (the exact
Revit-export failure mode from Phase 1). Confirms the whole pipeline
degrades gracefully to CANNOT_BE_EVALUATED instead of crashing, while
Rule 1 (room area, unaffected by the missing window data) still
evaluates normally.
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from generate_ifc import generate_model
from extract_ifc_data import extract_all
from validation.deterministic_checks import run_all_checks

FIXTURE_PATH = str(Path(__file__).parent / "fixtures" / "test_missing_data.ifc")


def setup_module(module):
    """Generate the missing-data fixture: window with no opening/quantities."""
    generate_model(output_path=FIXTURE_PATH, missing_data=True)


def test_extraction_does_not_crash():
    """The core robustness guarantee: missing data must not raise an exception."""
    data = extract_all(FIXTURE_PATH)  # would raise here if extraction wasn't robust
    assert data["room"] is not None
    assert data["window"] is not None


def test_sill_height_is_none():
    data = extract_all(FIXTURE_PATH)
    assert data["window"]["sill_height_m"] is None


def test_sill_height_check_is_cannot_be_evaluated():
    data = extract_all(FIXTURE_PATH)
    results = run_all_checks(data["room"], data["window"])
    sill_check = next(r for r in results if r["condition"] == "Window Sill Height")
    assert sill_check["status"] == "CANNOT_BE_EVALUATED"
    assert sill_check["calculated_value"] is None


def test_room_area_is_still_evaluated_normally():
    """Missing WINDOW data should not block the independent ROOM area check."""
    data = extract_all(FIXTURE_PATH)
    results = run_all_checks(data["room"], data["window"])
    room_check = next(r for r in results if r["condition"] == "Minimum Room Area")
    assert room_check["status"] == "PASS"  # room dimensions were untouched (defaults)


def test_overall_result_has_cannot_be_evaluated():
    data = extract_all(FIXTURE_PATH)
    results = run_all_checks(data["room"], data["window"])
    statuses = [r["status"] for r in results]
    assert "CANNOT_BE_EVALUATED" in statuses, f"Expected CANNOT_BE_EVALUATED present, got: {statuses}"