# Level 4 — Production RAG Engineering

**Status: In progress. Day 07 F02 keyed PDF upload, explicit recovery/reconciliation and local PostgreSQL + MinIO verification are implemented. Ingestion and production readiness remain incomplete.**

Levels 1–3 developed the RAG learning foundation. Level 4 builds an independent application with configuration, tests, operational visibility, and progressively stronger reliability. Its runtime does not import earlier learning-level services.

Start with the [beginner-friendly API foundation guide](docs/01-api-foundation.md). It explains concepts, request flow, setup, debugging, measured observations, and current limitations with minimal code.

## Documentation

Read these guides in implementation order. Earlier checkpoints retain their original scope and measurements; guide 07 describes the current upload behavior.

1. [API foundation](docs/01-api-foundation.md)
2. [Architecture and capacity plan](docs/02-architecture-and-capacity-plan.md)
3. [Document access and versioning](docs/03-document-access-and-versioning.md)
4. [Security, transactions and observability](docs/04-security-transactions-and-observability.md)
5. [Secure PDF upload validation](docs/05-secure-pdf-upload-validation.md)
6. [Upload claim and execution contract](docs/06-upload-claim-contract.md)
7. [Idempotent PDF upload and recovery](docs/07-idempotent-upload-and-recovery.md)

The Day 07 verification checkpoint recorded **18 real PostgreSQL + MinIO E2E tests** and **319 combined relevant tests passed in 14.26 seconds**. Guide 07 includes the exact scoped commands, disposable-resource requirements and evidence limitations. This documentation update did not rerun the tests.

The sections below retain the **original API-foundation checkpoint**, including its historical review notes, test count and roadmap. They are not the current upload specification or a current list of unimplemented security features. Use the ordered guides for subsequent work.

## Implemented checkpoint

- Application factory with injectable service creation for tests.
- Lifespan model initialization and startup warm-up.
- Environment-based embedding model settings and blank-value validation.
- Shared embedding service accessed through a dependency provider.
- Embedding routes with request/response schemas and input checks.
- Health and initialization-readiness endpoints.
- Controlled request-time inference failure response and startup failure behaviour.
- Standard text logs, request IDs, startup and inference timing, and application timing headers.
- 16 schema, configuration, and fake-service API tests.

The current checkpoint does not yet include ingestion, vector retrieval, generation, citations, or `/chat`. It does not establish production readiness or million-user capacity.

## Historical API-foundation review notes

In `app/main.py`, use `create_app(embedding_service_factory=None)` as the factory signature and `app = create_app()` for the exported app. Keep the existing configured-model branch for a None factory. This prevents plain `create_app()` from bypassing the model setting. See the guide for the explanation.

The reviewed file also has an unused `uuid4` import in `main.py` and an unused `ValidationError` import in `test_config.py`. Remove them. The custom-model config test accepts a nonempty name; rename it from `test_with_invalid_embedding_model` to `test_uses_custom_embedding_model` for clarity. Import ordering can be normalized with Ruff using the repository configuration.

## Setup and run

From the repository root:

```bash
uv sync --locked --python 3.12.3
EMBEDDING_MODEL=all-MiniLM-L6-v2 PYTHONPATH=levels/level-4-production-rag uv run uvicorn app.main:app
```

First model use may require a download. The model defaults to `all-MiniLM-L6-v2`; this local embedding checkpoint needs no OpenAI API key. Current settings also load the Level 4 `.env`. The original embedding-only setup predates the database, JWT and MinIO configuration required by the current application; see guides 04–07.

Interactive API: `http://127.0.0.1:8000/docs`.

For automatic restarts during development, append `--reload --reload-dir levels/level-4-production-rag`. Each server restart loads and warms the model again. Production should not use reload.

## Endpoints — original API-foundation checkpoint

| Method | Path | Behaviour at the API-foundation checkpoint |
| --- | --- | --- |
| GET | `/health` | Returns `{"success":"healthy"}` |
| GET | `/ready` | 200 when service state exists; 503 when missing |
| GET | `/debug/embedding` | Reports the service class name |
| POST | `/debug/embedding` | Accepts text; returns dimensions, five vector values, and embedding time |

POST requires 1–2,000 characters and rejects whitespace-only text. The character limit is an API policy, not a model token limit. Inference exceptions return a generic 503. Readiness checks initialization state, not continuous inference health.

```bash
curl -i http://127.0.0.1:8000/debug/embedding -H 'Content-Type: application/json' -d '{"text":"Hello world"}'
```

With the default model, expect 384 dimensions. `X-Request-ID` connects the response to logs. `X-Response-Time-Ms` measures application handling around the route; it excludes network travel and full response transmission. Request IDs do not provide idempotency.

## Validation and observations

```bash
PYTHONPATH=levels/level-4-production-rag uv run pytest levels/level-4-production-rag/tests -q
```

Original API-foundation user-run checkpoint: **16 passed, 1 warning in 2.09 seconds**. The warning concerns the Starlette TestClient's deprecated AnyIO BlockingPortal alias. This documentation preparation did not rerun the suite.

Tests cover schemas, settings, health/readiness, startup warm-up failure, handled inference failure, controlled success responses, and valid unique request IDs. Fake services avoid real model initialization. Real curl smoke requests also returned successful embeddings and timing/ID headers.

Local startup was observed at 4,461.80 ms. One sequential experiment measured roughly 11–12 ms warm inference; later isolated calls were much slower. These samples are not a load benchmark. See the guide for the before/after warm-up results and measurement boundaries.

## Roadmap — original API-foundation checkpoint

| Step | Focus | Status |
| --- | --- | --- |
| 1 | API foundation and baseline | Embedding foundation implemented; retrieval/context/generation/chat and broader baselines pending |
| 2 | Observability | Text logs, request IDs and basic timings implemented; JSON logging, metrics/tracing and token usage pending |
| 3 | Security and tenant isolation | Planned |
| 4 | Reliable ingestion and indexing | Planned |
| 5 | Caching | Planned |
| 6 | Latency and cost optimization | Initial local observations only; controlled benchmarks and optimization pending |
| 7 | Evaluation pipelines | Planned; current tests are API/configuration checks |
| 8 | Failure handling | Startup failure and inference 503 covered; timeouts, admission limits, retries and recovery pending |
| 9 | Distributed retrieval | Planned |
| 10 | Deployment and scaling | Planned |

At the original API-foundation checkpoint, authentication, PII redaction, token-aware input handling, model/index compatibility controls, concurrency limits and complete unhandled-error observability were not implemented. Subsequent authentication and tenant-isolation work is documented in guides 04–07. Do not expose debug routes as a finished public production service.

Millions of documents and high concurrency remain future measured targets. Corpus size, users, concurrent requests and requests per second must be reported separately. The [final project](../../final-project/README.md) remains reserved.
