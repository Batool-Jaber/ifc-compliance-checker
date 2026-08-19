"""
compare_retrieval.py
=====================
Runs the SAME set of test queries through both retrieval methods --
the original keyword-based retriever.py and the newer embeddings-based
vector_store.py -- and reports accuracy for each.

Includes deliberately "easy" queries (literal keyword overlap with the
rule text) and "hard" queries (same meaning, different wording, no
literal keyword overlap) to demonstrate WHERE and WHY embeddings-based
semantic retrieval outperforms simple keyword matching.

Neither retrieval method is used to make the PASS/FAIL decision --
this script only measures retrieval QUALITY (does it find the right
rule text?), which is a separate concern from validation.
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))

from chunking import load_and_chunk
from retriever import retrieve as keyword_retrieve
from vector_store import build_index, search as embedding_search

TEST_QUERIES = [
    {"query": "what is the minimum room area", "expected_id": 0, "difficulty": "easy"},
    {"query": "window area percentage requirement", "expected_id": 1, "difficulty": "easy"},
    {"query": "sill height range", "expected_id": 2, "difficulty": "easy"},
    {"query": "how small can a bedroom be", "expected_id": 0, "difficulty": "hard"},
    {"query": "how much daylight does a room need", "expected_id": 1, "difficulty": "hard"},
    {"query": "is it safe for a window to be very close to the floor", "expected_id": 2, "difficulty": "hard"},
]


def run_comparison():
    chunks = load_and_chunk()
    index = build_index(chunks)

    rows = []
    for tq in TEST_QUERIES:
        kw_results = keyword_retrieve(tq["query"], chunks, top_k=1)
        kw_id = kw_results[0]["id"] if kw_results else None
        kw_correct = kw_id == tq["expected_id"]

        emb_results = embedding_search(tq["query"], index, top_k=1)
        emb_id = emb_results[0]["id"] if emb_results else None
        emb_score = emb_results[0]["score"] if emb_results else None
        emb_correct = emb_id == tq["expected_id"]

        rows.append({
            "query": tq["query"],
            "difficulty": tq["difficulty"],
            "expected_id": tq["expected_id"],
            "keyword_id": kw_id,
            "keyword_correct": kw_correct,
            "embedding_id": emb_id,
            "embedding_score": emb_score,
            "embedding_correct": emb_correct,
        })

    return rows


def print_report(rows):
    print(f"{'Difficulty':<6} {'Query':<55} {'Keyword':<10} {'Embedding':<12}")
    print("-" * 90)
    for r in rows:
        kw_mark = "OK" if r["keyword_correct"] else "WRONG"
        emb_mark = "OK" if r["embedding_correct"] else "WRONG"
        print(f"{r['difficulty']:<6} {r['query'][:53]:<55} {kw_mark:<10} {emb_mark:<12}")

    kw_acc = sum(r["keyword_correct"] for r in rows) / len(rows)
    emb_acc = sum(r["embedding_correct"] for r in rows) / len(rows)

    easy_rows = [r for r in rows if r["difficulty"] == "easy"]
    hard_rows = [r for r in rows if r["difficulty"] == "hard"]
    kw_hard_acc = sum(r["keyword_correct"] for r in hard_rows) / len(hard_rows) if hard_rows else None
    emb_hard_acc = sum(r["embedding_correct"] for r in hard_rows) / len(hard_rows) if hard_rows else None

    print("-" * 90)
    print(f"Overall accuracy   -> keyword: {kw_acc:.0%}   embeddings: {emb_acc:.0%}")
    print(f"Hard-query accuracy -> keyword: {kw_hard_acc:.0%}   embeddings: {emb_hard_acc:.0%}")


if __name__ == "__main__":
    rows = run_comparison()
    print_report(rows)