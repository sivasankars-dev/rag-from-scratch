# 05 — Hybrid Search

## 1. Overview

Hybrid search combines two different retrieval approaches:

1. Semantic search
2. Keyword search

Semantic search finds chunks based on meaning, while keyword search finds chunks containing matching words.

The goal is to combine both signals so that the final ranking benefits from both semantic relevance and exact keyword matching.

This document focuses on the practical hybrid retrieval pipeline implemented in Level 2.

For the fundamentals of embeddings, vector search, cosine distance, and semantic retrieval, refer to Level 1’s [embeddings](../../level-1-fundamentals/docs/04-embeddings.md), [cosine similarity](../../level-1-fundamentals/docs/05-cosine-similarity.md), and [retrieval](../../level-1-fundamentals/docs/07-retrieval.md) chapters.

---

## 2. Why Hybrid Search?

Semantic search is useful when the query and document use different words for the same concept.

For example:

```text
Query:
How many vacation days do employees get?

Document:
Employees receive 20 days of annual leave each year.
```

A semantic search can recognize that:

```text
vacation days ≈ annual leave
```

However, some queries depend heavily on exact terms.

For example:

```text
Query:
What is EMP-1024's status?
```

An exact identifier such as:

```text
EMP-1024
```

can motivate keyword-based retrieval. However, this implementation extracts `emp` and `1024` separately; the possessive query also contributes `s`. It matches those individual words, not the complete identifier, so it does not guarantee whole-identifier matching.

Therefore:

```text
Semantic Search
    ↓
Meaning-based matching

Keyword Search
    ↓
Exact-term matching
```

Hybrid search combines both.

---

## 3. High-Level Flow

The conceptual retrieval flow below includes preparation outside the hybrid function. The implemented `hybrid_search()` pipeline begins with already-prepared result lists at the merge step:

```text
                    Query
                      |
             +--------+--------+
             |                 |
             v                 v
      Semantic Search     Keyword Search
             |                 |
             +--------+--------+
                      |
                      v
             Merge Search Results
                      |
                      v
          Convert Distance → Similarity
                      |
                      v
          Normalize Keyword Scores
                      |
                      v
           Calculate Hybrid Scores
                      |
                      v
                Sort Results
                      |
                      v
                   Top-K
```

The current implementation keeps semantic retrieval and keyword retrieval separate.

The hybrid search layer receives already-prepared semantic and keyword result lists and combines them. It does not execute Chroma retrieval or adapt its nested response. Chroma-to-hybrid end-to-end integration is not implemented or demonstrated yet.

---

## 4. Keyword Search

A simple keyword search implementation was created in:

```text
services/keyword_search.py
```

The function is:

```python
search_keywords(query, chunks, top_k=2)
```

It:

1. Converts the query to lowercase.
2. Extracts words using a regular expression.
3. Extracts words from each lowercased chunk.
4. Finds the intersection between query words and chunk words.
5. Uses the number of matched words as the keyword score.
6. Sorts results by keyword score.
7. Returns up to `top_k` positive-score matches.

Each returned record contains `chunk` (the original chunk dictionary), `score` (the unique matched-word count), and `matched_words` (the matched words sorted alphabetically). Zero-score chunks are omitted.

Example:

```text
Query:
employee leave policy
```

A chunk containing:

```text
employee leave policy requires manager approval
```

may have:

```text
matched_words:
employee
leave
policy

score:
3
```

---

## 5. Why Regular Expressions Are Used

The keyword search uses:

```python
re.findall(r"\b\w+\b", text.lower())
```

instead of simply using:

```python
text.split()
```

The regular expression allows punctuation to be ignored during word matching.

For example:

```text
leave.
```

is converted to:

```text
leave
```

Therefore:

```text
Query:
leave

Chunk:
Employees receive annual leave.
```

can still produce a match.

Lowercasing the query and chunk text provides case-insensitive matching.

---

## 6. Keyword Search Limitations

The current keyword search is intentionally simple.

It does not implement a full lexical retrieval algorithm such as BM25.

It currently:

- counts unique matching words
- does not consider term frequency
- does not use inverse document frequency
- does not handle word stemming
- does not understand synonyms
- does not provide production-level lexical ranking

The purpose is to understand the mechanics of hybrid retrieval before introducing a production-oriented lexical search system.

Production systems may use BM25 through systems such as Elasticsearch or OpenSearch.

---

## 7. Merging Semantic and Keyword Results

The first hybrid-search operation is:

```python
merge_search_results(
    semantic_results,
    keyword_results,
)
```

The function combines prepared records from the two retrieval methods. A semantic input record has this shape:

```python
{
    "chunk": {"chunk": "annual leave policy", "source": "handbook.pdf", "chunk_index": 0},
    "score": 0.10,  # cosine distance, not similarity
}
```

Keyword records use the same `chunk` and `score` keys, with `score` holding the match count. The merge does not retain `matched_words`.

Each result keeps:

```text
chunk
semantic_score
keyword_score
```

For example:

```text
Semantic result:

chunk A
semantic_score = 0.20
```

and:

```text
Keyword result:

chunk A
keyword_score = 3
```

become:

```text
chunk A
semantic_score = 0.20
keyword_score = 3
```

If a chunk exists only in semantic results:

```text
semantic_score = existing score
keyword_score = 0
```

If a chunk exists only in keyword results:

```text
semantic_score = 0
keyword_score = existing score
```

This allows both retrieval systems to contribute to the final ranking.

---

## 8. Identifying the Same Chunk

A chunk cannot be identified only by `chunk_index`.

For example:

```text
document-A → chunk_index = 1
document-B → chunk_index = 1
```

These are two different chunks.

Therefore the implementation creates a logical chunk ID using:

```python
f"{chunk['source']}_chunk_{chunk['chunk_index']}"
```

This matches the ID strategy used by the vector store.

This separates documents only when their source identifiers are distinct. Identical source/index pairs are treated as the same chunk, even if the caller intended them to represent different documents.

---

## 9. Converting Semantic Distance to Similarity

Chroma returns the semantic result using distance.

For ranking:

```text
lower distance = better
```

Keyword scores work in the opposite direction:

```text
higher score = better
```

Combining these directly would therefore be incorrect.

The implementation converts semantic distance into a higher-is-better similarity score:

```python
similarity = 1 - distance
```

For example:

```text
Distance    Similarity
--------    ----------
0.10        0.90
0.30        0.70
0.60        0.40
```

This operation is implemented by:

```python
convert_distance_to_similarity(results)
```

This conversion assumes the current cosine-distance setup; it is not a general conversion for every distance metric. Similarities can be negative when distance exceeds 1, so they are not guaranteed to lie in `[0, 1]`.

The function converts every entry, including the zero placeholder assigned to keyword-only chunks. That placeholder becomes `1.0`, a current scoring limitation illustrated in Section 15.

---

## 10. Keyword Score Normalization

Keyword scores can have different raw values.

For example:

```text
Chunk A → 3
Chunk B → 2
Chunk C → 1
```

These values are converted to a normalized range based on the maximum score:

```python
normalized_score = score / max_score
```

Therefore:

```text
3 → 1.00
2 → 2/3 ≈ 0.67 (rounded for display)
1 → 1/3 ≈ 0.33 (rounded for display)
```

The implementation is:

```python
normalize_keyword_scores(results)
```

The maximum is taken over the supplied results. The code retains full floating-point precision rather than rounding to two decimals. If all keyword scores are zero, it returns the results unchanged.

---

## 11. Why Normalization Is Needed

Consider:

```text
semantic_score = 0.85
keyword_score = 3
```

If we directly calculate:

```text
0.5 × 0.85 + 0.5 × 3
```

the keyword score dominates simply because it uses a different numerical scale.

If the maximum keyword score is 3, after normalization:

```text
semantic_score = 0.85
keyword_score = 1.00
```

Both signals can now contribute more fairly.

This is a simple score-normalization strategy for the current learning implementation.

---

## 12. Calculating the Hybrid Score

The final score is calculated using weighted scoring:

```python
hybrid_score = (
    semantic_weight * semantic_score
    + keyword_weight * keyword_score
)
```

The current default is:

```text
semantic_weight = 0.5
keyword_weight = 0.5
```

Therefore:

```text
Hybrid Score =
    0.5 × Semantic Score
    +
    0.5 × Keyword Score
```

Example:

```text
Semantic score = 0.90
Keyword score  = 2/3 ≈ 0.67 (rounded for display)

Hybrid score =
    0.5 × 0.90 +
    0.5 × (2/3)

≈ 0.78333
```

The implementation is:

```python
calculate_hybrid_scores(
    results,
    semantic_weight=0.5,
    keyword_weight=0.5,
)
```

The results are sorted by `hybrid_score` in descending order.

---

## 13. Configurable Weights

The weights are configurable, but are not validated or automatically normalized. The examples below use weights summing to 1; these are score coefficients, not measured percentages of relevance.

For example:

```python
calculate_hybrid_scores(
    results,
    semantic_weight=0.7,
    keyword_weight=0.3,
)
```

means:

```text
0.7 × semantic score
0.3 × keyword score
```

While:

```python
calculate_hybrid_scores(
    results,
    semantic_weight=0.3,
    keyword_weight=0.7,
)
```

means:

```text
0.3 × semantic score
0.7 × keyword score
```

The current `0.5 / 0.5` configuration is mainly useful for learning and demonstration.

In a production system, these weights should be evaluated against a retrieval evaluation dataset rather than chosen arbitrarily.

---

## 14. Complete Hybrid Search Function

The orchestration of prepared result lists is implemented as:

```python
hybrid_search(
    semantic_results,
    keyword_results,
    top_k=2,
    semantic_weight=0.5,
    keyword_weight=0.5,
)
```

The function performs the following operations:

```text
1. Merge semantic and keyword results
2. Convert semantic distance to similarity
3. Normalize keyword scores
4. Calculate weighted hybrid scores
5. Sort by hybrid score
6. Return top_k results
```

Conceptually:

```python
merged_results = merge_search_results(
    semantic_results,
    keyword_results,
)

converted_results = convert_distance_to_similarity(
    merged_results
)

normalized_results = normalize_keyword_scores(
    converted_results
)

scored_results = calculate_hybrid_scores(
    normalized_results,
    semantic_weight=semantic_weight,
    keyword_weight=keyword_weight,
)

return scored_results[:top_k]
```

This keeps each operation small and independently testable.

---

## 15. Example

Suppose semantic search returns:

```text
Chunk A → distance = 0.10
Chunk B → distance = 0.30
```

Keyword search returns:

```text
Chunk A → keyword score = 2
Chunk C → keyword score = 3
```

After merging:

```text
Chunk A:
    semantic = 0.10
    keyword  = 2

Chunk B:
    semantic = 0.30
    keyword  = 0

Chunk C:
    semantic = 0
    keyword  = 3
```

After distance conversion:

```text
Chunk A:
    semantic = 0.90

Chunk B:
    semantic = 0.70

Chunk C:
    semantic = 1.00  (1 - the zero placeholder)
```

After keyword normalization:

```text
Chunk A:
    keyword = 2/3 ≈ 0.67 (rounded for display)

Chunk B:
    keyword = 0.00

Chunk C:
    keyword = 1.00
```

With:

```text
semantic_weight = 0.5
keyword_weight = 0.5
```

the scores become approximately:

```text
Chunk A:
    0.5 × 0.90 + 0.5 × (2/3) ≈ 0.78333

Chunk B:
    0.5 × 0.70 + 0.5 × 0.00 = 0.350

Chunk C:
    0.5 × 1.00 + 0.5 × 1.00 = 1.000
```

Final ranking:

```text
1. Chunk C → 1.000
2. Chunk A → ≈ 0.78333
3. Chunk B → 0.350
```

**Current scoring limitation:** Chunk C has no semantic result, but its merge placeholder `0` is treated as zero distance and converted to similarity `1.0`. This artificially gives it the maximum semantic contribution. The ranking above records current behavior, not evidence that C is the most relevant chunk.

The final `top_k` controls how many ranked candidates are returned; with `top_k=2`, these are C and A.

---

## 16. Why This Design Is Split Into Small Functions

Instead of putting everything inside one large function, the implementation separates the responsibilities:

```text
hybrid_search() orchestrates:
    1. merge_search_results()
    2. convert_distance_to_similarity()
    3. normalize_keyword_scores()
    4. calculate_hybrid_scores() — scores and sorts
    5. return results[:top_k]
```

This provides:

- easier testing
- easier debugging
- clearer responsibilities
- easier modification
- simpler understanding for beginners

The individual functions can be tested independently, while `hybrid_search()` orchestrates the score-combination pipeline.

---

## 17. Current Architecture

The following is a conceptual composition of retrieval and score combination, not an implemented end-to-end query workflow:

```text
                    Query
                      |
          +-----------+-----------+
          |                       |
          v                       v
   Semantic Retrieval       Keyword Retrieval
          |                       |
          |                       |
          +-----------+-----------+
                      |
                      v
               Hybrid Search
                      |
          +-----------+-----------+
          |                       |
          v                       v
    Semantic Score         Keyword Score
          |                       |
          +-----------+-----------+
                      |
                      v
              Weighted Ranking
                      |
                      v
                    Top-K
```

The existing Chroma-based retrieval service returns a nested dictionary of documents, metadata, and distances. It cannot be passed directly to `hybrid_search()`, which expects the list format in Section 7. That response adaptation is not currently implemented.

The keyword path currently uses the simple keyword search implementation created for Level 2.

---

## 18. Tests

`tests/test_hybrid_search.py` has **7 unit tests** covering helpers and the score-combination pipeline with handcrafted inputs. `tests/test_keyword_search.py` has **6 tests** covering matching, ranking, case insensitivity, result limiting, no matches, and preservation of chunk metadata.

The tests cover:

- merging semantic and keyword results
- keeping chunks from different sources separate
- keyword score normalization
- normalization of an empty result list
- semantic distance-to-similarity conversion
- hybrid weighted scoring
- final hybrid search ranking
- `top_k` result limiting

The full hybrid-function test asserts two returned results, Chunk C first, and descending scores. It does not assert the exact worked-example scores. There is no complete empty-keyword pipeline test, direct all-zero normalization test, or Chroma-to-hybrid integration test.

Run both test files from the repository root:

```bash
cd levels/level-2-practical-rag
PYTHONPATH=. ../../.venv/bin/python -m pytest \
  tests/test_keyword_search.py tests/test_hybrid_search.py -v -p no:cacheprovider
```

Previously verified result: **13 passed in 0.01s**. The documentation-update rerun also passed all 13 tests in **0.02s**. Passing tests confirm the behaviors they assert, including the current keyword-only scoring limitation.

---

## 19. Current Limitations

This implementation is intentionally simple.

Current limitations include:

1. Keyword retrieval uses basic word matching.
2. It does not implement BM25.
3. Score normalization is simple max-score normalization.
4. Hybrid weights are manually configured.
5. Weight selection has not yet been optimized using an evaluation dataset.
6. Keyword search is currently an in-memory operation over supplied chunks.
7. Keyword-only candidates receive artificial semantic similarity of 1.0 after conversion.
8. The Chroma-to-hybrid result adaptation is not implemented.
9. Final ranking only considers supplied candidates. Keyword and vector retrieval have their own candidate `top_k` limits before the final hybrid `top_k`; fusion cannot recover omitted candidates.

These boundaries describe the current learning implementation. In particular, the missing-semantic-score conversion is a scoring limitation, not a desired ranking property.

---

## 20. Production Direction

A future production approach could use BM25 through Elasticsearch or OpenSearch for lexical retrieval, then combine its candidates with vector-search results. Reranking could follow that combination.

Those components are not implemented here. The current keyword search scans supplied chunks in memory, and hybrid search combines supplied result lists.
---

## 21. Key Takeaways

The main lessons from this phase are:

1. Semantic search and keyword search solve different retrieval problems.
2. Hybrid search combines their strengths.
3. Different score directions must be made compatible before combining them.
4. Semantic distance can be converted into a higher-is-better similarity score.
5. Keyword scores should be normalized before weighted combination.
6. Hybrid weights control the contribution of each retrieval signal.
7. The same chunk must be identified consistently when merging results.
8. Final hybrid `top_k` is applied after ranking the supplied candidates.
9. Simple keyword matching is useful for learning but is not equivalent to BM25.
10. Production hybrid retrieval can use vector search + BM25 + score fusion + reranking.

---

## 22. Next Step

The current learning implementation has keyword matching and hybrid score-combination helpers, with the limitations documented above.

The next retrieval improvement is **Reranking**.

The flow will become:

```text
Query
  ↓
Hybrid Retrieval
  ↓
Candidate Chunks
  ↓
Reranking
  ↓
Best Relevant Chunks
  ↓
Top-K
```

Reranking will focus on improving the ordering of the candidates returned by the initial retrieval stage.