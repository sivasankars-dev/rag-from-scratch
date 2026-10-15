# Multi-Query Retrieval — Beginner-Friendly Implementation Guide

## 1. Why am I learning this?

This document explains the Multi-Query Retrieval implementation in Level 3, starting from the RAG pipeline built in Level 2.

The goal is not just to remember the code. The goal is to understand:

- What problem Multi-Query Retrieval solves
- Why the Level 2 retrieval system is reused
- What each Level 3 class is responsible for
- How queries become retrieved chunks
- How duplicate chunks are merged
- How Reciprocal Rank Fusion (RRF) works
- How tests check behavior on controlled examples
- How to evaluate whether Multi-Query Retrieval actually helps

Read this document alongside the source code. The handbook text below is illustrative, not the evaluation dataset’s ground truth. The examples are deliberately small so that you can trace the entire flow without needing an LLM or a vector database.

---

## 2. Refresh: What did Level 2 already teach me?

Level 2 implemented the practical RAG foundation.

At a high level, the pipeline looks like this:

```text
Documents
   |
   v
Split documents into chunks
   |
   v
Create embeddings for chunks
   |
   v
Store embeddings + text + metadata in Chroma
```

When a user asks a question:

```text
User question
     |
     v
Create question embedding
     |
     v
Retrieve the top-k similar chunks from Chroma
     |
     v
Use retrieved context to generate a grounded answer
```

An **embedding** represents text as a list of numbers. Similar meanings can have similar vector representations, allowing semantic retrieval to find relevant text even when the wording differs.

For example, a user might ask:

> How much vacation can an employee take each year?

But the handbook might say:

> Employees receive 18 days of annual leave.

Semantic retrieval can find the handbook chunk even though the two sentences use different words.

However, semantic retrieval is not perfect. Sometimes the wording, intent, or terminology of a question causes the most useful chunk to be missed or ranked too low.

That is the problem we want to explore in Level 3.

### Important: What does `top_k` mean?

`top_k` is the maximum number of results requested from a retrieval operation.

If `top_k=3`, a retrieval call should return at most three chunks. In this Level 3 implementation, the final fused result is also limited to three chunks when `retrieve(..., top_k=3)` is called.

---

## 3. The problem: One question can have multiple search interpretations

Imagine the user asks:

> How many annual leave days do employees get?

The handbook may use any of these expressions:

- Annual leave entitlement
- Paid vacation days
- Yearly leave allowance
- Employee time-off policy

These phrases are related, but a single search may not retrieve the best chunk every time.

The basic idea of Multi-Query Retrieval is:

1. Keep the original question.
2. Generate alternative queries.
3. Retrieve chunks separately for each query.
4. Merge the results.
5. Rank the merged results.
6. Return only the requested number of chunks.

Conceptually:

```text
Original question
       |
       v
Generate alternative queries
       |
       +-------------------+
       |                   |
       v                   v
 Original query       Alternative queries
       |                   |
       v                   v
 Original results     One list per alternative
       |                   |
       +---------+---------+
                 |
                 v
        Merge and deduplicate
                 |
                 v
         Reciprocal Rank Fusion
                 |
                 v
            Final top-k
```

**Key idea:** We are not generating several answers. We are generating several ways to search for evidence before answering.

---

## 4. What are we reusing from Level 2?

We do not need to rebuild document loading, chunking, embeddings, or Chroma storage just to experiment with a new retrieval strategy.

Level 3 reuses the Level 2 retrieval capability and adds a layer around it.

The new components have separate responsibilities:

| File | Responsibility |
|---|---|
| `services/multi_query_generator.py` | Ask an LLM to generate alternative search queries |
| `services/retrieval_adapter.py` | Convert Level 2's raw retrieval response into the chunk format expected by Level 3 |
| `services/rrf.py` | Combine multiple rankings using Reciprocal Rank Fusion |
| `services/multi_query_retrieval.py` | Coordinate the entire multi-query retrieval process |
| `scripts/run_evaluate_multi_query_retrieval.py` | Compare baseline retrieval and multi-query retrieval |
| `tests/` | Verify individual components and their integration |

This separation makes the code easier to test and maintain. For example, we can test RRF using ordinary Python lists without calling OpenAI or Chroma.

---

## 5. Component 1 — MultiQueryGenerator

**File:** `services/multi_query_generator.py`

### Why do we need it?

The query generator takes the original question and asks an LLM to produce alternative search queries.

For example:

```text
Input:
How many annual leave days do employees get?

Possible generated queries:
1. Annual leave entitlement
2. Paid vacation days
3. Yearly employee leave allowance
```

The generated queries are suggestions for searching. They are not verified facts and are not answers to the user.

### What does `num_queries` mean?

The generator is configured with a requested number of alternative queries. For example, `num_queries=3` means we ask for three alternatives.

The original question is handled separately by the retrieval service. If the LLM returns three alternatives, there are up to four unique search queries after cleanup. However, `num_queries` is only a request in the prompt: the parser does not enforce a maximum, so extra returned lines can lead to more searches.

The exact number used in retrieval can be smaller if the LLM produces duplicate or empty queries.

### How is the response parsed?

`generate_queries(question)` calls `llm_client.generate(prompt)` and splits the returned text into lines. It trims whitespace, skips blank lines, and removes a leading bullet (`-`, `•`, or `*`) or number such as `1.` or `2)`. It returns the remaining nonempty lines as a list. Deduplication happens later in `_build_queries()`, not in the generator.

### Why inject the LLM client?

The generator receives an LLM client rather than creating a provider connection inside its core logic.

This is useful because:

- Production code can use the real OpenAI client.
- Tests can use a fake client that returns predictable text.
- Tests do not need API calls, network access, or API tokens.
- The generator can be tested independently.

The fake LLM in the tests might return:

```text
annual leave entitlement
paid vacation days
```

This lets the test verify how the generator parses its output without depending on the model's live response.

**Remember:** LLM-generated queries can vary between runs. Do not expect the exact same alternatives every time when using a real model.

---

## 6. Component 2 — RetrievalAdapter

**File:** `services/retrieval_adapter.py`

### Why is an adapter necessary?

The Level 2 retrieval service returns a Chroma-style response. In simplified form, it looks like this:

```python
{
    "documents": [
        [
            "Employees receive 18 days of annual leave.",
            "Leave must be approved by a manager."
        ]
    ],
    "metadatas": [
        [
            {"source": "handbook.pdf", "chunk_index": 1},
            {"source": "handbook.pdf", "chunk_index": 2}
        ]
    ],
    "distances": [[0.1, 0.2]]
}
```

Notice that the results are stored in nested lists. Chroma can return one list of results per input query, even when we only need the results for a single query.

Level 3 wants to work with a simpler, consistent representation for each chunk:

```python
{
    "document": "Employees receive 18 days of annual leave.",
    "metadata": {
        "source": "handbook.pdf",
        "chunk_index": 1
    },
    "distance": 0.1
}
```

The adapter forwards `query_embedding`, `top_k`, and `metadata_filter` to the Level 2 service. It takes the first inner list from each response field, checks that their lengths match, and zips them into a list of chunk dictionaries in the same order. Misaligned lengths raise `ValueError`; empty result lists produce `[]`. It handles a single query’s results, not a batch of queries.

### Why does the metadata matter?

The text alone is not enough to identify a chunk reliably.

Two different chunks could contain similar or identical text. We need metadata to identify where a result came from.

In this implementation, a chunk is identified by:

```python
(source, chunk_index)
```

For example:

```python
("handbook.pdf", 1)
```

means chunk 1 from `handbook.pdf`.

This identifier allows the multi-query service to recognize the same chunk when it appears in results from multiple queries. The index must use distinct source identifiers and consistent chunk indices. The service raises `ValueError` if either identity field is missing or `None`.

### What are distances?

A retrieval distance is a measure produced by the underlying vector search. Its interpretation depends on the distance metric and implementation.

In this project, distance is preserved as retrieval information. The RRF algorithm does not use these distances directly; it uses each chunk's rank in each result list.

---

## 7. Component 3 — MultiQueryRetrievalService

**File:** `services/multi_query_retrieval.py`

This is the coordinator. It connects query generation, embedding, retrieval, merging, and ranking.

Its constructor receives three dependencies:

```python
MultiQueryRetrievalService(
    query_generator=...,
    embedding_service=...,
    retrieval_service=...,
)
```

Each dependency does one job:

- `query_generator`: generates alternative queries.
- `embedding_service`: converts each query into an embedding.
- `retrieval_service`: retrieves chunks for the embedding.

The service does not need to know how OpenAI is connected or how Chroma stores vectors. It only needs the expected interfaces.

### Step 1 — Build a clean query list

The `_build_queries()` method combines the original question with the generated alternatives.

It also:

- Skips non-string values.
- Removes leading and trailing whitespace.
- Skips empty strings.
- Removes duplicates without regard to letter case.
- Preserves a nonempty string original question as the first query; blank or non-string originals are skipped too.

Example input:

```python
original = "Annual leave days"
generated = [
    "paid vacation",
    " Annual leave days ",
    "",
    "PAID VACATION",
]
```

The cleaned query list becomes:

```python
[
    "Annual leave days",
    "paid vacation",
]
```

Why keep the original question? Because the generated alternatives may lose some important meaning. Keeping the original ensures that the user's initial wording is still searched.

Why deduplicate? Repeating an identical search wastes retrieval work and can distort how often a chunk appears across the query rankings.

### Step 2 — Embed each query

For each query, the service calls:

```python
query_embedding = self.embedding_service.embed_text(query)
```

The embedding service turns the query text into a vector.

The current implementation embeds queries one at a time in a sequential loop. The evaluation uses Level 2’s local `all-MiniLM-L6-v2` embedding model; OpenAI generates the alternative query text.

### Step 3 — Retrieve chunks for each query

The service calls the retrieval dependency with the query embedding, `top_k`, and optional metadata filter.

Conceptually:

```python
chunks = self.retrieval_service.retrieve(
    query_embedding=query_embedding,
    top_k=top_k,
    metadata_filter=metadata_filter,
)
```

This produces one ranked list of chunks for each query.

For example:

```text
Original query:
1. Chunk A
2. Chunk B

Alternative query:
1. Chunk B
2. Chunk C
```

The order is important. RRF uses these positions to determine how much each chunk contributes to the final ranking.

### Step 4 — Identify and merge duplicate chunks

Suppose Chunk B appears in both result lists. We do not want to return two copies of the same chunk.

The service uses the `(source, chunk_index)` metadata to identify it.

The service copies the first-seen chunk, retaining its document, metadata, and distance. Later occurrences update only the query tracking; distances are not averaged or replaced by the smallest distance.

For each first-seen chunk, it records:

- The chunk itself
- `retrieved_by`: the queries that retrieved it
- `retrieval_count`: the number of unique queries that retrieved it

Example of a merged chunk before the RRF score is added:

```python
{
    "document": "Employees receive 18 days of annual leave.",
    "metadata": {
        "source": "handbook.pdf",
        "chunk_index": 1
    },
    "distance": 0.1,
    "retrieved_by": [
        "Annual leave days",
        "annual leave entitlement"
    ],
    "retrieval_count": 2
}
```

Here, `retrieval_count=2` means the chunk was found by two distinct queries. It does **not** mean the chunk is twice as relevant, and it is not the RRF score.

### Step 5 — Record each query's ranking

For RRF, we need a list of chunk identifiers in their retrieved order for each query.

For example:

```python
rankings = [
    [("handbook.pdf", 1), ("handbook.pdf", 2)],
    [("handbook.pdf", 2), ("handbook.pdf", 3)],
]
```

Each inner list is a separate ranking.

The service keeps these rankings and passes them to the RRF function.

### Step 6 — Fuse the rankings

The service calls:

```python
fused_results = reciprocal_rank_fusion(rankings)
```

This returns a list of `(chunk_id, score)` pairs sorted by descending score. The next section explains the algorithm.

### Step 7 — Return only the final top-k

The service slices the fused list:

```python
fused_results[:top_k]
```

This is important. If the caller requests `top_k=3`, the final multi-query service must return no more than three chunks.

Retrieving top-k results for each individual query does not mean the merged result automatically contains only top-k chunks. The merged result can contain more unique chunks than any individual retrieval list.

---

The service returns a list of chunk dictionaries, adding `rrf_score` to each retained merged chunk. For a chunk ranked first in two query lists, one result could be:

```python
{
    "document": "Employees receive 18 days of annual leave.",
    "metadata": {"source": "handbook.pdf", "chunk_index": 1},
    "distance": 0.1,
    "retrieved_by": ["Annual leave days", "annual leave entitlement"],
    "retrieval_count": 2,
    "rrf_score": 2 / 61,
}
```

## 8. Component 4 — Reciprocal Rank Fusion (RRF)

**File:** `services/rrf.py`

### Why do we need RRF?

Each query produces its own ranking. We need a way to combine those rankings into a single ranking.

One query might rank Chunk A first, while another query ranks Chunk B first. RRF combines the rank positions without requiring the scores from different searches to be directly comparable.

### The formula

Ranks start at 1. For a chunk appearing at rank \(r\) in a ranking, its contribution is:

\[
\frac{1}{k+r}
\]

The contributions from all rankings are added together.

In this implementation, the default constant is \(k=60\). This constant is part of the RRF formula; it is different from the retrieval parameter `top_k`.

- `k=60` is the RRF ranking constant.
- `top_k=3` means return at most three final chunks.

### A small example

Suppose two queries return these results:

| Rank | Query A | Query B |
|---|---|---|
| 1 | Chunk A | Chunk B |
| 2 | Chunk B | Chunk C |
| 3 | Chunk C | Chunk A |

With RRF constant \(k=60\):

| Chunk | Contributions | Total RRF score |
|---|---|---:|
| A | \(1/61 + 1/63\) | 0.0323 approximately |
| B | \(1/62 + 1/61\) | 0.0325 approximately |
| C | \(1/63 + 1/62\) | 0.0320 approximately |

The final order is B, A, C. Chunk B ranks first because it appears at rank 1 in one ranking and rank 2 in another.

The actual implementation computes the score for each chunk ID, then sorts chunks by their total score in descending order. Equal scores retain the order in which chunk IDs were first encountered.

### Why does the implementation track duplicates inside each ranking?

A chunk should contribute only once per ranking. If an accidental duplicate chunk ID occurs in one result list, it must not receive extra RRF credit from that same list.

The RRF implementation uses a set for each ranking to avoid counting the same ID repeatedly within that ranking. Positions are not renumbered: in `[A, A, B]`, A contributes at rank 1 and B at rank 3.

### What RRF does not tell us

An RRF score is a ranking score, not a probability.

For example, a score of `0.03` does not mean a chunk has a 3% chance of being relevant. RRF is useful for ordering results, not for interpreting relevance as a probability.

---

## 9. Follow one complete example

Suppose the user asks:

> How many annual leave days do employees get?

Assume the query generator returns:

```text
annual leave entitlement
paid vacation days
```

The service searches these three queries:

```text
1. How many annual leave days do employees get?
2. annual leave entitlement
3. paid vacation days
```

Imagine the retrieval results are:

```text
Original question:
1. Chunk A — annual leave entitlement
2. Chunk B — leave approval

Alternative 1:
1. Chunk A — annual leave entitlement
2. Chunk C — vacation policy

Alternative 2:
1. Chunk C — vacation policy
2. Chunk A — annual leave entitlement
```

The service now:

1. Recognizes that Chunk A is the same chunk in all three rankings.
2. Recognizes that Chunk C appears in two rankings.
3. Records which queries retrieved each chunk.
4. Uses RRF to combine the rank positions.
5. Sorts the unique chunks by RRF score.
6. Returns only the requested number of final results.

Chunk A's `retrieval_count` is 3. Chunk C's `retrieval_count` is 2. But the final order is determined by RRF scores, not by `retrieval_count` alone.

This distinction is important: frequency is useful diagnostic information, while RRF considers both frequency and rank position.

---

## 10. Component 5 — Tests

Tests help us verify that the code behaves correctly without depending on a live LLM or vector database.

The project uses fake dependencies to control the inputs and outputs. Unit tests isolate a component; integration tests connect several real Level 3 components with fake external dependencies. Passing these cases does not prove better retrieval quality or verify live OpenAI/Chroma behavior. Retrieval quality needs a separate evaluation against labeled examples.

### `test_multi_query_generator.py`

Checks the query generator's behavior, including how generated query text is handled.

### `test_retrieval_adapter.py`

Checks that the raw Level 2 retrieval response is converted into the expected chunk format and metadata is preserved.

### `test_rrf.py`

Checks that the RRF function calculates and orders scores correctly, including duplicate IDs within a ranking.

### `test_multi_query_retrieval.py`

Checks the main coordinator's behavior, such as:

- The original question is included.
- Blank and duplicate queries are skipped.
- Chunks retrieved by multiple queries are merged.
- `retrieved_by` and `retrieval_count` are tracked.
- RRF results are ordered.
- The final result respects `top_k`.

### `test_multi_query_integration.py`

Checks that the components work together. It simulates the Level 2 response format and verifies that the adapter, generator, embedding fake, and multi-query retrieval service can cooperate.

An integration test does not need to call OpenAI or create a real Chroma database to verify this data flow.

### Run the tests

From the repository root:

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run pytest levels/level-3-advanced-rag/tests -q
```

The latest known result before the documentation update was 23 passing tests. Rerun the suite after any code changes and use the actual output as the source of truth.

---

## 11. Evaluation — does Multi-Query Retrieval improve results?

A more complex retrieval method is not automatically a better method. We compare it with the baseline using an evaluation dataset with expected relevant chunks.

This project records two retrieval metrics. The script matches each case’s single `expected_source` and `expected_chunk` pair against returned metadata. It does not use `expected_answer` or evaluate generated answer quality.

### Hit Rate@K

Hit Rate@K measures the fraction of questions for which a relevant expected chunk appears within the first K results.

For one question:

- Expected chunk appears at ranks 1, 2, or 3: hit.
- Expected chunk is absent from the top three: miss.

For a dataset, Hit Rate@K is:

\[
\text{Hit Rate@K} =
\frac{\text{Questions with a hit in top K}}
{\text{Total questions}}
\]

For example, 16 hits out of 20 questions gives a Hit Rate@3 of 80%.

### Mean Reciprocal Rank (MRR@K)

MRR considers how high the first relevant result appears.

For a question with its first relevant chunk at rank \(r\), reciprocal rank is:

\[
RR = \frac{1}{r}
\]

If no relevant chunk appears within the cutoff, its reciprocal rank is zero.

MRR is the average reciprocal rank across all questions. A relevant result at rank 1 contributes more than one at rank 3.

### Recorded challenging-dataset result

One recorded run on the 20-question challenging dataset produced:

| Metric | Baseline | Multi-query |
|---|---:|---:|
| Hit Rate@3 | 80% | 80% |
| MRR@3 | 0.7500 | 0.7500 |

In that run, Multi-Query Retrieval did not improve the aggregate metrics.

That is a valid experimental result. The objective is to measure whether the approach helps, not to force the numbers to show improvement.

LLM-generated queries may vary between runs, so record the dataset and observed results when rerunning the experiment.

### Why the final top-k cutoff matters

The evaluator’s `find_expected_chunk_rank()` scans the entire supplied result list; it does not apply its own K cutoff. The script sets `top_k=3` for both methods: baseline Chroma retrieval requests three results, and the multi-query service slices the fused ranking to three. Without that final slice, an expected chunk at rank 4 could incorrectly count as a Hit Rate@3 hit and contribute to MRR@3.

Always verify that the evaluated result list uses the intended cutoff. Otherwise, metrics can look better than the actual top-k retrieval quality.

### Limitations of this evaluation

This is a small, 20-question dataset from one handbook. Equal aggregate metrics do not show whether individual questions improved or worsened, or establish why the method did not help overall. Compare per-question ranks and retrieved evidence before drawing those conclusions.

The expected chunk labels in a dataset are a useful test target, but they may not capture every chunk that contains relevant information. Some questions can have multiple valid supporting chunks.

A miss can mean:

- The retrieval strategy failed to find the needed information.
- A relevant chunk was ranked below the cutoff.
- The expected chunk label is too narrow.
- The generated alternative queries did not help for that question.

Inspect missed examples before deciding which explanation is correct. Do not assume every miss is a bug in RRF.

---

## 12. Run the evaluation

The evaluation script compares baseline retrieval with Multi-Query Retrieval.

To run the challenging dataset from the repository root:

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run python levels/level-3-advanced-rag/scripts/run_evaluate_multi_query_retrieval.py --dataset challenging
```

The original dataset can be selected with:

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run python levels/level-3-advanced-rag/scripts/run_evaluate_multi_query_retrieval.py --dataset original
```

The real evaluation requires `OPENAI_API_KEY` (loaded from the environment or `.env`) and makes paid OpenAI calls through Level 2’s LLM client. The local embedding model must also be available; its first use may require a download.

Both methods use the same populated Chroma collection, `employee_handbook_evaluation`, at `levels/level-2-practical-rag/data/chroma_employee_handbook`. The script does not ingest documents. It checks that every expected source/chunk pair exists in the collection before evaluating and raises `ValueError` if one is missing.

`--dataset original` (the default) reads `levels/level-2-practical-rag/data/employee_handbook_evaluation.json`; `--dataset challenging` reads `levels/level-3-advanced-rag/data/employee_handbook_challenging_evaluation.json`. The script fixes `top_k=3` and requests three alternative queries.

---

## 13. Limitations and next steps

Multi-Query Retrieval increases the number of retrieval calls. Generating alternative queries also adds LLM latency and API cost.

It may not help when:

- The original query already retrieves the right chunk at rank 1.
- Alternative queries are repetitive or poorly phrased.
- The relevant chunk is absent from the indexed documents.
- The retrieval model does not understand the alternative wording.
- The evaluation dataset does not accurately represent the questions the system needs to answer.

Possible next experiments:

1. Inspect questions missed by both baseline and multi-query retrieval.
2. Review whether the expected chunk labels are unambiguous.
3. Compare generated queries with the wording of the relevant chunks.
4. Evaluate other retrieval approaches, such as hybrid search or reranking.
5. Change one factor at a time and compare the same evaluation dataset.

Do not combine many new techniques before establishing which change helps. Small controlled experiments make the results easier to explain and debug.

---

## 14. Quick revision checklist

Before considering this topic complete, I should be able to explain:

- [ ] How Level 2 turns documents into searchable chunks.
- [ ] Why one original question may not be enough for retrieval.
- [ ] Why the original query is kept alongside generated queries.
- [ ] Why the Level 2 response needs an adapter.
- [ ] Why `(source, chunk_index)` identifies a chunk.
- [ ] What `retrieved_by` and `retrieval_count` mean.
- [ ] How RRF combines multiple rankings.
- [ ] Why the RRF constant `k` is different from `top_k`.
- [ ] Why the final fused list must be limited to `top_k`.
- [ ] What Hit Rate@K and MRR@K measure.
- [ ] Why a passing test suite does not guarantee retrieval quality.
- [ ] What the unchanged recorded metrics establish, and what further inspection is needed to explain them.

If I can explain each point in my own words, I understand the core implementation rather than merely recognizing the code.

## Final takeaway

Level 2 taught me how to retrieve chunks for a question.

Level 3 Multi-Query Retrieval teaches me how to search for the same information in several ways, merge the resulting rankings, and measure whether the additional complexity actually helps.

The most important engineering lesson is that an advanced retrieval strategy needs three things: a clear reason to exist, tests that verify its behavior, and evaluation results that demonstrate its actual effect.
