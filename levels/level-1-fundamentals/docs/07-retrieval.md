# Step 7 — Semantic retrieval

> Level 1 learning note: this chapter preserves its original checkpoint. Steps 1–17 are now complete; see the [learning index](../../../README.md#level-1-learning-sequence). Commands below run from the repository root and select Level 1 with `PYTHONPATH`. Shared data remains under root `data/`.

## What is retrieval, and why is it required?

Retrieval finds passages that are relevant to a question. It is the “R” in retrieval-augmented generation: it selects information that could later support an answer. Our current system stops at returning passages. There is no generated answer or language-model call.

## Simple analogy

Ask a librarian a question. Instead of searching only for the exact words you said, the librarian looks for passages about the idea and hands you the most relevant ones. Embeddings approximate that relationship numerically; they do not reason like a librarian or verify the answer.

## Technical explanation: the complete process

```text
User query string
    ↓
Same Sentence Transformer used during ingestion
    ↓
384-dimensional query embedding
    ↓
Chroma compares it with indexed document vectors using cosine distance
    ↓
Rank nearest results (lower distance first)
    ↓
Return top-k documents, IDs, metadata and distances
```

Stored embeddings avoid re-encoding every document for each question. Chroma's index handles vector search; the Python retrieval script formats the returned results.

## Current implementation walkthrough

[`levels/level-1-fundamentals/scripts/run_retrieve.py`](../scripts/run_retrieve.py) creates `EmbeddingService` and `VectorStore`, prints the collection count, embeds `How many annual leave days do I get?`, and calls `search(query_embedding, top_k=2)`.

[`VectorStore.search`](../services/vector_store.py) passes `query_embeddings=[query_embedding]` and `n_results=top_k` to Chroma. `include` requests documents, metadata and distances; IDs are also returned by Chroma. The outer lists correspond to queries. Because there is one query, the script takes `[0]`, zips the parallel result lists, and prints each rank starting at 1.

**Top-K** is the maximum number requested, here two. It is not a relevance guarantee. **Ranking** orders returned candidates by distance. **Metadata** identifies the source and zero-based chunk index. **Similarity** is printed as `1 - distance`, which is valid because the collection is now verified to use cosine.

## Actual experiment/output

Verified locally on 2026-09-24 using Python 3.12.3 on macOS arm64, the existing pinned packages, the cached `all-MiniLM-L6-v2` model and a fresh cosine collection rebuilt from the sample PDF:

```bash
PYTHONPATH=levels/level-1-fundamentals .venv/bin/python -m scripts.run_ingest_document
PYTHONPATH=levels/level-1-fundamentals .venv/bin/python -m scripts.run_inspect_chroma
PYTHONPATH=levels/level-1-fundamentals .venv/bin/python -m scripts.run_retrieve
```

Ingestion: **343 characters → 5 chunks → 384 dimensions per vector**.
Collection: `documents_cosine`, count **5**. Query: `How many annual leave days do I get?`

| Rank | Source | Chunk index | Cosine distance | Cosine similarity |
| --- | --- | --- | --- | --- |
| 1 | company_policy.pdf | 0 | 0.2849968672 | 0.7150031328 |
| 2 | company_policy.pdf | 2 | 0.3235648870 | 0.6764351130 |

Rank 1 document:

```text
Company Leave Policy
Annual Leave:
Employees are entitled to 20 days of annual leave per year.
Carry
```

Rank 2 document:

```text
annual leave days.
Sick Leave:
Employees are entitled to 12 days of sick leave per year.
Parental L
```

These are measured example results, not values hardcoded into the retrieval implementation or exact-score tests. Hardware, model revisions and floating-point computation can affect results. Earlier experimental distances around 0.57 and 0.65 came from a collection that inspection found used L2; converting those values with `1 - distance` did not yield cosine similarity. See the [configuration correction](06-chromadb.md).

The first passage contains the relevant annual-leave entitlement. The second is related to leave but mixes a leftover annual-leave fragment with sick leave. This shows the limitations of tiny character windows and ranking by semantic similarity alone. A high score does not mean every fact in the returned chunk answers the question.

## Keyword search vs semantic search

Keyword search for “annual leave” matches those words (with details depending on the search system). Semantic search for “How much vacation can I take?” can find passages about annual leave because the model represents related meanings. This alternate question is a conceptual example, not the query used for the table above. Semantic search can miss relevant content too; it is not automatically better for every query.

## Common mistakes

- Running retrieval before ingestion; it creates/opens the collection but does not populate it.
- Using a different model for the question than the stored passages.
- Thinking higher distance is better or that similarity is confidence/probability.
- Reading the nested result arrays without selecting the query first.
- Treating the second result's sick-leave number as the annual-leave answer.
- Assuming a successful sample proves retrieval quality across many documents.

## Validation

`levels/level-1-fundamentals/tests/test_retrieval.py` runs the actual PDF parser, chunker, model and Chroma wrapper in a temporary database. It checks the text/chunk/vector sizes, finite vectors, repeat-upsert count, two ranked results, source metadata, the annual-leave passage and agreement between returned cosine distance and the independent manual cosine formula. Tests do not introduce retrieval controls into the application.

```bash
HF_HUB_OFFLINE=1 PYTHONPATH=levels/level-1-fundamentals .venv/bin/python -m unittest discover -s levels/level-1-fundamentals/tests -v
```

Use offline mode only after caching the model; omit `HF_HUB_OFFLINE=1` when a first download is needed. The original `levels/level-1-fundamentals/tests/test_embedding.py` remains an empty placeholder; embedding behavior is exercised by the integration test and the existing demonstration script.

## Interview questions

1. Why embed the query? To compare it in the same vector space as the chunks.
2. Does top-k guarantee useful results? No; it limits count, not relevance.
3. Why return metadata? To identify the source passage and inspect retrieval behavior.
4. Is this a complete answer-generating RAG system? No; only ingestion and retrieval are implemented.

## What I learned

The pipeline now connects a real PDF to ranked text passages. Inspecting the retrieved text, chunk boundaries and the actual metric is as important as printing a score.

## What is still missing, and next step

Step 8 — Retrieval Controls is **not started**. There are no similarity thresholds, metadata filters, no-result handling, retrieval API, LLM generation, `/chat`, answer citations, reranking, hybrid search or query rewriting. LangChain, LangGraph and agents are not used. Continue only after an explicit request.
