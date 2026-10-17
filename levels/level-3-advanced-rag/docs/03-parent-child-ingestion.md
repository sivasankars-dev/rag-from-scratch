# Parent-Child handbook ingestion

This script prepares searchable child vectors and their parent context. It does not generate answers or evaluate retrieval quality. Read the [retrieval guide](02-parent-child-retrieval.md) for component responsibilities.

## Run

From the repository root, with the project's dependencies installed:

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run python levels/level-3-advanced-rag/scripts/run_parent_child_ingestion.py
```

[The script](../scripts/run_parent_child_ingestion.py) resolves all input/storage paths from its own location. An absolute script path also works from another working directory. It loads the existing Level 2 modules by file path to avoid confusing the two levels' `services` packages.

## Flow and initial configuration

1. Load `data/documents/rag_practice_employee_handbook.pdf` at the repository root using Level 2's `extract_text_from_pdf(filepath)`.
2. Use each returned dictionary's `text` and original 1-based `page_number`. The loader omits pages with no extracted text; the printed page count is the number of returned page records, not necessarily the PDF's physical page count. Whitespace-only or empty page text is skipped by ingestion.
3. Call `build_parent_child_chunks` for each nonempty page with source `rag_practice_employee_handbook.pdf`, parent size **100 words**, child size **30 words**, and child overlap **10 words**. Parents and children never cross page boundaries.
4. Generate all child embeddings with Level 2's `EmbeddingService().embed_texts(texts)`. Its default model is local `all-MiniLM-L6-v2`; first use may download model files. No OpenAI call or key is required. Retrieval must use the same embedding model.
5. Replace this source's old records, store parents using `ParentChildStore.store_parent`, and store children using `ChildVectorStore.store_children`.
6. Reload parents from disk and fetch child IDs filtered by source. Compare both stored ID sets and counts with the expected records. A mismatch raises an error rather than reporting success.

The current chunker includes page numbers in IDs: for example, `rag_practice_employee_handbook.pdf_page_2_parent_0` and its child suffix `_child_0`. This differs from the earlier page-independent ID examples in the retrieval guide. Source metadata remains the exact PDF filename. Duplicate generated IDs are rejected before embedding or resetting storage.

## Storage layout

All generated data is under `levels/level-3-advanced-rag/data/parent_child/`:

| Path/name | Contents |
|---|---|
| `parents.json` | JSON mapping parent IDs to full parent records |
| `chroma/` | Persistent Chroma database of child text, vectors, and metadata |
| Collection `parent_child_employee_handbook` | Dedicated ingestion collection inside that database |

These are generated local artifacts, not source files to commit. The script never deletes directories or touches Level 2 evaluation stores. Use these explicit paths and collection when constructing retrieval stores; the wrappers' defaults point elsewhere.

## Repeated runs and recovery

Run with readers and other writers stopped. This is a single-writer learning workflow, not a transactional ingestion service.

Extraction, chunking, and embedding finish before the reset begins. Empty content, duplicate IDs, extraction failures, or embedding failures leave existing records intact. An empty document is treated as an error, not an instruction to erase an index.

For a successful preparation, the script deletes children with this exact source from the dedicated collection. It removes the same source's old parent records from JSON, preserving other sources, and writes the new parents and children. This also removes obsolete IDs after changes to chunk sizes, page counts, or the ID scheme. Repeating the same ingestion replaces records instead of accumulating duplicates. Resetting is the ingestion script's policy; the store wrappers alone do not remove stale records.

The JSON reset uses a temporary file and replacement, but the complete operation across JSON and Chroma is **not atomic**. A storage failure after reset can leave partial data. Do not use that index until a rerun completes and verifies counts. There is no automatic rollback or concurrency lock. Records incorrectly labeled with another source will not be removed by this source-scoped reset.

Printed counts cover extracted page records, parent chunks, child chunks, embedded children, persisted parents, and stored children. Counts verify ingestion completeness, not semantic retrieval quality. All texts and embeddings are held in memory, and the parent wrapper rewrites its JSON on each parent save; this is intended for the practice handbook rather than large-scale ingestion.

## Tests

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run pytest levels/level-3-advanced-rag/tests/test_parent_child_ingestion.py -q
```

Tests use fake page loading, fake embeddings, a fake child store, and temporary JSON storage. They do not read the real PDF or use network services. They cover page metadata, chunk settings, path independence, repeat ingestion, stale-record removal, preservation of other sources, empty input, preparation failures, duplicate IDs, and stored-count mismatch. The existing integration test separately exercises the real Chroma wrapper with fake vectors.
