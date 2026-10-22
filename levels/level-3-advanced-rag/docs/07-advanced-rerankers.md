# Advanced Rerankers — Cross-Encoder

## 1. Objective

Improve the relevance ordering of retrieved documents by adding a Cross-Encoder reranking stage to the existing hybrid retrieval pipeline.

The current Level 3 hybrid retriever combines dense vector retrieval and BM25 retrieval using Reciprocal Rank Fusion (RRF). The Cross-Encoder reranks the hybrid candidate pool before returning the final Top-K results.

## 2. Retrieval pipeline

1. **Candidate retrieval:** Hybrid retrieval combines vector and BM25 results using RRF.
2. **Candidate pool:** Retrieve up to 10 candidates (`candidate_k=10`).
3. **Reranking:** Score each query-document pair with `cross-encoder/ms-marco-MiniLM-L-6-v2`.
4. **Final results:** Sort candidates by Cross-Encoder score and return the Top 3 (`top_k=3`).

The Cross-Encoder processes the query and each document together. Unlike a bi-encoder retrieval stage, it can model interactions between words in the query and document. Its scores are ranking signals, not calibrated probabilities.

## 3. Implementation

- Service: `services/cross_encoder_reranker.py`
- Tests: `tests/test_cross_encoder_reranker.py`
- Evaluation: `scripts/run_evaluate_hybrid_retrieval.py`
- Model: `cross-encoder/ms-marco-MiniLM-L-6-v2`
- Candidate pool: 10
- Final Top-K: 3

The reranker preserves the candidate fields and adds a `reranker_score`. It sorts candidates by descending score and returns at most `top_n` results.

## 4. Evaluation setup

| Setting | Value |
|---|---|
| Dataset | Challenging employee handbook questions |
| Questions | 20 |
| Corpus chunks | 28 |
| Final K | 3 |
| Hybrid candidate K | 10 |
| Warm-up queries per strategy | 3 |
| Quality metrics | Hit Rate@3, MRR@3 |
| Latency metrics | Average latency, P95 latency |

Warm-up calls are excluded from the reported measurements. The 20 evaluation questions are then measured for each strategy.

- **Hit Rate@3:** Fraction of questions where the expected chunk appears in the top 3 results.
- **MRR@3:** Mean reciprocal rank of the expected chunk; a higher score rewards placing it nearer the top.
- **Average latency:** Mean measured retrieval time per question.
- **P95 latency:** Nearest-rank 95th percentile of measured query latencies.

## 5. Results

Observed results from one run:

| Strategy | Hit Rate@3 | MRR@3 | Average latency | P95 latency |
|---|---:|---:|---:|---:|
| Vector-only | 80% | 0.7500 | 17.55 ms | 45.11 ms |
| BM25-only | 65% | 0.5417 | 0.07 ms | 0.08 ms |
| Hybrid (RRF) | 85% | 0.6500 | 10.50 ms | 10.82 ms |
| Hybrid + Cross-Encoder | **90%** | **0.8500** | 61.29 ms | 96.44 ms |

### Interpretation

- Hybrid + Cross-Encoder achieved the best observed Hit Rate@3 and MRR@3 in this run.
- Compared with Hybrid (RRF), Hit Rate@3 increased from 85% to 90%.
- MRR@3 increased from 0.6500 to 0.8500, indicating better placement of expected chunks in the ranked results.
- Cross-Encoder reranking increased latency. The measured average was approximately 61 ms, with a P95 of approximately 96 ms.
- These latency figures are local benchmark observations, not production latency guarantees.

## 6. Candidate pool experiment

The challenging dataset was also evaluated with different hybrid candidate pool sizes.

| Candidate K | Hit Rate@3 | MRR@3 | Average latency |
|---:|---:|---:|---:|
| 5 | 85% | 0.8000 | 85.56 ms |
| 10 | 90% | 0.8500 | 67.42 ms |
| 20 | 90% | 0.8500 | 89.54 ms |

Candidate K=10 was the best observed trade-off in these runs. Increasing the pool to 20 did not improve the measured quality metrics and increased observed latency.

Latency can vary across runs because of model initialization, caching, system load, and other environmental factors. These small-sample measurements should not be treated as a definitive performance comparison.

## 7. Known limitations

1. The challenging evaluation set contains only 20 questions and the corpus contains 28 chunks. Results may not generalize to larger or different corpora.
2. The evaluator checks whether the expected source/chunk appears in the ranked results. It does not establish complete semantic answer correctness.
3. A reranker cannot recover a relevant document that was not included in the candidate pool.
4. Cross-Encoder scoring adds inference cost and latency compared with returning hybrid results directly.
5. The benchmark uses one model and one corpus. Alternative models should be compared using the same dataset and measurement procedure before selecting a production model.
6. P95 latency from 20 questions is a rough estimate. A larger test set and repeated benchmark runs are needed for a more stable latency assessment.

## 8. Tests and validation

The implementation previously passed:

- Cross-Encoder unit tests: 12 passed.
- Full Level 3 test suite: 180 passed.

Re-run the tests and checks after the final documentation and script changes to confirm the current working tree remains valid.

## 9. Conclusion

Cross-Encoder reranking is implemented and integrated with hybrid retrieval. In the current challenging benchmark, it improved observed ranking quality at the cost of additional latency.

For this project, retain `candidate_k=10` as the current experimental default. Treat the results as a baseline for further evaluation, not as proof of production readiness.
