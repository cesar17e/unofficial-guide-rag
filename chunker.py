"""Stage 2: convert cleaned documents into retrievable chunks.

The default `campus_life` corpus contains short, topic-focused documents, so
`split_documents` preserves each document as one chunk. Keeping a title and its
supporting context together produced clearer retrieval inputs than arbitrary
character windows. `fallback_split` remains available for longer corpora that
need fixed-size overlapping chunks.
"""

from dataclasses import dataclass

import config
from ingest import Document


@dataclass
class Chunk:
    """One piece of one document."""

    text: str
    source: str        # which file it came from
    index: int         # which chunk within that file, starting at 0
    produced_by: str   # the function responsible for this chunk

    @property
    def label(self) -> str:
        return f"{self.source}#{self.index}"


def fallback_split(
    documents: list[Document],
    chunk_size: int | None = None,
    overlap: int | None = None,
) -> list[Chunk]:
    """
    Generic fixed-size character windows with overlap.

    This provides an option and comparison point for corpora whose documents
    are too long to preserve as single chunks.
    """
    chunk_size = chunk_size or config.CHUNK_SIZE
    overlap = overlap or config.CHUNK_OVERLAP

    if overlap >= chunk_size:
        raise ValueError("overlap has to be smaller than chunk_size")

    chunks: list[Chunk] = []
    for doc in documents:
        start = 0
        index = 0
        while start < len(doc.text):
            piece = doc.text[start : start + chunk_size].strip()
            if piece:
                chunks.append(
                    Chunk(
                        text=piece,
                        source=doc.source,
                        index=index,
                        produced_by="chunker.py::fallback_split",
                    )
                )
                index += 1
            start += chunk_size - overlap

    return chunks

def split_documents(documents: list[Document]) -> list[Chunk]:
    """
    Chunking strategy for campus_life.

    The campus-life corpus contains short, topic-focused posts, so each
    complete document is kept as one chunk. This preserves titles and
    supporting context instead of splitting at arbitrary character boundaries.
    Overlap is unnecessary because documents are not divided further.
    """
    chunks: list[Chunk] = []

    for doc in documents:
        text = doc.text.strip()

        if not text:
            continue

        chunks.append(
            Chunk(
                text=text,
                source=doc.source,
                index=0,
                produced_by="chunker.py::split_documents",
            )
        )

    return chunks



def describe(chunks: list[Chunk]) -> str:
    """A one-line summary, printed after indexing."""
    if not chunks:
        return "0 chunks"
    lengths = [len(c.text) for c in chunks]
    return (
        f"{len(chunks)} chunks, "
        f"{sum(lengths) // len(lengths)} characters on average "
        f"(shortest {min(lengths)}, longest {max(lengths)}), "
        f"produced by {chunks[0].produced_by}"
    )


if __name__ == "__main__":
    from ingest import load_documents

    chunks = split_documents(load_documents())
    print(describe(chunks))
