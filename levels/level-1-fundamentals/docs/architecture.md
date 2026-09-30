# Current architecture — Level 1, Steps 1–9

> Level 1 learning note: this chapter preserves its original checkpoint. Steps 1–17 are now complete; see the [learning index](../../../README.md#level-1-learning-sequence). Commands below run from the repository root and select Level 1 with `PYTHONPATH`. Shared data remains under root `data/`.

> This diagram records the Steps 1–9 architecture. For the subsequently completed plain Python answer workflow, see [Step 12 — RAG Orchestration and Integration](12-rag-orchestration.md). The existing HTTP routes remain separate from that workflow.

[Step 13 — Better Chunking](13-better-chunking.md) adds a separate `BetterChunker` class: text → sentences → chunk strings. It is tested independently; ingestion and upload still use Step 3, so the diagrams below retain their existing chunking behavior.

The repository contains a small FastAPI app and separate Python ingestion/retrieval scripts. The scripts use the services directly. No framework orchestrates the RAG pipeline.

```text
INGESTION: PYTHONPATH=levels/level-1-fundamentals python -m scripts.run_ingest_document

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

STEP 7 RETRIEVAL: PYTHONPATH=levels/level-1-fundamentals python -m scripts.run_retrieve
 Chroma results → ranked documents + metadata + distances
               → terminal output including similarity = 1 - distance
```

## Step 8 — Retrieval controls (complete)

Step 7 remains in `levels/level-1-fundamentals/services/vector_store.py` and `levels/level-1-fundamentals/scripts/run_retrieve.py`. Step 8 uses separate files, `levels/level-1-fundamentals/services/retrieval_controls_vector_store.py` and `levels/level-1-fundamentals/scripts/run_retrieval_control_retrieve.py`, so both learning stages remain easy to revisit. Both stores use the same persisted cosine collection.

```text
STEP 8: PYTHONPATH=levels/level-1-fundamentals python -m scripts.run_retrieval_control_retrieve

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

## Step 9 — Retrieval API (complete)

```text
HTTP client → POST /retrieve → Pydantic request validation
    → strip query/source → EmbeddingService
    → Step 8 VectorStore → Chroma source filter and Top-K search
    → similarity threshold → retrieved chunks → JSON response
```

The route lives in `levels/level-1-fundamentals/app/main.py`. `levels/level-1-fundamentals/app/schemas/retrieval.py` defines request/result/response models, and `levels/level-1-fundamentals/app/dependencies.py` supplies the embedding service and Step 8 vector store. The earlier learning implementations remain separate.

Top-K defaults to `5` and must be 1–20. The threshold defaults to `0.5` and must be 0–1. Bounds are inclusive; invalid ranges and non-finite thresholds produce HTTP 422 when dependencies initialize successfully. The threshold bounds are API policy: cosine similarity itself can be negative. Direct Step 8 calls do not use this request schema.

The endpoint returns the trimmed query and a list of result dictionaries, or an empty list with HTTP 200. A blank query is rejected with HTTP 400. The API returns chunks, not an LLM answer. See [Step 9](09-retrieval-api.md) for the full walkthrough and verified checks.

## Components and their responsibilities

| Component | Responsibility |
| --- | --- |
| `levels/level-1-fundamentals/app/main.py` | Health, upload and retrieval HTTP routes |
| `levels/level-1-fundamentals/app/dependencies.py` | Construct embedding and Step 8 vector-store services for requests |
| `levels/level-1-fundamentals/app/schemas/retrieval.py` | API request bounds and response structure |
| `levels/level-1-fundamentals/services/document_loader.py` | Extract page text and join it with newlines |
| `levels/level-1-fundamentals/services/chunker.py` | Slide overlapping character windows; trim outer whitespace |
| `levels/level-1-fundamentals/services/embedding_service.py` | Load Sentence Transformer and encode strings |
| `levels/level-1-fundamentals/scripts/run_similarity_demo.py` | Demonstrate the cosine formula independently |
| `levels/level-1-fundamentals/services/vector_store.py` | Persist/upsert records and query a verified cosine collection |
| `levels/level-1-fundamentals/scripts/run_ingest_document.py` | Connect the PDF-to-storage stages |
| `levels/level-1-fundamentals/scripts/run_inspect_chroma.py` | Print persisted documents and metadata |
| `levels/level-1-fundamentals/scripts/run_retrieve.py` | Step 7: embed the fixed sample question and print two ranked matches |
| `levels/level-1-fundamentals/services/retrieval_controls_vector_store.py` | Step 8: query with an optional source filter and apply a similarity threshold |
| `levels/level-1-fundamentals/scripts/run_retrieval_control_retrieve.py` | Step 8: print accepted results or handle an empty list |

## The existing HTTP branch

```text
GET /health → {"status": "ok"}
POST /documents/upload → data/uploads/<basename>.pdf
                      → PDF extraction
                      → chunks (size 100, overlap 10)
                      → JSON: filename, text_length, chunk_count, chunks
```

This upload branch does not call the embedding service or vector store. Its sample result has four chunks because its overlap differs from the ingestion script. FastAPI's generated `/docs` interface can exercise it. `POST /retrieve` is a separate route described above; it queries the already-ingested collection.

## Data lifecycle and boundaries

The two sample PDFs in `data/documents/` are source inputs committed to Git. Only `company_policy.pdf` is ingested by the script. Uploaded copies and all local Chroma files are generated and ignored. The original L2 database is preserved locally in ignored `data/chroma-backup-before-cosine/`; a fresh clone recreates the current database by running ingestion.

The model cache lives outside the repository and may require a first download. Dependency versions remain as originally locked. Scripts assume the repository root as their current directory and should run with `PYTHONPATH=levels/level-1-fundamentals python -m scripts.<name>` using `.venv`.

IDs combine source basename and chunk index. Upsert updates those IDs, but does not remove obsolete chunks when document length shrinks. There is no document lifecycle management beyond this small example.

## Current limits

Character windows can split words, tables are not reconstructed, and scanned-image PDFs need separate OCR. Search ranks related passages; it does not verify facts or generate answers. The returned source metadata is not an implemented answer-citation feature.

See [Step 7](07-retrieval.md) and [Step 8](08-retrieval-controls.md) for recorded experiments. The [existing validation notes](validation.md) cover Steps 1–7. Steps 8 and 9 are complete. See [Step 9](09-retrieval-api.md) for API checks and validation fixes. The API still constructs services per request and calls synchronous embedding/search code inside its async route; no application-wide model cache or asynchronous retrieval has been added.
