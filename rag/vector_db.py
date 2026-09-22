"""
rag/vector_db.py
=================
Unified persistent vector store for ALL RAG sources in this project
(building_conditions, engineer_guide, and later the building-code
regulations document) -- replaces the old in-memory rag/vector_store.py.

Design decisions (confirmed across multiple design reviews before any
code was written -- see project handoff docs):

- ONE Chroma collection for every source, NOT one collection per
  source. Permission scoping (audience_role) is enforced via a `where`
  filter at QUERY time, not via physical separation between
  collections. This is deliberate: the metadata IS the access-control
  mechanism being demonstrated here, not incidental to it. A maximum-
  security production system might prefer separate collections as
  "defense in depth" -- that trade-off is CONSCIOUSLY not taken here,
  since this project's goal is to demonstrate correct metadata-driven
  permission-aware retrieval, not production-grade defense in depth.

- Embeddings are computed via the EXISTING rag/embeddings.py
  (sentence-transformers, all-MiniLM-L6-v2), never Chroma's own default
  embedding function -- so indexing and querying always use the exact
  same model this project already tested and tuned
  help.py::CONFIDENCE_THRESHOLD against.

- The collection is explicitly created with hnsw:space="cosine".
  Chroma's default distance metric is squared L2, NOT cosine --
  leaving this unset would silently make every previously-tuned
  similarity score (including CONFIDENCE_THRESHOLD = 0.52) meaningless
  after migration. This single setting is what keeps those numbers
  valid going forward.

Unified metadata schema (every chunk upserted here must follow this):
    {
        "source": "building_conditions" | "engineer_guide" | "building_code",
        "doc_type": "condition" | "help_section" | "regulation_clause",
        "condition_id": str | None,   # explicit FK to Condition.id; None for non-DB sources
        "section_title": str,
        "audience_role": "engineer" | "admin" | "all",  # "all" = admin+engineer+viewer
        "page_number": int | None,    # only meaningful for the regulations doc
        "chunk_index": int,           # position within its own source
    }
"""

import sys
from pathlib import Path

import chromadb

sys.path.append(str(Path(__file__).parent))
from embeddings import embed_many, embed_text

_CHROMA_PATH = Path(__file__).parent.parent / "chroma_db"
_COLLECTION_NAME = "project_knowledge"

_client = None
_collection = None


def get_collection():
    """
    Lazily opens/creates the single persistent Chroma collection, once
    per process -- same singleton pattern already used by
    rag/embeddings.py::get_model() and
    admin/routes/help.py::_get_help_index().
    """
    global _client, _collection
    if _collection is None:
        _client = chromadb.PersistentClient(path=str(_CHROMA_PATH))
        _collection = _client.get_or_create_collection(
            name=_COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


def upsert_chunks(chunks: list[dict]) -> None:
    """
    Adds or updates chunks in the unified collection (add-or-replace by
    id, via Chroma's own upsert()). Each chunk dict must have:
    {"id": str, "text": str, "metadata": {...}} -- see module docstring
    for the required metadata fields.

    Calling this again with an id that already exists REPLACES that
    entry -- this is exactly what keeps the collection in sync when
    admin/services/proposal_service.py::approve_proposal() calls it
    after a live Condition changes (a future step, not yet wired up).
    """
    if not chunks:
        return

    collection = get_collection()
    ids = [c["id"] for c in chunks]
    texts = [c["text"] for c in chunks]
    metadatas = [c["metadata"] for c in chunks]
    vectors = embed_many(texts)

    collection.upsert(
        ids=ids,
        documents=texts,
        metadatas=metadatas,
        embeddings=[[float(x) for x in vec] for vec in vectors],
    )


def search(query: str, top_k: int = 1, audience_role: str | None = None) -> list[dict]:
    """
    Returns the top_k most similar chunks to `query`, each with a
    "score" key (cosine similarity, higher = more relevant -- same
    meaning and same scale as the old rag/vector_store.py, thanks to
    the explicit hnsw:space="cosine" setting above).

    If audience_role is given, results are restricted server-side to
    chunks where metadata audience_role == audience_role OR == "all" --
    applied as a Chroma `where` filter BEFORE similarity ranking
    (permission-aware retrieval), never as a post-hoc filter on
    already-ranked results.
    """
    collection = get_collection()
    if collection.count() == 0:
        return []

    query_vec = embed_text(query)
    where = None
    if audience_role is not None:
        where = {"audience_role": {"$in": [audience_role, "all"]}}

    result = collection.query(
        query_embeddings=[[float(x) for x in query_vec]],
        n_results=top_k,
        where=where,
    )

    chunks = []
    for cid, text, meta, dist in zip(
        result["ids"][0], result["documents"][0], result["metadatas"][0], result["distances"][0]
    ):
        chunks.append({
            "id": cid,
            "text": text,
            "title": meta.get("section_title"),
            "score": 1 - dist,  # cosine space: distance = 1 - similarity
            "metadata": meta,
        })
    return chunks


if __name__ == "__main__":
    # Smoke test -- confirms Chroma + embeddings.py wiring works end to
    # end, with zero dependency on Flask/the rest of the app.
    sample_chunks = [
        {
            "id": "test_1",
            "text": "The room's internal floor area must be at least 12 square meters.",
            "metadata": {
                "source": "building_conditions", "doc_type": "condition",
                "condition_id": "room_area", "section_title": "Minimum Room Area",
                "audience_role": "all", "page_number": None, "chunk_index": 0,
            },
        },
        {
            "id": "test_2",
            "text": "Only an admin can view or approve pending proposals.",
            "metadata": {
                "source": "engineer_guide", "doc_type": "help_section",
                "condition_id": None, "section_title": "Admin Approval",
                "audience_role": "admin", "page_number": None, "chunk_index": 1,
            },
        },
    ]

    upsert_chunks(sample_chunks)
    print(f"Collection now has {get_collection().count()} chunks total.")

    print("\nQuery as engineer (should NOT see the admin-only chunk):")
    for r in search("what is the minimum floor area", top_k=2, audience_role="engineer"):
        print(f"  [{r['id']}] score={r['score']:.4f} -- {r['metadata']['audience_role']}")

    print("\nQuery as admin (CAN see both):")
    for r in search("who can approve proposals", top_k=2, audience_role="admin"):
        print(f"  [{r['id']}] score={r['score']:.4f} -- {r['metadata']['audience_role']}")