"""
rag/llm_help_advisor.py
=========================
Answers a free-form engineer question about how to use the admin
system, grounded in the single best-matching section of
knowledge_base/help/engineer_guide.md (retrieved via
rag/vector_store.py's embeddings search -- see admin/routes/help.py,
which is the only caller of this module).

STRICT BOUNDARY: same safety pattern as rag/llm_advisor.py and
rag/llm_narration.py -- this module only rephrases/explains text it
is handed. It has no access to, and cannot change, anything about the
admin system's actual behavior, permissions, or data; it only explains
the guide section it's given.

Kept as its OWN module rather than a second function inside
llm_advisor.py: that module's own docstring scopes it specifically to
compliance-report questions ("this module is read-only with respect
to the report"). A help-guide question isn't about a report at all,
so it gets its own small, single-purpose module instead of stretching
that existing contract.
"""

import json
import urllib.request
import urllib.error

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "qwen2.5:7b"
TIMEOUT_SECONDS = 45

PROMPT_TEMPLATE = """You are a helpful assistant answering an engineer's question about how to use the IFC Compliance Checker admin system. Base your answer ONLY on the guide section below -- it is the single most relevant section retrieved for this question. Do not invent features, pages, or behavior that aren't described in it. If the section doesn't actually answer the question, say so honestly instead of guessing.

GUIDE SECTION (retrieved, most relevant match):
{section_text}

ENGINEER'S QUESTION:
{question}

Answer clearly and concisely, in plain language, using only the section above.

Answer:"""


def answer_help_question(question: str, section_text: str) -> str:
    """
    Returns the LLM's rephrased/explained answer as a plain string,
    grounded in `section_text` (the top-matching engineer_guide.md
    section for `question`, chosen by the caller via embeddings
    search). Raises no exception on failure -- returns a clear
    fallback message instead, so the UI never breaks (same pattern as
    rag/llm_advisor.py::ask_about_report()).
    """
    prompt = PROMPT_TEMPLATE.format(
        section_text=section_text.strip(),
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
    sample_section = (
        "## Proposing an edit to an existing condition\n"
        "From the Conditions list, click \"Propose Edit\" on any rule. "
        "You cannot change its title -- it's shown but greyed out."
    )
    print(answer_help_question("Can I rename a condition?", sample_section))