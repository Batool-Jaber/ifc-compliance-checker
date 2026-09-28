"""
rag/bm25_search.py
===================
Real BM25 keyword search (via the rank_bm25 library), deliberately
separate from both rag/retriever.py (the existing simple word-overlap +
title-weighting matcher, kept for its own comparison purpose against
embeddings -- see rag/compare_retrieval.py) and rag/vector_db.py (the
unified Chroma embeddings store).

WHY rank_bm25 instead of upgrading retriever.py: retriever.py's current
matching (stop-words + title weighting) is NOT real BM25 -- it has no
term-frequency saturation or document-length normalization, the two
things that actually make BM25 BM25. Calling it "BM25" without the real
algorithm would be indefensible in a technical interview. This module
uses the actual, documented algorithm instead.

This module is GENERIC -- it operates on any list of chunks in the
{id, title, text, metadata} shape already used everywhere else in this
project's RAG code (rag/chunking.py, rag/vector_db.py). It has zero
knowledge of which source ("building_code", "engineer_guide", etc.) the
chunks came from -- the caller decides that by which chunks it passes
in. This genericity is deliberate: the first real use is scoped narrowly
to building_code chunks only (see rag/hybrid_search.py), but the
function itself must not assume that scope, so widening to other
sources later needs zero changes here (same lesson already learned from
the SOURCE_CONFIG duplication discussion elsewhere in this project).
"""

from rank_bm25 import BM25Okapi


def _tokenize(text: str) -> list[str]:
    """Minimal, deliberately simple whitespace + lowercase tokenizer.
    BM25's own term-frequency/document-length math is what does the
    real work here -- a fancier tokenizer (stemming, etc.) is a
    separate, optional improvement, not required to have a genuine
    BM25 implementation."""
    return text.lower().split()


def bm25_search(query: str, chunks: list[dict], top_k: int = 5) -> list[dict]:
    """
    Ranks `chunks` (each a dict with at least "id" and "text") against
    `query` using real BM25 (Okapi variant, via rank_bm25). Returns the
    top_k chunks augmented with a "score" key (raw BM25 score -- NOT
    comparable across different queries or corpora, and NOT meant to
    be compared directly to a cosine-similarity score; see
    rag/hybrid_search.py's use of Reciprocal Rank Fusion, which
    deliberately avoids ever comparing these raw scores to embedding
    scores).

    Returns [] if `chunks` is empty.
    """
    if not chunks:
        return []

    tokenized_corpus = [_tokenize(c["text"]) for c in chunks]
    bm25 = BM25Okapi(tokenized_corpus)

    scores = bm25.get_scores(_tokenize(query))

    ranked = sorted(zip(chunks, scores), key=lambda pair: pair[1], reverse=True)

    results = []
    for chunk, score in ranked[:top_k]:
        result = dict(chunk)
        result["score"] = float(score)
        results.append(result)
    return results