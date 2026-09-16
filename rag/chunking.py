"""
chunking.py
===========
Splits building_conditions.md into retrievable chunks — one chunk per
"## Condition" section, since that's the natural retrieval unit here.

load_and_chunk() is UNCHANGED -- kept exactly as-is for standalone
diagnostics (its __main__ block, compare_retrieval.py's default run,
etc.), reading from the static file as before.

build_chunks_from_conditions() is NEW: builds the same chunk shape
({id, title, text}) from a list of condition dicts passed in directly
(coming from the live `conditions` DB table via main.py), so this
module has zero knowledge of Flask/SQLAlchemy -- same isolation
principle as validation/generic_engine.py. This is what the LIVE
pipeline (main.py) uses going forward; load_and_chunk() remains the
seed/standalone-diagnostic path only.
"""

import re
from pathlib import Path

KB_PATH = Path("knowledge_base/building_conditions.md")


def load_and_chunk(path: Path = KB_PATH) -> list[dict]:
    text = path.read_text(encoding="utf-8")

    # Split on "## " headers (each condition becomes one chunk)
    sections = re.split(r"\n(?=## )", text)
    chunks = []
    for section in sections:
        section = section.strip()
        if not section or section.startswith("# Building"):
            continue
        title = section.split("\n")[0].replace("## ", "").strip()
        chunks.append({"id": len(chunks), "title": title, "text": section})

    return chunks


def build_chunks_from_conditions(conditions: list[dict]) -> list[dict]:
    """
    Builds the SAME chunk shape as load_and_chunk() ({id, title, text}),
    but from a list of plain condition dicts passed in directly --
    e.g. [{"title": "...", "description": "..."}, ...] -- instead of
    reading the static knowledge_base/building_conditions.md file.

    This is what makes admin-approved conditions (original 3 AND any
    brand-new ones) retrievable by both retriever.py and
    vector_store.py without either of those files needing any change --
    they only care about the {id, title, text} shape, not where it
    came from.

    `text` is built as "## {title}\n{description}" to match the exact
    section shape load_and_chunk() produces from the markdown file, so
    a chunk from this function and a chunk from load_and_chunk() are
    indistinguishable to any retrieval code that consumes them.
    """
    chunks = []
    for condition in conditions:
        title = condition["title"]
        description = condition.get("description", "")
        text = f"## {title}\n{description}".strip()
        chunks.append({"id": len(chunks), "title": title, "text": text})
    return chunks


if __name__ == "__main__":
    chunks = load_and_chunk()
    for c in chunks:
        print(f"[{c['id']}] {c['title']}")
        print(c["text"])
        print("---")