# Level 3 — Advanced RAG

## Purpose

Level 3 builds on the practical RAG system developed in Level 2. The goal is to understand how to improve retrieval quality, handle difficult questions, and build more capable RAG workflows.

This level is a collection of independent learning topics. Each topic should include:

- A simple explanation of the problem
- An implementation with clearly separated responsibilities
- Unit and integration tests
- An evaluation where applicable
- A beginner-friendly document explaining the design and code

## Learning Roadmap

| Topic | Problem it addresses | Status |
|---|---|---|
| Multi-Query Retrieval | A user's wording may not match the wording in a document | Implemented; evaluation ongoing |
| Hybrid Search | Semantic search may miss exact keywords and identifiers | Planned |
| Reranking | Initial retrieval may return relevant chunks in a poor order | Planned |
| Query Decomposition | A complex question may require multiple simpler searches | Planned |
| Parent-Child Retrieval | Small chunks can lack the context needed to answer a question | Implemented; text-proxy evaluator available; real run pending |
| Contextual Retrieval | A chunk may lose important meaning when separated from its document | Implemented; ingestion and proxy evaluation complete |
| Hierarchical Retrieval | Large documents may need retrieval at multiple levels of detail | Planned |
| Query Routing | Different questions may require different retrieval strategies | Planned |
| Agentic and Tool-Based RAG | Some questions need a sequence of decisions or tool calls | Planned |
| Advanced Context Management | The system must select and organize context within a limited model context window | Planned |
| Advanced Evaluation | Retrieval and answer quality need systematic measurement | Retrieval comparison implemented; broader evaluation planned |

These topics may be implemented in stages. The roadmap describes learning goals, not a claim that every technique is already production-ready.

## How Level 3 Builds on Level 2

Level 2 established the core RAG pipeline:

1. Load and split documents into chunks.
2. Generate embeddings for the chunks.
3. Store the embeddings and metadata in Chroma.
4. Embed a user's question.
5. Retrieve relevant chunks.
6. Use the retrieved context to generate a grounded answer.
7. Evaluate retrieval and answer quality.

Level 3 reuses these fundamentals and explores ways to improve individual parts of the pipeline. It does not replace the basic RAG architecture; it extends it.

## Topics Implemented So Far

### Multi-Query Retrieval

Multi-Query Retrieval generates alternative search queries from the original question. It retrieves chunks for each query and combines the rankings using Reciprocal Rank Fusion (RRF).

The implementation includes:

- `services/multi_query_generator.py` — generates alternative queries through an LLM client.
- `services/retrieval_adapter.py` — converts the Level 2 retrieval response into a consistent chunk format.
- `services/rrf.py` — combines ranked results using Reciprocal Rank Fusion.
- `services/multi_query_retrieval.py` — coordinates query generation, retrieval, deduplication, ranking, and result limiting.
- `scripts/run_evaluate_multi_query_retrieval.py` — compares baseline retrieval with multi-query retrieval.
- `tests/` — tests individual components and their integration.
- `docs/01-multi-query-retrieval.md` — explains the implementation step by step, starting from the Level 2 pipeline.

### Parent-Child Retrieval

Small retrieved chunks can omit the surrounding context needed to answer a question. Parent-Child Retrieval searches smaller child chunks, then fetches their larger parent chunks as context. Multiple matching children from one parent produce only one returned parent.

The implementation includes:

- `services/parent_child_chunker.py` — splits text into non-overlapping parents and overlapping children, with IDs linking each child to its parent.
- `services/parent_child_store.py` — saves and retrieves parent records in a local JSON file.
- `services/child_vector_store.py` — persists caller-supplied child embeddings and metadata in Chroma and searches them.
- `services/parent_child_retrieval.py` — embeds the question, searches children, and returns unique existing parents.
- `tests/test_parent_child_chunker.py`, `tests/test_parent_child_store.py`, `tests/test_child_vector_store.py`, and `tests/test_parent_child_retrieval.py` — test individual components.
- `tests/test_parent_child_integration.py` — connects the pipeline using temporary JSON/Chroma storage and fake embeddings.

See [Parent-Child Retrieval](docs/02-parent-child-retrieval.md) for the design, runnable examples, and limitations. Implementation and tests are available; a first-pass text-proxy evaluator is available, with a real evaluation run pending. The integration test checks data flow, not semantic search quality.

### Ingest the handbook for Parent-Child Retrieval

From the repository root:

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run python levels/level-3-advanced-rag/scripts/run_parent_child_ingestion.py
```

Initial experimental sizes are **100 words per parent, 30 words per child, and 10 words of child overlap**. The script reuses Level 2's PDF loader and local embedding model, then replaces this handbook's records only in dedicated Level 3 stores. The first embedding-model use may require a download; no OpenAI call is made.

Stop readers and other ingestion processes before running. See [Parent-Child ingestion](docs/03-parent-child-ingestion.md) for storage paths, source-scoped reset behavior, counts, and failure recovery. This prepares data; it does not evaluate retrieval quality.

## Project Structure

- `services/` — reusable implementation components.
- `tests/` — unit and integration tests.
- `scripts/` — runnable evaluation and experiment scripts.
- `data/` — evaluation datasets used by this level.
- `docs/` — learning notes, design decisions, examples, and evaluation findings.

## Run the Tests

Run from the repository root:

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run pytest levels/level-3-advanced-rag/tests -q
```

## Evaluation

Multi-query retrieval is compared with baseline retrieval using metrics such as Hit Rate@K and Mean Reciprocal Rank (MRR@K).

An experiment must report its dataset, retrieval cutoff, and observed results. A more complex technique should not be assumed to be better merely because it uses more queries or more components.

Run the challenging-dataset evaluation from the repository root after completing the prerequisites in the guide (this makes paid OpenAI calls):

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run python levels/level-3-advanced-rag/scripts/run_evaluate_multi_query_retrieval.py --dataset challenging
```

See [Multi-Query Retrieval](docs/01-multi-query-retrieval.md) for the detailed explanation and recorded evaluation findings.

Parent-Child Retrieval now has a first-pass evaluator using normalized `expected_answer` substring matching against returned parent text. **This is only a relevance proxy, not human-verified semantic relevance or answer-generation evaluation.** A real run and recorded results remain pending.

After ingestion, run:

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run python levels/level-3-advanced-rag/scripts/run_evaluate_parent_child_retrieval.py
```

It reports Hit Rate@3, MRR@3, per-question outcomes, and average retrieval latency on the existing 20-question challenging dataset. `top_k=3` searches three children; metrics rank the deduplicated parent results. See [Parent-Child evaluation](docs/04-parent-child-evaluation.md) for prerequisites, the matching rule, and limitations. These proxy metrics are not directly comparable with Multi-Query's chunk-ID metrics.
