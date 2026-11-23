"""Embed, store, retrieve, and rerank document chunks.

Collections explicitly use cosine distance because the relevance threshold is
calibrated against cosine scores. The default local embedder is Chroma's ONNX
build of `all-MiniLM-L6-v2` (384 dimensions), avoiding a PyTorch dependency.
`search` preserves cosine distances for the relevance gate while returning
candidates in combined semantic and BM25 rank order.
"""

import os
import shutil
from dataclasses import dataclass

import re
from rank_bm25 import BM25Okapi

# Must be set BEFORE chromadb is imported. Without it, some Chroma versions
# print "Failed to send telemetry event ..." on every call even though the
# underlying Chroma operation succeeds.
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

import chromadb  # noqa: E402

import config
from chunker import Chunk


@dataclass
class Result:
    """One retrieved chunk and how far it was from the question."""

    text: str
    source: str
    label: str
    distance: float   # LOWER IS BETTER. 0.3 is close, 0.9 is unrelated.
    produced_by: str


_model = None

# The model Chroma bundles. Anything else in config.EMBEDDING_MODEL means
# "fetch that one from Hugging Face instead" — see `_embedder`.
BUNDLED_MODEL = "all-MiniLM-L6-v2"


class _OnnxEmbedder:
    """
    Chroma's built-in embedder, wrapped to look like the other two.

    Chroma's embedding functions are called directly and hand back numpy
    arrays. The rest of this file wants `.encode(texts)`, so the adapter lives
    here rather than making every caller care which embedder it got.
    """

    def __init__(self):
        from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2

        self._ef = ONNXMiniLM_L6_V2()

    def encode(self, texts, show_progress_bar: bool = False):
        return [vector.tolist() for vector in self._ef(list(texts))]


def _sentence_transformer(name: str):
    """
    Load an embedding model that is not bundled with Chroma.

    This optional path needs `sentence-transformers` and access to Hugging Face;
    neither dependency is required by the default ONNX configuration.
    """
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            f"config.EMBEDDING_MODEL is set to {name!r}, which isn't the model "
            f"Chroma bundles ({BUNDLED_MODEL!r}), so it has to be downloaded "
            f"from Hugging Face.\n"
            f"Install the optional dependency first:\n"
            f"    pip install 'sentence-transformers>=3.4,<3.5'\n"
            f"Or set EMBEDDING_MODEL back to {BUNDLED_MODEL!r}."
        ) from exc

    return SentenceTransformer(name)


def _embedder():
    """
    Load the embedding model once and keep it.

    First call is slow — it downloads about 80 MB. That's why setup happens
    before class.
    """
    global _model

    if _model is not None:
        return _model

    # Used only by this repo's own smoke test, which runs where no model can be
    # downloaded at all. Never set this yourself.
    if os.getenv("AI201_FAKE_EMBEDDINGS") == "1":
        from _smoke_embedder import FakeEmbedder

        _model = FakeEmbedder()
    elif config.EMBEDDING_MODEL == BUNDLED_MODEL:
        _model = _OnnxEmbedder()
    else:
        _model = _sentence_transformer(config.EMBEDDING_MODEL)

    return _model


def embed(texts: list[str]) -> list[list[float]]:
    """Turn text into vectors. Runs on your machine, costs no API quota."""
    vectors = _embedder().encode(texts, show_progress_bar=False)
    # sentence-transformers and the smoke stand-in return something with a
    # .tolist(); _OnnxEmbedder has already done that conversion itself.
    return vectors.tolist() if hasattr(vectors, "tolist") else vectors


def _client():
    return chromadb.PersistentClient(
        path=str(config.CHROMA_DIR),
        settings=chromadb.config.Settings(anonymized_telemetry=False),
    )


def build_index(
    chunks: list[Chunk],
    corpus: str | None = None,
    variant: str = "default",
) -> int:
    """
    Embed every chunk and store it.

    `variant` lets multiple indexes for one corpus coexist so chunking or
    embedding strategies can be compared without deleting the current index.
    """
    name = config.collection_name(corpus, variant)
    client = _client()

    try:
        client.delete_collection(name)
    except Exception:
        pass

    collection = client.create_collection(
        name=name,
        # ⚠️ Do not remove. Chroma defaults to squared L2, and every distance
        # relevance threshold in this application assumes cosine.
        metadata={"hnsw:space": "cosine"},
    )

    batch = 256
    for start in range(0, len(chunks), batch):
        window = chunks[start : start + batch]
        collection.add(
            ids=[f"{c.source}#{c.index}" for c in window],
            documents=[c.text for c in window],
            embeddings=embed([c.text for c in window]),
            metadatas=[
                {"source": c.source, "index": c.index, "produced_by": c.produced_by}
                for c in window
            ],
        )

    return len(chunks)

# ─── BM25 / reciprocal-rank reranking ───────────────────────────────────────


def _tokenize(text: str) -> list[str]:
    """Convert text into simple lowercase tokens for BM25."""
    return re.findall(r"[a-z0-9]+", text.lower())


def _rerank_with_bm25(question: str, results: list[Result]) -> list[Result]:
    """
    Re-rank semantic search results using BM25 keyword matching.

    Chroma determines the candidate set. BM25 changes its order so exact terms
    such as course numbers and location names receive additional weight.
    """
    if not results:
        return results

    tokenized_docs = [_tokenize(result.text) for result in results]
    query_tokens = _tokenize(question)

    if not query_tokens:
        return results

    bm25 = BM25Okapi(tokenized_docs)
    bm25_scores = bm25.get_scores(query_tokens)

    # Rank the existing semantic results by their BM25 scores.
    bm25_order = sorted(
        range(len(results)),
        key=lambda i: bm25_scores[i],
        reverse=True,
    )

    bm25_ranks = {index: rank for rank, index in enumerate(bm25_order, start=1)}

    # Combine semantic rank and BM25 rank using reciprocal rank fusion.
    scored_results = []

    for semantic_rank, result in enumerate(results, start=1):
        index = semantic_rank - 1

        semantic_score = 1 / (60 + semantic_rank)
        keyword_score = 1 / (60 + bm25_ranks[index])

        combined_score = semantic_score + keyword_score
        scored_results.append((combined_score, result))

    scored_results.sort(key=lambda item: item[0], reverse=True)

    return [result for _, result in scored_results]


def search(
    question: str,
    top_k: int | None = None,
    corpus: str | None = None,
    variant: str = "default",
) -> list[Result]:
    """
    Retrieve semantic candidates and re-rank them using BM25 keyword matching.

    Returns results in hybrid rank order. Each result keeps its original
    cosine distance for the relevance gate.
    """
    top_k = top_k or config.TOP_K
    name = config.collection_name(corpus, variant)

    try:
        collection = _client().get_collection(name)
    except Exception as exc:
        raise RuntimeError(
            f"No index called '{name}'. Run `python app.py index` first."
        ) from exc

    raw = collection.query(
        query_embeddings=embed([question]),
        n_results=min(top_k, collection.count()),
    )

    results: list[Result] = []
    for text, meta, distance in zip(
        raw["documents"][0], raw["metadatas"][0], raw["distances"][0]
    ):
        results.append(
            Result(
                text=text,
                source=str(meta.get("source", "unknown")),
                label=f"{meta.get('source', 'unknown')}#{meta.get('index', 0)}",
                distance=float(distance),
                produced_by=str(meta.get("produced_by", "unknown")),
            )
        )
    return _rerank_with_bm25(question, results)


def index_exists(corpus: str | None = None, variant: str = "default") -> bool:
    """Is there an index here to search, without searching it?

    `serve.py`'s health check asks this. It deliberately does not embed
    anything: loading the embedding model takes 80 MB and a few seconds, and a
    health check that heavy is a health check nobody can afford to call.
    """
    try:
        collection = _client().get_collection(config.collection_name(corpus, variant))
        return collection.count() > 0
    except Exception:
        return False


def reset():
    """Delete every index. Occasionally the fastest way out of a mess."""
    if config.CHROMA_DIR.exists():
        shutil.rmtree(config.CHROMA_DIR)
