# Current architecture — Level 1, Steps 1–7

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

RETRIEVAL: python -m scripts.retrieve
 Chroma results → ranked documents + metadata + distances
               → terminal output including similarity = 1 - distance
```

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
| `scripts/retrieve.py` | Embed the fixed sample question and print two ranked matches |

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

See [Step 7](07-retrieval.md) for measured output and [validation](validation.md) for checks. Step 8 and later capabilities remain unimplemented.
