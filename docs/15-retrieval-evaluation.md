# Retrieval Evaluation

Retrieval evaluation means measuring **how well our retriever finds relevant chunks for a user query**.

In RAG, retrieval happens before the LLM:

```text
User Question
      ↓
Retriever
      ↓
Retrieved Chunks
      ↓
LLM
      ↓
Answer
```

If the retriever gives poor chunks, the LLM may not have the correct information to answer the question.

So we need metrics to evaluate retrieval quality.

**What is implemented?** [Step 14](14-rag-evaluation.md) implements **Hit Rate@K and MRR@K**. Precision@K, Recall@K, F1, and NDCG@K are covered here as concepts for learning; they are not implemented yet.

The chunk numbers in this chapter are **hypothetical examples**, not necessarily the actual chunk indexes in the company policy dataset. The current dataset names one expected chunk per question. Examples with several relevant chunks or relevance grades assume additional ground-truth labels that our dataset does not currently contain.

---

## 1. Hit Rate@K

### What does it mean?

Hit Rate@K asks:

> **"Did we retrieve the relevant chunk within the top K results?"**

It does not care about the exact position, as long as the relevant result is somewhere inside top K.

### Example

Expected chunk:

```text
5
```

Retrieved top-3:

```text
[2, 5, 8]
```

Chunk `5` is present.

So:

```text
Hit = 1
```

If the relevant chunk is not present:

```text
[2, 7, 8]
```

Then:

```text
Hit = 0
```

### Formula

```text
Hit Rate@K =
Number of queries with a relevant result in top-K
--------------------------------------------------
Total number of queries
```

### Simple memory

> **Hit Rate = Did I find it?**

---

## 2. Reciprocal Rank (RR)

Hit Rate only tells us whether we found the relevant result.

It does not tell us **where** we found it.

RR measures the position of the **first relevant result**. Ranks start at **1**: the first result has rank 1, regardless of its chunk index.

### Formula

```text
RR = 1 / rank of the first relevant result
```

### Example 1

```text
Expected = 5

Retrieved:
[5, 2, 8]
```

Relevant result is at rank 1.

```text
RR = 1 / 1 = 1.0
```

### Example 2

```text
Expected = 5

Retrieved:
[2, 8, 5]
```

Relevant result is at rank 3.

```text
RR = 1 / 3 ≈ 0.33
```

### If the relevant result is not found

When evaluating only the top K results, RR is zero if no relevant result appears within that cutoff—even if one appears farther down.

```text
RR = 0
```

### Simple memory

> **RR = How high did I find it?**

---

## 3. Mean Reciprocal Rank (MRR)

MRR is the **average Reciprocal Rank across multiple queries**. Each query contributes the reciprocal rank of its first relevant result only.

**MRR@K** limits that check to the first K results for each query. A query with no relevant result within top K contributes zero. Step 14 uses K=3.

```text
MRR@K = sum of reciprocal ranks within the cutoff / number of queries
```

### Example

Suppose we have three queries:

```text
Q1 → RR = 1.0
Q2 → RR = 0.5
Q3 → RR = 0
```

Then:

```text
MRR = (1.0 + 0.5 + 0) / 3
    = 0.5
```

We report MRR as a decimal: **0.5**. It is an average rank-based score, not the percentage of questions with a hit.

### Simple memory

> **MRR = Average of RR across multiple queries.**

---

## 4. Precision@K

Precision asks:

> **"Of the chunks I retrieved, how many are actually relevant?"**

```text
Precision@K = relevant results in top K / K
```

These examples assume K distinct results are returned.

### Example

Actual relevant chunks:

```text
[2, 5, 8]
```

Retrieved top-5:

```text
[2, 7, 5, 1, 9]
```

Relevant retrieved chunks:

```text
[2, 5]
```

So:

```text
Precision@5 = 2 / 5
            = 40%
```

### Simple memory

> **Precision = Of what I retrieved, how much is relevant?**

---

## 5. Recall@K

Recall asks:

> **"Of all the relevant chunks that exist, how many did I retrieve?"**

```text
Recall@K = relevant results in top K / total known relevant results
```

Recall needs an **independently established ground-truth set** of relevant chunks for the question. Inspect the source material to establish that set; do not treat whatever the retriever returns as the answer sheet. The example assumes at least one known relevant chunk.

Using the same example:

Actual relevant chunks:

```text
[2, 5, 8]
```

Retrieved:

```text
[2, 7, 5, 1, 9]
```

We retrieved:

```text
[2, 5]
```

So:

```text
Recall@5 = 2 / 3
         ≈ 66.67%
```

### Simple memory

> **Recall = Of everything relevant that exists, how much did I find?**

---

## 6. Precision vs Recall

These two are easy to confuse.

### Precision

Focuses on the **retrieved results**.

> "I retrieved 5 chunks. How many of those 5 are relevant?"

### Recall

Focuses on the **actual relevant results**.

> "There are 3 relevant chunks. How many of those 3 did I retrieve?"

---

## 7. F1 Score

F1 is the **harmonic mean of Precision and Recall**. In simple terms, both need to be high for F1 to be high. It does not merely measure how close the two values are.

For F1@K, use Precision@K and Recall@K for the same question and cutoff.

It is useful when we want a balance between:

* retrieving relevant chunks
* avoiding irrelevant chunks

### Formula

```text
F1 = 2 × (Precision × Recall)
     ---------------------------
       Precision + Recall
```

### Example

```text
Precision = 0.80
Recall = 0.50
```

Then:

```text
F1 = 2 × (0.80 × 0.50) / (0.80 + 0.50)
   ≈ 0.615
```

So:

```text
F1 ≈ 61.5%
```

### Simple memory

> **F1 is high when both Precision and Recall are high.**

When both Precision and Recall are zero, F1 is conventionally reported as zero.

---

## 8. NDCG@K

NDCG means **Normalized Discounted Cumulative Gain**. NDCG@K evaluates the first K ranked results and is useful when chunks have **different levels of relevance**.

The values below are independently assigned **relevance grades**, not chunk IDs or vector similarity scores. Binary grades (1 for relevant, 0 for not relevant) also work; graded relevance is not mandatory.

For example:

```text
Rank 1 → Highly relevant
Rank 2 → Relevant
Rank 3 → Somewhat relevant
Rank 4 → Not relevant
```

We can represent this using relevance grades:

```text
3 → Highly relevant
2 → Relevant
1 → Somewhat relevant
0 → Not relevant
```

NDCG gives more importance to highly relevant results appearing at higher ranks.

### Why?

Consider:

```text
Ranking A:
[3, 2, 1, 0]
```

and:

```text
Ranking B:
[1, 0, 2, 3]
```

Both lists contain relevance grades in rank order, not chunk IDs. They contain the same grades; use K=4 for this example.

But Ranking A is better ordered because the highly relevant result appears earlier.

NDCG compares the ranking with an **ideal ranking**:

```text
NDCG@K = DCG@K / Ideal DCG@K
```

DCG adds up relevance gains, giving less weight to results farther down the list. Higher relevance at higher ranks receives more value.

The ideal ranking puts the highest ground-truth relevance grades first and takes the best K results. It considers the ground-truth candidates, including relevant chunks retrieval may have missed; it is not just a rearrangement of the retrieved list.

With nonnegative grades and a positive Ideal DCG, NDCG ranges from:

```text
0 → No relevance gain in the evaluated results
1 → Ideal ranking
```

If Ideal DCG is zero, the ratio is undefined; an evaluation needs a stated convention, such as reporting zero for that case.

### Simple memory

> **NDCG = How good is the overall ranking when results have different relevance levels?**

---

## 9. MRR vs NDCG

These metrics are related but answer different questions.

### MRR

Uses only the **first relevant result** for each query.

> "How high did I find the first relevant result?"

### NDCG

Considers relevance at **all positions within the K cutoff**, including different relevance levels.

> "How well are the first K results ranked?"

So:

```text
MRR  → First relevant result
NDCG → Overall ranking quality
```

---

## 10. Retrieval Metrics Summary

| Metric      | Simple Question                               |
| ----------- | --------------------------------------------- |
| Hit Rate@K  | Did I find a relevant result in top-K?        |
| RR          | How high was the first relevant result?       |
| MRR@K       | What is the average RR within top K?        |
| Precision@K | Of what I retrieved, how much is relevant?    |
| Recall@K    | Of what is relevant, how much did I retrieve? |
| F1          | Are Precision and Recall both high?        |
| NDCG@K      | How good is the overall ranking?              |

---

## 11. How These Metrics Fit into RAG

Retrieval evaluation compares the retrieved chunks with ground truth in a separate evaluation workflow. It is not a runtime step between retrieval and the LLM.

```text
Retrieved Chunks → Context → Prompt → LLM
        ↓
Compare with Ground Truth → Retrieval Metrics
```

The answer path uses context and prompt building, as explained in [Step 12](12-rag-orchestration.md). The current Step 14 evaluation runner calculates retrieval metrics without calling the LLM. These metrics do not evaluate final answer quality.

---

## 12. Important Point

No single metric tells us everything about retrieval quality.

Different metrics measure different aspects of retrieval.

For example:

```text
High Hit Rate
```

does not necessarily mean the relevant result is ranked first.

Similarly:

```text
High Precision
```

does not necessarily mean we retrieved every relevant chunk.

Therefore, different metrics can be used depending on what we want to evaluate.

---

## 13. Connection to Re-ranking

Re-ranking is a later RAG engineering concept.

The basic idea is:

```text
User Query
    ↓
Vector Search
    ↓
Initial Top-K Candidates
    ↓
Re-ranker
    ↓
Reordered Results
    ↓
LLM
```

Re-ranking can change the order of existing candidates, but cannot recover a relevant chunk missing from that candidate set.

Metrics such as **MRR@K and NDCG@K** can later compare results before and after re-ranking. Use the **same questions, ground truth, and evaluation cutoff** for both measurements. Reordering does not guarantee improvement; the comparison checks whether it helps.

Re-ranking remains a **Level 2** topic. This Level 1 chapter introduces the connection only; no re-ranking implementation is included.
