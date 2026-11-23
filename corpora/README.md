# Included corpora

The application ingests UTF-8 text and Markdown files from
corpora/<name>/documents. Each corpus has a different document shape, which
makes it useful for testing chunking and retrieval strategies.

The default configuration uses **campus_life**. Switch corpora with the
AI201_CORPUS environment variable or the global --corpus CLI option, then build
the matching index again:

    python app.py --corpus city_guides index
    python app.py --corpus city_guides ask "How do I travel between towns?"

## campus_life

Short posts about university life: dining, housing, courses, transportation,
and administrative policies. Most facts are contained in one focused document,
so the project keeps each document as one chunk.

**88 documents · 27,908 characters · approximately 317 characters/document**

## advice_threads

Question-and-answer threads with several replies of uneven length. Answers may
be distributed across speakers or include disagreement, making useful chunk
boundaries less obvious.

**23 documents · 12,490 characters · approximately 543 characters/document**

## city_guides

Longer travel guides divided into labeled sections such as transportation,
food, accessibility, and seasonal advice. Information is organized by heading
and often spans a complete paragraph.

**14 documents · 28,958 characters · approximately 2,068 characters/document**

## practice

A small, self-contained corpus about a fictional board game. It is useful for
smoke tests and chunking experiments that should not affect the default campus
index.

**28 documents · 15,901 characters · approximately 567 characters/document**

## Adding a corpus

Create a new directory with this shape:

    corpora/
      my_corpus/
        documents/
          document-one.txt
          document-two.md

Then build and query it:

    python app.py --corpus my_corpus index
    python app.py --corpus my_corpus ask "Your question"

Only .txt and .md files are loaded. Bringing a new corpus may require additional
cleaning, a different chunking strategy, and a recalibrated relevance threshold.
The default 0.60 threshold was evaluated against the shipped campus corpus and
should not be assumed correct for unrelated data.
