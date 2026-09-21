"""
admin/routes/help.py
======================
Engineer-only "Help" page: a free-form question box answered from
knowledge_base/help/engineer_guide.md via embeddings search (see
rag/vector_store.py), with an optional local-LLM rephrased answer
(see rag/llm_help_advisor.py) the engineer can toggle on/off.
"""

from pathlib import Path

from flask import jsonify, render_template, request

from admin import admin_bp
from admin.decorators import role_required
from admin.models import Role
from rag.chunking import load_and_chunk
from rag.llm_help_advisor import answer_help_question
from rag.vector_store import build_index, search as embedding_search

HELP_KB_PATH = Path("knowledge_base/help/engineer_guide.md")

# CONFIDENCE_THRESHOLD, tuned from real test data (12 manually-run
# questions, see project handoff doc / test table): the lowest
# confirmed-correct match scored 0.5476, the highest confirmed-incorrect
# match (including in-scope questions that matched the WRONG section --
# see the known retrieval-quality limitation note below) scored 0.4774.
# 0.52 sits in that gap and separates all 12 test cases correctly.
#
# CAVEAT: 12 questions is a small sample -- this is not a mathematically
# guaranteed boundary for all future questions, just the best value
# supported by real data so far. Revisit if real engineer usage produces
# borderline scores (roughly 0.48-0.55) that get misclassified.
#
# KNOWN LIMITATION (not fixed by this threshold): two questions clearly
# IN-SCOPE ("How do I propose a new condition?", "What does the Checks
# against dropdown do?") matched the WRONG section instead of the right
# one, because engineer_guide.md has multiple sections that are
# semantically close (e.g. "Proposing a brand-new condition" vs. "I
# proposed a new condition but I don't see it yet"). Raising the
# threshold happens to reject both of these too (their scores were
# 0.502 and 0.4228), but that's incidental, not a real fix -- the
# underlying retrieval-quality issue is deferred, same bucket as the
# project's broader "RAG differentiation" backlog item (decoy
# conditions, section disambiguation), not part of this feature.
CONFIDENCE_THRESHOLD = 0.52

NO_MATCH_MESSAGE = "I couldn't find anything in the guide closely related to that question."

# ---------------------------------------------------------------------------
# Embeddings index cache
# ---------------------------------------------------------------------------
# engineer_guide.md is a static file with no edit UI, so its chunk
# embeddings never change while the process is running. Mirroring the
# exact lazy-singleton pattern rag/embeddings.py already uses for the
# sentence-transformers model itself (_model = None, loaded once on
# first use), we build this index once per process and reuse it for
# every question -- instead of re-embedding all ~20 sections on every
# single request.
_help_index = None


def _get_help_index() -> dict:
    global _help_index
    if _help_index is None:
        chunks = load_and_chunk(HELP_KB_PATH)
        _help_index = build_index(chunks)
    return _help_index


@admin_bp.route("/help")
@role_required(Role.ENGINEER.value)
def help_page():
    return render_template("admin/help.html")


@admin_bp.route("/help/ask", methods=["POST"])
@role_required(Role.ENGINEER.value)
def help_ask():
    data = request.get_json(force=True) or {}
    question = data.get("question", "").strip()
    use_llm = bool(data.get("use_llm", False))

    if not question:
        return jsonify({"error": "Question is empty."}), 400

    index = _get_help_index()
    if not index["chunks"]:
        return jsonify({"error": "The help guide has no content to search."}), 500

    results = embedding_search(question, index, top_k=1)
    if not results:
        return jsonify({"error": "No matching section was found for that question."}), 404

    best = results[0]

    if best["score"] < CONFIDENCE_THRESHOLD:
        return jsonify({
            "matched": False,
            "section_title": None,
            "section_text": None,
            "similarity_score": round(best["score"], 4),
            "used_llm": False,
            "answer": NO_MATCH_MESSAGE,
        })

    answer = answer_help_question(question, best["text"]) if use_llm else None

    return jsonify({
        "matched": True,
        "section_title": best["title"],
        "section_text": best["text"],
        "similarity_score": round(best["score"], 4),
        "used_llm": use_llm,
        "answer": answer,
    })