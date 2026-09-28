"""
rag/vector_db.py
=================
Unified persistent vector store for ALL RAG sources in this project
(building_conditions, engineer_guide, building_code, materials_register)
-- used for open-domain, multi-source Q&A (Help Assistant today; future
admin-advisory features). NOT used by app.py/main.py's internal
compliance-citation lookup, which deliberately keeps using the isolated
rag/vector_store.py -- see app.py's own in-code comment for why.

Design decisions:
- ONE Chroma collection for every source, NOT one per source.
  Permission scoping (audience_role) is enforced via a `where` filter
  at QUERY time, not physical separation. Deliberate: the metadata IS
  the access-control mechanism being demonstrated, not incidental to
  it. A max-security production system might prefer separate
  collections as defense-in-depth -- consciously not chosen here.
- Embeddings computed via the EXISTING rag/embeddings.py
  (sentence-transformers, all-MiniLM-L6-v2), never Chroma's default
  embedding function.
- Collection explicitly created with hnsw:space="cosine". Chroma
  defaults to squared L2 -- leaving this unset would silently make
  every previously-tuned similarity score (CONFIDENCE_THRESHOLD=0.52)
  meaningless.

audience_role is a REQUIRED keyword-only argument on search() (no
default, no Optional/None path) -- deliberately changed from an
earlier `audience_role: str | None = None` signature. That version was
"fail-open": a future caller that forgot to pass audience_role would
silently get UNFILTERED results across every source and every
permission level, rather than an error. Making it required forces any
new caller (e.g. a future admin-advisory feature) to explicitly decide
which role it's querying for at the call site, at write time --
instead of a convenient-looking default silently reintroducing a
leakage risk later.
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
    """Lazily opens/creates the single persistent Chroma collection,
    once per process -- same singleton pattern already used by
    rag/embeddings.py::get_model()."""
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
    {"id": str, "text": str, "metadata": {...}}.
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


def search(
    query: str,
    top_k: int = 1,
    *,
    audience_role: str,
    extra_where: dict | None = None,
) -> list[dict]:
    """
    Returns the top_k most similar chunks to `query`, restricted to
    chunks where metadata audience_role == audience_role OR == "all" --
    applied as a Chroma `where` filter BEFORE similarity ranking.

    extra_where (NEW): an optional additional Chroma where-condition
    (e.g. {"source": "building_code"}), merged with the audience_role
    filter via "$and". This ensures top_k is applied AFTER narrowing to
    the caller's actual candidate set (e.g. one source), not on the
    whole unified collection first -- fixes a real bug found while
    building rag/hybrid_search.py: without this, a genuinely relevant
    chunk from a narrow source could rank outside the top_k of the
    ENTIRE multi-source collection and be silently lost, even though
    it would have ranked #1 within its own source.
    """
    collection = get_collection()
    if collection.count() == 0:
        return []

    query_vec = embed_text(query)
    role_filter = {"audience_role": {"$in": [audience_role, "all"]}}
    where = {"$and": [role_filter, extra_where]} if extra_where else role_filter

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
            "id": cid, "text": text, "title": meta.get("section_title"),
            "score": 1 - dist, "metadata": meta,
        })
    return chunks

if __name__ == "__main__":
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




def update_audience_role(source: str, new_role: str) -> int:
    """
    Updates ONLY the audience_role metadata field on every chunk
    belonging to `source`, leaving text/embeddings/every other
    metadata field untouched. Used when an admin corrects a mistaken
    "Visible to" choice after upload -- see
    admin/routes/knowledge.py::knowledge_edit_role().

    Chroma's collection.update() replaces the FULL metadata dict for
    each given id, not a partial merge -- so each chunk's existing
    metadata is fetched first, only audience_role is changed in that
    dict, and the whole dict is written back. This avoids silently
    dropping any other metadata field (section_title, chunk_index,
    chapter_title, etc.) that a naive partial-update could lose.
    """
    collection = get_collection()
    existing = collection.get(where={"source": source})

    if not existing["ids"]:
        return 0

    updated_metadatas = []
    for meta in existing["metadatas"]:
        meta = dict(meta)
        meta["audience_role"] = new_role
        updated_metadatas.append(meta)

    collection.update(ids=existing["ids"], metadatas=updated_metadatas)
    return len(existing["ids"])


def delete_source(source: str) -> int:
    """
    Permanently removes every chunk belonging to `source` from the
    unified collection. Used when an admin deletes an uploaded
    document -- see admin/routes/knowledge.py::knowledge_delete().
    Does NOT touch the underlying .md file on disk or the
    UploadedDocument DB row -- the caller is responsible for both,
    same separation of concerns as everywhere else in this project
    (this module only knows about the vector store).
    """
    collection = get_collection()
    existing = collection.get(where={"source": source})
    count = len(existing["ids"])

    if count > 0:
        collection.delete(where={"source": source})

    return count