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

from flask import Flask, render_template, request, jsonify

from main import run_pipeline
from generate_ifc import generate_model
from rag.compare_retrieval import run_comparison

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
def index():
    return render_template("index.html")


@app.route("/api/generate", methods=["POST"])
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
def api_compare():
    try:
        rows = run_comparison()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    kw_acc = sum(r["keyword_correct"] for r in rows) / len(rows)
    emb_acc = sum(r["embedding_correct"] for r in rows) / len(rows)

    return jsonify({"rows": rows, "keyword_accuracy": kw_acc, "embedding_accuracy": emb_acc})


if __name__ == "__main__":
    app.run(debug=True, port=5000)