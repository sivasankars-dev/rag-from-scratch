# Parent-Child Retrieval: first evaluation

**This is a text-matching proxy for retrieval relevance, not human-verified semantic relevance or answer-generation evaluation.** No LLM generates or judges answers. No real evaluation results are recorded by this implementation change.

## Prerequisites and command

Complete [Parent-Child ingestion](03-parent-child-ingestion.md) first. From the repository root, when you choose to run the real evaluation:

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run python levels/level-3-advanced-rag/scripts/run_evaluate_parent_child_retrieval.py
```

The script uses the existing [20-question challenging dataset](../data/employee_handbook_challenging_evaluation.json), without changing it. Paths resolve relative to the script, not the working directory. It opens these existing Level 3 stores:

- `data/parent_child/parents.json` under the Level 3 directory, via `ParentChildStore(storage_path=...)`.
- `data/parent_child/chroma/`, via `ChildVectorStore(persist_directory=..., collection_name="parent_child_employee_handbook")`.

The runner checks for the parent JSON and Chroma SQLite file, opens the existing collection before the wrapper can create one, and rejects empty or inconsistent stores. It checks that child parent IDs resolve, sources agree, and expected sources have indexed children. Missing/corrupt datasets, missing stores, or failed checks report an error with ingestion guidance. Stop ingestion while evaluating; these checks do not provide a transaction or prove that every expected chunk was ingested.

The actual `ParentChildRetrievalService` uses Level 2's local `EmbeddingService` (`all-MiniLM-L6-v2` by default) to call `embed_text(question)`. This must match ingestion's embedding model. First use may download the model; no OpenAI call or API key is required. The evaluator does not reset or upsert records, though opening Chroma may perform its normal database bookkeeping.

## Relevance rule

The isolated [evaluation helper](../services/parent_child_evaluator.py) validates nonempty string fields `question`, `expected_answer`, and `expected_source`. The command requires exactly 20 cases. `expected_chunk` is deliberately ignored: Level 2 chunk indices do not identify Level 3 parents.

For each returned parent:

1. Require its `source` to equal `expected_source` exactly.
2. Apply Python `casefold()` to parent text and expected answer, then split/rejoin whitespace to normalize spaces, tabs, and newlines.
3. Check whether the entire normalized expected answer is a substring of the normalized parent text.

For example, `ANNUAL\nleave` and `annual leave` normalize to the same phrase. This rule does not remove punctuation, stem words, expand abbreviations, or recognize paraphrases. A correct supporting paragraph can therefore be marked a miss. Conversely, a short expected phrase can match part of a longer word, a negated statement, or an irrelevant passage and produce a false hit. Evidence split between parents is not combined for matching.

These limitations appear prominently in console output. The metrics describe this exact proxy only. They must not be presented as semantic accuracy or compared directly with Multi-Query's expected-chunk metrics.

## Cutoff, ranks, and metrics

The runner calls `retrieve(question, top_k=3)`. This searches at most three **children**, then returns their unique existing parents. It does not request three distinct parents. The evaluator ranks that deduplicated parent list and applies its own first-three-parent cutoff as well.

If children rank as `parent A, parent A, parent B`, the returned parents rank as `A, B`. A first matching B contributes reciprocal rank `1/2`, not `1/3`. Missing parents are skipped by retrieval, so ranks describe the resulting list. Empty results are a miss.

- **Hit Rate@3 (proxy):** number of questions with a matching parent in the evaluated list divided by all 20 questions.
- **MRR@3 (proxy):** average of `1 / first_matching_parent_rank`; a miss contributes zero. Only the first match counts.
- **Average retrieval latency:** arithmetic mean of elapsed retrieval calls in milliseconds, measured with `time.perf_counter()`. Includes question embedding, child search, and parent lookup. Excludes dataset/store loading, embedding-model initialization, proxy scoring, and formatting. There is no explicit warm-up; the first retrieval may still incur cold-start costs.

The report prints every question, expected answer, first proxy-relevant parent rank (`None` on a miss), hit flag, number of returned parents, and retrieval latency, followed by aggregate metrics. Retrieval exceptions stop the run instead of silently becoming misses. Latency varies with hardware, caching, model configuration, and background work; it is supplementary, not a quality score.

## Tests and next steps

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run pytest levels/level-3-advanced-rag/tests/test_parent_child_evaluator.py -q
```

Tests use fake retrieval, embeddings, parent records, and collection clients. Temporary files are dataset/path fixtures, not real PDF or Chroma stores. They cover normalized matches, misses, wrong-source matches, cutoff, reciprocal ranks, aggregate metrics, deterministic timing, report formatting, dataset validation, and missing/inconsistent storage. One test uses the real retrieval coordinator with fake dependencies to verify parent-rank semantics after deduplication. They do not download models or access the network.

Before interpreting a real run, inspect matched and missed parents manually. Future work could add reviewed relevance labels, context-size measurements, and controlled comparisons with child-only retrieval. These are not implemented here. A proxy miss alone does not establish a retrieval failure, and a proxy hit alone does not establish sufficient evidence for a correct answer.

## Diagnose failed proxy matches

To inspect returned context when you choose to run the real evaluation:

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run python levels/level-3-advanced-rag/scripts/run_evaluate_parent_child_retrieval.py --show-context
```

For each failed substring/source proxy match, the report shows the question and expected answer followed by each returned parent's rank, source, page number, parent ID, and text preview. No returned parents produces an explicit empty-result message. Missing diagnostic metadata is shown as `Unknown`.

Previews preserve case, collapse whitespace, and are limited to 500 characters including a trailing `...` when truncated. A preview may omit relevant evidence later in the parent; inspect the full stored record by its ID before drawing conclusions. Printed source text may contain sensitive document content, so review output before sharing it.

A failed proxy match is **not a confirmed semantic retrieval failure**: a parent may contain a correct paraphrase without the expected substring. Diagnostic mode does not change scoring, ranks, retrieval calls, or storage. It reuses the parents returned by the original call, and prepares previews after the timed retrieval interval. Default output remains unchanged without the flag; latency can still vary between runs for ordinary environmental reasons.
