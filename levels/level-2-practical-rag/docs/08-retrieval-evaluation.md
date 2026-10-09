# Retrieval Evaluation

## 1. Goal

Retrieval evaluation measures whether a RAG system retrieves relevant document chunks for a given question.

In this implementation, we evaluate retrieval against a small employee handbook dataset using Hit Rate@K and Mean Reciprocal Rank (MRR@K).

## 2. Evaluation Dataset

File: `data/employee_handbook_evaluation.json`

Each evaluation case contains:

- `question`: The question sent to the retrieval system.
- `expected_answer`: The reference answer used for evaluation context.
- `expected_source`: The source document expected to contain the information.
- `expected_chunk`: The expected relevant chunk index.

The eight labels were checked directly against the 12-page PDF processed with `chunk_limit=100` and `overlap=20` (word counts, independently per page), producing 28 chunks. Labels were not changed based on retrieval results.

| Question topic | Expected chunk | PDF page |
| --- | ---: | ---: |
| Company name | 1 | 2 |
| Collaboration hours | 3 | 3 |
| Annual leave | 6 | 4 |
| Passwords | 12 | 6 |
| Pull requests | 15 | 7 |
| SEV-1 response | 17 | 8 |
| Support escalation | 19 | 9 |
| Lost laptop | 25 | 12 |

`expected_answer` is a human reference; the evaluator does not score answer text. Each case accepts exactly one `(expected_source, expected_chunk)` pair. Company name also appears in chunk 0, annual leave in chunk 25, and lost-device reporting in chunk 13. These alternatives are not accepted by the current labels. A miss can therefore mean failure to retrieve the designated chunk rather than failure to retrieve any useful evidence.

The expected chunk must be checked against the processed document. If chunking settings or source documents change, verify the expected chunk indices again.

## 3. Hit Rate@K

Hit Rate@K measures the proportion of evaluation questions for which the expected chunk appears in the top K retrieved results.

Formula:

Hit Rate@K = Number of hits / Total questions

A hit requires both the expected source and chunk index within the first K results.

For example, if 8 questions are evaluated and 7 expected chunks are retrieved within the top 3 results:

Hit Rate@3 = 7 / 8 = 87.5%

Hit Rate does not distinguish between an expected chunk ranked first and one ranked third.

## 4. Reciprocal Rank

Reciprocal rank assigns a score based on the rank of the expected chunk.

- Rank 1: 1 / 1 = 1.0
- Rank 2: 1 / 2 = 0.5
- Rank 3: 1 / 3 ≈ 0.333
- Expected chunk not found in the top K: 0.0

Ranks start at 1. Only the first matching result counts. The runner supplies at most K results; the metric helpers do not apply a separate cutoff.

The implementation uses `find_expected_chunk_rank()` to find the expected chunk's rank and `calculate_reciprocal_rank()` to convert that rank into a score.

## 5. Mean Reciprocal Rank (MRR@K)

MRR@K is the average reciprocal rank across all evaluation questions.

Formula:

MRR@K = Sum of reciprocal ranks / Total questions

Example:

Reciprocal ranks: [1.0, 0.5, 0.0]

MRR@3 = (1.0 + 0.5 + 0.0) / 3 = 0.5

A higher MRR means relevant chunks tend to appear closer to the top of the retrieved results.

## 6. Implementation

The evaluation logic is in `services/retrieval_evaluator.py`.

- `find_expected_chunk_rank(retrieved_chunks, expected_chunk, expected_source=None)`: Returns the first 1-based match or `None`. The handbook runner supplies metadata and the expected source to match both fields. Omitting the source preserves the earlier index-list examples for a single document.
- `calculate_reciprocal_rank()`: Returns the reciprocal of a rank, or `0.0` for `None`. Zero, negative, noninteger, and boolean ranks raise `ValueError`.
- `calculate_mrr()`: Calculates the average of reciprocal ranks, returning `0.0` for an empty list.
- `calculate_hit_rate()`: Calculates the proportion of successful retrieval cases, returning `0.0` for empty input. It expects boolean hit results.

`calculate_mrr()` expects reciprocal-rank values, not raw ranks. `evaluate_hit_rate()` checks that the number of result lists equals the number of cases. The injected-service helper `evaluate_retrieval_hit_rate()` supports deterministic testing without model downloads.

The real handbook evaluation script is `scripts/run_handbook_evaluation.py`. It embeds each question, retrieves the top K chunks from Chroma, and prints the Hit Rate@K and MRR@K metrics. It uses `all-MiniLM-L6-v2`, cosine Chroma search, and `top_k=3`. Each question is embedded and retrieved once, with that same ranking used for both metrics. No rewriting, hybrid search, reranking, or LLM answer generation is involved.

The dedicated collection is `employee_handbook_evaluation` under `data/chroma_employee_handbook/`. The runner rejects a collection missing any expected source/chunk label rather than reporting missing ingestion as poor retrieval. This check does not prove that stored text or embeddings are current.

## 7. Running the Evaluation

From the `level-2-practical-rag` directory, run:

```bash
PYTHONPATH=. uv run pytest tests/test_retrieval_evaluator.py -q
```

Run the full Level 2 suite:

```bash
PYTHONPATH=. uv run pytest -q
```

For a new environment, ingest the shared PDF first:

```bash
PYTHONPATH=. uv run python scripts/run_handbook_ingestion.py
```

The PDF is `../../data/documents/rag_practice_employee_handbook.pdf`. Ingestion uses the settings above and checks the stored chunk count. It upserts records; it does not delete obsolete records from earlier chunking settings. Generated Chroma files are excluded from Git. First use of the embedding model may require downloading its weights.

Run the real handbook evaluation:

```bash
PYTHONPATH=. uv run python scripts/run_handbook_evaluation.py
```

The script reports the expected source, expected chunk, retrieved chunk indices, expected chunk rank, hit status, reciprocal rank, Hit Rate@K, and MRR@K.

### Verified results

On this review run, all 28 stored texts and metadata records matched fresh PDF processing. The real evaluation returned each of the eight expected labels at rank 1:

```text
Questions evaluated: 8
Top-K: 3
Hits: 8
Hit Rate@3: 100.00%
MRR@3: 1.0000
```

These are results for this dataset and configuration, not a guarantee for other queries. The earlier 7/8 example is illustrative.

Deterministic tests cover ranks 1–3, missing and empty results, source mismatches, first-match behavior, invalid ranks, aligned case/result counts, and aggregation across questions. The fake services make no external API calls. Verification: 40 evaluator tests passed; the full Level 2 suite passed 119 tests. Real embedding/Chroma evaluation is the separate script above.

## 8. Limitations

- The evaluation dataset currently contains only eight questions. Results may not represent overall retrieval quality.
- Hit Rate and MRR evaluate retrieval, not the correctness of an LLM-generated answer.
- Expected chunk labels must be accurate. A relevant duplicate chunk may cause a false negative if only one chunk index is accepted.
- The handbook runner matches both `source` and `chunk_index`, even though the current collection contains one document. Labels and embeddings still need review if the document, chunking settings, or model changes.
- Scores depend on the document, chunking settings, embedding model, and retrieval configuration.

## 9. Summary

Hit Rate@K measures whether the expected chunk appears within the top K results. MRR@K additionally measures how highly the expected chunk is ranked. Together, these metrics provide a basic quantitative check of retrieval quality.
