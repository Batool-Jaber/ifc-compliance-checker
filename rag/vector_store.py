"""
vector_store.py
================
Minimal in-memory vector store: no FAISS/Chroma, just a numpy matrix
of chunk embeddings + cosine-similarity search. Chosen deliberately
(see project notes) since 3 chunks is far too small to justify an
external vector database.

This is the EMBEDDINGS-based retrieval path, kept alongside (not
replacing) the existing keyword-based retriever.py, so the two can be
compared later.
"""

import sys
from pathlib import Path

import numpy as np

sys.path.append(str(Path(__file__).parent))
from embeddings import embed_many, embed_text


def build_index(chunks: list[dict]) -> dict:
    """
    Computes and stores one embedding per chunk.

    Returns an "index" dict: {"chunks": [...], "vectors": np.ndarray of
    shape (N, 384)}. Kept as a plain dict (not a class) to match the
    simple, dependency-free style of the rest of rag/.
    """
    if not chunks:
        return {"chunks": [], "vectors": np.zeros((0, 384))}

    texts = [c["text"] for c in chunks]
    vectors = embed_many(texts)  # shape (N, 384)
    return {"chunks": chunks, "vectors": np.asarray(vectors)}


def _cosine_sim(query_vec: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """query_vec: (D,)  matrix: (N, D)  -> returns (N,) similarity scores."""
    if matrix.shape[0] == 0:
        return np.zeros(0)
    query_norm = query_vec / np.linalg.norm(query_vec)
    matrix_norms = matrix / np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix_norms @ query_norm


def search(query: str, index: dict, top_k: int = 1) -> list[dict]:
    """
    Embeds the query and returns the top_k most similar chunks from
    the index, each with an added "score" key (cosine similarity,
    higher = more relevant). Returns [] if the index is empty.
    """
    if not index["chunks"]:
        return []

    query_vec = embed_text(query)
    scores = _cosine_sim(query_vec, index["vectors"])

    top_indices = np.argsort(scores)[::-1][:top_k]
    results = []
    for i in top_indices:
        chunk_with_score = dict(index["chunks"][i])
        chunk_with_score["score"] = float(scores[i])
        results.append(chunk_with_score)
    return results


if __name__ == "__main__":
    from chunking import load_and_chunk

    chunks = load_and_chunk()
    index = build_index(chunks)
    print(f"Indexed {len(index['chunks'])} chunks, vector shape: {index['vectors'].shape}")

    test_queries = [
        "what is the minimum room area",
        "window area percentage requirement",
        "sill height range",
    ]

    for q in test_queries:
        print(f"\nQuery: {q}")
        results = search(q, index, top_k=1)
        for r in results:
            print(f"  -> [{r['id']}] {r['title']}  (score={r['score']:.4f})")