# Level 2 — Practical RAG Engineering

**Status: Learning implementation complete.** Production hardening continues in [Level 4](../level-4-production-rag/README.md).

## Implemented topics

- [document processing and chunking](docs/01-document-processing-and-chunking.md)
- [chunk overlap](docs/02-chunk-overlap.md)
- [document processing](docs/03-document-processing.md)
- [metadata filtering](docs/04-metadata-filtering.md)
- [hybrid search](docs/05-hybrid-search.md)
- [reranking](docs/06-reranking.md)
- [query rewriting](docs/07-query-rewriting.md)
- [retrieval evaluation](docs/08-retrieval-evaluation.md)
- [grounding controls](docs/09-grounding-controls.md)
- [source citations](docs/10-source-citations.md)
- [production fastapi architecture](docs/11-production-fastapi-architecture.md)

Services, runnable scripts, tests, documentation, and the FastAPI application live in this level.

## Tests

From the repository root:

```bash
PYTHONPATH=levels/level-2-practical-rag uv run pytest levels/level-2-practical-rag/tests -q
```

The API architecture chapter records **151 passed, 1 warning** at its checkpoint. This is historical validation, not a fresh test run or a fixed current count. Some tests load local models or open Chroma; first use may need model downloads.

## API

From `levels/level-2-practical-rag`:

```bash
PYTHONPATH=. uv run uvicorn app.main:app --reload
```

Endpoints: `GET /health` and `POST /answer`. The answer body contains `question`; responses contain `answer` and `citations`.

A real answer requires model weights, OPENAI_API_KEY, and a populated default Chroma collection. Generation incurs API cost. The API uses vector retrieval by default; hybrid search, reranking, and query rewriting are separate learning components.

Working directory matters: the API defaults to `data/chroma`, collection `documents_cosine`, relative to its working directory. The handbook evaluator uses a separate store. Follow the [API guide](docs/11-production-fastapi-architecture.md) and [evaluation guide](docs/08-retrieval-evaluation.md) before running them.

## Scope and limitations

Grounding prompts, an empty-context guard, and source citations are implemented; they do not prove that every answer is supported. Providers currently construct resources when called, and the async route calls synchronous services. Authentication, tenant isolation, operational monitoring, lifecycle management, and scaling remain Level 4 work.

Continue to [Level 3](../level-3-advanced-rag/README.md).
