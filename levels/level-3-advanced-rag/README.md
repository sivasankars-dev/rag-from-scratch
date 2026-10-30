# Level 3 — Advanced RAG

**Status: The ten planned learning implementations are complete.** Broader evaluation and production hardening remain ongoing work.

## Implemented topics

| Topic | Implemented scope |
| --- | --- |
| Multi-query retrieval | Query rewrites, deduplication, RRF fusion |
| Parent-child retrieval | Child-vector search with parent context lookup |
| Contextual retrieval | Generated chunk context during ingestion |
| BM25 + vector search | BM25 retrieval and hybrid RRF |
| Advanced rerankers | Cross-encoder candidate reranking |
| Hierarchical/document-aware retrieval | Section parser, section-aware parent/child chunks and metadata |
| Agentic RAG | Bounded retrieval/answer attempts |
| Graph RAG | Neo4j entity/evidence ingestion, retrieval, grounded generation |
| Multimodal RAG | PDF text, tables, rows, optional vision descriptions |
| Long-context strategies | Token-budgeted context construction and generation |

These are independent learning components, not one API that combines every strategy. Hierarchical retrieval preserves section metadata but does not automatically expand all ancestor sections. Query decomposition and general query routing from earlier roadmap drafts are outside this completed ten-topic scope.

## Documentation

- [multi query retrieval](docs/01-multi-query-retrieval.md)
- [parent child retrieval](docs/02-parent-child-retrieval.md)
- [parent child ingestion](docs/03-parent-child-ingestion.md)
- [parent child evaluation](docs/04-parent-child-evaluation.md)
- [contextual retrieval](docs/05-contextual-retrieval.md)
- [hybrid retrieval](docs/06-hybrid-retrieval.md)
- [advanced rerankers](docs/07-advanced-rerankers.md)
- [hierarchical document aware retrieval](docs/08-hierarchical-document-aware-retrieval.md)
- [agentic rag](docs/09-agentic-rag.md)
- [graph rag](docs/10-graph-rag.md)
- [multimodal rag](docs/11-multimodal-rag.md)
- [long context rag](docs/12-long-context-rag.md)
- [level 3 evaluation](docs/13-level-3-evaluation.md)

## Tests

Run from the repository root:

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run pytest levels/level-3-advanced-rag/tests -q
```

The evaluation chapter records **309 passed, 7 warnings** at its checkpoint. Later tests may change this count; this README update does not rerun the suite.

## Retrieval evaluation

The [evaluation chapter](docs/13-level-3-evaluation.md) compares vector, BM25, hybrid RRF, and hybrid plus cross-encoder retrieval on a 28-chunk handbook and 20 reviewed questions.

The saved reviewed report records Hybrid + Cross-Encoder Hit Rate@3 of **100%** and MRR@3 of **0.9750**, with 10 candidates and 3 warm-up queries. Labels were assistant-reviewed after inspecting failures and are not independently human-validated. This is a development benchmark; it does not establish general accuracy, answer correctness, or production capacity.

After the Level 2 handbook ingestion prerequisites are satisfied:

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run python \
  levels/level-3-advanced-rag/scripts/run_evaluate_hybrid_retrieval.py \
  --dataset reviewed --top-k 3 --candidate-k 10 --warmup-queries 3
```

This comparison uses local models; first use may download weights. Other workflows can make paid OpenAI calls, and graph workflows require Neo4j. Follow each topic's prerequisites and data paths. Parent-child text-proxy scores use a different relevance definition and are not directly comparable with reviewed chunk-label scores.

## Remaining evaluation and operational work

- Evaluate the other approaches with suitable source/page/section evidence labels.
- Add graph, table, diagram, unanswerable, and independently reviewed unseen cases.
- Measure generated answer correctness, grounding, citation support, abstention, tokens, and cost.
- Strengthen reproducibility with model revisions, corpus fingerprints, and machine details.
- Address non-atomic JSON/Chroma updates, security, observability, recovery, and scaling in Level 4.

Continue to [Level 4 — Production RAG Engineering](../level-4-production-rag/README.md).
