# Step 6 — ChromaDB and vector storage

## What is a vector database, and why do we need one?

A vector database stores embeddings together with their source records and supports searching for nearby vectors. Storage alone is not the main idea: its search index lets us retrieve passages by their relationship to a query embedding.

For five chunks, comparing every vector manually would be perfectly feasible and educational. As the collection grows, repeating a Python loop over all vectors costs more work. A vector search index, persistence and record management make that work easier to manage. Approximate indexes can trade exact nearest-neighbor guarantees for search efficiency.

## Simple analogy

A library keeps books plus a catalog. Here, chunks are the books, metadata is the label, and an embedding index is a catalog organized by learned meaning rather than alphabetical titles.

## Technical explanation: traditional vs vector database

| Typical relational database use | Vector database use here |
| --- | --- |
| Find rows by exact values, ranges and relationships | Find nearby embedding vectors |
| Index structured fields | Index a high-dimensional vector space |
| Return records satisfying a condition | Rank passages by a distance measure |

These categories can overlap; traditional databases can have vector-search extensions, and vector databases also store structured metadata. Chroma provides persistent storage and nearest-neighbor search in this project. HNSW is its graph-based approximate nearest-neighbor index configuration here.

## Current implementation

[`VectorStore`](../app/services/vector_store.py) creates a `chromadb.PersistentClient` at `data/chroma`, then gets or creates the `documents_cosine` collection. A collection groups records with a shared embedding dimension and search configuration.

```python
configuration={"hnsw": {"space": "cosine"}}
```

This spelling matches the [Chroma collection documentation](https://cookbook.chromadb.dev/core/collections/). Passing creation settings to `get_or_create_collection` does not convert an existing collection to a different metric. The wrapper verifies the stored configuration and raises an explanatory error if it is not cosine.

`upsert_chunks(chunks, embeddings, source)` writes matching lists:

| Field | Actual example / meaning |
| --- | --- |
| ID | `company_policy.pdf_chunk_0`: stable record identity |
| Document | The original chunk string |
| Embedding | 384 numbers from our Sentence Transformer service |
| Metadata | `{"source": "company_policy.pdf", "chunk_index": 0}` |

Upsert inserts a missing ID or updates an existing ID. Running the same five-chunk ingestion again leaves five records, rather than creating duplicates. It does not delete old higher-index records if a later ingestion produces fewer chunks. Source basenames can also collide across directories; the current exercise has one ingested source.

## What happens internally?

The ingestion script extracts and chunks the PDF, computes the vectors once, and passes them explicitly to Chroma. Chroma stores the fields and maintains its search index. The query script computes its own query vector and supplies `query_embeddings`, so it does not rely on Chroma's default embedding function to encode text. Local database files persist after the process exits.

## Cosine distance vs similarity

```text
cosine_distance = 1 - cosine_similarity
cosine_similarity = 1 - cosine_distance
Higher similarity is closer; lower distance is closer.
```

For example, similarity 0.8 means distance 0.2. Cosine distance is mathematically in [0, 2] for nonzero real vectors, not necessarily [0, 1]. Neither score is a probability. Do not use this conversion for L2 (squared Euclidean) distance.

## Correction found during repository inspection

The source originally used `"hsnw"`. Inspection of the actual installed Chroma configuration showed both existing collections (`documents` and `documents_cosine`) were using **L2**, despite the second collection's name. Thus the earlier retrieval script's `1 - distance` was not a valid cosine similarity interpretation.

We corrected the key to `"hnsw"`, preserved the old local database as `data/chroma-backup-before-cosine/`, and re-ingested into a fresh `data/chroma/` database. Both directories are ignored. No original database was deleted. Fresh clones simply run ingestion; they do not need the backup. If restoring an old database, inspect its metric before interpreting its scores.

The original `scripts/test_chroma.py` wrote three demonstration sentences with the same source/IDs as real ingestion, overwriting some PDF chunks. It now uses a temporary directory, so the example cannot contaminate the five-chunk collection.

## How to run and verify

```bash
.venv/bin/python -m scripts.ingest_document
.venv/bin/python -m scripts.inspect_chroma
.venv/bin/python -m scripts.test_chroma
.venv/bin/python -m unittest discover -s tests -p test_vector_store.py -v
```

The inspection script lists five records with their documents and metadata. The isolated example reports three stored chunks. Regression tests use deliberately unequal vector magnitudes so L2 and cosine would rank differently; they also check distances, upsert, reopening the persistent store and rejecting an existing L2 collection.

## Why metadata matters and common mistakes

Metadata connects a returned passage to its source file and chunk index. It helps inspect retrieval and explain where results came from. This project returns metadata but does not implement metadata filtering.

Do not trust a collection name to prove its metric, commit generated database files, confuse an upsert with a full document replacement, or mix demonstration records with real ingestion IDs. Keep the same embedding model for documents and queries.

## Interview questions

1. Why not a list of vectors? A list works for small exercises; a database adds persistence, record management and indexed search.
2. Why store original chunks? Retrieval needs readable content as well as numerical vectors.
3. What does upsert do? Insert or update by ID; it does not remove other IDs.
4. Why check an existing collection's configuration? Creation options do not migrate its metric.

## What I learned

The search metric is part of the data's meaning. Verifying actual configuration matters more than naming a collection “cosine.” Metadata and stable IDs keep retrieved vectors connected to their text.

## Next step

[Step 7 — Semantic retrieval](07-retrieval.md).
