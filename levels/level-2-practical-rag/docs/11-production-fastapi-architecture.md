# Production FastAPI Architecture

## 1. Goal

This stage exposes the existing Level 2 answering services through a FastAPI application. A client can submit a question over HTTP and receive an answer with source citations.

The chapter title describes the architectural direction. The current implementation is a small API layer; production lifecycle management and resource optimization are not implemented yet.

The [source citations chapter](10-source-citations.md) explains the answer and citation content. This chapter focuses on connecting those services to HTTP endpoints.

## 2. Why Do We Need an API Layer?

Scripts are useful for learning and manual checks. An API gives a web application or another service a consistent way to submit questions without importing the Python services directly.

The API layer handles request parsing, response structure, and routing. The service layer performs embedding, retrieval, context construction, and generation. Keeping these responsibilities separate makes the request flow easier to test.

## 3. Components

| Location | Current responsibility |
| --- | --- |
| [`app/main.py`](../app/main.py) | Creates the FastAPI application and registers the health and answer routers |
| [`app/routers/health.py`](../app/routers/health.py) | Handles `GET /health` |
| [`app/routers/answer.py`](../app/routers/answer.py) | Defines request/response models and connects services for `POST /answer` |
| [`app/dependencies.py`](../app/dependencies.py) | Provides functions that construct the services used by the route |
| `services/` | Contains the RAG behavior reused by the API |

The application title is `Level 2 Practical RAG API`, with version `0.1.0`.

### Services used by the answer route

- [`EmbeddingService`](../services/embedding_service.py) uses `all-MiniLM-L6-v2` by default and returns a query embedding as a list.
- [`RetrievalService`](../services/retrieval.py) forwards that embedding to the vector store and returns its result unchanged.
- [`GroundedRAGService`](../services/grounded_rag_service.py) builds context, applies the empty-context guard, and returns `answer` and `citations`.

For the underlying behavior, see [metadata filtering](04-metadata-filtering.md), [grounding controls](09-grounding-controls.md), and [source citations](10-source-citations.md).

## 4. Endpoints

### 4.1 GET /health

Successful response: HTTP `200`.

```json
{"status": "ok"}
```

This endpoint confirms that the application can respond. It does not check the embedding model, Chroma contents, or OpenAI connectivity, and does not resolve the answer route's service dependencies.

### 4.2 POST /answer

Request:

```json
{
  "question": "How many annual leave days?"
}
```

Example successful response: HTTP `200`.

```json
{
  "answer": "Annual leave is 12 days.",
  "citations": [
    "Source: company_policy.pdf, Page: 1, Chunk: 0"
  ]
}
```

This response is an illustrative API test fixture, not a verified policy fact or a guaranteed real-model answer.

For empty or whitespace-only built context, the service returns:

```json
{
  "answer": "I don't have enough information to answer that question.",
  "citations": []
}
```

The fallback is a normal `200` response. It skips the generation call, but dependency construction, question embedding, and retrieval have already occurred. In particular, the real LLM client is constructed before this guard and still requires an API key.

The request model currently exposes only `question`. The route calls retrieval with its defaults: `top_k=2` and no metadata filter. It does not invoke query rewriting, hybrid search, or reranking.

## 5. Request Flow

```text
POST /answer: question
          |
          v
Resolve the three service dependencies
          |
          v
EmbeddingService.embed_text(question)
          |
          v
RetrievalService.retrieve(query_embedding=...)
          |
          v
GroundedRAGService.answer(question, results)
          |
          +---- Empty / whitespace-only context
          |                 |
          |                 v
          |       Fallback answer + [] citations
          |
          +---- Nonempty context
                            |
                            v
                 Grounded prompt → LLM generation
                            |
                            v
                 Citations from retrieved metadata
          |
          v
AnswerResponse: answer + citations
```

The endpoint receives existing indexed data through retrieval; it does not ingest PDFs. Citations identify retrieved chunks and do not independently verify that each generated claim is supported.

## 6. Dependency Injection

The answer route declares three providers using `Depends`:

```python
embedding_service = Depends(get_embedding_service)
retrieval_service = Depends(get_retrieval_service)
grounded_rag_service = Depends(get_grounded_rag_service)
```

These declarations are simplified excerpts of the typed route parameters. FastAPI resolves the providers and supplies their returned objects when handling the request.

The providers currently construct objects when called:

- `get_embedding_service()` creates `EmbeddingService`.
- `get_retrieval_service()` calls `get_vector_store()` and constructs `RetrievalService`.
- `get_grounded_rag_service()` calls the context-builder and LLM-client providers and constructs `GroundedRAGService`.

The nested provider calls are ordinary Python calls, not nested `Depends` declarations. There is no application-wide model cache or startup/shutdown lifecycle in this implementation. FastAPI's request-level dependency resolution does not make these objects shared across requests.

### Dependency overrides in tests

The answer tests replace each of the three route-level providers:

```python
app.dependency_overrides[get_embedding_service] = (
    lambda: mock_embedding_service
)
```

They similarly override retrieval and the grounded service, then clear overrides in `finally` blocks. This lets tests inspect the arguments passed between services without loading real resources or making generation requests through this route.

Overriding `get_llm_service` alone through FastAPI would not intercept the ordinary Python call inside `get_grounded_rag_service`. The provider-composition tests instead patch functions in `app.dependencies` directly.

## 7. Request Validation and Response Models

The router defines:

```python
class AnswerRequest(BaseModel):
    question: str = Field(min_length=1)


class AnswerResponse(BaseModel):
    answer: str
    citations: list[str]
```

`AnswerRequest` requires a question with at least one character. Missing `question` and `question=""` are invalid. FastAPI uses the model for request-body validation and normally returns HTTP `422` for invalid bodies.

The current tests verify these two validation cases by constructing the Pydantic model directly; they do not exercise invalid HTTP requests. Whitespace-only questions are not rejected by this length constraint because the route does not strip or validate their meaning.

`response_model=AnswerResponse` defines the expected JSON response shape. It does not check whether an answer is true or whether a citation supports it.

## 8. Running the API

Run from `levels/level-2-practical-rag` with the project environment installed:

```bash
PYTHONPATH=. uv run uvicorn app.main:app --reload
```

For example:

```bash
curl http://127.0.0.1:8000/health

curl -X POST http://127.0.0.1:8000/answer \
  -H 'Content-Type: application/json' \
  -d '{"question": "How many annual leave days?"}'
```

A real answer request needs the embedding model, an `OPENAI_API_KEY`, and a populated Chroma collection with the expected document metadata. The LLM wrapper can load environment values using `python-dotenv`; see [query rewriting](07-query-rewriting.md) for its existing client setup.

`get_vector_store()` uses the defaults `data/chroma` and collection `documents_cosine`. The database path is relative to the working directory. With the command above, it is inside the Level 2 directory. This is not the separate handbook-evaluation collection from [retrieval evaluation](08-retrieval-evaluation.md).

Creating the collection does not ingest documents. Do not assume that running the handbook evaluation ingestion script populates the API's default collection.

## 9. Tests

### Health endpoint

[`tests/test_api_health.py`](../tests/test_api_health.py) checks the `200` response and `{"status": "ok"}` body with FastAPI's `TestClient`.

### Dependency providers

[`tests/test_api_dependencies.py`](../tests/test_api_dependencies.py) checks provider return types and service composition. LLM construction and selected provider calls are patched.

Two tests instantiate the real embedding service and vector store. Consequently, this test file can load model weights and create/open `data/chroma`. It is not entirely isolated from local resources; a first model load may need a download.

### Answer endpoint

[`tests/test_api_answer.py`](../tests/test_api_answer.py) checks:

- Required and nonempty question validation through Pydantic.
- The answer/citations response model.
- Successful route handling using dependency overrides.
- Passing the question to the embedding service.
- Passing the embedding to retrieval.
- Passing the question and retrieval results to the grounded service.

The route tests use mocked services. The mocked fallback response checks the HTTP response path, not the real empty-context guard; the service tests described in [grounding controls](09-grounding-controls.md) cover that behavior.

### Commands and verification

From `levels/level-2-practical-rag`:

```bash
PYTHONPATH=. uv run pytest tests/test_api_health.py tests/test_api_dependencies.py tests/test_api_answer.py -q
PYTHONPATH=. uv run pytest -q
```

Verified full Level 2 result: **151 tests passed, 1 warning**. The warning is the existing Starlette/AnyIO `BlockingPortal` deprecation warning.

For this documentation review, the suite ran with the existing virtual environment and offline model settings, reusing cached weights:

```bash
PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONPATH=. \
  ../../.venv/bin/python -m pytest -q -p no:cacheprovider
```

These unit and integration-style API tests verify application wiring and response behavior. They do not establish that a real request retrieves the right passage or that OpenAI generates a supported answer. No live end-to-end answer request was performed for this documentation review.

## 10. Current Limitations

- Dependency providers construct service objects when called. Cross-request resource reuse, lifecycle cleanup, and production resource optimization are not implemented.
- The `/answer` handler is `async`, but calls synchronous embedding, retrieval, and generation methods directly. It does not make that work nonblocking.
- The route uses default vector retrieval; other Level 2 retrieval components are not connected here.
- There is no custom API error handling for model, database, generation, or citation failures.
- Nonempty context can still be insufficient, and citations are not claim verification.
- Authentication, rate limiting, deployment infrastructure, and operational monitoring are outside this API implementation.

This stage establishes a small HTTP boundary around working services. It provides a basis for later production work without claiming that the application is production-ready.
