# AI-Assisted IFC Compliance Checker

An AI-assisted application that checks a BIM/IFC building model against
written building compliance rules, combining **Python**, **IfcOpenShell**,
**RAG** (Retrieval-Augmented Generation), and **deterministic validation**.

The system reads an IFC model, extracts room and window data dynamically
— by IFC type and relationship, never by hardcoded IDs or names — retrieves
the relevant building condition using RAG, validates the extracted data
with pure Python arithmetic, and produces a compliance report: **PASS**,
**FAIL**, or **CANNOT_BE_EVALUATED** for each condition.

---

## Table of Contents

- [Building Conditions Checked](#building-conditions-checked)
- [Architecture](#architecture)
- [Installation](#installation)
- [Usage](#usage)
- [Libraries & Models Used](#libraries--models-used)
- [Assumptions & Limitations](#assumptions--limitations)

---

## Building Conditions Checked

| # | Condition | Requirement |
|---|---|---|
| 1 | **Minimum Room Area** | Internal floor area ≥ 12 m² |
| 2 | **Minimum Window Area** | Window area ≥ 10% of room area |
| 3 | **Window Sill Height** | Between 0.80 m and 1.10 m |

---

## Architecture

```
IFC File
   │
   ▼
extract_ifc_data.py ──────────────► Room + Window data
                                     (dynamic, type-based)
   │
   ▼
validation/deterministic_checks.py ─► PASS / FAIL / CANNOT_BE_EVALUATED
   │                                  (pure Python — no LLM involved)
   ▼
rag/ (retriever.py OR vector_store.py) ─► Rule text citation only
   │
   ▼
rag/llm_narration.py                ─► Natural-language explanation
(optional, local Ollama)              (rephrases only — cannot
   │                                   change the status)
   ▼
main.py ───────────────────────────► Combined JSON compliance report
                                      (reports/)
```

> **Core design principle:** the LLM/RAG layer is used only for retrieval,
> explanation, and structuring. All calculations and the final PASS/FAIL
> decision are deterministic Python — the LLM never decides compliance.
> This is enforced and verified by an automated meta-test
> (`tests/test_llm_narration_meta.py`).

---

## Installation

```bash
git clone https://github.com/Batool-Jaber/ifc-compliance-checker.git
cd ifc-compliance-checker
python -m venv .venv

# Activate the virtual environment:
.venv\Scripts\Activate.ps1    # Windows PowerShell
.venv\Scripts\activate.bat    # Windows CMD
source .venv/bin/activate     # macOS/Linux

pip install -r requirements.txt
```

**Optional (for `--narrate`):** install [Ollama](https://ollama.com), start
it, then pull the local model used for narration:

```bash
ollama serve
ollama pull qwen2.5:7b
```

If Ollama isn't running, `--narrate` still works — it falls back to the
deterministic explanation text instead of failing.

---

## Usage

**1. Generate a test IFC model** (the repo doesn't ship `.ifc` files —
they're regenerated on demand):

```bash
python generate_ifc.py --output data/generated/compliant_model.ifc

# A model that violates a rule (room too small)
python generate_ifc.py --room-width 3.0 --room-length 3.0 \
    --output data/generated/violation_model.ifc

# A model with missing data (window with no opening/quantities)
python generate_ifc.py --missing-data \
    --output data/generated/missing_data_model.ifc
```

**2. Inspect an IFC model** (general-purpose CLI tool):

```bash
python inspect_ifc.py data/generated/compliant_model.ifc
```

**3. Run the full compliance-checking pipeline:**

```bash
python main.py data/generated/compliant_model.ifc

# Choose the retrieval method (default: keyword)
python main.py data/generated/compliant_model.ifc --retrieval-method embeddings

# Add natural-language narration via a local LLM
python main.py data/generated/compliant_model.ifc --narrate
```

Each run saves a JSON report to `reports/<model_name>_report.json`.

**4. Run the automated test suite:**

```bash
pytest
```

> No `python -m` prefix needed — `__init__.py` files in `validation/`
> and `tests/` resolve an import issue that can otherwise occur on
> Windows machines with Application Control / WDAC security policies.

**5. Compare keyword vs. embeddings retrieval accuracy:**

```bash
python rag/compare_retrieval.py
```

---

## Libraries & Models Used

| Library / Model | Purpose |
|---|---|
| [IfcOpenShell](https://ifcopenshell.org/) 0.8.5 | Reading, generating, and querying IFC models |
| [NumPy](https://numpy.org/) | Geometric transformations (wall/window placement matrices), vector math for embeddings search |
| [sentence-transformers](https://www.sbert.net/) (`all-MiniLM-L6-v2`) | Local embedding model for the RAG embeddings-based retrieval path |
| [pytest](https://pytest.org/) | Automated test suite |
| [Ollama](https://ollama.com/) + `qwen2.5:7b` | Local LLM for optional natural-language narration (`--narrate`) |

> **No external/paid APIs are used anywhere in this project.** Both the
> embeddings model and the narration LLM run entirely locally — the
> project works fully offline after initial setup, and no API keys are
> required or stored anywhere in the repository.

### Why a local LLM instead of a cloud API?

- Satisfies the assessment's constraint of no API keys in the repository
- Works offline, so a live demo never depends on network availability
- Free and unlimited for repeated testing during development

`qwen2.5:7b` (an instruct model) was chosen over reasoning models like
DeepSeek-R1-Distill-Qwen-7B after testing: reasoning models produce a
long internal `<think>` chain even for the simple rephrasing task this
project needs, adding unnecessary latency with no benefit here.

### Why in-memory NumPy instead of FAISS/Chroma for the vector store?

The knowledge base currently holds 3 chunks (one per building
condition). A dedicated vector database is unnecessary overhead at
this scale — a plain NumPy matrix with cosine similarity is simpler,
has zero extra dependencies, and performs identically for this data
size.

---

## Assumptions & Limitations

### Scope assumptions

- The system evaluates **one room and one window** per model, matching
  the assessment's specification ("one enclosed room... one window").
  If an IFC model contains multiple rooms, `extract_room_data()` uses
  the first `IfcSpace` found (dynamic by type, not by name/ID). Multi-
  room support is a natural extension but out of scope here.
- Sill height is computed from the standard IFC relationship chain
  `IfcWindow.FillsVoids → IfcOpeningElement → placement Z, relative to
  the storey elevation`. This requires the model to have a proper
  `IfcOpeningElement` cut into the host wall. Models that lack this
  relationship return `sill_height_m: null`, which the deterministic
  checker correctly reports as `CANNOT_BE_EVALUATED` rather than
  guessing or crashing.

### Error handling

- A missing or invalid `.ifc` file path is caught explicitly and
  reported as a clean `[ERROR]` message with exit code 1, instead of a
  raw Python traceback.
- A corrupted or non-IFC file (e.g. wrong extension on a text file) is
  also caught and reported cleanly. Note: `ifcopenshell` itself
  occasionally prints a harmless internal `Exception ignored in
  __del__` warning to stderr *after* our error message in this case —
  this is a known cleanup quirk inside the IfcOpenShell C++ binding,
  not a bug in this project's code, and does not affect the exit code
  or the reported error.

### Real-world BIM interoperability limitation (Revit)

Early in this project, a real Autodesk Revit sample model
(`rac_basic_sample_project.rvt`, Autodesk's official sample
architecture file) was exported to IFC and tested as an alternative,
real-world data source. This surfaced two genuine Revit → IFC export
limitations, investigated in depth:

1. Walls exported as `IfcBuildingElementProxy` instead of `IfcWall`
   (54 of 56 walls) — confirmed the Category Mapping in Revit was
   already correct, and re-exporting as IFC2x3 instead of IFC4 made no
   difference, ruling out an export-setting fix.
2. The file contained **zero** `IfcOpeningElement` entities anywhere —
   meaning window/door openings were never cut into the walls in the
   export, which made reliable sill-height extraction impossible via
   any of three different geometric methods attempted.

Both were confirmed to be genuine limitations of this specific model/
exporter combination, not bugs in this project's Python code (the same
extraction code works correctly and precisely on the code-generated
model — see above). The project's actual deliverable therefore relies
entirely on a **code-generated IFC model** (`generate_ifc.py`), which
gives full, correct control over wall/opening/quantity data and is
what the assessment's "generate a simple IFC model" requirement
explicitly asks for. The Revit exploration is kept in
`data/revit_reference/` (git-ignored, regenerable/re-downloadable) as
a documented reference, not as the system's data source.

### RAG / LLM scope

- The knowledge base currently contains 3 chunks (one per building
  condition), which is enough to demonstrate a full RAG pipeline
  (chunking → embeddings → vector search → retrieval) but too small to
  fully stress-test retrieval precision at scale. `rag/
  compare_retrieval.py` still shows a meaningful accuracy gap between
  keyword search (50%) and embeddings (100%) on rephrased/non-literal
  queries.
- LLM narration (`--narrate`) requires a local Ollama installation. If
  Ollama is not running or unreachable, the system automatically falls
  back to the original deterministic explanation text. This is backed
  by two forms of evidence: an automated meta-test
  (`tests/test_llm_narration_meta.py`) proving the LLM cannot override
  the `status` field even when fed an adversarial prompt-injection
  attempt, and separate manual verification (Ollama intentionally
  stopped) confirming the narration text exactly matches the
  deterministic explanation in that scenario.