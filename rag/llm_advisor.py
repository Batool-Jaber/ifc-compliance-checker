"""
rag/llm_advisor.py
====================
Lets the user ask free-form questions about an already-computed
compliance report. The LLM answers using the report's fixed results
(status/calculated_value/required_value/explanation) plus the relevant
building-condition rule text as grounding context.

STRICT BOUNDARY: this module is read-only with respect to the report.
It receives already-decided data and returns advisory text -- it has
no mechanism to alter status, calculated_value, or required_value in
the report the frontend already holds. Same safety pattern as
rag/llm_narration.py.
"""

import json
import urllib.request
import urllib.error

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "qwen2.5:7b"
TIMEOUT_SECONDS = 45

PROMPT_TEMPLATE = """You are a helpful assistant answering questions about a building compliance report. The report below is FINAL and was produced by a separate deterministic system -- you cannot change any status, calculated value, or required value in it. Your job is only to explain, discuss, and give advice grounded in the data given.

COMPLIANCE REPORT (fixed, already decided):
{report_summary}

RELEVANT BUILDING RULES:
{rules_context}

USER QUESTION:
{question}

Answer the question clearly and helpfully, using only the report and rules above. If asked how to fix a FAIL condition, you may suggest general changes (e.g. "increase room width or length"), but do not invent specific numbers beyond what's needed to explain the existing gap. If the question is unrelated to this report, say so honestly instead of making something up.

Answer:"""


def _format_report_summary(report: dict) -> str:
    lines = [f"Overall result: {report.get('overall_result')}"]
    room = report.get("room") or {}
    window = report.get("window") or {}
    lines.append(f"Room: area={room.get('floor_area_m2')} m², {room.get('width_m')}x{room.get('length_m')} m")
    lines.append(f"Window: area={window.get('area_m2')} m², sill_height={window.get('sill_height_m')} m")
    for c in report.get("conditions", []):
        lines.append(
            f"- {c.get('condition')}: {c.get('status')} "
            f"(calculated={c.get('calculated_value')}, required={c.get('required_value')})"
        )
    return "\n".join(lines)


def _format_rules_context(report: dict) -> str:
    texts = []
    for c in report.get("conditions", []):
        if c.get("rule_text"):
            texts.append(c["rule_text"])
    return "\n\n".join(texts) if texts else "(no rule text available)"


def ask_about_report(report: dict, question: str) -> str:
    """
    Returns the LLM's advisory answer as a plain string. Raises no
    exception to the caller on failure -- returns a clear fallback
    message instead, so the UI never breaks.
    """
    prompt = PROMPT_TEMPLATE.format(
        report_summary=_format_report_summary(report),
        rules_context=_format_rules_context(report),
        question=question.strip(),
    )

    payload = json.dumps({
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
    }).encode("utf-8")

    req = urllib.request.Request(
        OLLAMA_URL, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode("utf-8"))
            answer = body.get("response", "").strip()
            return answer if answer else "The local LLM returned an empty response. Please try again."
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError):
        return "Unable to reach the local LLM (Ollama). Make sure Ollama is running (`ollama serve`) and try again."


if __name__ == "__main__":
    sample_report = {
        "overall_result": "FAIL",
        "room": {"floor_area_m2": 9.0, "width_m": 3.0, "length_m": 3.0},
        "window": {"area_m2": 1.2, "sill_height_m": 0.9},
        "conditions": [
            {
                "condition": "Minimum Room Area", "status": "FAIL",
                "calculated_value": "9.00 m²", "required_value": ">= 12.0 m²",
                "rule_text": "The internal floor area of a room must be at least 12 square meters (m²).",
            }
        ],
    }
    print(ask_about_report(sample_report, "Why did this fail and what should I change?"))

    