# Validation of Level 1, Steps 1–7

> Level 1 learning note: this chapter preserves its original checkpoint. Steps 1–17 are now complete; see the [learning index](../../../README.md#level-1-learning-sequence). Commands below run from the repository root and select Level 1 with `PYTHONPATH`. Shared data remains under root `data/`.

Validated on 2026-09-24 in the existing Python 3.12.3 / macOS arm64 environment. No dependency versions were changed. The original repository had demonstration scripts and an empty test file, but no automated assertions or commits.

## Checks and results

| Check | Result |
| --- | --- |
| Parse all project Python files | Passed |
| `uv lock --check --offline --cache-dir /tmp/rag-uv-cache` | 129 lock packages resolved; consistent |
| `uv sync --locked --python 3.12.3 --dry-run --offline --cache-dir /tmp/rag-uv-cache` | 113 installed packages audited; would make no changes |
| Installed package metadata vs lock | All installed lockfile packages match |
| `PYTHONPATH=levels/level-1-fundamentals .venv/bin/python -m uvicorn --version` | Uvicorn 0.53.0 / Python 3.12.3 |
| FastAPI test client | Health, PDF upload and non-PDF rejection pass |
| Real sample extraction | 343 characters |
| Ingestion chunking | Five chunks, size 100 / overlap 20 |
| Existing upload chunking | Four chunks, size 100 / overlap 10 |
| Embedding demo and single/batch check | Finite 384-dimensional vectors |
| Manual cosine checks | Aligned, orthogonal, opposite and 0.8 example; invalid inputs rejected |
| Similarity demo | Refund/money-back ≈ 0.591858; refund/weather ≈ -0.053061 |
| Chroma configuration | `documents_cosine` uses `hnsw.space = cosine` |
| Ingest / inspect scripts | Five PDF records stored with IDs, text and metadata |
| Isolated Chroma demo | Three records in temporary storage; sample store unchanged |
| Retrieval script | Two results, chunks 0 and 2; full output in Step 7 |
| Standard-library test suite | Eight tests passed |

The live server CLI module/version was checked, and HTTP behavior was exercised in-process using FastAPI's test client. A fresh dependency install was not performed over the working environment; setup was verified with a locked dry run. Offline model checks reused the existing cache, so a fresh machine's first model download is not covered.

The installed Starlette test client emits a deprecation warning about its httpx integration. Tests pass. This warning was not used as a reason to modify the working dependency set.

## Reproduce the checks

From the repository root:

```bash
HF_HUB_OFFLINE=1 PYTHONPATH=levels/level-1-fundamentals .venv/bin/python -m unittest discover -s levels/level-1-fundamentals/tests -v
HF_HUB_OFFLINE=1 PYTHONPATH=levels/level-1-fundamentals .venv/bin/python -m scripts.run_embedding_demo
HF_HUB_OFFLINE=1 PYTHONPATH=levels/level-1-fundamentals .venv/bin/python -m scripts.run_similarity_demo
HF_HUB_OFFLINE=1 PYTHONPATH=levels/level-1-fundamentals .venv/bin/python -m scripts.run_chroma_demo
HF_HUB_OFFLINE=1 PYTHONPATH=levels/level-1-fundamentals .venv/bin/python -m scripts.run_ingest_document
PYTHONPATH=levels/level-1-fundamentals .venv/bin/python -m scripts.run_inspect_chroma
HF_HUB_OFFLINE=1 PYTHONPATH=levels/level-1-fundamentals .venv/bin/python -m scripts.run_retrieve
```

Remove the offline environment variable if the model has not been downloaded. The test suite's integration check calls the actual services and compares Chroma distances with the manually implemented cosine formula. It uses temporary storage rather than altering the local sample database.

## Small code changes and why

- Whitespace cleanup in the initial baseline: syntax trees were compared to verify no behavior change. PDFs are marked binary with `.gitattributes`.
- PDF page separator: `"/n"` corrected to `"\n"`; tested with a two-page PDF.
- Upload filename: use only its basename so a supplied path cannot escape the upload directory; regression tested with `../outside.pdf`.
- Chunk size: explicitly reject zero with `<= 0` and a clearer error message; retain the existing algorithm.
- Chroma configuration: correct `hsnw` to `hnsw` and reject an existing non-cosine collection so the retrieval script cannot silently mislabel distances.
- Chroma experiment: use a temporary database rather than overwriting the first three real PDF chunk IDs.

The previous database remains in ignored `data/chroma-backup-before-cosine/`. The fixed sample database was rebuilt under `data/chroma/`; no original data was deleted. Tests were added only for these meaningful behaviors and the requested end-to-end validation.

## Repository review

Documentation links are checked against files. Git diffs are reviewed before each commit. Tracked paths and text are checked for generated databases, virtual environments, environment secrets and common credential patterns; the small sample PDFs were inspected by extraction as well. These are scoped checks, not a claim of a comprehensive security audit.

The first commit captures the user's existing Step 1–7 code and setup documentation. Six subsequent commits cover the remaining learning steps, with fixes where relevant. No synthetic historical implementation commits or rewritten history are needed.

## Scope boundary

The only application routes are the original health and PDF-upload routes (plus FastAPI's generated documentation). The fixed `top_k=2` search already existed. No Step 8 retrieval controls or later features were added. The collection metric check is a Step 6 correctness guard, not a similarity threshold or no-result policy.

## Step 13 validation — 2026-09-27

[Step 13 — Better Chunking](13-better-chunking.md) adds 11 automated tests for sentence splitting, grouping, overlap, size checks and oversized sentences. The current full suite includes the eight earlier tests recorded above:

```bash
PYTHONPATH=levels/level-1-fundamentals uv run python -m pytest
```

Result: **19 passed, 1 warning**. The current warning comes from Starlette's test client using AnyIO's deprecated `BlockingPortal` alias. It is a dependency warning; the Step 13 tests pass. pytest is now in the development dependency group.

The Step 13 class is tested separately. Existing ingestion and upload still use Step 3, and this validation does not establish an improvement in retrieval or generated-answer quality. The earlier sections retain their original checkpoint results.

## Level 1 directory migration — 2026-09-30

Level 1 now lives under `levels/level-1-fundamentals/`. Run from the repository root; pytest selects the Level 1 import path automatically:

```bash
uv run python -m pytest
```

Migration validation: **22 passed, 1 warning**. The warning remains Starlette's use of AnyIO's deprecated `BlockingPortal` alias. The three dataset tests added after Step 13 account for the increase from the historical 19-test result.

Verified with the cached embedding model:

- Dataset printing, context builder, and prompt builder demos.
- Embedding, cosine similarity, and isolated Chroma demos.
- Ingestion, inspection, Step 7 retrieval, and Step 8 retrieval controls.
- Retrieval evaluation: five cases, Hit Rate@3 **100.00%**, MRR@3 **0.87**.
- Imports for all 32 service, application, and script modules.
- API health, Swagger, and OpenAPI responses, plus the upload checks in the suite.
- Documentation links and module command references.

The cost-calculator demo still raises its previously documented unexpected `model` keyword error. Paid LLM, cache, and RAG orchestration demos were import-checked but not executed against the external API during migration.

Python files were compared with their pre-migration versions: only service imports, sample-test paths, and the generated upload directory changed. Step 3's chunker, PDF inputs, and `uv.lock` remain byte-for-byte unchanged. Generated Chroma data was reused in place; new uploads go to root `data/uploads/`. Future levels and the final project contain placeholders only.
