# Step 16 — Retrieval Failure Cases

[Step 14](14-rag-evaluation.md) implemented Hit Rate@K and MRR@K. [Step 15](15-retrieval-evaluation.md) explained what retrieval metrics tell us. Now we will look at situations where retrieval or the final answer can go wrong.

A useful question is: **At which stage did we lose the information needed for a supported answer?**

All chunk numbers, policies, rankings, and scores below are **hypothetical teaching examples**. They are not measured results from our company policy dataset. In particular, the remote-work policy and one-year eligibility condition are examples, not claims about the existing PDF.

This chapter covers eight failure cases followed by evaluation concepts. It adds no implementation or new evaluation metrics.

---

## 1. Wrong Chunk Retrieved

Suppose a user asks:

> How many annual leave days do I get?

The indexed document has a chunk stating that employees receive 20 days of annual leave. However, retrieval returns travel reimbursement and office parking chunks instead.

The supporting information exists, but the returned chunks do not answer the question. This is a **retrieval failure**.

Increasing `top_k` may give the relevant chunk a chance to appear among more candidates. It does not guarantee success, and it may return more irrelevant material too.

For this question, if the expected annual-leave chunk is absent from the evaluated top K:

- The hit is **0**, lowering Hit Rate@K across the questions.
- Reciprocal Rank within the cutoff, or **RR@K**, is **0**, lowering MRR@K.

If the chunk is found, its position matters for RR. A match at rank 1 scores 1.0; a match at rank 3 scores approximately 0.33.

---

## 2. Relevant Chunk Exists but Falls Outside top_k

Sometimes the problem is easier to identify: the relevant chunk is ranked below the selected cutoff.

Consider this hypothetical ranking:

| Rank | Chunk | Relevant to this question? |
| --- | --- | --- |
| 1 | Chunk 3 | No |
| 2 | Chunk 2 | No |
| 3 | Chunk 4 | No |
| 4 | Chunk 1 | No |
| 5 | Chunk 0 | Yes |

With `top_k=3`, Chunk 0 is not returned. With `top_k=5`, it is returned in this example, assuming no later filter rejects it.

This is a **cutoff problem**: the relevant result is outside the part of the ranking we keep. Here, the hit changes from 0 at K=3 to 1 at K=5. Its reciprocal rank at K=5 is still only `1 / 5 = 0.2`.

Increasing K exposes more of this ranking; it does not move the relevant chunk to the top. Other questions may still miss their relevant chunks, and the extra results may be unhelpful. Evaluate the trade-off rather than assuming that a larger K fixes retrieval.

---

## 3. Chunking Problem

The information needed to answer a question can be split across chunks.

### Original document

> Employees who complete one year of service are eligible for 20 days of annual leave per year. Annual leave must be approved by a manager.

Suppose the first sentence is split like this:

| Chunk | Text |
| --- | --- |
| Chunk 1 | Employees who complete one year of service are eligible for |
| Chunk 2 | 20 days of annual leave per year. |

The user asks:

> Who is eligible for annual leave and how many days do they get?

Chunk 2 is relevant: it contains the number of days. But it is **incomplete** because it does not contain the eligibility condition.

If Chunk 2 is the labeled relevant chunk and retrieval returns it first, this query earns a hit at K=1. For a one-query evaluation, Hit Rate@1 would be 1. Yet the retrieved text is not enough to answer both parts of the question.

This is why relevance and sufficient context are different. A retrieval metric scores against its ground-truth labels; it does not directly guarantee final answer correctness.

Increasing `top_k` may retrieve both chunks, but it does not guarantee that neighboring pieces will appear together. Better chunking strategies can reduce this problem, but no chunking strategy guarantees that every question will retrieve complete context.

---

## 4. Query / Document Vocabulary Mismatch

A user and a document can describe the same idea using different words.

**Document:**

> Employees may avail themselves of the organization's remote working arrangement for two days per week.

**User:**

> Can I work from home?

“Remote working arrangement” and “work from home” are related concepts, but the wording differs.

Embeddings can help match related meanings even when the words are different. They are not perfect: wording, missing context, or unfamiliar terms can still lead to an unhelpful ranking.

Query rewriting, multi-query retrieval, and hybrid search are possible **Level 2** topics for exploring this problem. We do not implement or teach those techniques here.

---

## 5. Similarity Score Does Not Always Mean “Correct”

Consider the question:

> How many annual leave days do I get?

Suppose retrieval produces:

| Chunk | Topic | Similarity |
| --- | --- | --- |
| A | Sick leave | 0.82 |
| B | Annual leave | 0.75 |

Chunk A has the higher score, but its sick-leave entitlement does not answer the annual-leave question.

Similarity measures closeness between embeddings. It does not verify that a passage contains the answer. Related policies can share vocabulary, and embedding models can rank the wrong passage higher.

Do not use a rule such as **“if similarity > 0.7, the answer is definitely correct.”** A score is not proof of correctness or a probability that the answer is right.

Use this mental model:

```text
User Query
    → Embedding
    → Similarity Search
    → Similarity Score
    → Candidate Ranking
    → “Is it actually relevant?”
    → Requires evaluation / ground truth
```

Ground truth gives us an independent reference for checking relevance. It must come from examining the source material, not from assuming the highest-scoring result is correct.

---

## 6. Similarity Threshold Too Strict

Suppose the user asks:

> Can I work from home?

The relevant remote-work chunk has similarity **0.68**, but the threshold is **0.70**. Even if that chunk is among the retrieved candidates, it is rejected.

Raising the threshold does not improve similarity scores or reorder the results. It only filters candidates more aggressively.

A threshold of **0.60** would allow this candidate through. However, it might also admit irrelevant candidates. A threshold that is too strict can reduce **Recall** by rejecting relevant information.

### top_k and threshold have different jobs

| Setting | What it controls |
| --- | --- |
| `top_k` | The maximum number of candidates requested from retrieval |
| Similarity threshold | The minimum similarity required for a candidate to be accepted |

In [Step 8](08-retrieval-controls.md), Chroma returns up to K candidates, and the wrapper then filters them. The final accepted count can be smaller than K. A candidate whose similarity equals the threshold is accepted.

There is **no universal similarity threshold**. A useful setting depends on the embedding model, domain, documents, chunking, and types of questions. Try settings against independently labeled evaluation cases and inspect what they accept and reject.

---

## 7. Similarity Threshold Too Loose

Now consider the annual-leave question with these candidates:

| Chunk | Topic | Similarity | Accepted at 0.50? |
| --- | --- | --- | --- |
| A | Annual leave | 0.78 | Yes |
| B | Sick leave | 0.71 | Yes |
| C | Work from home | 0.58 | Yes |
| D | Travel reimbursement | 0.51 | Yes |

Assume all four are in the candidate set before filtering. A threshold of **0.50** accepts all four, although only Chunk A may be needed to answer the question.

If A is the only relevant chunk among these four accepted results, then the precision of this accepted set is `1 / 4 = 25%`. Retrieving more chunks does not by itself mean higher precision.

Extra context can contain unrelated numbers and policies. That may make the LLM's job harder: for example, it might mix a sick-leave allowance with an annual-leave entitlement.

### The trade-off

| Threshold choice | Possible effect |
| --- | --- |
| Too strict | Relevant chunks are rejected; recall may decrease |
| Too loose | Irrelevant chunks are accepted; precision may decrease |

**Precision** asks how much of the retrieved material is relevant. **Recall** asks how much of the known relevant material was retrieved. Step 15 defines these at a chosen K cutoff. When evaluating a filtered result set, also state which results and denominator you are measuring.

Tune the threshold using evaluation, not guesses. Raising or lowering it is not a guarantee of better results across all questions.

---

## 8. Retrieval Succeeds but Final Answer Is Wrong

Finding the right passage is only one stage of RAG.

**Policy:**

> Employees who complete one year of service are eligible for 20 days of annual leave per year.

**Question:**

> How many annual leave days do I get?

**Retriever:** Returns the annual-leave chunk. ✅

**LLM:** “You get 30 days.” ❌

Retrieval found the supporting policy, but the generation stage produced an unsupported number. This is a generation or **grounding** failure. Grounding means keeping the answer supported by the supplied information.

The LLM may misunderstand the context, combine facts incorrectly, or generate unsupported information. This can be a hallucination problem even when retrieval succeeds. A supported answer should also preserve the one-year condition rather than assume the user meets it.

### Relevant context can still leave the question unanswered

**Context:**

> Employees with one year of service receive 20 days of annual leave.

**Question:**

> How many annual leave days do I get if I've worked for only 6 months?

The context does not establish the entitlement for six months. It does not justify confidently answering 20 days, 10 days, or zero days.

A supported response would explain that the provided policy does not specify that case. This is desired behavior, not a guarantee implemented by our current RAG service. Step 12's workflow does not yet enforce an insufficient-context response.

---

## 9. Retrieval Failure vs Generation Failure

These stages ask different questions:

| Stage | Question |
| --- | --- |
| Retrieval | Did we find the right information? |
| Generation | Did the LLM produce an answer supported by that information? |

```text
User Query
    ↓
Query Embedding
    ↓
Retrieval
    ↓
Relevant Context (the goal, not a guarantee)
    ↓
LLM Generation
    ↓
Final Answer
```

This diagram is simplified: the Step 12 implementation builds context and a prompt before calling the LLM.

Failure can occur at different points. Retrieval may miss a useful passage or return an incomplete one. Generation may ignore or misinterpret useful context. Sometimes both stages need investigation.

Look at the retrieved text as well as the final answer before deciding where the problem started.

---

## 10. Retrieval Evaluation vs Final Answer Evaluation

Hit Rate, MRR, Precision, Recall, and the other retrieval metrics from Step 15 assess retrieved results against relevance labels. They do not directly prove that the LLM's final answer is correct.

| Evaluation | What we inspect |
| --- | --- |
| Retrieval evaluation | Which chunks were found and where they appeared |
| Final answer evaluation | Whether the answer addresses the question and is supported by the information |

Our current Step 14 implementation calculates Hit Rate@K and MRR@K by comparing expected chunk indexes. The other retrieval metrics remain conceptual, and final answer evaluation is a separate concern.

For example, a query can earn a hit and reciprocal rank of 1.0 while the LLM still says “30 days” instead of the supported “20 days.” Retrieval success and answer correctness must be checked separately.

This is still **Level 1**. Re-ranking and the other advanced retrieval techniques belong to Level 2 or later. No new retrieval strategy or evaluation pipeline is added here.

---

## 11. What should I remember?

1. A similarity score is not proof of correctness.
2. `top_k` controls how many candidates are requested from retrieval.
3. A threshold controls the minimum similarity accepted.
4. A threshold that is too strict can reduce recall.
5. A threshold that is too loose can reduce precision.
6. A relevant chunk can still be incomplete.
7. Retrieval success does not guarantee final answer correctness.
8. RAG has separate retrieval and generation failure points.
9. There is no universal similarity threshold.
10. Measure retrieval quality with evaluation rather than intuition alone.
