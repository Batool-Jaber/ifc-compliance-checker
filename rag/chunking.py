"""
chunking.py
===========
Splits building_conditions.md into retrievable chunks — one chunk per
"## Condition" section, since that's the natural retrieval unit here.
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


if __name__ == "__main__":
    chunks = load_and_chunk()
    for c in chunks:
        print(f"[{c['id']}] {c['title']}")
        print(c["text"])
        print("---")