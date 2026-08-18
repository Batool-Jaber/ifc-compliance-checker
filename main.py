"""
main.py
=======
End-to-end pipeline: IFC file -> RAG-retrieved rule text -> extracted
IFC data -> deterministic PASS/FAIL/CANNOT_BE_EVALUATED -> combined
compliance report, saved as a JSON file under reports/.

Wiring:
    extract_ifc_data.extract_all()                    -> room/window measurements
    validation.deterministic_checks.run_all_checks()   -> pure-Python verdicts
    rag.chunking.load_and_chunk()                      -> knowledge_base chunks
    rag.retriever.retrieve()                           -> the rule TEXT that
                                                           explains each verdict
                                                           (RAG is used only for
                                                           retrieval/citation, never
                                                           for the calculation or
                                                           the PASS/FAIL decision)

Usage:
    python main.py data/generated/compliant_model.ifc
    python main.py data/generated/violation_model.ifc --output reports/custom_name.json
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).parent))

from extract_ifc_data import extract_all
from validation.deterministic_checks import run_all_checks
from rag.chunking import load_and_chunk
from rag.retriever import retrieve

# Maps each check's "condition" name to the natural-language query used
# to retrieve its matching rule text from the knowledge base.
CONDITION_TO_QUERY = {
    "Minimum Room Area": "what is the minimum room area",
    "Minimum Window Area": "window area percentage requirement",
    "Window Sill Height": "sill height range",
}


def run_pipeline(ifc_path: str) -> dict:
    """
    Runs the full pipeline against one IFC file and returns a single
    combined compliance report dict.
    """
    extracted = extract_all(ifc_path)
    check_results = run_all_checks(extracted["room"], extracted["window"])

    chunks = load_and_chunk()
    for result in check_results:
        query = CONDITION_TO_QUERY.get(result["condition"], result["condition"])
        retrieved = retrieve(query, chunks, top_k=1)
        result["rule_source"] = retrieved[0]["title"] if retrieved else None
        result["rule_text"] = retrieved[0]["text"] if retrieved else None

    statuses = [r["status"] for r in check_results]
    if "FAIL" in statuses:
        overall = "FAIL"
    elif "CANNOT_BE_EVALUATED" in statuses:
        overall = "CANNOT_BE_EVALUATED"
    else:
        overall = "PASS"

    return {
        "source_file": ifc_path,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "room": extracted["room"],
        "window": extracted["window"],
        "conditions": check_results,
        "overall_result": overall,
    }


def save_report(report: dict, output_path: str) -> str:
    """Writes the report dict to output_path as formatted JSON. Returns the path."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(out)


def default_report_path(ifc_path: str) -> str:
    """Derives reports/<model_name>_report.json from the input IFC filename."""
    model_name = Path(ifc_path).stem  # e.g. "compliant_model"
    return str(Path("reports") / f"{model_name}_report.json")


def parse_args():
    parser = argparse.ArgumentParser(description="Run the IFC compliance-checking pipeline.")
    parser.add_argument("ifc_path", nargs="?", default="data/generated/compliant_model.ifc")
    parser.add_argument("--output", default=None, help="Report output path (default: reports/<model>_report.json)")
    parser.add_argument("--quiet", action="store_true", help="Don't print the report to stdout")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    report = run_pipeline(args.ifc_path)
    output_path = args.output or default_report_path(args.ifc_path)
    saved_path = save_report(report, output_path)

    if not args.quiet:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\n[OK] Report saved to {saved_path}  (overall_result: {report['overall_result']})", file=sys.stderr)