# Current architecture — Level 1, Steps 1–8

The repository contains a small FastAPI app and separate Python ingestion/retrieval scripts. The scripts use the services directly. No framework orchestrates the RAG pipeline.

```text
INGESTION: python -m scripts.ingest_document

 data/documents/company_policy.pdf
                 ↓
 extract_text_from_pdf (pypdf) → 343 characters
                 ↓
 chunk_text (100 characters, overlap 20) → 5 chunks
                 ↓
 EmbeddingService (all-MiniLM-L6-v2)
    internal tokenization → 5 vectors of 384 dimensions
                 ↓
 VectorStore.upsert_chunks
                 ↓
 Chroma PersistentClient: data/chroma
 Collection: documents_cosine; HNSW space: cosine
 Records: IDs + chunk text + embeddings + source/chunk_index metadata
                 ↑
 VectorStore.search (query embedding, top_k=2)
                 ↑
 EmbeddingService → 384-dimensional query vector
                 ↑
 Question: How many annual leave days do I get?

STEP 7 RETRIEVAL: python -m scripts.retrieve
 Chroma results → ranked documents + metadata + distances
               → terminal output including similarity = 1 - distance
```

## Step 8 — Retrieval controls (complete)

Step 7 remains in `app/services/vector_store.py` and `scripts/retrieve.py`. Step 8 uses separate files, `app/services/retrieval_controls_vector_store.py` and `scripts/retrieval_control_retrieve.py`, so both learning stages remain easy to revisit. Both stores use the same persisted cosine collection.

```text
STEP 8: python -m scripts.retrieval_control_retrieve

Query → query embedding
      → optional source filter (where, inside Chroma)
      → Chroma search among eligible chunks
      → Top-K candidates
      → distance converted to cosine similarity
      → similarity threshold
      → final results or []
```

The script supplies `top_k=5` and `source="company_policy.pdf"`; the threshold defaults to `0.50`. Source filtering happens inside Chroma before Top-K selection. Threshold filtering happens afterward and preserves candidate order.

The Step 8 store returns a list of dictionaries containing `document`, `metadata`, `distance` and `similarity`. If none pass the current settings it returns `[]`, and the script prints a message. This does not prove that the knowledge base has no answer. See the [Step 8 guide](08-retrieval-controls.md) for the explanation and recorded experiments.

## Components and their responsibilities

| Component | Responsibility |
| --- | --- |
| `app/services/document_loader.py` | Extract page text and join it with newlines |
| `app/services/chunker.py` | Slide overlapping character windows; trim outer whitespace |
| `app/services/embedding_service.py` | Load Sentence Transformer and encode strings |
| `scripts/test_similarity.py` | Demonstrate the cosine formula independently |
| `app/services/vector_store.py` | Persist/upsert records and query a verified cosine collection |
| `scripts/ingest_document.py` | Connect the PDF-to-storage stages |
| `scripts/inspect_chroma.py` | Print persisted documents and metadata |
| `scripts/retrieve.py` | Step 7: embed the fixed sample question and print two ranked matches |
| `app/services/retrieval_controls_vector_store.py` | Step 8: query with an optional source filter and apply a similarity threshold |
| `scripts/retrieval_control_retrieve.py` | Step 8: print accepted results or handle an empty list |

## The existing HTTP branch

```text
GET /health → {"status": "ok"}
POST /documents/upload → docs/uploads/<basename>.pdf
                      → PDF extraction
                      → chunks (size 100, overlap 10)
                      → JSON: filename, text_length, chunk_count, chunks
```

This upload branch does not call the embedding service or vector store. Its sample result has four chunks because its overlap differs from the ingestion script. FastAPI's generated `/docs` interface can exercise it. There is no retrieval HTTP endpoint.

## Data lifecycle and boundaries

The two sample PDFs in `data/documents/` are source inputs committed to Git. Only `company_policy.pdf` is ingested by the script. Uploaded copies and all local Chroma files are generated and ignored. The original L2 database is preserved locally in ignored `data/chroma-backup-before-cosine/`; a fresh clone recreates the current database by running ingestion.

The model cache lives outside the repository and may require a first download. Dependency versions remain as originally locked. Scripts assume the repository root as their current directory and should run with `python -m scripts.<name>` using `.venv`.

IDs combine source basename and chunk index. Upsert updates those IDs, but does not remove obsolete chunks when document length shrinks. There is no document lifecycle management beyond this small example.

## Current limits

Character windows can split words, tables are not reconstructed, and scanned-image PDFs need separate OCR. Search ranks related passages; it does not verify facts or generate answers. The returned source metadata is not an implemented answer-citation feature.

See [Step 7](07-retrieval.md) and [Step 8](08-retrieval-controls.md) for recorded experiments. The [existing validation notes](validation.md) cover Steps 1–7. Step 8 retrieval controls are complete; Step 9 — Retrieval API is not started.
