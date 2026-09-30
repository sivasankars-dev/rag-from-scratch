# Level 1 — RAG Fundamentals

**Steps 1–17 complete.** Services, manual scripts, automated tests, and learning notes are kept together here. `app/` contains the FastAPI routes, dependencies, and schemas; learning services live in `services/`.

See the [root learning index](../../README.md#level-1-learning-sequence) for the ordered chapters and commands. Chapters record their original checkpoints; their descriptions of later work are historical, not the overall repository status.

Run from the repository root with this level selected:

```bash
PYTHONPATH=levels/level-1-fundamentals uv run python -m scripts.run_evaluation_dataset
uv run python -m pytest
```

For interactive Python or individual scripts, set `PYTHONPATH=levels/level-1-fundamentals`. Root pytest configuration supplies that path automatically. Shared PDFs, evaluation data, and generated Chroma files remain under root `data/`; no database was duplicated.

Step 13 is a separate chunker, Step 14 implements Hit Rate and MRR, and Steps 15–17 explain metrics, failure cases, and generation concepts. Later techniques remain conceptual. Continue to [Level 2](../level-2-practical-rag/README.md), which currently contains placeholders only.
