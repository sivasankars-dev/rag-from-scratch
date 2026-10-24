# Agentic RAG with LangGraph

## 1. Objective

Traditional RAG follows a mostly fixed workflow: retrieve documents, provide the retrieved context to an LLM, and generate an answer.

Agentic RAG adds a bounded decision step. The workflow can check whether retrieved evidence appears relevant, refine the retrieval query when necessary, and retry within a configured limit. If it still cannot find adequate evidence, it returns an insufficient-evidence response instead of intentionally generating an unsupported answer.

This Level 3 implementation is a small, controlled Agentic RAG workflow built with LangGraph. It reuses the existing Level 3 hybrid retriever and Level 2 LLM client rather than rebuilding vector or BM25 retrieval.

## 2. High-Level Workflow

```text
User question
     |
     v
  Retrieve  <--------------------------------+
     |                                       |
     v                                       |
  Grade evidence                             |
     |                                       |
     +-- relevant -----------------------> Answer
     |                                       |
     +-- not relevant, attempts remain -> Refine query
     |                                       |
     +-- not relevant, limit reached ---> Insufficient-evidence answer
                                             
```

The workflow is bounded by `max_attempts`, which counts the initial retrieval. With `max_attempts=2`, the graph can perform at most two retrieval attempts: the original query and one refined query.

## 3. Components

### 3.1 LangGraph workflow

File: `services/agentic_rag.py`

`AgenticRAGService` defines the graph using `StateGraph` with four nodes:

- `retrieve`: calls the injected retriever with the current query and `top_k`, stores results, and increments the attempt count.
- `grade`: asks the LLM whether retrieved excerpts contain enough relevant evidence to answer the original question. The expected output is `YES` or `NO`.
- `refine`: asks the LLM to produce one improved natural-language query for the local handbook corpus. A deterministic normalizer removes common web-search syntax such as `site:`, URLs, Boolean operators, and surrounding quotation marks.
- `answer`: generates a grounded answer from the retrieved excerpts only when the evidence passed the relevance check. Otherwise, it returns the insufficient-evidence message.

Conditional routing after `grade` follows these rules:

1. If evidence is judged relevant, go to `answer`.
2. If evidence is not relevant and attempts remain, go to `refine`, then retrieve again.
3. If evidence is not relevant and the attempt limit is reached, go to `answer`, which returns the insufficient-evidence response.

### 3.2 Shared state

`AgenticRAGState` tracks:

- `question`: original user question.
- `current_query`: query used for the current retrieval attempt.
- `query_history`: original and refined queries.
- `documents`: the most recent retrieval results.
- `attempt_count` and `max_attempts`: bounded retry control.
- `top_k`: number of documents requested per retrieval attempt.
- `relevant`: LLM relevance decision.
- `answer`: final answer or insufficient-evidence message.
- `status`: `running`, `answered`, or `insufficient_evidence` at the relevant stage of execution.

The public `run()` method returns the question, answer, status, final documents, query history, retrieval attempt count, and evidence-relevance decision.

### 3.3 Existing hybrid retriever

The runner uses the Level 2 employee-handbook evaluation collection:

- Chroma directory: `levels/level-2-practical-rag/data/chroma_employee_handbook`
- Collection: `employee_handbook_evaluation`

The runner loads the corpus from that collection, uses the existing embedding and vector-retrieval services, builds a BM25 retriever over the same corpus, and combines vector and BM25 rankings with the existing `HybridRetriever` and Reciprocal Rank Fusion implementation.

The Agentic RAG runner currently uses this 28-chunk Level 2 corpus, not the newer Level 3 hierarchical parent-child collection.

### 3.4 LLM client

The runner reuses the Level 2 `OpenAILLMClient`, which uses the configured OpenAI model and requires `OPENAI_API_KEY`. The LLM is called for relevance grading, query rewriting when required, and final answer generation when evidence is accepted.

## 4. Running the workflow

Show the runner options without invoking retrieval or the LLM:

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run python \
  levels/level-3-advanced-rag/scripts/run_agentic_rag.py --help
```

Run a question against the employee handbook:

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run python \
  levels/level-3-advanced-rag/scripts/run_agentic_rag.py \
  --question "How many annual leave days are provided?" \
  --top-k 3 \
  --max-attempts 2
```

Try an out-of-scope question to exercise the bounded retry path:

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run python \
  levels/level-3-advanced-rag/scripts/run_agentic_rag.py \
  --question "What is the company cafeteria menu for next Friday?" \
  --top-k 3 \
  --max-attempts 2
```

The commands that execute a question initialize the embedding model and LLM client and may incur API usage. The `--help` command does not run retrieval or call the LLM.

## 5. Input validation and limits

The workflow rejects empty questions and non-positive `top_k` or `max_attempts` values. Retry attempts are explicitly bounded, so the graph cannot repeat retrieval indefinitely through its own retry edge.

The query normalizer is intentionally lightweight. It removes common web-specific syntax that is not appropriate for the local corpus, but it is not a complete natural-language query repair system.

## 6. Test Coverage

Agentic RAG unit tests:

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run pytest \
  levels/level-3-advanced-rag/tests/test_agentic_rag.py -q
```

Full Level 3 suite:

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run pytest \
  levels/level-3-advanced-rag/tests -q
```

The Agentic RAG unit tests use fake retriever and LLM dependencies, so they test routing and control flow without making OpenAI API calls. Covered scenarios include:

- Relevant first-pass results go directly to answer generation.
- Irrelevant results trigger query refinement and a second retrieval.
- Empty results and exhausted retries return an insufficient-evidence response.
- Empty questions and invalid configuration are rejected.
- Refined queries have common web-search syntax removed.

At documentation time, the Agentic RAG tests passed with 9 tests, and the full Level 3 suite passed with 209 tests in 3.37 seconds. `git diff --check` reported no errors.

## 7. Manual Smoke-Test Results

### In-scope question

Question: `How many annual leave days are provided?`

Observed result:

- Status: `answered`
- Retrieval attempts: 1
- The answer stated that full-time employees generally receive 20 annual leave days per calendar year, subject to employment terms and applicable regional requirements.

This demonstrates that the successful first-pass route worked for this example. It is not a measure of overall retrieval quality.

### Out-of-scope question

Question: `What is the company cafeteria menu for next Friday?`

Observed before query-normalization was added:

- Status: `insufficient_evidence`
- Retrieval attempts: 2
- The workflow returned its insufficient-evidence response after the retry.
- The generated retry query included web-search syntax, revealing a mismatch between the LLM rewrite and the local-only corpus.

A deterministic query normalizer and a regression test were subsequently added. The normalizer's behavior is unit-tested, but the live out-of-scope question has **not yet been rerun after that fix**.

## 8. Current Limitations

1. **LLM grading is not a correctness guarantee.** The grader can incorrectly accept irrelevant evidence or reject useful evidence. It currently expects a simple `YES` or `NO` response and is not a calibrated relevance model.
2. **Query rewriting can drift.** The normalizer removes common web-search syntax, but it cannot guarantee that every rewritten query improves retrieval.
3. **Only one retrieval strategy is orchestrated.** The agent uses the existing hybrid retriever; it does not dynamically choose among vector-only, BM25-only, reranking, parent-child, or hierarchical stores.
4. **No query planning or multi-tool use is implemented.** This is a bounded retrieval/refinement graph, not a general autonomous agent.
5. **The runner uses the Level 2 28-chunk handbook collection.** It does not yet retrieve from the Level 3 hierarchical parent-child collection.
6. **The answer prompt asks for grounded responses, but generation is not formally verified.** A prompt alone cannot guarantee that every answer claim is supported by a source.
7. **Live integration coverage is small.** The in-scope query has been run successfully, and the out-of-scope retry was observed before query-normalization was added. More post-fix smoke tests are required.
8. **Formal comparative evaluation is pending.** There is not yet evidence that this agentic workflow improves Hit Rate@K, MRR, answer correctness, latency, or cost compared with normal hybrid RAG.
9. **API cost and latency can increase.** Each retry may invoke the LLM for grading and rewriting; an accepted result requires answer generation as well. The retry limit controls the maximum number of retrieval attempts, not a strict global token or cost budget.

## 9. Evaluation Status

**Status: Deferred until the planned Level 3 retrieval topics are complete.**

Formal evaluation should compare the existing hybrid-RAG baseline with Agentic RAG on the same representative questions. Report at least answer correctness or groundedness, retrieval relevance, retry frequency, latency, and LLM call/token cost where available. Include both answerable and unanswerable questions.

No claim of measured quality improvement is made at this stage. The current results demonstrate workflow behavior and integration for a small number of smoke tests only.

## 10. Summary

This implementation adds a bounded LangGraph workflow around the existing hybrid retriever. The graph retrieves documents, checks whether they contain useful evidence, optionally refines the query and retries, and generates an answer only after the evidence is accepted. If evidence remains insufficient at the retry limit, the workflow returns an explicit insufficient-evidence response.

The unit tests and current smoke tests demonstrate basic control flow. Query-normalization has unit coverage, but a live out-of-scope test after that fix and formal comparison with non-agentic RAG remain pending.
