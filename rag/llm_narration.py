"""
llm_narration.py
=================
Turns a deterministic compliance-check result into a natural-language
explanation using a LOCAL LLM (Ollama). The LLM only rephrases; it has
NO ability to change the PASS/FAIL/CANNOT_BE_EVALUATED status -- that
value is computed entirely in validation/deterministic_checks.py and is
never sent to the LLM as something it's asked to decide, only as a
fixed fact it must describe.

If Ollama is unreachable or errors in any way, narrate() falls back to
returning the original deterministic `explanation` string, so the report
never breaks due to an LLM failure.
"""

import json
import urllib.request
import urllib.error

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "qwen2.5:7b"
TIMEOUT_SECONDS = 30

PROMPT_TEMPLATE = """You are a technical writing assistant. Rephrase the following building-compliance check result as one clear, natural-language sentence for a report reader.

STRICT RULES:
- The status below is FINAL and ALREADY DECIDED by a separate deterministic system. You must NOT change it, question it, or suggest a different outcome.
- Do not invent numbers. Use only the values given.
- Output ONLY the rephrased sentence, nothing else.

Condition: {condition}
Status: {status}
Calculated value: {calculated_value}
Required value: {required_value}
Original explanation: {explanation}

Rephrased sentence:"""


def _call_ollama(prompt: str) -> str:
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
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as response:
        body = json.loads(response.read().decode("utf-8"))
        return body.get("response", "").strip()


def narrate(check_result: dict) -> str:
    """
    Returns a natural-language narration string for one check result.
    Falls back to the original deterministic explanation on ANY failure
    (Ollama not running, network error, timeout, malformed response...).
    The returned string is informational only -- it is never used to
    determine or overwrite check_result["status"].
    """
    fallback = check_result.get("explanation", "")

    prompt = PROMPT_TEMPLATE.format(
        condition=check_result.get("condition"),
        status=check_result.get("status"),
        calculated_value=check_result.get("calculated_value"),
        required_value=check_result.get("required_value"),
        explanation=fallback,
    )

    try:
        narration = _call_ollama(prompt)
        return narration if narration else fallback
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError):
        return fallback


if __name__ == "__main__":
    sample = {
        "condition": "Minimum Room Area",
        "status": "PASS",
        "calculated_value": "14.00 m²",
        "required_value": ">= 12.0 m²",
        "explanation": "Room area is 14.00 m², which meets the 12.0 m² minimum.",
    }
    print(narrate(sample))