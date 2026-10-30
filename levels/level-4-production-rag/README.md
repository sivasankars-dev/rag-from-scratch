# Level 4 — Production RAG Engineering

**Status: Next; implementation has not started.** Levels 1–3 provide the learning foundation. The existing services, scripts, tests, and docs directories are reserved for this level.

## Roadmap

| Step | Focus | Completion evidence |
| --- | --- | --- |
| 1 | API foundation and baseline | Validated configuration, resource lifecycle, health/readiness, chat endpoint, API tests and baseline measurements |
| 2 | Observability | Request IDs, structured logs, stage timings, errors and token usage |
| 3 | Security and tenant isolation | Authentication, server-enforced tenant/document access, isolation tests |
| 4 | Reliable ingestion and indexing | Background jobs, document/index versions, idempotency and recovery |
| 5 | Caching | Tenant-aware keys, expiry and invalidation |
| 6 | Latency and cost optimization | Before/after p50/p95, throughput, token and cost measurements |
| 7 | Evaluation pipelines | Versioned datasets, retrieval/answer checks and CI regression gates |
| 8 | Failure handling | Timeouts, bounded retries, rate/concurrency limits and dependency-failure tests |
| 9 | Distributed retrieval | Shared retrieval service and measured index/replica/shard experiments |
| 10 | Deployment and scaling | Reproducible deployment, load tests, backup/restore and capacity report |

PII handling applies to ingestion, access controls, logs, caches, and evaluation artifacts. Storage and infrastructure choices, including PostgreSQL, vector services, and Redis, will be justified as the milestones need them.

## First milestone

Build an independent FastAPI application with a simple retrieval → context → generation path, application-lifetime dependencies, validated settings, consistent errors, health/readiness checks, and per-stage baseline timings. Verify API behavior with fake dependencies and record a separate real smoke run.

All endpoints and operational features above are planned, not available yet.

## Scale targets

Millions of documents and high user concurrency are future measurement targets. Corpus size, registered users, concurrent requests, and requests per second must be reported separately. Increase workloads gradually and claim only demonstrated capacity.

The [final project](../../final-project/README.md) remains reserved for integrating the learned concepts.
