# Step 9 — Retrieval API

## What are we learning, and why do we need an API?

In [Step 8](08-retrieval-controls.md), a Python script called our retrieval logic directly. Step 9 lets an HTTP client, such as a browser interface or another application, send a question and receive retrieved passages as JSON.

```text
Step 8: Retrieval logic
Step 9: Expose that retrieval logic through FastAPI
```

The API does not generate an LLM answer. It returns chunks that pass the current retrieval settings. Their similarity scores do not guarantee that they answer the question.

---

## Simple analogy

Step 8 is the librarian's method for finding and filtering passages. Step 9 adds a request desk.

The client fills in a form containing a question and optional search settings. The desk checks the form, passes the question to the existing retrieval services, and returns a structured list of passages. It does not write an answer from those passages.

---

## The complete flow

```text
HTTP Client
    ↓
POST /retrieve with a JSON body
    ↓
FastAPI
    ↓
Pydantic Request: parse fields and apply defaults
    ↓
Endpoint: strip query/source and reject an empty query
    ↓
EmbeddingService: query → embedding
    ↓
Step 8 VectorStore.search()
    ↓
ChromaDB: optional source filter → Top-K candidates
    ↓
VectorStore: distance → similarity → threshold filtering
    ↓
Retrieved chunks or []
    ↓
Pydantic Response model
    ↓
JSON Response
```

FastAPI also resolves the two service dependencies before calling the endpoint. This diagram explains the data flow; it does not promise that dependency construction waits until every input check has succeeded.

---

## 1. The endpoint: `POST /retrieve`

The route is defined directly in [`app/main.py`](../app/main.py):

```python
@app.post("/retrieve", response_model=RetrievalResponse)
async def retrieve(
    request: RetrievalRequest,
    embedding_service: EmbeddingService = Depends(get_embedding_service),
    vector_store: VectorStore = Depends(get_vector_store),
):
```

`POST` accepts a JSON request body. `RetrievalRequest` describes that body. `Depends(...)` asks FastAPI to supply the services. `response_model=RetrievalResponse` declares the shape of a successful response and lets FastAPI validate and serialize the returned data.

The endpoint returns ordinary Python dictionaries; FastAPI turns them into JSON. Successful retrieval, including an empty result list, uses HTTP **200**.

The existing `GET /health` and `POST /documents/upload` remain separate routes. Uploading a PDF still only extracts and chunks its text; it does not insert those chunks into Chroma. The existing ingestion script populates the vector store.

---

## 2. Request schema and actual validation

[`app/schemas/retrieval.py`](../app/schemas/retrieval.py) defines:

```python
from pydantic import BaseModel, Field


class RetrievalRequest(BaseModel):
    query: str
    top_k: int = Field(default=5, ge=1, le=20)
    source: str | None = None
    similarity_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
```

| Field | Required? | Default | Meaning |
| --- | --- | --- | --- |
| `query` | Yes | None; must be supplied | Question to embed |
| `top_k` | No | `5` | Maximum number of candidates requested from Chroma; 1–20 inclusive |
| `source` | No | `None` | Optional exact source metadata restriction |
| `similarity_threshold` | No | `0.5` | Minimum cosine similarity to keep a candidate; 0–1 inclusive |

A minimal request is:

```json
{"query": "How many annual leave days do I get?"}
```

A request with all settings is:

```json
{
  "query": "How many annual leave days do I get?",
  "top_k": 5,
  "source": "company_policy.pdf",
  "similarity_threshold": 0.5
}
```

Pydantic checks required fields and types. For example, a missing `query` or a list supplied as the query produces FastAPI's HTTP **422** validation response, assuming dependencies initialize successfully.

The model is not configured for strict types. In the current environment, `"top_k": "5"` is converted to integer `5`, and `"similarity_threshold": "0.5"` to float `0.5`. Extra fields are ignored by default. See [Pydantic's model documentation](https://docs.pydantic.dev/latest/concepts/models/) for conversion and extra-field behavior.

**Type checking and value checking have separate jobs.** `Field(...)` now enforces numeric bounds: `ge` means greater than or equal to, and `le` means less than or equal to. Top-K must be between 1 and 20; the threshold must be between 0 and 1. Both endpoints are allowed. Values outside those bounds, including non-finite thresholds such as `"NaN"` and `"Infinity"`, produce HTTP **422** when dependencies initialize successfully.

The threshold range is an **API rule**, not the mathematical range of cosine similarity. Cosine similarity can range from -1 to 1; this API allows callers to choose minimum scores only from 0 to 1. The Step 8 store itself is unchanged and is not given these Pydantic bounds when called directly.

Validation is still not strict about input types: for example, `true` can become Top-K `1` or threshold `1.0`. Numeric strings can also be converted as described above. Blank-query handling remains in the endpoint after `.strip()`; a blank string produces HTTP 400.

---

## 3. Response schema

The same schema file defines:

```python
class RetrievalResult(BaseModel):
    document: str
    metadata: dict
    distance: float
    similarity: float


class RetrievalResponse(BaseModel):
    query: str
    results: list[RetrievalResult]
```

The returned `query` is the **trimmed query**, not necessarily the original string including outer spaces.

| Response field | Meaning |
| --- | --- |
| `query` | Query used to create the embedding |
| `results` | Ordered list of accepted chunks; may be empty |
| `document` | Original stored chunk text |
| `metadata` | Stored metadata, normally `source` and `chunk_index` from ingestion |
| `distance` | Chroma cosine distance; lower is closer |
| `similarity` | `1 - distance`; higher means closer vector directions |

`metadata: dict` does not specifically validate that `source` or `chunk_index` exists. Those keys are supplied by our ingestion code. The response does not include an answer, total count, explicit rank field, or Chroma IDs. List order represents ranking.

For the annual-leave query with `top_k=1`, this response was observed during the review against a temporary copy of the sample database:

```json
{
  "query": "How many annual leave days do I get?",
  "results": [
    {
      "document": "Company Leave Policy\nAnnual Leave:\nEmployees are entitled to 20 days of annual leave per year.\nCarry",
      "metadata": {
        "source": "company_policy.pdf",
        "chunk_index": 0
      },
      "distance": 0.2849968671798706,
      "similarity": 0.7150031328201294
    }
  ]
}
```

These are measured example values, not constants in the route. Later runs can differ slightly. A similarity of about `0.715` is not a confidence percentage or a guarantee of correctness.

---

## 4. Dependency injection: who creates the services?

Dependency injection means the endpoint asks for a service and FastAPI supplies it by calling a function.

[`app/dependencies.py`](../app/dependencies.py) contains:

```python
from app.services.embedding_service import EmbeddingService
from app.services.retrieval_controls_vector_store import VectorStore


def get_embedding_service():
    return EmbeddingService()


def get_vector_store():
    return VectorStore()
```

Step by step:

1. FastAPI sees `Depends(get_embedding_service)` and calls that function.
2. The function constructs an `EmbeddingService`, which loads `all-MiniLM-L6-v2`.
3. FastAPI calls `get_vector_store()` to construct the Step 8 store using its default database path and collection.
4. FastAPI supplies both objects to `retrieve()`.

The database path is `data/chroma`, and the collection is `documents_cosine`. The store opens or creates it and checks that its metric is cosine. Construction does not ingest the sample PDF.

**Current lifetime:** these functions create new service objects on each request. There is no application-wide model cache or startup initialization in this code. Cached model files on disk are different from reusing a loaded Python model object. FastAPI's normal dependency reuse is within a request, not automatically across requests. See [FastAPI's dependency caching explanation](https://fastapi.tiangolo.com/tutorial/dependencies/sub-dependencies/).

This simple setup works for the learning exercise, but repeated model construction adds overhead. Dependency resolution also happens before the endpoint's blank-query check, so an invalid request can still cause service initialization work.

---

## 5. Why use the Step 8 VectorStore?

The API imports:

```python
from app.services.retrieval_controls_vector_store import VectorStore
```

The two learning implementations are intentionally separate:

| Implementation | Search parameters | Returned structure |
| --- | --- | --- |
| Step 7: `app/services/vector_store.py` | Query embedding and Top-K | Chroma's nested result dictionary |
| Step 8: `app/services/retrieval_controls_vector_store.py` | Query embedding, Top-K, optional source, threshold | List of result dictionaries or `[]` |

Step 9 needs the Step 8 parameters and return shape. The existing draft records an earlier wrong-import issue: the Step 7 search does not accept `source` or `similarity_threshold`. The current imports are correct. The two implementations have not been merged or redesigned.

---

## 6. Normalize the query and optional source

The endpoint uses:

```python
query = request.query.strip()
source = request.source.strip() if request.source else None
```

`.strip()` removes whitespace from the beginning and end. It does not rewrite the question, change capitalization, or remove spaces between words.

```text
"  How many annual leave days do I get?  "
    ↓
"How many annual leave days do I get?"
```

The optional source behaves as follows:

| Request value | Value passed to search | Effect |
| --- | --- | --- |
| Omitted or `null` | `None` | No source restriction |
| `""` | `None` | No source restriction |
| `"   "` | `""` | Step 8's `if source:` applies no source restriction |
| `" company_policy.pdf "` | `"company_policy.pdf"` | Match that source metadata value |

The source is a metadata value, not a file path to load. Supplying it does not ingest a new document. Clients can omit it when they want to search across the current collection.

---

## 7. Empty-query handling and HTTP errors

After stripping the query, the endpoint checks:

```python
if not query:
    raise HTTPException(status_code=400, detail="Query doesn't be empty.")
```

This is the exact current error text, including its grammar. For `{"query": "   "}`, the route returns HTTP **400** with:

```json
{"detail": "Query doesn't be empty."}
```

That differs from a missing query: `{}` fails request-schema validation with HTTP **422**. The blank query is rejected before `embed_text()` runs, but after service dependencies have been resolved.

| Situation | Current behavior |
| --- | --- |
| Valid retrieval request | HTTP 200 with query and results |
| No candidates survive | HTTP 200 with `results: []` |
| Empty or whitespace-only query | Explicit HTTP 400 |
| Missing query, invalid field type, or out-of-range retrieval settings | FastAPI/Pydantic HTTP 422 when dependencies succeed |
| Unhandled model/store errors | Server error; no custom translation is implemented |

There is no `try/except` around embedding or search, no retry policy, and no custom retrieval error handler. The earlier Top-K validation bug is fixed: `top_k=0`, `-1` or `21` now fails request validation with HTTP **422** before the route calls Chroma. Unexpected model/store failures are still not translated into custom responses.

---

## 8. Query → embedding → vector retrieval

The endpoint calls the existing services:

```python
query_embedding = embedding_service.embed_text(query)

results = vector_store.search(
    query_embedding=query_embedding,
    top_k=request.top_k,
    source=source,
    similarity_threshold=request.similarity_threshold,
)
```

The embedding service turns the normalized question into the same kind of vector used for the stored chunks. The Step 8 store then:

1. Converts a nonempty source into `where={"source": source}`.
2. Asks Chroma to search among eligible records and return up to `top_k` candidates.
3. Converts each cosine distance to similarity using `1 - distance`.
4. Keeps candidates whose similarity is greater than or equal to the threshold.
5. Returns the accepted dictionaries in their existing ranking order.

The API defaults to `top_k=5` and passes it explicitly. This overrides the store method's own default of `2`. The final result count can be smaller than Top-K.

The endpoint is declared `async def`, but `embed_text()` and `search()` are synchronous calls made directly inside it. There is no asynchronous embedding/database implementation or explicit offloading of those calls. They can block the event loop while running. Declaring the route async does not automatically make those calls nonblocking. See [FastAPI's explanation of directly called utility functions](https://fastapi.tiangolo.com/async/).

---

## 9. No-result response

If the store returns `[]`, the endpoint prints a terminal message and returns:

```python
return {"query": query, "results": []}
```

For the tested query `do you know my name?`, the observed HTTP **200** response was:

```json
{
  "query": "do you know my name?",
  "results": []
}
```

The terminal message `No relevant documents found.` is not a field in the JSON response. Both successful branches use the same response structure.

An empty result means no candidates passed the current retrieval settings. It does not prove the knowledge base has no answer. A source restriction, retrieval misses, or the threshold can exclude useful information.

Do not assume every question outside the PDF returns an empty list. Step 8's work-from-home experiment returned an incomplete policy fragment above the threshold. Exposing retrieval through HTTP does not fix that retrieval-quality limitation, and no LLM is involved here.

---

## 10. How to run and test through Swagger

Run from the repository root using the existing environment. If the sample is not yet ingested, run:

```bash
.venv/bin/python -m scripts.run_ingest_document
```

Then start the app:

```bash
.venv/bin/python -m uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs`:

1. Expand **POST /retrieve**.
2. Select **Try it out**.
3. Paste the full request from section 2.
4. Select **Execute**.
5. Inspect the status code, normalized query, and result fields.

FastAPI builds this interactive documentation from the route and Pydantic models. Its OpenAPI description is available at `/openapi.json`.

The same request can be sent with curl:

```bash
curl -X POST http://127.0.0.1:8000/retrieve \
  -H 'Content-Type: application/json' \
  -d '{"query":"How many annual leave days do I get?","top_k":5,"source":"company_policy.pdf","similarity_threshold":0.5}'
```

Try these small variations:

| Variation | What to inspect |
| --- | --- |
| Add outer spaces to query and source | Query is trimmed; source still matches |
| Set `top_k` to `1` | At most one accepted chunk |
| Omit source | Search without a source restriction |
| Raise threshold to `0.8` for the sample annual-leave query | Fewer results; the recorded sample scores are below it |
| Ask `do you know my name?` | Observed empty list with HTTP 200 |
| Use a whitespace-only query | HTTP 400 and the exact error text above |
| Omit `query` | HTTP 422 |

Use Top-K from 1 to 20 and finite thresholds from 0 to 1. To check validation, try `top_k=0`, `top_k=21`, `similarity_threshold=1.1` or `similarity_threshold="NaN"`; each should return HTTP 422, assuming service dependencies initialize successfully.

---

## 11. Current project structure

```text
app/
├── __init__.py
├── main.py                         Existing routes plus POST /retrieve
├── dependencies.py                 Service factory functions
├── schemas/
│   └── retrieval.py                Request, result and response models
└── services/
    ├── __init__.py
    ├── document_loader.py          PDF extraction
    ├── chunker.py                  Character chunking
    ├── embedding_service.py        Embedding model wrapper
    ├── vector_store.py             Step 7 learning implementation
    └── retrieval_controls_vector_store.py  Step 8 store used by Step 9
scripts/
├── run_ingest_document.py              Populates the sample collection
├── run_retrieve.py                     Step 7 script
└── run_retrieval_control_retrieve.py   Step 8 script
```

This shows the relevant files, not every script. There is currently no `app/schemas/__init__.py`; the import works in the inspected environment. There is no separate retrieval router module: the route lives in `app/main.py`.

---

## 12. Review checks and known gaps

During this documentation review, the API was exercised in-process with FastAPI's `TestClient`, the real embedding service, and the real Step 8 store directed at a temporary copy of `data/chroma`. The store constructor was patched only in the temporary check to select that copy; the route and dependency functions were unchanged. No API test file or new framework was added.

Observed checks:

* The default annual-leave request returned HTTP 200 and chunks `0`, `2`, `1`.
* Top-K set to one returned one accepted chunk.
* Outer query/source whitespace was removed, and whitespace-only source behaved as no restriction.
* The unrelated name question returned HTTP 200 and an empty list.
* Blank query returned 400; missing query and a list-valued query returned 422.
* `/docs` and `/openapi.json` responded successfully. These were HTTP checks, not a browser-based Swagger interaction.
* The existing eight tests passed with `HF_HUB_OFFLINE=1 .venv/bin/python -m unittest discover -s tests -v`. They cover earlier services/routes, not `/retrieve`. The installed test client emits a deprecation warning, but the tests pass.

### Validation fixes verified on 2026-09-26

The first review found that nonpositive Top-K reached Chroma and caused HTTP 500, and that a `"NaN"` threshold bypassed rejection. Adding the current `Field(...)` bounds fixed both issues. A follow-up check with the real services and a temporary database copy confirmed:

| Input/check | Observed result |
| --- | --- |
| Top-K `0`, `-1`, `21`, `1.5`, invalid text or `null` | HTTP 422 |
| Threshold `-0.1`, `1.1`, `"NaN"`, `"Infinity"`, `"-Infinity"`, invalid text or `null` | HTTP 422 |
| Boundary values: Top-K `1` and `20`, threshold `0` and `1` | Accepted |
| Normal annual-leave query | HTTP 200; chunks `0`, `2`, `1` |
| Step 8 ranking, source filtering, threshold and no-result checks | Passed |
| Existing eight tests | Passed; still no dedicated `/retrieve` tests in the repository |
| OpenAPI request schema | Shows the new minimum and maximum values |

The follow-up checks were temporary review checks, not new committed test files. The recorded retrieval scores earlier in this guide remain unchanged.

### Remaining limitations

| Finding | Why it matters |
| --- | --- |
| Pydantic still converts some types | Numeric strings and booleans may be accepted after conversion; strict type rejection is not configured |
| New model/service objects are constructed per request | Dependency injection is present, but application-wide reuse is not |
| Synchronous work runs inside `async def` | The endpoint is not a nonblocking retrieval implementation |

The route has basic `print()` statements for the question and no-result case, not structured application logging. Do not describe authentication, rate limiting, pagination, dedicated API regression tests, or advanced error handling as implemented.

---

## 13. Common mistakes and interview questions

### Does Pydantic validate everything about a request?

No. This model checks types, required fields and the explicit numeric bounds: Top-K 1–20 and threshold 0–1. The endpoint separately rejects blank queries. These checks do not establish that a question has an answer or that retrieved chunks are relevant.

### What does dependency injection do here?

FastAPI calls the two provider functions and gives their returned service objects to the endpoint. It does not automatically create a globally shared model.

### Why use the Step 8 store?

It accepts source and threshold parameters and returns the flat list expected by the response schema. The Step 7 store has a different interface.

### Why are blank and missing queries different?

A missing query fails the request model with 422. A blank string is a valid string type, so the endpoint strips and rejects it explicitly with 400.

### Is an empty result an HTTP error?

No. A completed search can return HTTP 200 with `results: []`. It does not establish that no answer exists anywhere in the collection.

### Does the API generate an answer?

No. It exposes retrieval results. Returning passages as JSON is different from generating a natural-language answer.

---

## What I learned

Step 9 connects an HTTP request to the services already built. Request models define inputs; dependencies supply services; the endpoint normalizes text and calls retrieval; response models describe the returned JSON.

I also learned to distinguish type validation from value validation, a per-request dependency from a shared model, and an async route declaration from nonblocking service calls.

## What is completed, and what is left for later?

The retrieval API path is implemented: request/response schemas, `POST /retrieve`, dependency injection, query/source normalization, empty-query handling, bounded Top-K and threshold validation, Step 8 search integration, and consistent JSON for populated and empty results.

Both reported validation bugs are fixed and rechecked. Step 9 is complete as a learning POC; the remaining limitations above are not a claim of production readiness.

Future work is intentionally not implemented in this step. The API returns retrieved chunks only; it does not generate an LLM answer. No further architecture or features were added during this documentation review.
