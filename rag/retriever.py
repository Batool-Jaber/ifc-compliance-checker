"""
retriever.py
============
Keyword-based retrieval with two improvements over naive word overlap:
1. Common stop words are excluded (they match everywhere and add noise).
2. Matches in the chunk's title are weighted higher than matches in the
   body text, since the title is the strongest signal of relevance.
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))
from chunking import load_and_chunk

STOP_WORDS = {
    "a", "an", "the", "is", "are", "was", "were", "what", "which", "who",
    "how", "when", "where", "of", "for", "to", "in", "on", "at", "and",
    "or", "must", "be", "this", "that", "it", "its", "with", "as"
}

TITLE_WEIGHT = 3
BODY_WEIGHT = 1


def _keywords(text: str) -> set[str]:
    words = text.lower().replace("(", " ").replace(")", " ").split()
    return {w.strip(".,%") for w in words if w.strip(".,%") not in STOP_WORDS}


def retrieve(query: str, chunks: list[dict], top_k: int = 1) -> list[dict]:
    query_words = _keywords(query)

    scored = []
    for chunk in chunks:
        title_words = _keywords(chunk["title"])
        body_words = _keywords(chunk["text"])

        title_overlap = len(query_words & title_words)
        body_overlap = len(query_words & body_words)

        score = (title_overlap * TITLE_WEIGHT) + (body_overlap * BODY_WEIGHT)
        scored.append((score, chunk))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [chunk for score, chunk in scored[:top_k] if score > 0]


if __name__ == "__main__":
    chunks = load_and_chunk()

    test_queries = [
        "what is the minimum room area",
        "window area percentage requirement",
        "sill height range",
    ]

    for q in test_queries:
        print(f"Query: {q}")
        results = retrieve(q, chunks)
        for r in results:
            print(f"  -> [{r['id']}] {r['title']}")
        print()