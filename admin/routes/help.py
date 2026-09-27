"""
admin/routes/help.py
======================
Engineer-only "Help" page, now with TWO tabs:

1. "Ask the Guide" (help_ask()) -- unchanged RAG behavior: free-form
   question answered from the unified Chroma collection
   (rag/vector_db.py), scoped to audience_role="engineer".

2. "My Proposals Status" (help_proposals_status()) -- NEW, and
   deliberately NOT RAG at all. This is TOOL-USE: a direct,
   deterministic database query scoped to the current engineer's own
   ConditionProposal rows via get_current_user() (never a user-supplied
   id). No embeddings, no Chroma, no LLM involved -- the engineer's
   real proposal history is looked up directly, the same way
   admin/routes/proposals.py::my_proposals() already does for the full
   proposals page. This tab is a lightweight, conversational-style
   summary; the full-featured /admin/my-proposals page (which also
   handles editing a reopened proposal) is unchanged and still the
   place for that.

TAB-CONFUSION SAFETY NET (NEW): help_ask() also runs a simple,
deterministic keyword check (_looks_like_status_question()) on the
question text. If the engineer is on "Ask the Guide" but their wording
suggests they actually mean their own proposal status (e.g. "did I get
approved"), the response includes possible_status_question: true --
the frontend shows a soft hint pointing at the other tab, WITHOUT
changing which tab is active or which answer is shown. This is
deliberately keyword-based, not an LLM classification: consistent with
this project's standing preference for deterministic, predictable
behavior over a model's guess (same philosophy as the deterministic
compliance checks themselves). It is a heuristic, not a guarantee --
some phrasings won't be caught, and that's an accepted, documented
trade-off, not a hidden gap.

CONFIDENCE_THRESHOLD is unchanged -- see prior history for its tuning.
"""

from flask import jsonify, render_template, request

from admin import admin_bp
from admin.decorators import get_current_user, role_required
from admin.models import ConditionProposal, Role
from rag.llm_help_advisor import answer_help_question
from rag.vector_db import search as unified_search

CONFIDENCE_THRESHOLD = 0.52

NO_MATCH_MESSAGE = "I couldn't find anything in the guide closely related to that question."

# Deliberately PHRASE-based, not single words -- an earlier draft
# considered bare "pending"/"approved"/"rejected", but the guide itself
# has a real section literally titled "My proposal has been pending for
# a while, is something wrong?", which would have falsely triggered the
# hint on a perfectly normal guide question. Phrases that specifically
# imply "about ME" are a better (though still imperfect) signal.
_STATUS_KEYWORDS = (
    "my proposal", "my proposals", "my condition", "my status",
    "did i", "was my", "have i", "am i",
)


def _looks_like_status_question(question: str) -> bool:
    q = question.lower()
    return any(kw in q for kw in _STATUS_KEYWORDS)


@admin_bp.route("/help")
@role_required(Role.ENGINEER.value)
def help_page():
    return render_template("admin/help.html")


@admin_bp.route("/help/ask", methods=["POST"])
@role_required(Role.ENGINEER.value)
def help_ask():
    """
    Queries the unified Chroma collection, scoped to
    audience_role="engineer". If the top match's similarity score is
    below CONFIDENCE_THRESHOLD, returns NO_MATCH_MESSAGE instead of
    calling the LLM on an unrelated section. Also flags
    possible_status_question -- see module docstring.
    """
    data = request.get_json(force=True) or {}
    question = data.get("question", "").strip()
    use_llm = bool(data.get("use_llm", False))

    if not question:
        return jsonify({"error": "Question is empty."}), 400

    status_hint = _looks_like_status_question(question)

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
            "possible_status_question": status_hint,
        })

    answer = answer_help_question(question, best["text"]) if use_llm else None

    return jsonify({
        "matched": True,
        "section_title": best["title"],
        "section_text": best["text"],
        "similarity_score": round(best["score"], 4),
        "used_llm": use_llm,
        "answer": answer,
        "possible_status_question": status_hint,
    })


@admin_bp.route("/help/proposals-status", methods=["GET"])
@role_required(Role.ENGINEER.value)
def help_proposals_status():
    """
    TOOL-USE, not RAG: a direct, deterministic query of the current
    engineer's own ConditionProposal rows -- no embeddings, no Chroma,
    no LLM. Scoped via get_current_user(), never a user-supplied id.
    Powers the "My Proposals Status" tab.
    """
    current = get_current_user()
    proposals = (
        ConditionProposal.query.filter_by(submitted_by=current.id)
        .order_by(ConditionProposal.submitted_at.desc())
        .all()
    )

    return jsonify({
        "proposals": [
            {
                "id": p.id,
                "type": p.proposal_type,
                "title": p.proposed_title if p.proposal_type == "new" else (p.condition.title if p.condition else None),
                "status": p.status,
                "submitted_at": p.submitted_at.strftime("%Y-%m-%d %H:%M"),
                "reviewed_at": p.reviewed_at.strftime("%Y-%m-%d %H:%M") if p.reviewed_at else None,
                "review_note": p.review_note,
                "reopened_from_id": p.reopened_from_id,
            }
            for p in proposals
        ]
    })