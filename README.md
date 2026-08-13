# AI-Assisted IFC Compliance Checker

An AI-assisted application that checks a BIM/IFC building model against
written building compliance rules, combining **Python**, **IfcOpenShell**,
**RAG** (Retrieval-Augmented Generation), and **deterministic validation**.

## Status
🚧 Work in progress — built incrementally as part of a Junior AI Developer
technical assessment.

## What's implemented so far
- `generate_ifc.py` — generates a small IFC4 model (1 building, 1 storey,
  1 enclosed room, 4 walls, 1 window installed via a proper
  `IfcOpeningElement`) with clean, fully-controlled geometry.
- `inspect_ifc.py` — general-purpose IFC inspection CLI tool (schema,
  element counts, spatial hierarchy, property/quantity sets, relationships).
- `extract_ifc_data.py` — dynamic extraction of compliance-relevant data
  (room floor area, window width/height/area, window sill height) from
  any IFC file following this structure — no hardcoded IDs or names.

## Coming next
- Building requirements knowledge source + RAG retrieval pipeline
- Deterministic compliance validation (PASS / FAIL / CANNOT_BE_EVALUATED)
- JSON/HTML compliance report
- Automated tests (compliant / violation / missing data)
- Full documentation (architecture, setup, assumptions & limitations)

## Quick start
```bash
pip install -r requirements.txt
python generate_ifc.py
python extract_ifc_data.py
python inspect_ifc.py data/generated/compliant_model.ifc
```