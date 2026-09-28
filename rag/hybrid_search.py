"""
rag/hybrid_search.py
=====================
Generic Reciprocal Rank Fusion (RRF) combining rag/bm25_search.py
(keyword) and rag/vector_db.py::search() (embeddings) into one ranked
result list.

WHY RRF, not a weighted linear combination (e.g. 0.5*bm25 + 0.5*cosine):
BM25 scores and cosine similarity scores are not just on different
numeric scales -- they measure fundamentally different things with no
mathematically principled way to compare their raw magnitudes. A BM25
score of 12.4 vs 3.1 does not mean "4x better" the way a cosine score
of 0.8 vs 0.2 has a clear, bounded meaning -- BM25's magnitude depends
on document length and corpus-wide term statistics, not a fixed [0,1]
scale. Any linear combination would require an arbitrary normalization
scheme with no principled justification. RRF sidesteps this entirely
by using only each result's RANK (1st, 2nd, 3rd place...) in each
method's own list, never comparing raw score magnitudes across
methods. This is a standard, documented technique used by real search
systems (e.g. Elasticsearch's own RRF implementation), not a
project-specific workaround.

This module is GENERIC over its chunk source -- see module docstrings
of bm25_search.py and vector_db.py for why. The FIRST real caller
(rag/routes/proposals.py::check_building_code_route()) scopes it to
building_code chunks only, by filtering what it passes in / what
audience_role it queries with -- this module itself makes no
assumption about which source it's fusing results for.
"""

from rag.bm25_search import bm25_search
from rag.vector_db import search as embedding_search

# Standard RRF damping constant -- widely used default (e.g. in the
# original RRF paper and most production implementations), not tuned
# specifically for this project. Lower k gives more weight to items
# ranked #1; higher k flattens the difference between top ranks. 60 is
# the conventional starting point; revisit only if real testing shows
# a reason to.
RRF_K = 60


def hybrid_search(
    query: str,
    chunks: list[dict],
    top_k: int = 3,
    audience_role: str | None = None,
) -> list[dict]:
    """
    Fuses BM25 (over `chunks`, a caller-provided, already-filtered list
    -- e.g. building_code chunks only) with embeddings search (over the
    unified Chroma collection, scoped by `audience_role` exactly like
    every other embeddings call in this project) via Reciprocal Rank
    Fusion.

    Each chunk's final "rrf_score" is the sum of 1/(RRF_K + rank) across
    whichever of the two result lists it appears in (rank is 0-indexed
    position). A chunk found by only one method still gets a score
    (from that one list) -- it isn't penalized to zero just for missing
    from the other list, since a real keyword match OR a real semantic
    match are each independently meaningful signals.

    Returns chunks sorted by rrf_score descending, each with the
    original chunk fields PLUS "rrf_score", "bm25_score" (if found by
    BM25, else None), and "embedding_score" (if found by embeddings,
    else None) -- both raw scores are preserved for transparency/
    debugging, but the actual ranking decision uses ONLY rrf_score.
    """
    bm25_results = bm25_search(query, chunks, top_k=max(top_k * 3, 10))

    # Determine the source(s) this call is scoped to directly from the
    # caller-provided chunks, and pass it through to search()'s new
    # extra_where -- this is what makes top_k apply AFTER narrowing to
    # the right candidate pool, not before (see search()'s own
    # docstring for the bug this fixes).
    sources = {c["metadata"]["source"] for c in chunks if "metadata" in c and "source" in c["metadata"]}
    extra_where = {"source": {"$in": list(sources)}} if sources else None

    embedding_results = embedding_search(
        query, top_k=max(top_k * 3, 10), audience_role=audience_role, extra_where=extra_where
    )

    rrf_scores: dict[str, float] = {}
    bm25_by_id = {r["id"]: r for r in bm25_results}
    embedding_by_id = {r["id"]: r for r in embedding_results}

    for rank, r in enumerate(bm25_results):
        rrf_scores[r["id"]] = rrf_scores.get(r["id"], 0.0) + 1.0 / (RRF_K + rank)
    for rank, r in enumerate(embedding_results):
        rrf_scores[r["id"]] = rrf_scores.get(r["id"], 0.0) + 1.0 / (RRF_K + rank)

    all_ids = list(rrf_scores.keys())
    all_ids.sort(key=lambda cid: rrf_scores[cid], reverse=True)

    chunks_by_id = {c["id"]: c for c in chunks}

    results = []
    for cid in all_ids[:top_k]:
        base = dict(chunks_by_id.get(cid) or bm25_by_id.get(cid) or embedding_by_id.get(cid))
        # "title" isn't a top-level key on the caller's raw chunk dicts
        # (it's only inside metadata["section_title"]) -- fall back to
        # whichever result actually has it (bm25_search()/vector_db.search()
        # both add it explicitly), so callers can rely on r["title"]
        # existing regardless of which method(s) found this chunk.
        if "title" not in base:
            base["title"] = base.get("metadata", {}).get("section_title")
        base["rrf_score"] = rrf_scores[cid]
        base["bm25_score"] = bm25_by_id[cid]["score"] if cid in bm25_by_id else None
        base["embedding_score"] = embedding_by_id[cid]["score"] if cid in embedding_by_id else None
        results.append(base)

    return results