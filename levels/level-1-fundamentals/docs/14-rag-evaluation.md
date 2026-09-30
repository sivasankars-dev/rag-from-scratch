# Step 14 — RAG Evaluation

> Level 1 learning note: this chapter preserves its original checkpoint. Steps 1–17 are now complete; see the [learning index](../../../README.md#level-1-learning-sequence). Commands below run from the repository root and select Level 1 with `PYTHONPATH`. Shared data remains under root `data/`.

## 1. Where We Are

We have built a pipeline that extracts PDF text, creates chunks, embeds them, and stores them in ChromaDB. Retrieval finds chunks for a question. Step 12 connects those chunks to context building, prompt construction, and LLM generation.

[Step 13 — Better Chunking](13-better-chunking.md) introduced a separate sentence-based chunker. Its tests check how it splits and groups text. That raises our next question: how do we measure whether retrieval finds the passages we expect?

The current Step 14 evaluation uses the existing `company_policy.pdf` collection. Ingestion still uses Step 3's character chunker with a size of 100 and overlap of 20. **This is not yet an evaluation of BetterChunker or a comparison between chunking strategies.** The PDF itself was not changed for this step.

## 2. Why Do We Need RAG Evaluation?

A pipeline can run without errors and still return an unhelpful passage. A fluent answer can also be wrong.

Previously, we could ask a question and inspect the result ourselves. Evaluation makes that check repeatable: keep a small set of questions and expected results, run them through retrieval, and calculate scores.

For example, when we ask about annual leave, we want retrieval to find the chunk containing the entitlement of **20 days**. Merely returning a passage that mentions company policy is not enough for this check.

## 3. What Does Evaluation Mean?

Evaluation means comparing what the system returns with what we independently expect.

Think of a short practice quiz with an answer sheet. Here, the questions are in a JSON file, and the expected chunk numbers are part of the answer sheet.

The current implementation measures two things:

- **Hit Rate@K:** did the expected chunk appear among the first K results?
- **Mean Reciprocal Rank:** how early did the expected chunk appear, averaged across questions?

This part of Step 14 evaluates retrieval. It does not generate or judge LLM answers.

## 4. Evaluation Dataset

[`data/evaluation_dataset.json`](../../../data/evaluation_dataset.json) contains five cases:

| Question | Expected answer | Expected chunk |
| --- | --- | --- |
| What is the name of the policy? | Company Leave Policy | 0 |
| How many annual leave days are employees entitled to per year? | 20 days | 0 |
| How many unused annual leave days can employees carry forward? | 10 days | 1 |
| How many sick leave days are employees entitled to per year? | 12 days | 2 |
| Who can apply for parental leave? | Eligible employees can apply for parental leave. | 3 |

Every case has `expected_source` set to `company_policy.pdf`.

One case looks like this:

```json
{
  "question": "How many annual leave days are employees entitled to per year?",
  "expected_answer": "20 days",
  "expected_source": "company_policy.pdf",
  "expected_chunk": 0
}
```

These are five questions about one document. They are a small starting point for learning evaluation.

## 5. Ground Truth

**Ground truth** means the reference we decide is correct before measuring retrieval.

For this dataset, inspect the PDF and the chunks produced by the existing ingestion settings. Chunk 0 contains the policy title and annual-leave entitlement; chunk 1 contains carry-forward information; chunk 2 contains sick leave; chunk 3 contains parental leave information.

Choose expected chunks by reading that source material. **Do not run the retriever and use whatever it returns as the expected chunk.** That would make the evaluation circular: the system would create its own answer sheet and then be scored against it.

A chunk number describes a position in this particular set of chunks. Changing the text, chunk size, overlap, or chunking strategy can change those numbers. They are convenient for this learning repository, but are not always stable identifiers in production systems. Ground truth must be reviewed if the chunks change.

## 6. Expected Answer vs Expected Source vs Expected Chunk

These fields describe different parts of the reference:

| Field | Meaning | Use in the current evaluator |
| --- | --- | --- |
| `question` | What we ask retrieval | Passed to the embedding service |
| `expected_answer` | The fact we expect the source to support | Loaded and printed; not scored |
| `expected_source` | The document that should contain the fact | Loaded and printed; not checked |
| `expected_chunk` | The chunk index expected to contain the supporting text | Compared with retrieved `chunk_index` values |

For the annual-leave case, the expected answer is `20 days`, the source is `company_policy.pdf`, and the chunk index is `0`.

The current metrics compare **chunk numbers only**. If another document has a chunk with the same index, it could count as a match even though its source differs. Keep this limitation in mind when interpreting this single-document exercise.

## 7. Retrieval Evaluation

The runner uses [`levels/level-1-fundamentals/services/vector_store.py`](../services/vector_store.py), the Step 7 store. It searches the persisted `documents_cosine` collection in `data/chroma` using cosine distance.

For each question, the evaluator:

1. Creates a query embedding.
2. Requests the top K chunks.
3. Reads their chunk indexes in returned order.
4. Checks for the expected chunk index.

It does not use Step 8's source filtering or similarity threshold. It also does not call `RAGService`, build a prompt, or call the LLM.

## 8. Hit Rate@K

Hit Rate asks:

> Did the retriever find the expected chunk somewhere in the top K results?

`K=3` means we examine up to the first three results for each question.

```text
Hit Rate@K = questions with a hit / total evaluation questions
```

Suppose the annual-leave question expects chunk 0. These illustrative results count as a hit:

```text
Retrieved chunk indexes: [2, 0, 1]
Expected chunk index:    0
```

Chunk 0 is present, so the question earns one hit. Its position does not change that hit score. If chunk 0 is absent, the question earns zero.

In the reported run, all five questions found their expected chunk within the top three:

```text
Hit Rate@3 = 5 / 5 = 1.0 = 100.00%
```

The method returns a fraction; the runner formats it as a percentage.

## 9. Reciprocal Rank

Reciprocal Rank gives more credit when the expected chunk appears earlier.

```text
Reciprocal Rank = 1 / rank
```

| Position of the expected chunk | Reciprocal rank |
| --- | --- |
| Rank 1 | 1.0 |
| Rank 2 | 0.5 |
| Rank 3 | Approximately 0.33 |
| Not found within the evaluated top K | 0.0 |

**Rank starts at 1. Chunk indexes start at 0.** They are different numbers. In `[2, 0, 1]`, chunk 0 appears at rank 2, so its reciprocal rank is `1 / 2 = 0.5`.

Reciprocal rank is calculated inside `mean_reciprocal_rank()`; there is no separate public reciprocal-rank method.

## 10. Mean Reciprocal Rank (MRR)

MRR is the average of the reciprocal ranks across all evaluation questions:

```text
MRR = sum of reciprocal ranks / number of evaluation questions
```

For a small illustrative example, suppose three questions find their expected chunk at ranks 1, 2, and 3:

```text
MRR = (1.0 + 0.5 + 0.333...) / 3
    ≈ 0.61
```

The current runner passes `k=3`, so we label its result **MRR@3**. Any expected chunk outside those results contributes zero.

The reported result is **MRR@3 = 0.87**, rounded to two decimal places. The runner prints the average, not the individual ranks. No per-question rank report is claimed here.

## 11. Step 14 Architecture / Flow

```text
Evaluation Dataset
        ↓
Question
        ↓
Create Query Embedding
        ↓
Search Vector Store
        ↓
Get Top K Chunks
        ↓
Compare Retrieved Chunks
with Ground Truth
        ↓
Hit Rate / Reciprocal Rank
        ↓
MRR
```

Hit Rate averages hit/miss results. MRR averages reciprocal ranks; it is not calculated from Hit Rate.

The runner calls the two metric methods separately. Each method embeds and searches all five questions again, so the current runner performs ten embedding calls and ten searches. Results are not shared between the methods.

## 12. Files Added in Step 14

| File | Purpose |
| --- | --- |
| [`data/evaluation_dataset.json`](../../../data/evaluation_dataset.json) | Five questions and their reference fields |
| [`levels/level-1-fundamentals/services/evaluation_dataset.py`](../services/evaluation_dataset.py) | Load the JSON file |
| [`levels/level-1-fundamentals/scripts/run_evaluation_dataset.py`](../scripts/run_evaluation_dataset.py) | Print the case count and each case's fields |
| [`levels/level-1-fundamentals/services/retrieval_evaluator.py`](../services/retrieval_evaluator.py) | Calculate Hit Rate@K and MRR |
| [`levels/level-1-fundamentals/scripts/run_retrieval_evaluation.py`](../scripts/run_retrieval_evaluation.py) | Load services, run both metrics with K=3, and print scores |
| [`levels/level-1-fundamentals/tests/test_evaluation_dataset.py`](../tests/test_evaluation_dataset.py) | Three dataset checks |
| [`levels/level-1-fundamentals/tests/test_retrieval_evaluator.py`](../tests/test_retrieval_evaluator.py) | Currently empty; no evaluator assertions yet |
| `levels/level-1-fundamentals/docs/14-rag-evaluation.md` | Explain the current learning checkpoint |

## 13. How the Evaluation Code Works

### Load the cases

`EvaluationDataset(file_path)` stores a `Path`. Its `load()` method opens the file as UTF-8 and returns `json.load(file)`.

The loader does not validate the dataset structure or required fields. Missing files and invalid JSON raise errors rather than producing a custom fallback.

### Calculate Hit Rate

`hit_rate_at_k()` checks that `k` is greater than zero. An empty case list returns `0.0` for valid K.

For each case, it embeds `case["question"]`, calls `vector_store.search(..., top_k=k)`, and reads `results["metadatas"][0]`. Chroma groups results by query; `[0]` selects the results for the single query supplied here.

It collects each metadata entry's `chunk_index`. If `expected_chunk` appears in that list, the hit count increases by one. Finally, it divides by the number of cases.

### Calculate MRR

`mean_reciprocal_rank()` applies the same K and empty-list checks. It searches each question and walks the returned chunk indexes using ranks starting at 1.

At the first match, it records `1 / rank` and stops looking for that question. If no match appears, the value stays `0.0`. It returns the average across all cases.

### Print the summary

The runner creates `EmbeddingService`, `VectorStore`, and `RetrievalEvaluator`. It calculates MRR first and Hit Rate second, both with `k=3`, then prints Hit Rate followed by MRR.

The existing dataset tests check the five-case count, required field presence, and the annual-leave reference values. They do not verify metric calculations or establish general retrieval quality.

## 14. How to Run the Evaluation

Run these commands from the repository root so the relative data paths resolve correctly.

First, inspect the dataset:

```bash
PYTHONPATH=levels/level-1-fundamentals uv run python -m scripts.run_evaluation_dataset
```

This prints all five cases without loading the embedding model or querying Chroma.

For retrieval evaluation, the sample must already be ingested into the expected collection. On a fresh setup, use the existing ingestion script:

```bash
PYTHONPATH=levels/level-1-fundamentals uv run python -m scripts.run_ingest_document
```

This creates embeddings and writes the sample chunks to Chroma. It uses Step 3's size 100 and overlap 20. Inspect those source chunks independently when checking the dataset labels.

Then run:

```bash
PYTHONPATH=levels/level-1-fundamentals uv run python -m scripts.run_retrieval_evaluation
```

The embedding service uses `all-MiniLM-L6-v2`. Its first load may need to download model files; later runs can use the local cache. This evaluation does not call the LLM or require its API key.

Opening a vector store does not ingest the PDF automatically. An empty, outdated, or different collection will not reproduce the intended evaluation.

## 15. Actual Evaluation Result

The developer reported this output for the current five-case dataset and existing collection:

```text
============================================================
RAG Retrieval Evaluation
============================================================
Evaluation cases: 5
Metric: Hit Rate@3
Hit Rate@3: 100.00%
MRR@3: 0.87
```

This is the supplied run result, not a newly measured run during documentation. The labels and number formatting match the current runner. The scores are calculated at runtime, not hardcoded.

## 16. What the Current Result Means

**Hit Rate@3 = 100.00%** means the expected chunk index appeared within the first three results for all five questions.

**MRR@3 = 0.87** means the average reciprocal rank was approximately 0.87 for those five questions. Because it is below 1.0, the expected chunk was not first for every question in that run.

Together, the scores describe both whether the expected chunk was found and how early it appeared.

## 17. What the Current Result Does NOT Mean

These results do not establish that:

- The entire RAG system is perfect.
- Every returned chunk is relevant.
- Retrieval works equally well on other questions or documents.
- BetterChunker improves retrieval over Step 3.
- Retrieved sources were checked against `expected_source`.
- Final LLM answers are correct, faithful to the source, or relevant to the question.

`expected_answer` is present in the dataset, but no generated answer is compared with it. A 100% Hit Rate is a result for this small chunk-index check, not a score for the whole RAG pipeline.

## 18. Why Hit Rate and MRR Are Different

Consider a question whose expected chunk is 0:

| Illustrative retrieved indexes | Hit | Reciprocal rank |
| --- | --- | --- |
| `[0, 1, 2]` | 1 | 1.0 |
| `[1, 0, 2]` | 1 | 0.5 |
| `[1, 2, 0]` | 1 | Approximately 0.33 |
| `[1, 2, 3]` | 0 | 0.0 |

All three successful lists count equally for Hit Rate. Reciprocal rank rewards placing the expected chunk earlier. MRR averages that position-sensitive score over the dataset.

That is why we can have 100% Hit Rate@3 while MRR@3 is below 1.0.

## 19. Beginner Interview Explanation

> “I created five evaluation questions from our policy PDF and recorded the expected supporting chunk for each one. I embed each question, retrieve the top three chunks, and compare their indexes with the reference. Hit Rate tells me whether the expected chunk was found. MRR tells me how early it appeared on average. Our reported results are 100% Hit Rate@3 and 0.87 MRR@3. This evaluates retrieval on five cases; it does not yet evaluate the LLM's final answers.”

**Why do we need ground truth?** To have an independent reference against which we can check retrieval.

**Why not use the retriever's output as ground truth?** That would let retrieval define what counts as correct and hide its mistakes.

**Why use two metrics?** Hit Rate measures finding the expected chunk; MRR also considers its position.

**Why is 100% not enough to declare success for all RAG?** We checked only five questions and chunk indexes. Answer quality and broader retrieval behavior remain unmeasured.

## 20. Current Limitations

- The dataset has five cases, all about one policy document.
- Each case names one expected chunk; multiple acceptable supporting chunks are not represented.
- Only chunk indexes are matched. Source and expected-answer fields are not scored.
- Chunk indexes depend on the current text and chunking settings.
- The runner fixes K at 3, although the metric methods accept K as an argument and default to 3.
- The evaluator expects Step 7's nested result structure. Step 8's filtered result list is a different interface.
- There is no per-question result report, saved evaluation history, or chunker comparison.
- The dataset loader has no schema validation, and the evaluator test file is currently empty.
- Final answer quality, faithfulness, and answer relevance are not evaluated.

These boundaries describe the implementation as it exists. The documentation does not change them.

## 21. What Comes Next

The current part of Step 14 gives us a small, repeatable retrieval check. We can now distinguish finding the expected chunk from placing it first.

Later work can broaden the evaluation cases and examine generated answers: did the answer address the question, and was it supported by the retrieved text? Those checks are future work. For now, the implemented metrics are Hit Rate@K and Mean Reciprocal Rank over the current dataset.
