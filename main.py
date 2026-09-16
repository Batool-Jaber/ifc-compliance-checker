"""
main.py
=======
End-to-end pipeline: IFC file -> RAG-retrieved rule text -> extracted
IFC data -> deterministic PASS/FAIL/CANNOT_BE_EVALUATED -> combined
compliance report, saved as a JSON file under reports/.

Supports TWO interchangeable retrieval methods for fetching the
human-readable rule text attached to each condition (--retrieval-method):
  - "keyword"    : rag/retriever.py (stop-words + title-weighted overlap)
  - "embeddings" : rag/vector_store.py (sentence-transformers + cosine similarity)
See rag/compare_retrieval.py for a head-to-head accuracy comparison of
the two methods.

Optionally (--narrate) attaches a natural-language "narration" string
per condition using a LOCAL LLM (rag/llm_narration.py, via Ollama). The
LLM ONLY rephrases -- it has zero ability to change status, and the
original deterministic `explanation` is always preserved unchanged
alongside it.

In ALL cases, RAG/LLM only supply text for citation/explanation -- they
have zero influence on calculated_value/required_value/status, which
come entirely from validation/deterministic_checks.py's pure-Python
arithmetic.

DYNAMIC CONDITIONS (NEW): run_pipeline() accepts an optional
`conditions` list -- plain dicts read from the live `conditions` DB
table by the CALLER (app.py, which runs inside a Flask app context).
This module itself has ZERO knowledge of Flask/SQLAlchemy (same
isolation principle as validation/generic_engine.py and
rag/chunking.py::build_chunks_from_conditions -- see those modules).

  - conditions=None (default): behaves EXACTLY as before -- standalone
    CLI usage, no DB/Flask involved at all. Uses the static
    CONDITION_TO_QUERY dict and rag/chunking.py::load_and_chunk()
    (reads knowledge_base/building_conditions.md).
  - conditions=[...]: used by the live web app. RAG chunks are built
    from these conditions directly (build_chunks_from_conditions()),
    the retrieval query for EVERY condition (original 3 included) is
    generated from that condition's own title, and any condition
    beyond the original 3 (identified by field_path being set) is
    passed to run_all_checks() as extra_conditions, evaluated by the
    generic engine.

Usage (unchanged):
    python main.py data/generated/compliant_model.ifc
    python main.py data/generated/violation_model.ifc --retrieval-method embeddings
    python main.py data/generated/compliant_model.ifc --narrate
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).parent))

from extract_ifc_data import extract_all
from validation.deterministic_checks import run_all_checks
from rag.chunking import load_and_chunk, build_chunks_from_conditions
from rag.retriever import retrieve as keyword_retrieve
from rag.vector_store import build_index, search as embedding_search
from rag.llm_narration import narrate

# Used only when run_pipeline() is called with conditions=None (the
# original 3, standalone-CLI path). Left exactly as before -- untouched.
CONDITION_TO_QUERY = {
    "Minimum Room Area": "what is the minimum room area",
    "Minimum Window Area": "window area percentage requirement",
    "Window Sill Height": "sill height range",
}


def _retrieve_rule_text(query: str, retrieval_method: str, chunks: list, index: dict | None):
    """Returns (rule_source, rule_text) using the selected retrieval method."""
    if retrieval_method == "embeddings":
        results = embedding_search(query, index, top_k=1)
    else:
        results = keyword_retrieve(query, chunks, top_k=1)

    if not results:
        return None, None
    return results[0]["title"], results[0]["text"]


def run_pipeline(
    ifc_path: str,
    retrieval_method: str = "keyword",
    narrate_results: bool = False,
    conditions: list[dict] | None = None,
) -> dict:
    """
    Runs the full pipeline against one IFC file and returns a single
    combined compliance report dict.

    conditions=None -> standalone/CLI behavior, unchanged (static file
    + static CONDITION_TO_QUERY). conditions=[...] -> live DB-driven
    behavior (see module docstring).
    """
    extracted = extract_all(ifc_path)

    if conditions is None:
        # ---- Unchanged original path ----
        check_results = run_all_checks(extracted["room"], extracted["window"])
        chunks = load_and_chunk()
        query_for = lambda condition_title: CONDITION_TO_QUERY.get(condition_title, condition_title)
    else:
        # ---- New DB-driven path ----
        # Conditions with a field_path are the ones beyond the original
        # 3 (those are still evaluated by their own hardcoded functions
        # inside run_all_checks() -- never touched, per the agreed design).
        extra_conditions = [
            c for c in conditions
            if c.get("field_path") and c["title"] not in CONDITION_TO_QUERY
        ]
        check_results = run_all_checks(extracted["room"], extracted["window"], extra_conditions)
        chunks = build_chunks_from_conditions(conditions)

        # Query generated from each condition's OWN title -- works for
        # the original 3 too, since build_chunks_from_conditions()
        # produces one chunk per condition regardless of count (same
        # guarantee load_and_chunk() already provided for the static file).
        query_for = lambda condition_title: condition_title

    # Only build the (heavier, model-loading) embedding index if actually needed
    index = build_index(chunks) if retrieval_method == "embeddings" else None

    for result in check_results:
        query = query_for(result["condition"])
        rule_source, rule_text = _retrieve_rule_text(query, retrieval_method, chunks, index)
        result["rule_source"] = rule_source
        result["rule_text"] = rule_text

        # Narration is purely additive: "explanation" (deterministic) is
        # never modified or removed. status is set above by run_all_checks
        # and is never touched again anywhere below this point.
        if narrate_results:
            result["narration"] = narrate(result)

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
        "retrieval_method": retrieval_method,
        "narrated": narrate_results,
        "room": extracted["room"],
        "window": extracted["window"],
        "conditions": check_results,
        "overall_result": overall,
    }


def save_report(report: dict, output_path: str) -> str:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(out)


def default_report_path(ifc_path: str) -> str:
    model_name = Path(ifc_path).stem
    return str(Path("reports") / f"{model_name}_report.json")


def parse_args():
    parser = argparse.ArgumentParser(description="Run the IFC compliance-checking pipeline.")
    parser.add_argument("ifc_path", nargs="?", default="data/generated/compliant_model.ifc")
    parser.add_argument("--retrieval-method", choices=["keyword", "embeddings"], default="keyword")
    parser.add_argument("--narrate", action="store_true", help="Attach LLM-generated natural-language narration per condition (requires Ollama running locally).")
    parser.add_argument("--output", default=None)
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    try:
        report = run_pipeline(args.ifc_path, retrieval_method=args.retrieval_method, narrate_results=args.narrate)
    except FileNotFoundError:
        print(f"[ERROR] IFC file not found: '{args.ifc_path}'", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Failed to process IFC file '{args.ifc_path}': {e}", file=sys.stderr)
        sys.exit(1)

    output_path = args.output or default_report_path(args.ifc_path)
    saved_path = save_report(report, output_path)

    if not args.quiet:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\n[OK] Report saved to {saved_path}  (method: {args.retrieval_method}, narrated: {args.narrate}, overall_result: {report['overall_result']})", file=sys.stderr)