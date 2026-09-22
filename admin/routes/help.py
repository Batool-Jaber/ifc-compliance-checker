"""
admin/routes/help.py
======================
Engineer-only "Help" page: a free-form question box answered from the
unified Chroma collection (rag/vector_db.py), scoped to
audience_role="engineer" (so it can see anything marked "engineer" or
"all", never "admin"-only content like the building-code regulations
or, previously, an admin-only slice of the materials register --
none of that currently exists, but the filtering is real and
enforced at query time regardless), plus an optional local-LLM
rephrased answer (see rag/llm_help_advisor.py) the engineer can
toggle on/off.

Previously this route built its own private, in-memory, per-process
index (_get_help_index() over rag/chunking.py::load_and_chunk() +
rag/vector_store.py) reading ONLY knowledge_base/help/engineer_guide.md.
That has been retired: this route now queries the SAME unified
collection every other RAG-backed part of this project uses
(rag/migrate_to_chroma.py populates it from building_conditions,
engineer_guide, building_code, and materials_register). Practically,
for an engineer's question, this means the Help Assistant can now also
surface a relevant materials_register product (audience_role
"engineer") in addition to engineer_guide sections -- not just guide
text -- since both are visible to the engineer role in the unified
store.

CONFIDENCE_THRESHOLD is UNCHANGED from before this migration -- the
score is cosine similarity from the same embeddings model
(all-MiniLM-L6-v2) either way; empirically confirmed identical
(0.5424) for the same test question before and after the Chroma
migration, so the previously-tuned value stays valid.
"""

from flask import jsonify, render_template, request

from admin import admin_bp
from admin.decorators import role_required
from admin.models import Role
from rag.llm_help_advisor import answer_help_question
from rag.vector_db import search as unified_search

# NOTE: this value is tuned from real test data (12 manually-run
# questions against the pre-migration engineer_guide-only index -- see
# project handoff docs for the full table). The lowest confirmed-correct
# match scored 0.5476, the highest confirmed-incorrect match scored
# 0.4774; 0.52 sits in that gap. CAVEAT: small sample, and this now also
# gates materials_register results (not just engineer_guide) -- revisit
# if real usage on the newly-included source produces misclassified
# borderline scores.
CONFIDENCE_THRESHOLD = 0.52

NO_MATCH_MESSAGE = "I couldn't find anything in the guide closely related to that question."


@admin_bp.route("/help")
@role_required(Role.ENGINEER.value)
def help_page():
    return render_template("admin/help.html")


@admin_bp.route("/help/ask", methods=["POST"])
@role_required(Role.ENGINEER.value)
def help_ask():
    """
    Queries the unified Chroma collection, scoped to
    audience_role="engineer" (sees "engineer" + "all" content, never
    "admin"-only). If the top match's similarity score is below
    CONFIDENCE_THRESHOLD, returns NO_MATCH_MESSAGE instead of calling
    the LLM on an unrelated section -- avoids a confidently-worded
    answer grounded in the wrong context.
    """
    data = request.get_json(force=True) or {}
    question = data.get("question", "").strip()
    use_llm = bool(data.get("use_llm", False))

    if not question:
        return jsonify({"error": "Question is empty."}), 400

    results = unified_search(question, top_k=1, audience_role="engineer")

    if not results:
        return jsonify({"error": "The knowledge base has no content to search."}), 500

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