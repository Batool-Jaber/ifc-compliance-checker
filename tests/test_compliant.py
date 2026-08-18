"""
tests/test_compliant.py
========================
Automated test: a fully compliant model must PASS all 3 conditions.

The model is generated fresh by this test (not assumed to already
exist on disk), using the same generate_model() function the CLI
uses, so this test is fully self-contained and reproducible.
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from generate_ifc import generate_model
from extract_ifc_data import extract_all
from validation.deterministic_checks import run_all_checks

FIXTURE_PATH = str(Path(__file__).parent / "fixtures" / "test_compliant.ifc")


def setup_module(module):
    """Generate the compliant fixture once before the tests in this file run."""
    generate_model(output_path=FIXTURE_PATH)  # all defaults -> passes every rule


def test_room_area_passes():
    data = extract_all(FIXTURE_PATH)
    results = run_all_checks(data["room"], data["window"])
    room_check = next(r for r in results if r["condition"] == "Minimum Room Area")
    assert room_check["status"] == "PASS"


def test_window_ratio_passes():
    data = extract_all(FIXTURE_PATH)
    results = run_all_checks(data["room"], data["window"])
    window_check = next(r for r in results if r["condition"] == "Minimum Window Area")
    assert window_check["status"] == "PASS"


def test_sill_height_passes():
    data = extract_all(FIXTURE_PATH)
    results = run_all_checks(data["room"], data["window"])
    sill_check = next(r for r in results if r["condition"] == "Window Sill Height")
    assert sill_check["status"] == "PASS"


def test_all_three_conditions_pass():
    """Overall sanity check: the compliant model must have zero FAIL/CANNOT_BE_EVALUATED."""
    data = extract_all(FIXTURE_PATH)
    results = run_all_checks(data["room"], data["window"])
    statuses = [r["status"] for r in results]
    assert statuses == ["PASS", "PASS", "PASS"], f"Expected all PASS, got: {statuses}"