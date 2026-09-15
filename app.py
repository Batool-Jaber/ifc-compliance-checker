"""
app.py
======
Flask backend for the IFC Compliance Checker web interface.
Wraps the existing project logic (generate_ifc.generate_model,
main.run_pipeline, rag.compare_retrieval.run_comparison) -- no
duplicated business logic, this file is a thin API layer only.
"""

import sys
from pathlib import Path
import os
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, jsonify, url_for
from main import run_pipeline, CONDITION_TO_QUERY
from generate_ifc import generate_model
from rag.compare_retrieval import run_comparison
from rag.llm_advisor import ask_about_report
from rag.chunking import load_and_chunk
from rag.retriever import explain as keyword_explain
from rag.vector_store import build_index, search as embedding_search
from admin import init_admin
from admin.decorators import login_required, get_current_user
from admin.models import Role

app = Flask(__name__)

SCENARIO_PARAMS = {
    "compliant": {},
    "violation": {"room_width": 3.0, "room_length": 3.0},
    "missing_data": {"missing_data": True},
}

SCENARIO_PATHS = {
    "compliant": "data/generated/compliant_model.ifc",
    "violation": "data/generated/violation_model.ifc",
    "missing_data": "data/generated/missing_data_model.ifc",
}

CUSTOM_OUTPUT_PATH = "data/generated/custom_model.ifc"
CUSTOM_FIELDS = ["room_width", "room_length", "window_width", "window_height", "sill_height"]

UPLOAD_DIR = "data/uploaded"
os.makedirs(UPLOAD_DIR, exist_ok=True)
sys.path.append(str(Path(__file__).parent))


@app.route("/")
@login_required
def index():
    user = get_current_user()
    admin_link = None
    if user.role == Role.ADMIN.value:
        admin_link = url_for("admin.proposals_list")
    elif user.role == Role.ENGINEER.value:
        admin_link = url_for("admin.conditions_list")
    return render_template("index.html", current_user=user, admin_link=admin_link)


@app.route("/api/generate", methods=["POST"])
@login_required
def api_generate():
    data = request.get_json(force=True) or {}
    scenario = data.get("scenario", "compliant")

    if scenario == "custom":
        raw_params = data.get("params", {})
        try:
            values = {field: float(raw_params[field]) for field in CUSTOM_FIELDS}
        except (KeyError, TypeError, ValueError):
            return jsonify({
                "error": "Custom scenario requires numeric values for: "
                         + ", ".join(CUSTOM_FIELDS)
            }), 400

        if any(values[f] <= 0 for f in ("room_width", "room_length", "window_width", "window_height")):
            return jsonify({"error": "Room and window dimensions must be greater than 0."}), 400
        if values["sill_height"] < 0:
            return jsonify({"error": "Sill height cannot be negative."}), 400

        try:
            summary = generate_model(output_path=CUSTOM_OUTPUT_PATH, **values)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

        return jsonify({"scenario": "custom", "ifc_path": CUSTOM_OUTPUT_PATH, "summary": summary})

    if scenario not in SCENARIO_PARAMS:
        return jsonify({"error": f"Unknown scenario '{scenario}'"}), 400

    output_path = SCENARIO_PATHS[scenario]
    try:
        summary = generate_model(output_path=output_path, **SCENARIO_PARAMS[scenario])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"scenario": scenario, "ifc_path": output_path, "summary": summary})


@app.route("/api/upload", methods=["POST"])
@login_required
def api_upload():
    if "file" not in request.files:
        return jsonify({"error": "No file part in the request"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    if not file.filename.lower().endswith(".ifc"):
        return jsonify({"error": "Only .ifc files are accepted"}), 400

    filename = secure_filename(file.filename)
    save_path = os.path.join(UPLOAD_DIR, filename)
    file.save(save_path)

    return jsonify({"ifc_path": save_path, "filename": filename})


@app.route("/api/run", methods=["POST"])
@login_required
def api_run():
    data = request.get_json(force=True) or {}
    ifc_path = data.get("ifc_path")
    retrieval_method = data.get("retrieval_method", "keyword")
    narrate = bool(data.get("narrate", False))

    if not ifc_path:
        return jsonify({"error": "ifc_path is required"}), 400

    try:
        report = run_pipeline(ifc_path, retrieval_method=retrieval_method, narrate_results=narrate)
    except FileNotFoundError:
        return jsonify({"error": f"IFC file not found: {ifc_path}. Generate a model first."}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify(report)


@app.route("/api/compare", methods=["GET"])
@login_required
def api_compare():
    try:
        rows = run_comparison()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    kw_acc = sum(r["keyword_correct"] for r in rows) / len(rows)
    emb_acc = sum(r["embedding_correct"] for r in rows) / len(rows)

    return jsonify({"rows": rows, "keyword_accuracy": kw_acc, "embedding_accuracy": emb_acc})


@app.route("/api/retrieval-process", methods=["GET"])
@login_required
def api_retrieval_process():
    """
    For each of the 3 fixed internal queries (CONDITION_TO_QUERY from
    main.py), runs BOTH retrieval methods and returns full detail:
    which rule each matched, its score, and (for keyword) which exact
    words caused the match. Independent of any IFC file -- purely
    about the RAG layer itself. Used by the "Retrieval Process" panel.
    """
    try:
        chunks = load_and_chunk()
        index = build_index(chunks)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    results = []
    for condition, query in CONDITION_TO_QUERY.items():
        kw_results = keyword_explain(query, chunks)
        best_kw = kw_results[0] if kw_results else None

        emb_results = embedding_search(query, index, top_k=1)
        best_emb = emb_results[0] if emb_results else None

        results.append({
            "condition": condition,
            "query": query,
            "keyword": {
                "matched_rule": best_kw["chunk"]["title"] if best_kw else None,
                "score": best_kw["score"] if best_kw else 0,
                "matched_keywords": best_kw["matched_keywords"] if best_kw else [],
            },
            "embeddings": {
                "matched_rule": best_emb["title"] if best_emb else None,
                "score": round(best_emb["score"], 4) if best_emb else 0,
            },
        })

    return jsonify({"conditions": results})


@app.route("/api/ask", methods=["POST"])
@login_required
def api_ask():
    data = request.get_json(force=True) or {}
    report = data.get("report")
    question = data.get("question", "").strip()

    if not report:
        return jsonify({"error": "No report provided. Run a compliance check first."}), 400
    if not question:
        return jsonify({"error": "Question is empty."}), 400

    answer = ask_about_report(report, question)
    return jsonify({"answer": answer})


app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-insecure-secret-key")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///admin.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
init_admin(app)

if __name__ == "__main__":
    app.run(debug=True, port=5000)