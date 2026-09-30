# Step 9 — Retrieval API (original learning draft)

> Level 1 learning note: this chapter preserves its original checkpoint. Steps 1–17 are now complete; see the [learning index](../../../README.md#level-1-learning-sequence). Commands below run from the repository root and select Level 1 with `PYTHONPATH`. Shared data remains under root `data/`.

> Historical draft retained for the learning journey. For the current implementation, validated request bounds, exact responses and review results, use [Step 9 — Retrieval API](09-retrieval-api.md). The examples below predate the validation fixes and are not the current API contract.

## Goal

In Step 8, we implemented retrieval controls inside our `VectorStore`.

The retrieval logic could be called directly from Python, but a real application needs an API so that clients can send a question and receive retrieval results.

In this step, we exposed the retrieval functionality through a FastAPI endpoint.

The basic flow is:

```text
HTTP Client
    ↓
POST /retrieve
    ↓
FastAPI
    ↓
EmbeddingService
    ↓
VectorStore
    ↓
ChromaDB
    ↓
Retrieved chunks
    ↓
JSON response
```

---

## 1. Why Do We Need a Retrieval API?

Previously, retrieval was tested using a Python script.

For example:

```python
query_embedding = embedding_service.embed_text(question)

results = vector_store.search(
    query_embedding=query_embedding,
    top_k=5,
    source="company_policy.pdf",
    similarity_threshold=0.5
)
```

This works inside Python, but an application or frontend cannot directly call this Python function.

Instead, we expose it through an HTTP API:

```text
POST /retrieve
```

Now any HTTP client can send a query.

---

## 2. Request Schema

We created a Pydantic request model:

```python
class RetrievalRequest(BaseModel):
    query: str
    top_k: int = 5
    source: str | None = None
    similarity_threshold: float = 0.5
```

The API accepts:

| Field                  | Purpose                              |
| ---------------------- | ------------------------------------ |
| `query`                | User's question                      |
| `top_k`                | Maximum number of results            |
| `source`               | Optional document/source restriction |
| `similarity_threshold` | Minimum similarity required          |

Example request:

```json
{
    "query": "How many annual leave days do I get?",
    "top_k": 5,
    "source": "company_policy.pdf",
    "similarity_threshold": 0.5
}
```

---

## 3. Response Schema

We created a response model:

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

The API returns the original query and the retrieved chunks.

Example:

```json
{
    "query": "How many annual leave days do I get?",
    "results": [
        {
            "document": "...",
            "metadata": {
                "source": "company_policy.pdf",
                "chunk_index": 0
            },
            "distance": 0.28,
            "similarity": 0.71
        }
    ]
}
```

---

## 4. FastAPI Endpoint

The retrieval endpoint is:

```python
@app.post("/retrieve", response_model=RetrievalResponse)
async def retrieve(
    request: RetrievalRequest,
    embedding_service: EmbeddingService = Depends(get_embedding_service),
    vector_store: VectorStore = Depends(get_vector_store)
):
```

The endpoint receives:

1. `RetrievalRequest`
2. `EmbeddingService`
3. `VectorStore`

FastAPI's `Depends()` is used for dependency injection.

---

## 5. Dependency Injection

We created:

```text
levels/level-1-fundamentals/app/dependencies.py
```

It contains:

```python
def get_embedding_service():
    return EmbeddingService()


def get_vector_store():
    return VectorStore()
```

The important point is that `get_vector_store()` must import the **Step 8 VectorStore**:

```python
from services.retrieval_controls_vector_store import VectorStore
```

We initially had:

```python
from services.vector_store import VectorStore
```

That was the Step 7 implementation.

This caused an error because the Step 7 `search()` method did not accept:

```text
source
similarity_threshold
```

The correct dependency is therefore the Step 8 implementation.

---

## 6. Query Normalization

Before performing retrieval, the API removes unnecessary spaces:

```python
query = request.query.strip()
```

For example:

```text
"  How many annual leave days do I get?  "
```

becomes:

```text
"How many annual leave days do I get?"
```

We also normalize the optional source:

```python
source = request.source.strip() if request.source else None
```

If the source is not provided, it remains:

```python
None
```

This means the retriever can search without a source restriction.

---

## 7. Empty Query Handling

An empty query should not be sent to the embedding model.

Therefore we check:

```python
if not query:
    raise HTTPException(
        status_code=400,
        detail="Query cannot be empty."
    )
```

For example:

```json
{
    "query": "   "
}
```

results in a `400 Bad Request`.

---

## 8. Query → Embedding

Once the query is validated, we create its embedding:

```python
query_embedding = embedding_service.embed_text(query)
```

The flow is:

```text
User question
     ↓
EmbeddingService
     ↓
Query vector
```

The query vector is then passed to the vector store.

---

## 9. Calling the Retriever

The API passes the request values to the Step 8 retrieval implementation:

```python
results = vector_store.search(
    query_embedding=query_embedding,
    top_k=request.top_k,
    source=source,
    similarity_threshold=request.similarity_threshold
)
```

Therefore the API does not implement the retrieval logic itself.

It simply connects the HTTP request to the existing retrieval service.

```text
API
 ↓
EmbeddingService
 ↓
VectorStore.search()
 ↓
ChromaDB
```

This keeps the API layer simple.

---

## 10. Optional Source

The `source` field is optional.

If the user knows the document:

```json
{
    "query": "How many annual leave days do I get?",
    "source": "company_policy.pdf"
}
```

the retriever can restrict the search to that source.

If the user does not know the document:

```json
{
    "query": "How many annual leave days do I get?"
}
```

then no source restriction is applied.

The important idea is:

```text
source provided
    → filter by source

source not provided
    → search without source filter
```

We should not require the user to know the document name.

---

## 11. No Results

The retrieval service can return an empty list:

```python
[]
```

The API returns:

```json
{
    "query": "What is the work from home policy?",
    "results": []
}
```

An empty result means that no retrieved candidates passed the current retrieval settings.

It does not automatically mean that the knowledge base has no answer.

---

## 12. FastAPI Swagger

FastAPI automatically generates API documentation.

After starting the application, we can open the Swagger UI and test:

```text
POST /retrieve
```

This allows us to test the API without writing a separate frontend.

We can test:

* normal retrieval
* different `top_k`
* source filtering
* similarity threshold
* no source
* no relevant results
* invalid/empty queries

---

## 13. Project Structure

The relevant Step 9 files are:

```text
levels/level-1-fundamentals/app/
├── main.py
├── dependencies.py
└── schemas/
    └── retrieval.py
levels/level-1-fundamentals/services/
├── embedding_service.py
└── retrieval_controls_vector_store.py
```

---

## 14. Important Learning From Step 9

Step 9 connects the components we built in previous steps.

Previously:

```text
Python script
    ↓
EmbeddingService
    ↓
VectorStore
    ↓
ChromaDB
```

Now:

```text
HTTP request
    ↓
FastAPI endpoint
    ↓
Pydantic validation
    ↓
EmbeddingService
    ↓
VectorStore
    ↓
ChromaDB
    ↓
JSON response
```

The API layer is mainly responsible for:

* receiving the request
* validating input
* normalizing input
* calling the appropriate services
* returning a structured response

The retrieval service remains responsible for retrieval logic.

---

## 15. What We Have Completed

By the end of Step 9, we have:

* Created a retrieval request schema
* Created a retrieval response schema
* Created `POST /retrieve`
* Connected FastAPI to `EmbeddingService`
* Connected FastAPI to the Step 8 `VectorStore`
* Added dependency injection
* Added query validation
* Added query/source normalization
* Exposed `top_k`
* Exposed optional `source`
* Exposed `similarity_threshold`
* Added structured JSON responses
* Tested the endpoint through Swagger

The system can now receive a user's query through an API and return relevant document chunks.

The next major step is to use an **LLM to generate an answer from the retrieved chunks**.
