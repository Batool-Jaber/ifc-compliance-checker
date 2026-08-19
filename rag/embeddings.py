"""
embeddings.py
=============
Converts text into semantic embedding vectors using a local
sentence-transformers model (no API key, no internet needed after
the first download).

This is a SECOND retrieval method, added alongside the existing
keyword-based retriever.py (not a replacement) -- the two are meant
to be compared later, not to replace one another.
"""

from sentence_transformers import SentenceTransformer

_MODEL_NAME = "all-MiniLM-L6-v2"
_model = None  # loaded lazily, once, on first use


def get_model() -> SentenceTransformer:
    """Loads the model once and reuses it (loading is the slow part)."""
    global _model
    if _model is None:
        _model = SentenceTransformer(_MODEL_NAME)
    return _model


def embed_text(text: str):
    """Returns the embedding vector (numpy array, shape (384,)) for one string."""
    model = get_model()
    return model.encode(text)


def embed_many(texts: list[str]):
    """Returns embedding vectors for a list of strings (more efficient than one-by-one)."""
    model = get_model()
    return model.encode(texts)


if __name__ == "__main__":
    import numpy as np

    def cosine_sim(a, b):
        return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

    vec = embed_text("What is the minimum room area?")
    print(f"Embedding shape: {vec.shape}")  # expect (384,)

    sent_a = "The room's internal floor area must be at least 12 square meters."
    sent_b = "What is the minimum floor area required for a room?"
    sent_c = "Emergency exits must remain unobstructed at all times."

    emb_a, emb_b, emb_c = embed_many([sent_a, sent_b, sent_c])

    print(f"Similarity (related, both about room area): {cosine_sim(emb_a, emb_b):.4f}")
    print(f"Similarity (unrelated, room area vs fire exits): {cosine_sim(emb_a, emb_c):.4f}")