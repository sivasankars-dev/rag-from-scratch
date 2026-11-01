# Production API Foundation — Beginner-Friendly Implementation Guide

## 1. Why am I learning this?

Levels 1–3 explored how RAG works and how different retrieval strategies behave. Level 4 starts building an independent application that we can operate, test, and extend.

This chapter covers the first API foundation checkpoint: accepting text, generating an embedding, validating requests, handling failures, and observing execution. It does not yet implement document ingestion, vector retrieval, or a chat answer pipeline.

The goal is to understand why each part exists, how a request moves through the application, and how to debug failures. Read this guide alongside the Level 4 source. No imports from earlier learning levels are required.

## 2. Refresh: Where do embeddings fit in RAG?

During ingestion, a RAG system embeds document chunks and stores their vectors with text and metadata. During retrieval, it embeds the user's question and searches for relevant chunks. The retrieved context can then support an LLM answer.

Our current Level 4 API only demonstrates the text-to-vector step. An embedding is a numerical representation of text. The default local model, `all-MiniLM-L6-v2`, produces 384 values for each input. Individual values can be positive or negative; they are not similarity scores.

The API shows the first five values as a preview. Similarity comparison requires the complete vectors, not just the preview. Documents and questions must use compatible embedding spaces. Equal vector dimensions alone do not make different models compatible.

## 3. What problem does application startup solve?

Loading a model can be expensive. Creating a new model for every request repeats that work and consumes resources unnecessarily.

The lifespan creates one service instance per application process. Requests in that process reuse it through application state. Multiple worker processes each have their own instance and memory requirements.

Startup follows this order:

1. Read and validate settings.
2. Create the selected embedding service.
3. Execute a warm-up embedding.
4. Store the ready service in application state.
5. Begin accepting requests.

The lifespan's `yield` separates startup from normal serving and shutdown. If model creation or warm-up fails before `yield`, startup fails. The application does not continue as if initialization succeeded.

The current shutdown block logs a message. It does not implement explicit model disposal or prove that every underlying library resource has been released.

## 4. Model loading and warm-up are different

Model creation loads the weights and prepares the service. Warm-up executes an example input before a user arrives, allowing some first-inference setup to happen during startup.

Warm-up is optional. It can reduce first-user overhead but adds startup time. It does not guarantee that every request becomes faster or that all future cold effects disappear.

One local sequential experiment recorded:

| Measurement | Before startup warm-up | After startup warm-up |
| --- | ---: | ---: |
| First measured embedding | 324.06 ms | 61.23 ms |
| Average of requests 2–10 | 11.00 ms | 11.77 ms |
| Average of all 10 requests | 42.30 ms | 16.72 ms |

This single comparison suggests an improvement in the first request. It does not establish the exact cause or a guaranteed speedup. Later isolated requests around 300–350 ms also occurred. Machine load, scheduling, input shape, and idle gaps can affect observations. No production throughput claim follows from these runs.

## 5. Configuration: choosing the model without editing service code

`load_settings()` reads `EMBEDDING_MODEL` from the process environment. Missing values use `all-MiniLM-L6-v2`; leading/trailing whitespace is removed. A blank value raises `ValueError`.

A name such as `example-model` passes this configuration check because it is nonempty. Whether that model exists and can load is checked later by model creation. Configuration validation is not model availability validation.

The implementation does not automatically read `.env`. Set the variable in the launching shell or explicitly add an environment-file loader later. The local embedding service does not require an OpenAI API key.

### Keep the factory default consistent

In the reviewed snapshot, `create_app` defaults to `EmbeddingService`, while the module's exported app explicitly passes `None`. That exported app correctly enters the configured-model branch. However, calling plain `create_app()` uses the class's own default model and can bypass the configured name.

Before committing, make these two lines consistent:

```python
def create_app(embedding_service_factory=None):
    ...

app = create_app()
```

Keep the existing branch that constructs `EmbeddingService(model=settings.embedding_model)` when no custom factory is supplied. Fake factories supplied by tests still take no arguments.

The current loading log is placed after service construction. Moving it immediately before real-model construction would make it useful while a slow load is actually happening. Fake test factories do not necessarily represent the model named in settings.

## 6. Application factory and dependency injection

An application factory creates and returns a FastAPI application. It lets the caller choose how the embedding service will be created when startup runs.

| Situation | Service supplied |
| --- | --- |
| Normal application | Real model selected through settings |
| API tests | Small fake service with predictable output |
| Failure tests | Fake service that raises an expected error |

Passing a class or factory is different from creating the object immediately. Startup calls the supplied factory to create the instance.

The dependency provider retrieves the stored service from `request.app.state`. It does not create another model. FastAPI calls the provider and passes its returned object to the endpoint.

Using `Depends` alone does not guarantee reuse. A provider that creates a new service on every call still creates repeated instances. Lifespan owns creation; the provider supplies access.

## 7. Follow one request

For a valid POST to `/debug/embedding`:

1. Middleware creates a UUID request ID and begins application timing.
2. FastAPI validates the request body against `EmbeddingRequest`.
3. The dependency provider supplies the existing service.
4. The router strips surrounding whitespace and rejects blank text.
5. The service generates a vector while the endpoint measures that call.
6. The response model returns dimensions, five preview values, and embedding time.
7. Middleware attaches request ID and response-time headers and logs completion.

The router handles HTTP concerns. The service handles model inference. The service does not need a FastAPI request object.

`APIRouter` adds the `/debug` prefix to the route `/embedding`. Repeating the prefix in the route itself would produce `/debug/debug/embedding`.

## 8. Request and response validation

The request requires a text string with length 1–2,000 characters. The router separately rejects whitespace-only text after stripping it.

The 2,000-character limit is an initial API policy, not a tokenizer limit. A model can have a smaller effective token window and may truncate input even when the API accepts it. Token-aware chunking and truncation policy remain future work.

| Input | Expected result | Reason |
| --- | --- | --- |
| `Hello` | 200 | Valid input |
| Missing text | 422 | Required schema field absent |
| Empty string | 422 | Schema minimum length |
| Spaces only | 422 | Router blank-text check |
| Exactly 2,000 characters | Accepted by schema | Inclusive upper boundary |
| 2,001 characters | 422 | Schema maximum length |

The response model describes `dimensions`, `preview`, and `embedding_ms`. Use `response_model` for this Pydantic schema, not `response_class`.

Schema validation errors contain a list under `detail`; the router's explicit blank-text error contains a string. A client or test must inspect the actual response shape.

Current default validation errors may echo the submitted input. Custom error redaction is not implemented, so do not treat this endpoint as a completed PII-handling solution.

## 9. Why is the embedding endpoint a normal def?

The local model's encode method is synchronous. FastAPI runs a normal `def` endpoint in a worker thread, keeping that work off the event-loop thread.

Simply changing the endpoint to `async def` does not make a direct synchronous model call nonblocking or faster. An async endpoint with explicit thread offloading is another possible design.

A thread pool allows concurrency but does not provide unlimited inference capacity. Requests share the service instance, CPU/GPU resources remain finite, and concurrency behaviour must be measured. Batching, bounded concurrency, admission control, queues, and model-serving replicas are not implemented yet.

## 10. Health, readiness, and failures

| Endpoint or event | Meaning in this checkpoint |
| --- | --- |
| GET `/health` | Application can respond; returns `success: healthy` |
| GET `/ready` | Stored embedding service is not None; returns `status: ready` |
| Missing service state | Readiness returns 503 |
| Startup warm-up failure | Startup fails before serving |
| Request inference failure | Router logs traceback and returns a generic 503 |

Readiness currently checks initialization state only. It does not run an inference, inspect saturation, or automatically become unhealthy after an inference failure.

The router catches exceptions around the inference call. Its generic 503 avoids exposing exception details in that response, but it can also hide programming errors from clients; traceback logs remain important. No retry, timeout, circuit breaker, or fallback is present.

## 11. What do the logs and timings mean?

The application uses standard text logging through the Uvicorn logger. Messages include named fields, but this is not yet a JSON structured-logging pipeline.

| Measurement | Includes | Excludes |
| --- | --- | --- |
| `startup_ms` | Settings, service creation, warm-up | Server's entire boot lifecycle |
| `embedding_ms` | Timed encode call and list conversion | Request validation, thread waiting, networking |
| `X-Response-Time-Ms` | Work around `call_next`, including route handling and response preparation | Client network time and complete body transmission |

For one recorded request, embedding time was 351.79 ms and application time was 362.80 ms. The 11.01 ms difference is surrounding overhead; these two measurements do not identify its exact breakdown.

Request IDs connect a response to related success/failure logs. A fresh ID is generated per request. It is not an idempotency key and does not prevent repeated operations on retries.

Middleware attaches headers after `call_next` returns. Handled 422/503 responses can pass through this path. Unexpected unhandled exceptions can bypass its completion log and headers; global error observability remains incomplete. No user text or full vectors are intentionally logged by these messages.

## 12. Run and check the application

From the repository root, use the committed environment:

```bash
uv sync --locked --python 3.12.3
EMBEDDING_MODEL=all-MiniLM-L6-v2 PYTHONPATH=levels/level-4-production-rag uv run uvicorn app.main:app
```

Initial model use may need a download. Later runs can reuse cached weights. Ensure port 8000 is free. Open `http://127.0.0.1:8000/docs` for the interactive API.

For development, append `--reload --reload-dir levels/level-4-production-rag`. Saving files then restarts the server process, so model initialization and warm-up repeat. Do not use reload in production.

Check readiness and a real embedding:

```bash
curl -i http://127.0.0.1:8000/ready
curl -i http://127.0.0.1:8000/debug/embedding -H 'Content-Type: application/json' -d '{"text":"Hello world"}'
```

Expect 200 for both. The embedding response has 384 dimensions with the default model and five preview values. Response headers contain a request ID and application timing. Find the same request ID in the server log. Exact floating-point values and timing vary.

## 13. Tests: what do the 16 passing cases establish?

Latest user-run result: **16 passed, 1 warning in 2.09 seconds**. This documentation preparation did not rerun the application suite.

| Test file | Cases | Main behaviour |
| --- | ---: | --- |
| `test_embedding_schema.py` | 4 | Normal input, empty input, 2,000 and 2,001 boundaries |
| `test_config.py` | 3 | Default, custom name, blank setting |
| `test_readiness_api.py` | 4 | Health, ready, missing state, warm-up failure |
| `test_embedding_api.py` | 5 | Whitespace, missing field, success, inference failure, request IDs |

API tests supply fake service factories. They verify API wiring and controlled behaviour without loading real model weights, although importing the app still imports the model library. The success fake returns 384 values of 0.1, and the preview assertion confirms fake output is used.

A request-time failure fake lets the first warm-up call succeed and later raises an error. That separates startup failure from inference failure.

Tests use Arrange → Act → Assert. Expected errors belong inside `pytest.raises`. HTTP response objects need `.json()` before accessing body fields. `json.dumps` creates a string; it is not needed when directly constructing a schema.

```bash
PYTHONPATH=levels/level-4-production-rag uv run pytest levels/level-4-production-rag/tests -q
```

These cases do not establish live retrieval quality, live model correctness, load capacity, or complete log/timing coverage. Configuration tests do not verify that a custom model name reaches the real constructor; the factory-default issue above can therefore coexist with a passing suite.

## 14. Common mistakes and debugging

| Symptom | First check |
| --- | --- |
| Missing `dimensions` field | Compare constructor keyword spelling with schema; `dimentions` is a different key |
| Code looks fixed but old error remains | Save the correct file; restart server or enable development reload |
| Embedding method receives wrong object | Pass the text field, not the entire request schema |
| 404 on expected embedding route | Check router prefix plus route path |
| New instance on every request | Ensure dependency retrieves state rather than constructing a service |
| Valid input test fails with DID NOT RAISE | Valid input should use assertions, not expect an exception |
| Slow first request | Separate startup, warm-up, inference, and application timing |
| Semaphore warning only with reload | Compare without reload; exact dependency/process cause needs investigation |

Read a traceback from the final exception upward: identify the exception type, message, actual input, then the nearest frame in your own source. Do not assume every framework frame is a separate failure.

## 15. Limits and next steps

This checkpoint is a reusable embedding API foundation, not a complete production RAG system. Debug routes have no authentication and are not ready for unrestricted public exposure.

Next work includes vector storage and retrieval, context building, generation with citations, and a chat endpoint. Operational work includes input/token policies, concurrency controls, timeouts, robust error logging, JSON logs/metrics, tenant isolation, access control, retries/recovery, and deployment/load measurements.

Switching an embedding model is not only a settings change once documents are indexed. The document index must remain compatible, usually requiring re-embedding or a separate versioned index.

## 16. Quick revision checklist

- [ ] Explain model loading versus warm-up.
- [ ] Explain one instance per process versus one instance per request.
- [ ] Explain application factory versus dependency provider.
- [ ] Identify schema rejection versus router rejection.
- [ ] Explain why async syntax alone does not speed up inference.
- [ ] Explain initialization readiness versus actual inference health.
- [ ] Read an error from the traceback and locate the relevant own-code frame.
- [ ] Distinguish request ID from idempotency key.
- [ ] Distinguish startup, embedding, and application timing.
- [ ] Explain what fake-service tests prove and what requires real integration/load tests.

If I can explain these points in my own words, I can extend and debug the foundation rather than only recognize the code.
