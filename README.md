# RAG From Scratch

Learn RAG by building it in independent levels, from fundamentals to production engineering.

**Level 1 — RAG Fundamentals: Steps 1–17 complete. Level 2 is next.** Completion describes each learning checkpoint's scope; it does not mean every discussed technique is implemented.

## Learning philosophy

Each level has its own services, scripts, tests, and documentation. Later concepts can evolve without changing or obscuring the earlier learning implementations.

`levels/` contains these learning implementations. `final-project/` is reserved for combining the concepts into a production-oriented RAG application. It is not implemented yet.

```text
Level 1: Fundamentals
    ↓
Level 2: Practical RAG
    ↓
Level 3: Advanced RAG
    ↓
Level 4: Production RAG
    ↓
Final Project
```

## Repository structure

```text
levels/
├── level-1-fundamentals/
│   ├── services/       Existing learning services
│   ├── app/            Level 1 FastAPI routes, dependencies, and schemas
│   ├── scripts/        Manual run_* demonstrations
│   ├── tests/          Automated checks
│   └── docs/           Steps 1–17 and historical validation notes
├── level-2-practical-rag/   Next; placeholders only
├── level-3-advanced-rag/    Planned; placeholders only
└── level-4-production-rag/ Planned; placeholders only
final-project/
├── app/
├── scripts/
├── tests/
└── docs/
data/
├── documents/         Shared sample PDFs
├── evaluation_dataset.json
├── chroma/            Generated local vector store, ignored
└── uploads/           Generated upload copies, ignored
pyproject.toml         Shared environment and test configuration
uv.lock               Locked dependencies
```

Every level has `services/`, `scripts/`, `tests/`, and `docs/`. Level 1 additionally keeps the HTTP application in `app/`. No learning implementation is copied into the future levels or final project. The sample PDFs and existing Chroma data stay in the root `data/` directory.

| Level | Status | Guide |
| --- | --- | --- |
| 1 — RAG Fundamentals | Steps 1–17 complete | [Level 1](levels/level-1-fundamentals/README.md) |
| 2 — Practical RAG Engineering | Next | [Roadmap](levels/level-2-practical-rag/README.md) |
| 3 — Advanced RAG | Planned | [Roadmap](levels/level-3-advanced-rag/README.md) |
| 4 — Production RAG Engineering | Planned | [Roadmap](levels/level-4-production-rag/README.md) |
| Final Project | Reserved; not implemented | [Plan](final-project/README.md) |

## Level 1 learning sequence

| Step | Topic |
| --- | --- |
| 1 | [Project setup](levels/level-1-fundamentals/docs/01-project-setup.md) |
| 2 | [PDF to text](levels/level-1-fundamentals/docs/02-pdf-to-text.md) |
| 3 | [Chunking](levels/level-1-fundamentals/docs/03-chunking.md) |
| 4 | [Embeddings](levels/level-1-fundamentals/docs/04-embeddings.md) |
| 5 | [Cosine similarity](levels/level-1-fundamentals/docs/05-cosine-similarity.md) |
| 6 | [ChromaDB](levels/level-1-fundamentals/docs/06-chromadb.md) |
| 7 | [Semantic retrieval](levels/level-1-fundamentals/docs/07-retrieval.md) |
| 8 | [Retrieval controls](levels/level-1-fundamentals/docs/08-retrieval-controls.md) |
| 9 | [Retrieval API](levels/level-1-fundamentals/docs/09-retrieval-api.md) |
| 10 | [LLM generation](levels/level-1-fundamentals/docs/10-llm-generation.md) |
| 11 | [Usage and cost monitoring](levels/level-1-fundamentals/docs/11-llm-usage-and-cost-monitoring.md) |
| 12 | [RAG orchestration](levels/level-1-fundamentals/docs/12-rag-orchestration.md) |
| 13 | [Better chunking](levels/level-1-fundamentals/docs/13-better-chunking.md) |
| 14 | [RAG evaluation](levels/level-1-fundamentals/docs/14-rag-evaluation.md) |
| 15 | [Retrieval metrics](levels/level-1-fundamentals/docs/15-retrieval-evaluation.md) |
| 16 | [Retrieval failure cases](levels/level-1-fundamentals/docs/16-retrieval-failure-cases.md) |
| 17 | [Generation basics](levels/level-1-fundamentals/docs/17-generation-basics.md) |

Older chapters retain their checkpoint explanations and measured results. Paths and commands now use the Level 1 layout. See the [architecture](levels/level-1-fundamentals/docs/architecture.md) and [validation history](levels/level-1-fundamentals/docs/validation.md).

## Environment and imports

Run commands from the **repository root**. The verified interpreter is Python 3.12.3; dependencies have not been upgraded for this reorganization.

```bash
uv sync --locked --python 3.12.3
```

Select the level for a Python process with `PYTHONPATH=levels/level-1-fundamentals`. Python then finds that level's `services`, `scripts`, and `app` packages. The hyphenated folder name is a filesystem path, not a Python import name. Select one level at a time; do not combine different levels on `PYTHONPATH`.

Shared data paths remain relative to the repository root. Keep this working directory when running scripts or the API. Existing generated databases are reused, not copied. Legacy ignored `docs/uploads/` files, if present locally, are left untouched; new uploads use `data/uploads/`.

## Run Level 1

### Ingest, inspect, and retrieve

```bash
PYTHONPATH=levels/level-1-fundamentals uv run python -m scripts.run_ingest_document
PYTHONPATH=levels/level-1-fundamentals uv run python -m scripts.run_inspect_chroma
PYTHONPATH=levels/level-1-fundamentals uv run python -m scripts.run_retrieve
PYTHONPATH=levels/level-1-fundamentals uv run python -m scripts.run_retrieval_control_retrieve
```

Ingestion uses the original character chunker with size 100 and overlap 20. It produces five chunks from the sample and stores 384-dimensional `all-MiniLM-L6-v2` embeddings in the cosine Chroma collection. First model use may need a download; subsequent runs can use cached files.

The separate Step 13 `BetterChunker` remains available and tested, but ingestion and upload still use Step 3. Retrieval behavior is unchanged.

### Retrieval evaluation

```bash
PYTHONPATH=levels/level-1-fundamentals uv run python -m scripts.run_evaluation_dataset
PYTHONPATH=levels/level-1-fundamentals uv run python -m scripts.run_retrieval_evaluation
```

Step 14 evaluates expected chunk indexes for five questions using Hit Rate@3 and MRR@3. Precision, Recall, F1, and NDCG are conceptual material only. Final answer evaluation is not implemented.

### API

```bash
PYTHONPATH=levels/level-1-fundamentals uv run python -m uvicorn app.main:app --reload
```

Visit `http://127.0.0.1:8000/docs`. The routes are `GET /health`, `POST /documents/upload`, and `POST /retrieve`. Upload extracts/chunks text without inserting it into Chroma. Retrieval returns passages, not an LLM answer.

### Generation and orchestration

With `OPENAI_API_KEY` configured in your environment or ignored root `.env` file:

```bash
PYTHONPATH=levels/level-1-fundamentals uv run python -m scripts.run_llm_demo
PYTHONPATH=levels/level-1-fundamentals uv run python -m scripts.run_rag_service_demo
```

These make paid API calls. The orchestration demo connects question → embedding → retrieval → context → prompt → LLM → answer. There is no `/chat` endpoint. Usage and estimated cost are printed; they are not persisted. The cost estimate has the limitations documented in Step 11.

The manual `run_cost_calculator_build_demo` still calls an outdated calculator interface and fails. That existing mismatch is preserved, not fixed as part of moving files.

## Tests

```bash
uv run python -m pytest
```

Root pytest configuration selects the Level 1 import path and test directory. To run one file:

```bash
uv run python -m pytest levels/level-1-fundamentals/tests/test_better_chunker.py -v
```

After the embedding model is cached, use `HF_HUB_OFFLINE=1` before the command for offline testing. Migration validation: **22 passed, 1 dependency warning**. The suite covers the original chunker, PDF/upload behavior, vector storage, retrieval, BetterChunker, and dataset checks. It does not yet have assertions for every conceptual topic or the paid generation path. A Starlette/AnyIO dependency deprecation warning is known.

Levels 2–4 and the final project will receive their own implementations and tests as learning progresses.
