"""
rag/migrate_to_chroma.py
=========================
Populates the unified Chroma collection (rag/vector_db.py) from ALL
FOUR RAG sources in this project:
- building_conditions: live rows from the `conditions` DB table
- engineer_guide: the static knowledge_base/help/engineer_guide.md file
- building_code: knowledge_base/regulations/building_code_regulations.md
  (two-level Chapter/Article structure -- see chunking.py::load_regulations_chunks())
- materials_register: knowledge_base/materials/approved_materials_register.pdf
  (real PDF extraction -- see pdf_chunking.py)

sync_building_conditions() is called from TWO places:
1. This file's own __main__ block, for a full one-off migration.
2. admin/services/proposal_service.py::approve_proposal(), after every
   approval, to keep Chroma in sync with the live `conditions` table.
   Re-syncing ALL conditions (not just the one that changed) keeps
   chunk_index correct and consistent, and is cheap at this project's
   scale -- avoids a second, divergent partial-update code path.
   VERIFIED end-to-end through the real admin UI (proposal edit ->
   approve -> fresh Chroma query reflects the new value).

sync_engineer_guide() and sync_building_code() read STATIC files -- no
Flask app context needed, never called from proposal_service.py (their
source files don't change through the app's UI).

sync_materials_register() also reads a STATIC file (the PDF) -- same
category as the two above.

Safe to re-run: upsert_chunks() replaces existing ids in place, so
running this multiple times never creates duplicates.
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))
sys.path.append(str(Path(__file__).parent.parent))

from chunking import load_and_chunk, load_regulations_chunks
from pdf_chunking import load_and_chunk as load_pdf_chunks
from vector_db import upsert_chunks, get_collection

HELP_KB_PATH = Path("knowledge_base/help/engineer_guide.md")
BUILDING_CODE_PATH = Path("knowledge_base/regulations/building_code_regulations.md")
MATERIALS_PDF_PATH = "knowledge_base/materials/approved_materials_register.pdf"


def sync_building_conditions() -> int:
    """
    Reads every LIVE row from the `conditions` DB table (requires a
    Flask app context) and upserts one chunk per condition -- same
    text shape ("## {title}\n{description}") that
    rag/chunking.py::build_chunks_from_conditions() already produces,
    so retrieval quality doesn't change, only where it's stored.

    audience_role is "all": this data is currently shown to any
    logged-in user via the main tool's Conditions reference panel and
    Retrieval Process panel, regardless of role.
    """
    from admin.models import Condition

    conditions = Condition.query.order_by(Condition.title).all()
    chunks = []
    for i, condition in enumerate(conditions):
        text = f"## {condition.title}\n{condition.description}".strip()
        chunks.append({
            "id": f"building_conditions::{condition.id}",
            "text": text,
            "metadata": {
                "source": "building_conditions",
                "doc_type": "condition",
                "condition_id": condition.id,
                "section_title": condition.title,
                "audience_role": "all",
                "page_number": None,
                "chunk_index": i,
            },
        })
    upsert_chunks(chunks)
    return len(chunks)


def sync_engineer_guide() -> int:
    """
    Reads knowledge_base/help/engineer_guide.md via the EXISTING
    load_and_chunk() (unchanged) and upserts one chunk per section.
    audience_role is "engineer" -- matches the Help Assistant's current
    access restriction exactly.
    """
    chunks_raw = load_and_chunk(HELP_KB_PATH)
    chunks = []
    for i, c in enumerate(chunks_raw):
        chunks.append({
            "id": f"engineer_guide::{c['id']}",
            "text": c["text"],
            "metadata": {
                "source": "engineer_guide",
                "doc_type": "help_section",
                "condition_id": None,
                "section_title": c["title"],
                "audience_role": "engineer",
                "page_number": None,
                "chunk_index": i,
            },
        })
    upsert_chunks(chunks)
    return len(chunks)


def sync_building_code() -> int:
    """
    Reads knowledge_base/regulations/building_code_regulations.md via
    load_regulations_chunks() (two-level Chapter/Article splitting,
    NOT the single-level "## " splitting load_and_chunk() uses -- see
    that function's own docstring for why this document needed its own
    parser) and upserts one chunk per Article.

    audience_role is "admin" -- a RECOMMENDATION, not a confirmed
    supervisor instruction (see project handoff notes). Matches
    roadmap "idea 4.5": a strictly-advisory layer shown to an admin
    before approving a proposal, never a hard gate.

    page_number is deliberately null: this document has no literal
    page numbers, it's organized by Chapter/Article numbering instead
    -- chapter_number/chapter_title/article_number carry that
    structure, which is more useful for citation than a page number
    would have been anyway.
    """
    chunks_raw = load_regulations_chunks(BUILDING_CODE_PATH)
    chunks = []
    for i, c in enumerate(chunks_raw):
        chunks.append({
            "id": f"building_code::{c['article_number'] or c['id']}",
            "text": c["text"],
            "metadata": {
                "source": "building_code",
                "doc_type": "regulation_clause",
                "condition_id": None,
                "section_title": c["title"],
                "chapter_title": c["chapter_title"],
                "article_number": c["article_number"] or "",
                "audience_role": "admin",
                "page_number": None,
                "chunk_index": i,
            },
        })
    upsert_chunks(chunks)
    return len(chunks)


def sync_materials_register() -> int:
    """
    Reads knowledge_base/materials/approved_materials_register.pdf via
    the EXISTING pdf_chunking.py (real, non-scanned PDF extraction --
    font-size classification + a literal "Product Code: ... |
    Manufacturer: ..." anchor for product boundaries, tables
    linearized separately, header/footer stripped by BOTH position and
    frequency) and upserts one chunk per product.

    # TODO(schema): audience_role currently a flat enum (engineer/admin/all).
    # A 4th source (materials_register) already wants "engineer+admin, not viewer" --
    # not expressible without a list, which Chroma metadata doesn't support.
    # Deferred hierarchical minimum_role_rank design exists (see: convo 2026-09-22).
    # Trigger to implement: the moment a route needs to query admin+engineer together.
    # Verified via grep (2026-09-22): zero current callers pass more than one role
    # to search(), so this simplification has zero practical effect today.

    Extra source-specific metadata fields (beyond the shared schema):
    category, product_code, manufacturer -- mirrors how building_code
    added chapter_title/article_number as its own extra fields.
    """
    raw_chunks = load_pdf_chunks(MATERIALS_PDF_PATH)

    chunks = []
    for i, c in enumerate(raw_chunks):
        chunks.append({
            "id": f"materials_register::{c.metadata['product_code']}",
            "text": c.text,
            "metadata": {
                "source": "materials_register",
                "doc_type": "product_datasheet",
                "condition_id": None,
                "section_title": c.metadata["product_name"],
                "category": c.metadata["category"],
                "product_code": c.metadata["product_code"],
                "manufacturer": c.metadata["manufacturer"],
                "audience_role": "engineer",
                "page_number": c.metadata["page"],
                "chunk_index": i,
            },
        })
    upsert_chunks(chunks)
    return len(chunks)


if __name__ == "__main__":
    from app import app  # reuses the existing Flask app object/config

    with app.app_context():
        n1 = sync_building_conditions()

    n2 = sync_engineer_guide()      # static file, no app context needed
    n3 = sync_building_code()       # static file, no app context needed
    n4 = sync_materials_register()  # static file, no app context needed

    total = get_collection().count()
    print(
        f"Migrated {n1} building_conditions + {n2} engineer_guide + "
        f"{n3} building_code + {n4} materials_register chunks."
    )
    print(f"Collection total: {total} chunks.")