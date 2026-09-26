"""
rag/knowledge_upload.py
=========================
Live upload path for admin-added markdown knowledge sources -- distinct
from rag/migrate_to_chroma.py's sync_*() functions, which are hand-
written for the 4 KNOWN sources (building_conditions, engineer_guide,
building_code, materials_register) and run as a one-off/manual
migration script. This module handles a NEW source whose name/shape
isn't known ahead of time, arriving via a live admin request.

Both paths write to the exact same place: rag/vector_db.py's
upsert_chunks() into the ONE unified Chroma collection
(project_knowledge). There is no separate storage here -- "where the
data lives" was unified per the project's core requirement; this file
only concerns itself with "how do we turn an admin's uploaded .md file
into chunks", the same way each existing sync_*() function does for
its own fixed source.

QUALITY CHECK (analyze_markdown_quality): runs BEFORE the admin can
confirm a new source. Returns WARNINGS ONLY, never a hard block --
same "system informs, human decides" principle already applied to the
Safe Tester and Building Code Advisory features. A section that's
unusually long, or a duplicate title, or a vague back-reference
("as mentioned above") is very often a real content problem, but the
admin -- not this heuristic -- makes the final call.
"""

import re
import statistics
from pathlib import Path

from rag.chunking import load_and_chunk, load_regulations_chunks
from rag.vector_db import upsert_chunks

UPLOAD_DIR = Path("knowledge_base/uploaded")

# Loose, deliberately simple patterns for vague back-references that
# only make sense to a human reading the ORIGINAL document in order --
# they lose all meaning once a section becomes an independently-
# retrieved RAG chunk with no guaranteed neighboring context.
_VAGUE_REFERENCE_PATTERNS = [
    r"as (?:mentioned|noted|stated|discussed) (?:above|earlier|previously)",
    r"(?:the|see) (?:previous|above|preceding) (?:section|article|chapter)",
    r"as (?:above|before)\b",
]


def chunk_uploaded_file(path: Path, split_mode: str) -> list[dict]:
    """
    Splits an uploaded markdown file using the SAME two chunking
    functions every other markdown source in this project already
    uses -- load_and_chunk() for "single_level", load_regulations_chunks()
    for "two_level". No new chunking logic is introduced here; this
    function only picks which existing one to call.
    """
    if split_mode == "single_level":
        return load_and_chunk(path)
    elif split_mode == "two_level":
        return load_regulations_chunks(path)
    else:
        raise ValueError(f"Unknown split_mode '{split_mode}'")


def analyze_markdown_quality(chunks: list[dict]) -> dict:
    """
    Read-only heuristic quality check over an already-chunked document.
    Returns {"warnings": [str, ...], "stats": {...}} -- NEVER raises,
    NEVER blocks. The admin sees every warning plus the raw stats and
    decides whether to confirm the upload anyway.
    """
    warnings = []

    if len(chunks) == 0:
        warnings.append(
            "Zero sections were found. The chosen split mode may not match "
            "this file's actual heading structure -- check the file uses "
            "'## ' headers (single-level) or '## Chapter' + '### Article' "
            "headers (two-level)."
        )
        return {"warnings": warnings, "stats": {"section_count": 0}}

    if len(chunks) == 1:
        warnings.append(
            "Only 1 section was found. If this file has multiple real "
            "topics, they'll all be retrieved as one oversized chunk -- "
            "double-check the heading structure matches the chosen split mode."
        )

    lengths = [len(c["text"]) for c in chunks]
    mean_len = statistics.mean(lengths)
    stdev_len = statistics.pstdev(lengths) if len(lengths) > 1 else 0

    # Sections more than 2 standard deviations from the mean length --
    # a simple, standard outlier signal, not a hard rule. On documents
    # with very few sections this naturally flags less (there's not
    # enough spread to compute a meaningful outlier), which is the
    # correct, honest behavior rather than a false sense of precision.
    outliers = []
    if stdev_len > 0:
        for c, length in zip(chunks, lengths):
            if abs(length - mean_len) > 2 * stdev_len:
                outliers.append((c["title"], length))

    for title, length in outliers:
        warnings.append(
            f"Section '{title}' is {length} characters, unusually "
            f"{'long' if length > mean_len else 'short'} compared to the "
            f"document's average ({mean_len:.0f} chars). Consider whether "
            f"it should be split further or merged."
        )

    titles = [c["title"] for c in chunks]
    seen = set()
    duplicates = set()
    for t in titles:
        if t in seen:
            duplicates.add(t)
        seen.add(t)
    for dup in duplicates:
        warnings.append(
            f"The title '{dup}' appears more than once. Duplicate titles "
            f"can make retrieved results ambiguous to whoever reads them."
        )

    for c in chunks:
        for pattern in _VAGUE_REFERENCE_PATTERNS:
            if re.search(pattern, c["text"], re.IGNORECASE):
                warnings.append(
                    f"Section '{c['title']}' contains a vague reference "
                    f"(e.g. \"as mentioned above\") that assumes reading "
                    f"order -- this won't make sense once retrieved as a "
                    f"standalone chunk. Consider naming the section/article "
                    f"explicitly instead."
                )
                break  # one warning per section is enough, don't repeat per pattern

    return {
        "warnings": warnings,
        "stats": {
            "section_count": len(chunks),
            "avg_length": round(mean_len),
            "min_length": min(lengths),
            "max_length": max(lengths),
        },
    }


def sync_uploaded_markdown(
    source_name: str, file_path: Path, split_mode: str, audience_role: str
) -> int:
    """
    Chunks an already-saved uploaded file and upserts it into the
    unified Chroma collection -- the SAME upsert_chunks() every other
    source (building_conditions, engineer_guide, building_code,
    materials_register) already uses. No separate storage, no parallel
    index -- this is the "live upload" counterpart to
    rag/migrate_to_chroma.py's hand-written sync_*() functions, for a
    source whose name/shape wasn't known ahead of time.
    """
    chunks_raw = chunk_uploaded_file(file_path, split_mode)

    chunks = []
    for i, c in enumerate(chunks_raw):
        metadata = {
            "source": source_name,
            "doc_type": "uploaded_document",
            "condition_id": None,
            "section_title": c["title"],
            "audience_role": audience_role,
            "page_number": None,
            "chunk_index": i,
        }
        # two_level chunks carry extra keys (chapter_title,
        # article_number) -- same pattern building_code's own metadata
        # already uses, kept here too so an uploaded two-level document
        # cites just as precisely.
        if split_mode == "two_level":
            metadata["chapter_title"] = c.get("chapter_title")
            metadata["article_number"] = c.get("article_number") or ""

        chunks.append({
            "id": f"{source_name}::{c['id']}",
            "text": c["text"],
            "metadata": metadata,
        })

    upsert_chunks(chunks)
    return len(chunks)