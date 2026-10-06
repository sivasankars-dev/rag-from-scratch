# Metadata Filtering

## 1. Purpose

Metadata filtering allows retrieval to restrict the searchable chunks before returning results.

This phase uses the metadata-enriched processor in `services/document_processor_with_source_policy.py`. Its chunk records contain:

- `source`
- `document_type`
- `page_number`
- `chunk_index`

This phase stores that metadata in Chroma and uses it during retrieval to constrain the result set.

The goal is not to replace semantic search. Instead:

```text
User Query
    ↓
Query Embedding
    ↓
Metadata Filter
    ↓
Vector Similarity Search
    ↓
Filtered Top-K Results
```

Metadata filtering answers:

> "Which chunks are allowed to participate in retrieval?"

Semantic similarity then determines:

> "Which of those allowed chunks are most relevant?"

For embedding, vector, and similarity fundamentals, refer to the relevant Level 1 documentation instead of repeating those concepts here.

---

## 2. Why Metadata Filtering Matters

Semantic similarity alone does not always provide enough control over the retrieval scope.

A vector collection may contain chunks from multiple documents or document categories.

For example:

```text
employee_handbook.pdf
    document_type = hr_policy

security_handbook.pdf
    document_type = security_policy

remote_work_policy.pdf
    document_type = hr_policy
```

A query such as:

```text
What is the annual leave policy?
```

may be semantically relevant to several chunks.

If the application knows that the user only wants HR policies, retrieval can be constrained with:

```python
where={"document_type": "hr_policy"}
```

This prevents chunks outside that metadata condition from participating in the retrieval result.

---

## 3. Metadata Schema

The earlier [`services/document_processor.py`](../services/document_processor.py) produces `chunk`, `page_number`, and `chunk_index`, as described in [Stage 3 — Document Processing](03-document-processing.md).

This phase uses [`services/document_processor_with_source_policy.py`](../services/document_processor_with_source_policy.py):

```python
process_document(
    pages,
    chunk_limit,
    overlap=0,
    source="",
    document_type="",
)
```

Callers supply `source` and `document_type`; the processor copies those values into each processed chunk. It preserves the page number and assigns the chunk index. The resulting metadata schema is:

| Field | Type | Purpose |
|---|---|---|
| `source` | string | Identifies the source document |
| `document_type` | string | Categorizes the document |
| `page_number` | integer | Identifies the original PDF page |
| `chunk_index` | integer | Identifies the chunk's position in the processed document |

Example processed chunk:

```python
{
    "chunk": "Employees get annual leave.",
    "page_number": 1,
    "chunk_index": 0,
    "source": "employee_handbook.pdf",
    "document_type": "hr_policy",
}
```

The metadata structure is created during document processing and preserved when the chunk is inserted into the vector store.

The Stage 3 document describes the earlier page/chunk-metadata implementation; the enriched processor above adds the caller-supplied source and document category.

---

## 4. Storing Metadata in Chroma

The Level 2 `VectorStore` provides:

```python
upsert_processed_chunks(processed_chunks, embeddings)
```

This method receives processed chunk records containing content and metadata, plus already-created embeddings. `VectorStore` does not generate embeddings.

Each chunk receives a deterministic ID:

```python
f"{chunk['source']}_chunk_{chunk['chunk_index']}"
```

Identical `source` and `chunk_index` values identify the same stored record. `document_type` is not part of the ID, and `source` defaults to an empty string in the enriched processor. These IDs therefore depend on the source values supplied by the caller.

The metadata stored in Chroma is:

```python
{
    "chunk_index": chunk["chunk_index"],
    "source": chunk["source"],
    "page_number": chunk["page_number"],
    "document_type": chunk["document_type"],
}
```

The chunk text is stored as the Chroma document, while the additional fields are stored as Chroma metadata.

This keeps retrieval content and retrieval constraints together.

---

## 5. Empty Input Handling

Chroma does not accept an empty embeddings list for an upsert operation.

Therefore, `upsert_processed_chunks()` returns immediately when there are no processed chunks:

```python
if not processed_chunks:
    return
```

This makes the vector-store method safely handle:

```python
upsert_processed_chunks([], [])
```

without attempting an invalid Chroma operation.

The behavior is covered by:

```text
test_upsert_empty_processed_chunks
```

---

## 6. Metadata-Filtered Search

The vector store exposes an optional metadata filter through the `search()` method:

```python
def search(self, query_embedding, top_k=2, where=None):
```

The filter is passed to Chroma:

```python
return self.collection.query(
    query_embeddings=[query_embedding],
    n_results=top_k,
    where=where,
    include=[
        "documents",
        "metadatas",
        "distances",
    ],
)
```

The important parameter is:

```python
where=where
```

This allows callers to constrain retrieval using metadata.

Example:

```python
result = vector_store.search(
    query_embedding=query_embedding,
    top_k=2,
    where={"document_type": "hr_policy"},
)
```

When `where` is not provided, the search can operate without a metadata restriction. `top_k` is an upper bound; metadata filtering may leave fewer matching results.

---

## 7. Filtering by `document_type`

A document type can be used to restrict retrieval to a particular category.

Example:

```python
where={"document_type": "hr_policy"}
```

If the collection contains:

```text
employee_handbook.pdf → hr_policy
security_handbook.pdf → security_policy
```

an HR-policy filter excludes the security-policy chunk from the retrieval result.

This was verified by:

```text
test_search_with_document_type_filter
```

The test confirms that only the HR-policy document is returned.

---

## 8. Filtering by `source`

Metadata filtering can also restrict retrieval to a specific source document.

Example:

```python
where={"source": "employee_handbook.pdf"}
```

This is useful when the application needs retrieval from a particular document while multiple documents exist in the same collection.

This behavior is covered by:

```text
test_search_with_source_filter
```

---

## 9. Filtering by `page_number`

`page_number` is stored as an integer rather than a string.

Example:

```python
where={"page_number": 2}
```

This matches page 2 across all documents in the collection unless another metadata condition, such as `source`, narrows the scope.

This is useful when an application has page-level context or needs to inspect a particular section of a source document.

This behavior is covered by:

```text
test_search_with_page_number_filter
```

The test supplies an integer page number, filters using an integer value, and checks that the returned value equals `2`. It does not explicitly assert the returned Python type.

---

## 10. Combining Metadata Filters

Multiple metadata conditions can be combined.

Example:

```python
where={
    "$and": [
        {"document_type": "hr_policy"},
        {"source": "employee_handbook.pdf"},
    ]
}
```

This means the chunk must satisfy both conditions.

For example:

```text
employee_handbook.pdf + hr_policy
```

matches both conditions.

Whereas:

```text
remote_work_policy.pdf + hr_policy
```

fails the `source` condition, and:

```text
security_handbook.pdf + security_policy
```

fails the `document_type` condition.

The combined-filter behavior is covered by:

```text
test_search_with_combined_metadata_filters
```

This demonstrates that metadata filtering can narrow the retrieval scope using multiple constraints.

---

## 11. Retrieval Service Responsibility

The retrieval layer provides an application-level boundary around the vector store.

The current `RetrievalService` accepts:

```python
retrieve(
    query_embedding,
    top_k=2,
    metadata_filter=None,
)
```

and passes the metadata filter to the vector store:

```python
return self.vector_store.search(
    query_embedding=query_embedding,
    top_k=top_k,
    where=metadata_filter,
)
```

The responsibility is therefore separated:

```text
Application / RAG layer
        ↓
RetrievalService
        ↓
VectorStore
        ↓
Chroma
```

The service receives an already-created query embedding and an optional Chroma-compatible metadata filter. It passes them to `VectorStore`, using `where` for the filter, and returns the vector-store result unchanged.

It does not generate embeddings, translate metadata-filter syntax, or normalize Chroma's nested results into a backend-independent format. Direct Chroma calls stay inside the vector-store layer.

---

## 12. Unit Testing the Retrieval Boundary

The retrieval service has a focused unit test using a fake vector store.

The purpose of this test is different from the Chroma filtering tests.

The vector-store tests verify:

> Chroma actually filters metadata correctly.

The fake-store test checks the retrieval service response path. `FakeVectorStore.search()` ignores its arguments and returns a fixed response, so this test does not independently verify argument propagation.

The real integration test below verifies metadata-filtered retrieval through `RetrievalService → VectorStore → Chroma`.

---

## 13. Integration Testing

A real integration test uses:

```text
RetrievalService
      ↓
VectorStore
      ↓
Chroma
```

The test inserts multiple processed chunks with different metadata and performs retrieval through `RetrievalService`.

The retrieval request contains:

```python
metadata_filter={"document_type": "hr_policy"}
```

The test verifies that the real Chroma-backed retrieval returns only the HR-policy chunk.

This confirms that the complete metadata-filtering path works together rather than only testing each component independently.

---

## 14. Test Coverage

The metadata filtering implementation is currently covered by the following tests in `tests/test_vector_store.py`:

```text
test_upsert_processed_chunks
test_upsert_multiple_processed_chunks
test_upsert_different_document_types
test_upsert_empty_processed_chunks
test_search_with_document_type_filter
test_search_with_source_filter
test_search_with_page_number_filter
test_search_with_combined_metadata_filters
```

The retrieval layer is covered by tests in:

```text
tests/test_retrieval.py
```

including:

```text
test_retrieve_with_metadata_filter
test_retrieve_with_real_vector_store_and_metadata_filter
```

The tests cover:

- Metadata storage
- Multiple processed chunks
- Different document types
- Empty input
- String metadata filtering
- Integer metadata filtering
- Combined metadata filtering
- Retrieval-service response path using a fake store
- Metadata-filtered retrieval through the service using real Chroma

---

## 15. Design Decisions

### Metadata belongs to the processed chunk

Metadata is created during document processing rather than reconstructed during retrieval.

This ensures that information such as page number and source travels with the chunk throughout the ingestion pipeline.

### Filtering is optional

The vector store accepts:

```python
where=None
```

so retrieval does not require a metadata filter for every query.

### Filtering is separate from semantic similarity

Metadata filtering defines the retrieval scope.

Vector similarity ranks chunks within that scope.

These are complementary mechanisms rather than alternatives.

### `chunk_index` is primarily an ordering and identity field

`chunk_index` is stored as metadata because it identifies the chunk's position within the processed document.

`chunk_index` can be passed through the generic `metadata_filter` interface. This phase does not demonstrate or test filtering by `chunk_index`.

---

## 16. Current Scope and Limitations

This phase implements metadata storage and basic metadata filtering.

It does not yet implement:

- Hybrid search
- Reranking
- Query rewriting
- Retrieval evaluation beyond the existing Level 1 fundamentals
- Production-scale filtering strategies
- Complex user-facing filter construction
- Multiple collection strategies

Those are separate concerns and will be addressed in later phases where appropriate.

The current implementation also keeps Chroma as the vector-store backend. The `RetrievalService` provides a boundary so that application-level retrieval logic does not need to directly interact with Chroma.

---

## 17. Key Takeaways

The important practical concepts from this phase are:

1. **Metadata should travel with every processed chunk.**
2. **The vector store should persist metadata alongside the chunk.**
3. **Metadata can restrict the candidate set before semantic ranking.**
4. **String and integer metadata can both be used for filtering.**
5. **Multiple metadata conditions can be combined.**
6. **The retrieval layer should provide a clean boundary between application logic and the vector database.**
7. **Unit tests and integration tests should verify different responsibilities.**

The resulting retrieval flow is:

```text
Document
    ↓
Metadata-Enriched Document Processing
    ↓
Processed Chunk
    ├── chunk
    ├── source
    ├── document_type
    ├── page_number
    └── chunk_index
    ↓
Processed Chunks + Already-Created Embeddings
    ↓
VectorStore
    ↓
Chroma
    ↓
Already-Created Query Embedding + Optional Metadata Filter
    ↓
RetrievalService
    ↓
Filtered Vector Search
    ↓
Top-K Results
```

---

## 18. Related Documentation

For concepts intentionally not repeated here:

- [Level 1 fundamentals](../../level-1-fundamentals/README.md) — embeddings, vectors, similarity, and basic retrieval
- [03-document-processing.md](03-document-processing.md) — earlier document processing with page numbers and chunk indexes
- [Metadata-enriched processor](../services/document_processor_with_source_policy.py) — adds caller-supplied `source` and `document_type`

This document focuses specifically on **persisting and using metadata during retrieval**.

---

## 19. Next Phase

The next Level 2 topic is:

**Hybrid Search**

The goal will be to combine semantic/vector retrieval with keyword-based retrieval so that the system can handle both semantic meaning and exact-term matching.