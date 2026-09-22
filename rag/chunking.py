"""
chunking.py
===========
Splits a markdown knowledge-base file into retrievable chunks -- one
chunk per "## " section, since that's the natural retrieval unit.

load_and_chunk() reads knowledge_base/building_conditions.md by
default, but accepts any `path` -- this is what makes it reusable for
knowledge_base/help/engineer_guide.md too (see rag/migrate_to_chroma.py).
The intro-section check was generalized from the literal
`section.startswith("# Building")` to `section.startswith("# ")` so it
correctly discards the leading H1 + intro paragraph of ANY markdown
file that starts with a single "# " title line, not just
building_conditions.md specifically. This is a no-op for
building_conditions.md itself (its title already starts with
"# Building...", so it still matches) -- confirmed safe, no behavior
change for any existing caller (main.py, retriever.py, vector_store.py,
compare_retrieval.py -- none of them assert anything about this specific
string, only about the resulting chunk list).

build_chunks_from_conditions() builds the same chunk shape
({id, title, text}) from a list of condition dicts passed in directly
(coming from the live `conditions` DB table via main.py), so this
module has zero knowledge of Flask/SQLAlchemy -- same isolation
principle as validation/generic_engine.py. This is what the LIVE
compliance-check pipeline (main.py) uses; load_and_chunk() remains the
path for any static markdown file with SINGLE-LEVEL "## " headers
(the original seed/standalone-diagnostic file, or the Help Assistant's
engineer_guide.md).

load_regulations_chunks() is separate from load_and_chunk() because
knowledge_base/regulations/building_code_regulations.md has a
TWO-LEVEL heading structure ("## Chapter N -- Title" grouping several
"### Article N.M -- Title" sections each) -- splitting on "## " alone
(as load_and_chunk() does) would produce one oversized, topically-mixed
chunk per CHAPTER instead of one focused chunk per ARTICLE. This is a
genuinely different document shape, not a near-duplicate of
load_and_chunk() the way an earlier (reverted) load_help_chunks() draft
was for engineer_guide.md -- that one differed from load_and_chunk() by
a single skip condition; this one needs real two-level parsing.
"""

import re
from pathlib import Path

KB_PATH = Path("knowledge_base/building_conditions.md")


def load_and_chunk(path: Path = KB_PATH) -> list[dict]:
    text = path.read_text(encoding="utf-8")

    # Split on "## " headers (each section becomes one chunk)
    sections = re.split(r"\n(?=## )", text)
    chunks = []
    for section in sections:
        section = section.strip()
        if not section or section.startswith("# "):
            continue
        title = section.split("\n")[0].replace("## ", "").strip()
        chunks.append({"id": len(chunks), "title": title, "text": section})

    return chunks


def build_chunks_from_conditions(conditions: list[dict]) -> list[dict]:
    """
    Builds the SAME chunk shape as load_and_chunk() ({id, title, text}),
    but from a list of plain condition dicts passed in directly --
    e.g. [{"title": "...", "description": "..."}, ...] -- instead of
    reading a static markdown file.

    This is what makes admin-approved conditions (original 3 AND any
    brand-new ones) retrievable by both retriever.py and
    vector_store.py without either of those files needing any change --
    they only care about the {id, title, text} shape, not where it
    came from.

    `text` is built as "## {title}\n{description}" to match the exact
    section shape load_and_chunk() produces from a markdown file, so a
    chunk from this function and a chunk from load_and_chunk() are
    indistinguishable to any retrieval code that consumes them.
    """
    chunks = []
    for condition in conditions:
        title = condition["title"]
        description = condition.get("description", "")
        text = f"## {title}\n{description}".strip()
        chunks.append({"id": len(chunks), "title": title, "text": text})
    return chunks


def load_regulations_chunks(path: Path) -> list[dict]:
    """
    Splits a two-level markdown document (## Chapter N -- Title,
    ### Article N.M -- Title) into one chunk PER ARTICLE, not per
    chapter. See module docstring for why this needs its own function
    instead of reusing/generalizing load_and_chunk().

    Each returned dict has: id, title (the article's own title), text
    (the full article block including its "### Article N.M -- Title"
    header), chapter_number, chapter_title, article_number.
    """
    text = path.read_text(encoding="utf-8")
    chapter_blocks = re.split(r"\n(?=## Chapter)", text)

    chunks = []
    for chapter_block in chapter_blocks:
        chapter_block = chapter_block.strip()
        if not chapter_block.startswith("## Chapter"):
            continue  # the "# Title" front matter before the first chapter

        chapter_header = chapter_block.split("\n")[0]
        chapter_match = re.match(r"## Chapter (\d+) — (.+)", chapter_header)
        chapter_number = chapter_match.group(1) if chapter_match else None
        chapter_title = chapter_match.group(2).strip() if chapter_match else chapter_header

        article_blocks = re.split(r"\n(?=### Article)", chapter_block)
        for article_block in article_blocks:
            article_block = article_block.strip()
            if not article_block.startswith("### Article"):
                continue  # the chapter header line itself, already captured above

            article_header = article_block.split("\n")[0]
            article_match = re.match(r"### Article ([\d.]+) — (.+)", article_header)
            article_number = article_match.group(1) if article_match else None
            article_title = article_match.group(2).strip() if article_match else article_header

            chunks.append({
                "id": len(chunks),
                "title": article_title,
                "text": article_block,
                "chapter_number": chapter_number,
                "chapter_title": chapter_title,
                "article_number": article_number,
            })

    return chunks


if __name__ == "__main__":
    chunks = load_and_chunk()
    for c in chunks:
        print(f"[{c['id']}] {c['title']}")
        print(c["text"])
        print("---")