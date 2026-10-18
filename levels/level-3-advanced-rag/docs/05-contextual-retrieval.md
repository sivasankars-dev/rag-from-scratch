# Contextual Retrieval

## 1. Problem

A document chunk may not contain enough information to explain its meaning when retrieved independently.

For example, a chunk might say:

> Employees are entitled to 20 days per year.

Without additional context, a retrieval system may not know which policy, employee group, or type of leave this refers to.

Contextual Retrieval adds a short description of the chunk's context before creating its embedding.

## 2. How It Works

For each child chunk:

1. Extract the original document page.
2. Generate a short contextual description using an LLM.
3. Combine the context and original chunk text.
4. Generate an embedding from the combined text.
5. Store the embedding and combined retrieval text in Chroma; preserve the original child text separately in the JSON manifest.
6. Preserve the parent-child relationship so the parent text can be retrieved later.

The retrieval text has this structure:

```text
This section describes the relevant employee handbook policy.

Employees are entitled to 20 days per year.
```

The example above is illustrative; the actual context is generated from the source document.

## 3. Implementation

- `services/contextual_query_context.py` — generates and validates contextual descriptions.
- `services/contextual_ingestion.py` — builds contextual records, generates embeddings, writes the manifest, and stores parent and child records.
- `scripts/run_contextual_ingestion.py` — extracts PDF text, creates parent-child chunks, generates context, embeds records, and persists the data.
- `tests/test_contextual_query_context.py` — tests contextual description generation and validation.
- `tests/test_contextual_ingestion.py` — tests contextual record preparation and storage-related logic.
- `tests/test_contextual_store_setup.py` — tests storage setup and configuration.

## 4. Storage Design

The contextual pipeline uses dedicated storage paths under:

`levels/level-3-advanced-rag/data/contextual_retrieval/` by default. The completed full ingestion used `levels/level-3-advanced-rag/data/contextual_retrieval_full/`, which is the evaluation runner’s fixed input directory.

It maintains three kinds of data:

- `parents.json` — parent chunks used to provide broader context.
- `contextual_chunks.json` — a manifest containing each child's original text, generated context, combined retrieval text, source metadata, and parent text.
- `chroma/` — vector storage for child chunks.

The embedding is generated from the combined contextual retrieval text. Chroma stores `retrieval_text` (generated context, a blank line, then original child text) as its document. The manifest preserves `original_text` separately, along with `context` and `retrieval_text`. The embedding is a numeric vector derived from `retrieval_text`, not another text field. Parent retrieval returns the original parent text from `parents.json`.

The dedicated contextual store avoids mixing contextual embeddings with the baseline parent-child dataset.

## 5. Context Scope

This proof of concept generates context from the page containing each child chunk, rather than passing the entire PDF to the LLM.

Page-level context keeps prompts smaller and fits the configured input limits. However, a page may not contain all the information needed to interpret a chunk. Future evaluation can compare page-level context with section-level or document-level context.

## 6. Running Ingestion

Run commands from the repository root with the project dependencies installed (`uv sync`). First, inspect the planned chunk counts without generating contexts or writing data:

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run python \
  levels/level-3-advanced-rag/scripts/run_contextual_ingestion.py \
  --dry-run
```

For a small test ingestion, use a separate, initially empty output directory:

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run python \
  levels/level-3-advanced-rag/scripts/run_contextual_ingestion.py \
  --limit 3 \
  --data-path levels/level-3-advanced-rag/data/contextual_retrieval_test
```

The ingestion script refuses to overwrite existing data. Do not rerun against a directory containing existing output files.

The full ingestion has completed in `contextual_retrieval_full/`. The following command documents that destination; **do not rerun it against the existing data**:

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run python \
  levels/level-3-advanced-rag/scripts/run_contextual_ingestion.py \
  --data-path levels/level-3-advanced-rag/data/contextual_retrieval_full
```

Full ingestion makes LLM calls for the child chunks and generates local embeddings. It requires a configured `OPENAI_API_KEY` and may incur API charges.

## 7. Current Validation

The initial integration smoke test processed three child chunks. It verified that:

- Contextual records were generated.
- Embeddings were created.
- Child records were stored in Chroma.
- Child records could be inspected alongside the manifest. The current storage contract is that Chroma documents match `retrieval_text`; original text is preserved in the manifest.
- Parent records could be retrieved.
- Retrieved child IDs could be matched to manifest records.

Full ingestion is now complete: the full-run manifest contains 95 contextual child records and `parents.json` contains 24 parents. These file counts do not independently prove that all persisted vectors are correct. The evaluation runner checks that the existing collection is nonempty and its parent references and sources are consistent.

The Level 3 unit and integration test suite also passed during implementation.

These checks validate data flow and storage integration. They do **not** prove that contextual retrieval improves ranking or answer quality.

## 8. Evaluating Existing Contextual Data

Run the dedicated evaluation from the repository root:

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run python \
  levels/level-3-advanced-rag/scripts/run_evaluate_contextual_retrieval.py
```

Add `--show-context` to print returned parent previews for failed proxy matches.

The runner reads `data/employee_handbook_challenging_evaluation.json` under Level 3 and requires exactly 20 valid cases. It opens `data/contextual_retrieval_full/parents.json` and `data/contextual_retrieval_full/chroma/`, using the existing `contextual_employee_handbook` collection. Missing, empty, or inconsistent stores cause an error; evaluation does not create a collection or run ingestion. It reuses the Level 2 `EmbeddingService` (`all-MiniLM-L6-v2`) for question embeddings. No LLM answers or OpenAI calls are made; a first local model load may require a download.

**Hit Rate@3 and MRR@3 are substring/source relevance proxies, not semantic answer-quality metrics.** The shared evaluator normalizes case and whitespace, then checks whether `expected_answer` occurs in an original parent’s text and its source equals `expected_source`. Paraphrases can cause false negatives; partial or context-insensitive matches can cause false positives. Level 2 `expected_chunk` IDs are not compared to parent IDs.

`top_k=3` searches up to three contextual children. `ParentChildRetrievalService` deduplicates their parents, so fewer than three parents may be returned. Metrics rank that returned parent list, not child ranks or contextual descriptions. Hit Rate is the fraction of questions with a match; MRR averages the reciprocal of the first matching parent rank, using zero for misses. The report includes each question, expected answer, hit, first matching rank, and average retrieval latency measured with `time.perf_counter()` (question embedding, search, and parent lookup; excludes startup).

No real evaluation was run when adding this runner, and no contextual quality scores are recorded here. For a baseline comparison, use the same questions, embedding model, chunking configuration, parent content, and child cutoff. Compare proxy failures manually before drawing conclusions about quality. Offline setup tests live in `tests/test_contextual_evaluator.py`.

### Comparing Baseline and Contextual Retrieval

From the repository root, with both ingestions already present:

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run python \
  levels/level-3-advanced-rag/scripts/compare_contextual_retrieval.py
```

The tool validates both existing stores and uses the same 20 questions, embedding service, shared evaluator, and child `top_k=3`. It neither runs ingestion nor adds or replaces stored records. Baseline data comes from `data/parent_child/` (collection `parent_child_employee_handbook`); contextual data comes from `data/contextual_retrieval_full/` (collection `contextual_employee_handbook`), both under Level 3. Missing stores or collections cause an error.

Rows are matched by the exact question string; duplicates, missing questions, or mismatches cause an error. Only the displayed question is shortened. `improved` means baseline miss to contextual hit; `regressed` means hit to miss; `rank_changed` means both hit at different parent ranks (in either direction); `unchanged` means both miss or both hit at the same rank.

Aggregate differences are contextual minus baseline: Hit Rate in percentage points, MRR as an absolute difference, and average retrieval latency in milliseconds. Hit Rate and MRR remain **substring/source relevance proxies**, not semantic relevance or answer-quality measurements. The tool does not verify that the two ingestions used identical chunking or parent content; confirm those conditions before attributing differences to context enrichment. A single run is not a controlled latency benchmark: baseline runs first, and model/cache warm-up and system load can affect timing. No real comparison was run when implementing this tool.

## 9. Limitations and Next Steps

- Retrieval quality has not yet been evaluated against baseline parent-child retrieval.
- Generated contexts can be inaccurate or omit important information.
- Page-level context may miss information elsewhere in the document.
- The manifest and vector/parent stores are written separately; a failure during persistence can leave partially written data.
- The current smoke test is too small to support conclusions about retrieval quality.

Next, run the contextual evaluation on the completed stores, inspect failed proxy matches, and compare against baseline parent-child retrieval using the same questions and metrics. A human-reviewed relevance set is needed for stronger quality claims.
