# 06 — Reranking

## 1. Goal

Improve the ordering of retrieved candidates before they are passed to the final answer-generation stage.

The retrieval stage is responsible for finding a candidate set.

The reranking stage aims to improve the ordering of those candidates using another relevance model.

High-level conceptual flow:

```text
User Query
    ↓
Hybrid Search
    ↓
Candidate Chunks
    ↓
Cross-Encoder Reranker
    ↓
Reranked Chunks
    ↓
Top-K Context
```

This flow represents the typical RAG architecture conceptually. The current Level 2 implementation does not yet connect Hybrid Search directly to the reranker or construct the final LLM context.

The current implementation focuses on:

```text
Supplied Candidate Chunks
    ↓
Query + Chunk Pairs
    ↓
Cross-Encoder Scoring
    ↓
Reranked Results
    ↓
Top-K
```

> Embeddings, vector search, cosine distance, and basic retrieval concepts are covered in Level 1. Refer to the Level 1 documentation when those concepts need to be reviewed.

---

## 2. Why Reranking?

Initial retrieval is optimized for efficiently finding relevant candidates.

However, the top retrieved chunks are not always ordered perfectly by their relevance to the user's question.

For example:

```text
Query:

"How many annual leave days are available?"

Retrieved candidates:

1. "Employees can request leave through the HR portal."
2. "Employees receive 18 days of annual leave per year."
3. "Leave requests must be approved by the manager."
```

The first retrieval stage may return all three because they are related to leave.

The second chunk appears more useful for answering the question.

Reranking allows us to reconsider the candidate chunks using another relevance model and aims to improve their ordering.

Reranking cannot recover a relevant chunk if that chunk was not included in the initial candidate set.

---

## 3. Retrieval vs Reranking

These two stages have different responsibilities.

### Retrieval

Retrieval answers:

> "Which chunks could be relevant?"

It should be relatively efficient because it may operate over a large document collection.

### Reranking

Reranking answers:

> "Among these candidate chunks, which ones should be ranked higher for this query?"

Because reranking is more computationally expensive, it is normally applied to a smaller candidate set.

Example:

```text
10,000 document chunks
        ↓
Initial retrieval
        ↓
Top 20 candidates
        ↓
Reranking
        ↓
Top 3 candidates
        ↓
LLM
```

This is a conceptual production-style flow. The current project does not yet implement this complete pipeline.

The important idea is:

**Retrieve broadly, then rerank narrowly.**

---

## 4. Cross-Encoder

Our Cross-Encoder reranker uses:

```text
cross-encoder/ms-marco-MiniLM-L-6-v2
```

A Cross-Encoder receives the query and candidate chunk together.

Example:

```text
Query:

"How many annual leave days are available?"

Chunk:

"Employees receive 18 days of annual leave per year."
```

The model produces a relevance score.

```text
(query, chunk)
      ↓
 Cross-Encoder
      ↓
 relevance score
```

A higher returned score ranks the candidate higher relative to candidates with lower scores.

These scores are relevance scores, not probabilities.

The current implementation does not require scores to be between `0` and `1`.

For example, the model may produce:

```text
Candidate A → -2.4
Candidate B →  1.7
Candidate C →  0.3
```

The important property for reranking is the relative ordering: higher scores are ranked first.

---

## 5. Why Not Use Embeddings Again?

Our initial retrieval already uses embeddings.

The important difference is how the models process the query and document.

### Embedding retrieval

The query and document are encoded separately:

```text
Query ─────→ Query Embedding
                   │
                   ↓
             Similarity Search
                   ↑
                   │
Chunk ─────→ Chunk Embedding
```

This is efficient and suitable for searching a large collection.

### Cross-Encoder

The query and chunk are processed together:

```text
Query ─────┐
           ├──→ Cross-Encoder ──→ Relevance Score
Chunk ─────┘
```

Because the model receives both pieces together, it can evaluate their relationship directly.

The trade-off is that Cross-Encoder scoring is more computationally expensive than simple vector similarity, which is why it is generally applied to a smaller candidate set.

> The embedding and vector-search fundamentals are covered in Level 1. Refer to the relevant Level 1 documentation for those concepts.

---

## 6. Reranking Strategy

Our Level 2 implementation focuses on the reranking portion of the pipeline.

The current implementation receives candidates that have already been prepared by an earlier retrieval stage.

The flow is:

```text
Supplied candidates
       ↓
Create (query, chunk) pairs
       ↓
Cross-Encoder scoring
       ↓
Attach reranker scores
       ↓
Sort descending
       ↓
Return top_k
```

For example:

```text
Candidate A → 0.21
Candidate B → 0.89
Candidate C → 0.54
```

After reranking:

```text
1. Candidate B → 0.89
2. Candidate C → 0.54
3. Candidate A → 0.21
```

The example scores are illustrative relevance scores, not probabilities.

---

## 7. Implementation

The implementation is located in:

```text
services/reranker.py
```

There are two reranking approaches in this file.

### Simple lexical baseline

The file contains:

```python
calculate_reranker_score()
```

and:

```python
rerank()
```

These functions use simple word-overlap scoring.

They provide a basic baseline for understanding the mechanics of reranking.

### Cross-Encoder reranking

The main implementation covered in this document is:

```python
def rerank_with_cross_encoder(query, candidates, model, top_k=2):
```

The Cross-Encoder model is passed into the function rather than created inside it.

This separates model construction from the reranking logic.

For example, the caller can create the model:

```python
from sentence_transformers import CrossEncoder

model = CrossEncoder(
    "cross-encoder/ms-marco-MiniLM-L-6-v2"
)
```

and then pass it to:

```python
results = rerank_with_cross_encoder(
    query,
    candidates,
    model,
)
```

This also allows the unit tests to provide a fake model.

Later, in the production FastAPI phase, the model can be loaded once during application startup and reused across requests.

---

## 8. Empty Candidate Handling

Before calling the model, we check whether candidates exist:

```python
if not candidates:
    return []
```

This avoids unnecessary model execution.

It also gives the function a clear result for an empty candidate list.

```text
No candidates
     ↓
Return []
```

---

## 9. Creating Query-Chunk Pairs

The Cross-Encoder expects query and document pairs.

Our implementation creates them using:

```python
pairs = [
    (query, candidate["chunk"]["chunk"])
    for candidate in candidates
]
```

For example:

```text
Query:

"annual leave days"

Candidate 1:

"Employees receive annual leave days."

Candidate 2:

"Employees can request leave."
```

becomes:

```python
[
    (
        "annual leave days",
        "Employees receive annual leave days."
    ),
    (
        "annual leave days",
        "Employees can request leave."
    )
]
```

Each pair contains:

```text
(query, candidate chunk text)
```

---

## 10. Batched Prediction

The implementation sends all pairs to the model through one `predict()` call:

```python
scores = model.predict(pairs)
```

Instead of:

```python
for pair in pairs:
    model.predict([pair])
```

we use:

```python
model.predict(pairs)
```

This gives the model the complete set of candidate pairs supplied to the function.

The exact internal batching behavior is handled by the model/library and is not assumed by this implementation.

The important application-level behavior is that we make one prediction call for the candidate list.

---

## 11. Score Validation

The number of scores returned by the model must match the number of candidates.

We therefore validate:

```python
if len(scores) != len(candidates):
    raise ValueError(
        "Number of reranker scores must match number of candidates"
    )
```

This protects against a silent problem with:

```python
zip(candidates, scores)
```

If there were three candidates but only two scores, `zip()` would silently process only two candidates.

The explicit validation makes the failure visible instead.

---

## 12. Adding Reranker Scores

Each candidate receives its corresponding Cross-Encoder score:

```python
for candidate, score in zip(candidates, scores):
    result = candidate.copy()
    result["reranker_score"] = float(score)

    reranked_results.append(result)
```

We use `candidate.copy()` so existing information is preserved.

For example:

```python
{
    "chunk": {...},
    "hybrid_score": 0.80,
    "reranker_score": 0.95
}
```

The existing `hybrid_score` is not removed.

This allows us to retain information from the previous retrieval stage.

---

## 13. Sorting

After adding the Cross-Encoder scores, candidates are sorted from highest score to lowest:

```python
reranked_results.sort(
    key=lambda result: result["reranker_score"],
    reverse=True,
)
```

Therefore:

```text
0.95
0.72
0.41
0.10
```

becomes the final relevance order.

The scores determine the ranking; the implementation does not convert them into probabilities.

---

## 14. top_k

Finally, the function returns:

```python
return reranked_results[:top_k]
```

`top_k` limits the number of candidates returned after reranking.

For example:

```python
top_k=2
```

with four candidates:

```text
Candidate A → 0.95
Candidate B → 0.72
Candidate C → 0.41
Candidate D → 0.10
```

returns:

```text
Candidate A
Candidate B
```

### Important implementation detail

All supplied candidates are scored before the `top_k` slice is applied.

Therefore, reducing `top_k` does not reduce the Cross-Encoder scoring work for the same candidate list.

For example:

```text
20 candidates + top_k=3
```

still scores all 20 candidates and returns only the best 3.

The current function does not perform explicit `top_k` validation.

Therefore, its behavior follows normal Python slicing semantics for values such as `0` or negative integers.

---

## 15. Complete Cross-Encoder Reranker

The current implementation is:

```python
def rerank_with_cross_encoder(query, candidates, model, top_k=2):
    if not candidates:
        return []

    pairs = [
        (query, candidate["chunk"]["chunk"])
        for candidate in candidates
    ]

    scores = model.predict(pairs)

    if len(scores) != len(candidates):
        raise ValueError(
            "Number of reranker scores must match number of candidates"
        )

    reranked_results = []

    for candidate, score in zip(candidates, scores):
        result = candidate.copy()
        result["reranker_score"] = float(score)

        reranked_results.append(result)

    reranked_results.sort(
        key=lambda result: result["reranker_score"],
        reverse=True,
    )

    return reranked_results[:top_k]
```

---

## 16. Testing Strategy

The unit tests are located in:

```text
tests/test_reranker.py
```

The test file contains tests for both reranking approaches.

The simple lexical baseline tests verify the behavior of:

```text
calculate_reranker_score()
rerank()
```

The Cross-Encoder-focused tests verify:

```text
rerank_with_cross_encoder()
```

For the Cross-Encoder tests, we do not load the actual model.

Instead, we use a small fake model:

```python
class FakeCrossEncoder:
    def __init__(self, scores):
        self.scores = scores
        self.received_pairs = None

    def predict(self, pairs):
        self.received_pairs = pairs
        return self.scores
```

This allows us to control the returned scores and verify our application logic without performing real model inference.

Because the real model is no longer constructed at module import time, importing `services.reranker` does not require the model to be downloaded or initialized.

This makes the Cross-Encoder unit tests independent of real-model loading.

The actual Cross-Encoder model is used separately when we want to perform real inference.

---

## 17. What We Test

The Cross-Encoder reranker tests verify:

### Query and chunk pairs

The correct query/chunk pairs are passed to the model.

### Score assignment

The returned scores are attached as:

```text
reranker_score
```

### Correct ordering

Candidates are sorted according to the reranker score.

### Existing fields

Existing fields such as:

```text
hybrid_score
chunk
```

are preserved.

### top_k

Only the requested number of candidates is returned.

### Empty candidates

An empty candidate list returns:

```python
[]
```

without calling the model.

### Score-count mismatch

A mismatch between candidate count and returned score count raises `ValueError`.

The test suite currently covers both the lexical baseline and the Cross-Encoder reranking function.

---

## 18. Why We Don't Rerank Everything

Reranking is not automatically required for every query.

It adds additional computation and therefore can add latency.

A typical production architecture may use:

```text
Large corpus
    ↓
Fast retrieval
    ↓
Small candidate set
    ↓
More expensive reranking
    ↓
Final context
```

For example:

```text
10,000 chunks
     ↓
Retrieve 20
     ↓
Cross-Encoder rerank 20
     ↓
Keep 3
```

The exact numbers are application-dependent.

We should not choose an arbitrary rule such as:

```text
"If retrieval score < 0.7 → rerank"
```

without measuring whether that policy actually improves the desired retrieval/ranking quality enough to justify its latency.

Retrieval evaluation later in Level 2 will help us make such decisions based on measurements.

---

## 19. Important Trade-Off

Reranking introduces a quality-vs-latency trade-off.

```text
More candidates
      ↓
More Cross-Encoder scoring work
      ↓
Potentially more candidate coverage
      ↓
Higher latency
```

Therefore, the practical pattern is generally:

**Retrieve enough candidates to provide a useful candidate set, but rerank only a manageable candidate set.**

The exact candidate count should be selected based on the application's quality and latency requirements.

---

## 20. Current Scope

This Level 2 implementation intentionally focuses on understanding and implementing the core reranking logic.

### Implemented boundary

```text
Supplied Candidate Chunks
       ↓
Create Query + Chunk Pairs
       ↓
Cross-Encoder Scoring
       ↓
Attach Reranker Scores
       ↓
Sort Results
       ↓
Return Top-K
```

The implementation does **not** currently:

- execute Hybrid Search itself
- connect Hybrid Search directly to the Cross-Encoder
- construct the final LLM context
- call an LLM for answer generation

### Not yet covered

- production model serving
- GPU optimization
- model quantization
- advanced batching strategies
- latency benchmarking
- reranker model comparison
- dynamic reranking policies

These can be considered later if required for production architecture.

---

## 21. Key Interview Takeaways

### What is reranking?

Reranking takes an initial set of retrieved candidates and reorders them using another relevance model.

The goal is to improve the ordering of the candidate set.

### Why use a Cross-Encoder?

A Cross-Encoder processes the query and candidate together, allowing it to model their interaction directly rather than relying only on independently generated embeddings.

### Why not use it over the entire corpus?

Cross-Encoder scoring is more computationally expensive, so it is normally applied after initial retrieval to a smaller candidate set.

### What happens if the relevant chunk was not retrieved?

Reranking cannot recover a chunk that is absent from the candidate set.

This is why initial retrieval quality still matters.

### What is the common architecture?

Conceptually:

```text
Retrieve Top-N
      ↓
Cross-Encoder Rerank
      ↓
Select Top-K
      ↓
LLM
```

The current project implements the reranking boundary itself; the complete end-to-end orchestration will be addressed later.

### What do the Cross-Encoder scores mean?

They are relevance scores used for ranking.

They are not probabilities and are not required to be between `0` and `1`.

Higher returned scores are ranked first.

### What is the main trade-off?

Reranking can improve candidate ordering, but additional Cross-Encoder computation can increase latency and compute usage.

---

## 22. Level 2 Position

Completed Level 2 components:

```text
🟢 Better chunking
🟢 Metadata filtering
🟢 Hybrid search
🟢 Reranking
```

Remaining:

```text
⬜ Query rewriting
⬜ Retrieval evaluation
⬜ Hallucination / grounding controls
⬜ Source citations
⬜ Production FastAPI architecture
```

The next topic is **Query Rewriting**.