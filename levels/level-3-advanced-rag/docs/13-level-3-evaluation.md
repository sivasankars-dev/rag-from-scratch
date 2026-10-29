# Level 3 — Evaluation

## 1. Scope

This chapter records the first shared retrieval comparison for Level 3:

- Vector-only retrieval
- BM25-only retrieval
- Hybrid retrieval using Reciprocal Rank Fusion (RRF)
- Hybrid retrieval followed by cross-encoder reranking

This checkpoint evaluates retrieval evidence, not generated answers.
It does not complete evaluation of every Level 3 technique.

For retrieval metric fundamentals, see
[Level 1 retrieval evaluation](../../level-1-fundamentals/docs/15-retrieval-evaluation.md).

For implementation details, see:

- [Hybrid retrieval](06-hybrid-retrieval.md)
- [Advanced rerankers](07-advanced-rerankers.md)

## 2. Corpus and Configuration

| Setting | Value |
|---|---|
| Source | rag_practice_employee_handbook.pdf |
| Corpus size | 28 chunks |
| Questions | 20 |
| Final retrieval cutoff | Top 3 |
| Reranking candidate count | 10 |
| Warm-up queries | 3 per strategy |
| Embedding model | all-MiniLM-L6-v2 |
| Cross-encoder | cross-encoder/ms-marco-MiniLM-L-6-v2 |
| Chroma collection | employee_handbook_evaluation |
| Chroma directory | levels/level-2-practical-rag/data/chroma_employee_handbook |

The comparison uses the same stored corpus for vector and BM25 retrieval.

The reranked strategy retrieves 10 hybrid candidates and returns the
highest-ranked 3 after cross-encoder scoring. Its results therefore reflect
both the larger candidate pool and reranking; they do not isolate the
cross-encoder's effect alone.

No OpenAI API calls are required for this comparison. Local models may
require downloads on first use.

## 3. Why the Original Labels Needed Review

The original challenging dataset assigns one expected chunk to each question.

However, this handbook repeats some policies in its FAQ and contains
overlapping chunks. A different chunk may contain sufficient evidence
even when the single expected chunk is absent.

Two examples exposed this limitation:

### Q6: Lost company computer

Original expected chunk: 25.

In the diagnostic run:

- Hybrid candidate rank of chunk 25: 1.
- Reranked position of chunk 25: 5.
- Reranked position of chunk 13: 2.

Chunk 13 states that lost devices must be reported immediately through
the security incident channel.

The single-label evaluator reported a miss even though useful reporting
evidence remained in the final top 3.

### Q18: Production service ownership

Original expected chunk: 1.

In the diagnostic run using the original question:

- Hybrid candidate rank of chunk 1: 2.
- Reranked position of chunk 1: 4.
- Reranked position of chunk 26: 1.

Chunk 26 explicitly states that each production service should have a
technical owner and backup owner.

The original question was also ambiguous about whether it asked for
ownership roles or the person responsible for assigning them.

The reviewed question is:

> What ownership roles should every production service have?

These findings motivated a review of all 28 chunks against all 20 questions.

## 4. Reviewed Dataset

File:

`data/employee_handbook_reviewed_evaluation_v1.json`

Dataset version: `handbook-reviewed-v1`.

Each case retains its original `expected_chunk` for traceability and adds:

- `case_id`: stable question identifier.
- `relevant_chunks`: accepted evidence chunk indexes.

Example:

```json
{
  "case_id": "handbook-q06",
  "question": "What is the reporting procedure if a work-issued computer goes missing?",
  "expected_source": "rag_practice_employee_handbook.pdf",
  "expected_chunk": 25,
  "relevant_chunks": [13, 25]
}
```

### Relevance Rule

An accepted chunk must independently contain sufficient evidence to answer
the question. Topic similarity alone is insufficient.

| Question | Accepted chunk indexes |
|---|---|
| Q1 | 6, 25 |
| Q2 | 3 |
| Q3 | 15 |
| Q4 | 17 |
| Q5 | 19 |
| Q6 | 13, 25 |
| Q7 | 26 |
| Q8 | 16, 27 |
| Q9 | 7, 8 |
| Q10 | 10 |
| Q11 | 16 |
| Q12 | 14, 23 |
| Q13 | 18, 26, 27 |
| Q14 | 7, 25 |
| Q15 | 10, 26 |
| Q16 | 23 |
| Q17 | 26 |
| Q18 | 1, 26 |
| Q19 | 13 |
| Q20 | 20 |

The labels were assistant-reviewed against the supplied corpus.
They have not been independently human-validated.

This dataset was revised after inspecting retrieval failures. Treat it
as a development benchmark, not an untouched held-out test set.

Labels are tied to this 28-chunk corpus. Rechunking or changing the
document requires another label review.

## 5. Evaluation Logic

Implementation:

`services/reviewed_retrieval_evaluator.py`

The helper `find_relevant_chunk_rank`:

1. Validates the final cutoff, expected source, and relevance labels.
2. Inspects only the first `top_k` returned metadata records.
3. Matches both source and accepted chunk index.
4. Returns the first relevant rank, or `None`.

Example:

```text
Accepted chunks: [13, 25]
Returned chunks: [11, 13, 22]
First relevant rank: 2
Hit: True
Reciprocal rank: 1 / 2
```

The runner uses this helper when a case contains `relevant_chunks`.
Original datasets continue using their single expected chunk.

The runner also validates that every required labeled chunk exists
in the loaded corpus before evaluation.

### Hit Rate@3

The fraction of questions with at least one accepted chunk in the top 3.

### MRR@3

The mean reciprocal rank of the first accepted chunk.

A question with no accepted chunk in the top 3 contributes zero.

### Latency

The runner reports average and nearest-rank P95 retrieval latency.

Warm-up calls are excluded. Timings cover each strategy's retrieval
function, including query embedding or reranking where applicable.
They exclude initial model loading and answer generation.

Each reported run contains only 20 timed questions per strategy.
Latency is an observation from a local run, not a production benchmark.

## 6. Original Single-Label Baseline

Configuration: challenging dataset, top-k 3, candidate-k 10,
three warm-up queries per strategy.

| Strategy | Hit Rate@3 | MRR@3 | Average latency | P95 latency |
|---|---:|---:|---:|---:|
| Vector-only | 80.00% | 0.7500 | 16.95 ms | 44.34 ms |
| BM25-only | 65.00% | 0.5417 | 0.07 ms | 0.08 ms |
| Hybrid RRF | 85.00% | 0.6500 | 10.56 ms | 10.89 ms |
| Hybrid + Cross-Encoder | 90.00% | 0.8500 | 60.82 ms | 91.44 ms |

These results use the original question wording and single-chunk labels.

## 7. Reviewed Dataset Results

Configuration: reviewed dataset, top-k 3, candidate-k 10,
three warm-up queries per strategy.

| Strategy | Hits | Hit Rate@3 | MRR@3 | Average latency | P95 latency |
|---|---:|---:|---:|---:|---:|
| Vector-only | 19/20 | 95.00% | 0.8167 | 19.92 ms | 44.96 ms |
| BM25-only | 17/20 | 85.00% | 0.7000 | 0.07 ms | 0.09 ms |
| Hybrid RRF | 19/20 | 95.00% | 0.8500 | 10.20 ms | 10.78 ms |
| Hybrid + Cross-Encoder | 20/20 | 100.00% | 0.9750 | 61.84 ms | 98.39 ms |

### Findings

- Hybrid + Cross-Encoder returned accepted evidence for all 20 questions.
- Its first accepted result ranked first for 19 questions and second for Q6.
- Its MRR is therefore `(19 + 0.5) / 20 = 0.975`.
- Q14 was missed by Hybrid at top 3 and recovered by the reranked strategy.
- Q6 moved from Hybrid rank 1 to reranked rank 2.
- Reranking does not improve every individual ranking.
- The reranked strategy took approximately six times Hybrid's average
  retrieval latency in this run.

The change from the original 90% result to the reviewed 100% result
does not demonstrate model improvement. The relevance labels and Q18
wording changed.

The result also does not establish perfect answer generation or general
retrieval accuracy beyond this development dataset.

## 8. Run Evaluation

Run from the repository root after ingesting the Level 2 handbook.

### Original challenging dataset

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run python \
  levels/level-3-advanced-rag/scripts/run_evaluate_hybrid_retrieval.py \
  --dataset challenging \
  --top-k 3 \
  --candidate-k 10 \
  --warmup-queries 3
```

### Reviewed dataset

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run python \
  levels/level-3-advanced-rag/scripts/run_evaluate_hybrid_retrieval.py \
  --dataset reviewed \
  --top-k 3 \
  --candidate-k 10 \
  --warmup-queries 3
```

### Original-label failure diagnostics

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run python \
  levels/level-3-advanced-rag/scripts/run_evaluate_hybrid_retrieval.py \
  --dataset challenging \
  --top-k 3 \
  --candidate-k 10 \
  --warmup-queries 3 \
  --diagnose
```

Diagnostics inspect Q6 and Q18, including full reranking candidate lists.
The diagnostic flag is currently blocked for the reviewed dataset because
its diagnostic output still uses original single-chunk labels.

Changing the hybrid retrieval cutoff can also change the input rankings
used by RRF. The top-3 hybrid output need not be a simple prefix of a
separate top-10 hybrid call.

## 9. Tests and Validation

Helper tests:

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run pytest \
  levels/level-3-advanced-rag/tests/test_reviewed_retrieval_evaluator.py -q
```

Observed: **19 passed**.

Coverage includes alternative evidence, first relevant rank, source
matching, cutoff enforcement, empty results, chunk index zero, and
invalid inputs.

Full Level 3 suite:

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run pytest \
  levels/level-3-advanced-rag/tests/ -q
```

Observed: **309 passed, 7 warnings**.

The warnings concern PyMuPDF/Swig deprecations.

The 19 new tests validate the ranking helper. They do not by themselves
establish test coverage for the runner's new dataset-loading,
validation, or command-line branches. A real reviewed evaluation run
also completed successfully.

## 10. Remaining Level 3 Evaluation

This checkpoint covers four retrieval configurations only.

Remaining work includes:

- Evaluate other Level 3 approaches using evidence labels appropriate
  to their output formats.
- Use source/page/section evidence to compare strategies with different
  chunk boundaries.
- Add separate graph, table, and diagram evaluation cases.
- Evaluate generated answer correctness, grounding, citation support,
  and abstention on unanswerable questions.
- Record generation latency, token usage, and API cost.
- Add independently reviewed, unseen questions.
- Strengthen runner integration tests and persist machine-readable reports.

Do not directly compare parent-child text-proxy metrics with these
reviewed chunk-label metrics. Their relevance definitions differ.

## 11. Saved Evaluation Reports

The runner supports `--output` to save configuration, strategy metrics,
per-question ranks, retrieved metadata, and measured latency as JSON.

Recorded report:

`../data/evaluation_reports/handbook-reviewed-v1-run-01.json`

| Strategy | Hit Rate@3 | MRR@3 | Average latency | P95 latency |
|---|---:|---:|---:|---:|
| Vector-only | 95.00% | 0.8167 | 18.98 ms | 44.25 ms |
| BM25-only | 85.00% | 0.7000 | 0.07 ms | 0.08 ms |
| Hybrid RRF | 95.00% | 0.8500 | 10.45 ms | 10.89 ms |
| Hybrid + Cross-Encoder | 100.00% | 0.9750 | 62.54 ms | 97.25 ms |

These measurements come from a subsequent run. Quality scores matched
the earlier reviewed run; latency varied.

Example:

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run python \
  levels/level-3-advanced-rag/scripts/run_evaluate_hybrid_retrieval.py \
  --dataset reviewed \
  --top-k 3 \
  --candidate-k 10 \
  --warmup-queries 3 \
  --output levels/level-3-advanced-rag/data/evaluation_reports/handbook-reviewed-v1-run-02.json
```

Existing output files are not overwritten. Use a new filename per run.
The report does not yet capture model revisions, corpus fingerprints,
or machine details needed for stronger reproducibility.