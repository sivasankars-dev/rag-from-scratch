
# Hybrid Retrieval: BM25 + Vector Search

## 1. Objective

Hybrid retrieval combines semantic vector search with lexical keyword search.

- Vector search retrieves chunks based on semantic similarity.
- BM25 retrieves chunks based on keyword relevance.
- Reciprocal Rank Fusion (RRF) combines the rankings.

The objective is to improve retrieval robustness when either semantic similarity or exact keyword matching alone is insufficient.

## 2. Architecture

1. Receive the user's query.
2. Run vector retrieval using the embedding model and Chroma.
3. Run BM25 keyword retrieval over the document chunks.
4. Identify chunks using stable IDs: `(source, chunk_index)`.
5. Fuse both ranked lists using RRF.
6. Return the highest-ranked unique chunks.

## 3. Reciprocal Rank Fusion

For a chunk appearing in multiple ranked lists, its RRF score is:

RRF(d) = sum(1 / (k + rank_i(d)))

Here:
- `d` is a document chunk.
- `rank_i(d)` is its rank in a retrieval result list.
- `k` is a smoothing constant, set to 60.
- A missing chunk contributes zero from that ranking.

RRF combines ranks rather than directly comparing BM25 scores with vector distances. This avoids mixing incompatible score scales.

## 4. Implementation

- `services/bm25_retrieval.py`: BM25 indexing and keyword retrieval.
- `services/hybrid_retrieval.py`: combines vector and BM25 retrieval.
- `services/rrf.py`: reciprocal rank fusion.
- `scripts/run_evaluate_hybrid_retrieval.py`: compares retrieval strategies.
- `tests/test_bm25_retrieval.py`: BM25 tests.
- `tests/test_hybrid_retrieval.py`: hybrid retrieval tests.

The existing Level 2 vector retrieval implementation is reused without modifying Level 2.

## 5. Evaluation Results

Dataset: `employee_handbook_challenging_evaluation.json`

- Questions: 20
- Corpus chunks: 28
- Evaluation cutoff: Top 3
- Relevance: expected chunk defined by each evaluation case

| Strategy | Hit Rate@3 | MRR@3 | Relevant chunks retrieved |
|---|---:|---:|---:|
| Vector-only | 80% | 0.7500 | 16/20 |
| BM25-only | 65% | 0.5417 | 13/20 |
| Hybrid RRF | 85% | 0.6500 | 17/20 |

On the original 8-question dataset:

| Strategy | Hit Rate@3 | MRR@3 |
|---|---:|---:|
| Vector-only | 100% | 1.0000 |
| BM25-only | 87.5% | 0.8125 |
| Hybrid RRF | 100% | 1.0000 |

## 6. Interpreting the Results

Hybrid retrieval improved Hit Rate@3 from 80% to 85% on the challenging dataset.

However, its MRR@3 was lower than vector-only retrieval. This means hybrid retrieval recovered an additional expected chunk, but did not consistently place relevant chunks near the top.

### Example: Unused vacation days

The vector retriever missed the expected chunk, while BM25 ranked it first. RRF recovered the chunk but placed it third because another chunk received contributions from both ranked lists.

### Example: Service ownership

BM25 retrieved the expected chunk at rank 2, but RRF placed it outside the final top 3. The chunk was a candidate, but its fused rank was not high enough.

These cases demonstrate the difference between candidate retrieval and final ranking.

## 7. Limitations and Future Experiments

- RRF considers rank positions, not the original retrieval score magnitudes.
- A chunk appearing in both lists can outrank a highly relevant chunk appearing in only one.
- The small evaluation datasets limit how confidently the results generalize.
- Hit Rate@K and MRR@K measure retrieval, not answer correctness or factual grounding.

Potential future experiments:
1. Increase candidate depth before fusion.
2. Compare weighted RRF against standard RRF.
3. Add a reranker after fusion.
4. Evaluate on a larger, independently curated dataset.
5. Measure answer quality and citation correctness in addition to retrieval metrics.

Do not assume any experiment improves quality until it is evaluated on the same fixed dataset.

## 8. Reproduce the Evaluation

Original dataset:

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run python \
  levels/level-3-advanced-rag/scripts/run_evaluate_hybrid_retrieval.py \
  --dataset original
```

Challenging dataset:

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run python \
  levels/level-3-advanced-rag/scripts/run_evaluate_hybrid_retrieval.py \
  --dataset challenging
```

Run Level 3 tests:

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run pytest \
  levels/level-3-advanced-rag/tests -q
```
