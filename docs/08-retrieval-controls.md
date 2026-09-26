# Step 8 — Retrieval Controls

## What are retrieval controls, and why are they required?

Step 7 implemented semantic retrieval: the system converts a user question into an embedding and retrieves the nearest document chunks from Chroma.

However, retrieving the nearest chunks does **not** guarantee that every returned chunk is actually useful.

Retrieval controls add rules around the raw vector search so the application can decide:

* How many candidates should be retrieved?
* How relevant must a result be?
* Should the search be restricted to a particular source?
* What should happen when no result is relevant enough?

Our current retrieval controls are:

1. **Top-K**
2. **Similarity threshold**
3. **Metadata filtering**
4. **No relevant results handling**

The system still does not generate an answer. It only retrieves and filters document passages.

---

## Simple analogy

Imagine asking a librarian:

> "What is the company's work-from-home policy?"

If you say:

> "Search only the company policy document."

the librarian first limits the search to that source. That is **metadata filtering**.

Within the allowed source, the librarian finds up to five pages that look closest to your question. That is **Top-K**.

Then a rough score-based rule removes pages whose similarity is below the chosen minimum. That is the **similarity threshold**. Passing this rule does not prove that a page answers the question.

Finally, if no pages pass the current rules, the librarian says:

> "I couldn't find relevant information."

That is **no relevant results handling**.

---

## Technical explanation: the complete process

```text
User query string
        ↓
Same Sentence Transformer used during ingestion
        ↓
Query embedding
        ↓
Optional source filter (Chroma where)
        ↓
Chroma vector search among eligible chunks
        ↓
Retrieve up to Top-K candidates
        ↓
Distance → cosine similarity
        ↓
Apply similarity threshold
        ↓
┌───────────────────────┴───────────────────────┐
↓                                               ↓
Candidates passing the threshold               No results
↓                                               ↓
Return filtered results                  Return empty list
                                               ↓
                                      Caller handles no result
```

The source filter is passed into Chroma using `where`. Chroma applies it before selecting the Top-K results, so candidates come from the eligible records. Python then applies the similarity threshold to those returned candidates.

The important distinction is:

```text
Top-K
    → controls how many candidates are retrieved

Similarity threshold
    → keeps candidates that meet the minimum similarity score

Metadata filter
    → controls which documents/chunks are eligible

No-result handling
    → controls what happens when nothing passes the filters
```

---

# 1. Top-K

**Top-K** controls the maximum number of nearest candidates requested from Chroma.

For example:

```python
results = self.collection.query(
    query_embeddings=[query_embedding],
    n_results=5,
)
```

means:

> "Return up to 5 nearest candidates."

Top-K does **not** mean that all returned results are relevant.

For example:

```text
Rank 1 → similarity 0.82
Rank 2 → similarity 0.71
Rank 3 → similarity 0.12
Rank 4 → similarity 0.08
Rank 5 → similarity 0.03
```

With:

```text
top_k = 5
```

all five can be returned.

Therefore:

```text
Top-K = quantity control
```

not:

```text
Top-K = relevance guarantee
```

Our implementation passes `top_k` to Chroma as `n_results`.

---

# 2. Similarity threshold

Top-K alone can return weak results.

To control this, we calculate cosine similarity from Chroma's cosine distance:

```python
cosine_similarity = 1 - distance
```

For example:

```text
distance = 0.28

similarity = 1 - 0.28
           = 0.72
```

We then compare the similarity against a threshold.

Current example:

```python
similarity_threshold = 0.50
```

The filtering logic is:

```python
if cosine_similarity < similarity_threshold:
    continue
```

Therefore:

```text
0.72 >= 0.50 → keep
0.67 >= 0.50 → keep
0.66 >= 0.50 → keep
0.47 <  0.50 → reject
0.13 <  0.50 → reject
```

The final number of results can therefore be smaller than Top-K.

For example:

```text
top_k = 5
threshold = 0.50

5 candidates retrieved
        ↓
2 rejected
        ↓
3 results returned
```

The threshold is a retrieval heuristic. It is **not a probability, confidence score, or guarantee that the passage contains the answer**.

---

# 3. Metadata filtering

During ingestion, every chunk receives metadata:

```python
{
    "chunk_index": index,
    "source": source
}
```

For example:

```python
{
    "chunk_index": 0,
    "source": "company_policy.pdf"
}
```

Chroma can use metadata to restrict which records participate in the search.

For example:

```python
where={"source": "company_policy.pdf"}
```

means:

> Search only chunks whose `source` metadata is `company_policy.pdf`.

Our search method supports an optional `source` parameter:

```python
def search(
    self,
    query_embedding,
    top_k=2,
    source=None,
    similarity_threshold=0.50,
):
```

When a nonempty source is supplied:

```python
source="company_policy.pdf"
```

we construct:

```python
where = {"source": source}
```

When no source is supplied:

```python
source=None
```

we use:

```python
where = None
```

The current `if source:` check also treats an empty string as no source restriction. Use `None` when you intend to search all sources.

This means the same search method supports both:

```text
Search all documents
```

and:

```text
Search only one metadata-defined source
```

Metadata filtering and similarity filtering solve different problems:

```text
Metadata filter
    ↓
"Which documents are eligible?"

Similarity threshold
    ↓
"Which retrieved documents meet the minimum similarity score?"
```

---

# 4. No relevant results handling

After applying the similarity threshold, it is possible that no result remains.

The following scores are an illustrative example, not the measured work-from-home experiment later in this document:

```text
Query:
"What is the company's work-from-home policy?"

Similarity threshold:
0.50

Candidate similarities:

0.45 → reject
0.39 → reject
0.31 → reject
0.20 → reject
0.12 → reject
```

The final result is:

```python
[]
```

An empty list is intentionally returned by `VectorStore.search()`.

The vector store should not sometimes return a list and sometimes return a string such as:

```python
"No relevant documents found."
```

because that would create inconsistent return types.

Instead:

```text
VectorStore
    ↓
returns []
```

and the caller decides how to present the situation.

For example:

```python
if not results:
    print("No relevant documents found.")
    return
```

`[]` means no candidates passed the current source filter and similarity threshold. The source filter may have matched no records, or none of the returned Top-K candidates met the threshold.

It does **not** prove that the knowledge base has no answer. Useful information might be excluded by the source filter, missed by retrieval, or rejected by the threshold. The caller's message describes this search attempt, not a certainty about the whole knowledge base.

---

# Current implementation walkthrough

`VectorStore.search()` first queries Chroma:

```python
collections = self.collection.query(
    query_embeddings=[query_embedding],
    n_results=top_k,
    where=where,
    include=[
        "documents",
        "metadatas",
        "distances"
    ],
)
```

Chroma returns parallel result lists for the single query.

The implementation then iterates through the document, metadata and distance values together:

```python
for document, metadata, distance in zip(
    collections["documents"][0],
    collections["metadatas"][0],
    collections["distances"][0],
):
```

For each candidate:

```python
cosine_similarity = 1 - distance
```

Candidates below the threshold are skipped:

```python
if cosine_similarity < similarity_threshold:
    continue
```

Accepted results are converted into a simpler application-level structure:

```python
{
    "document": document,
    "metadata": metadata,
    "distance": distance,
    "similarity": cosine_similarity,
}
```

The method returns a list of these filtered result dictionaries.

This means the calling code no longer needs to understand Chroma's nested response structure.

---

# Step 7 vs Step 8: separate learning implementations

We keep both implementations so we can revisit each learning step. They are not merged.

| Step | Vector store | Retrieval script | Search return value |
| --- | --- | --- | --- |
| 7 | `app/services/vector_store.py` | `scripts/retrieve.py` | Chroma's nested result dictionary |
| 8 | `app/services/retrieval_controls_vector_store.py` | `scripts/retrieval_control_retrieve.py` | A list of filtered result dictionaries, or `[]` |

Both modules define a class named `VectorStore`. In this document, `VectorStore.search()` refers to the **Step 8** class.

Step 7 requests candidates and formats Chroma's raw response in the script. It does not apply a similarity threshold. Step 8 adds source and threshold controls in its separate vector store, so its caller can consume a simpler result list.

```text
scripts/retrieval_control_retrieve.py
    ↓
Step 8 VectorStore.search()
    ↓
Query embedding + optional source filter (where)
    ↓
Chroma search within eligible records
    ↓
Top-K candidates
    ↓
Distance → cosine similarity → similarity threshold
    ↓
Final result list or []
    ↓
scripts/retrieval_control_retrieve.py displays results or a message
```

Run Step 8 from the repository root after ingesting the sample:

```bash
.venv/bin/python -m scripts.retrieval_control_retrieve
```

The script uses `top_k=5`, `source="company_policy.pdf"`, and the search method's default `similarity_threshold=0.50`. The method itself defaults to `top_k=2` when the caller does not supply it.

---

# Actual experiment: similarity threshold

For the question:

```text
How many annual leave days do I get?
```

the retrieval system produced the following measured values:

| Rank | Chunk index | Cosine distance | Cosine similarity | Threshold 0.50 |
| ---- | ----------: | --------------: | ----------------: | -------------- |
| 1    |           0 |    0.2849969864 |      0.7150030136 | Keep           |
| 2    |           2 |    0.3235650063 |      0.6764349937 | Keep           |
| 3    |           1 |    0.3379920125 |      0.6620079875 | Keep           |
| 4    |           3 |    0.5227910876 |      0.4772089124 | Reject         |
| 5    |           4 |    0.8659673929 |      0.1340326071 | Reject         |

Therefore:

```text
Top-K = 5

5 candidates retrieved
        ↓
2 candidates below threshold
        ↓
3 candidates returned
```

The threshold does not change Chroma's original ranking. It filters the candidates after the vector search.

The table preserves the recorded experimental values, including rejected candidates. The current Step 8 script prints only the accepted results. Small floating-point differences on a later run do not require changing this historical record.

---

# Actual experiment: metadata filtering

The same query can be restricted to a specific source:

```python
results = vector_store.search(
    query_embedding=query_embedding,
    top_k=5,
    source="company_policy.pdf",
)
```

The metadata filter becomes:

```python
where={"source": "company_policy.pdf"}
```

If `source` is omitted:

```python
results = vector_store.search(
    query_embedding=query_embedding,
    top_k=5,
)
```

the search is performed without a source restriction.

This makes the source filter optional.

---

# Actual experiment: no relevant results

A question outside the sample document was tested:

```text
do you know my name?
```

With a similarity threshold of `0.50`, no retrieved candidate passed the threshold.

The final result was:

```python
[]
```

The caller handled this using:

```python
if not results:
    print("No relevant documents found.")
    return
```

This demonstrates that the retrieval layer does not assume that every user question has an answer in the indexed documents.

---

# Important discovery: retrieval quality vs hallucination

During testing, the question:

```text
What is the company's work from home policy?
```

returned a chunk similar to:

```text
ing to company policy.
```

with a cosine similarity of approximately:

```text
0.54
```

`similarity = 0.54` does **not** mean:

* 54% confidence
* 54% correctness
* 54% probability of being the answer

It is the cosine similarity between the query embedding and the retrieved chunk embedding. It measures how closely their vector directions align, not whether the chunk answers the question.

This is a poor retrieval result even though it passed the `0.50` threshold.

The problem is partly related to the intentionally small character-based chunks:

```text
chunk_size = 100
chunk_overlap = 20
```

The chunk:

```text
ing to company policy.
```

is only a fragment and does not contain a work-from-home policy.

The current PDF itself does not contain a work-from-home policy. Better chunking can preserve context, but it cannot create information missing from the document.

This demonstrates an important limitation:

> A similarity score does not guarantee that a chunk contains the answer.

This is currently a **retrieval-quality problem**, not an LLM hallucination.

Hallucination would occur later if an LLM received poor or insufficient context and generated an unsupported answer.

The relationship is:

```text
Poor chunking
      ↓
Poor retrieval
      ↓
Poor context
      ↓
Potentially higher risk of an unsupported LLM answer
```

This chunking problem will be addressed later as a separate retrieval-quality topic rather than hiding it with an arbitrary threshold.

---

# Common mistakes

* Thinking Top-K guarantees relevant results.
* Assuming a similarity threshold guarantees correctness.
* Treating similarity as confidence or probability.
* Using `where={"source": None}` when no source filter is intended.
* Returning different data types for successful and empty searches.
* Forgetting that Top-K is the maximum candidate count, not the final result count.
* Assuming an empty retrieval means the application itself failed.
* Assuming a high similarity score means the passage directly answers the question.
* Treating poor retrieval as the same thing as LLM hallucination.
* Increasing the threshold arbitrarily without evaluating whether genuinely relevant passages are being removed.

---

# Validation

The retrieval controls were manually checked using the Step 8 implementation and `scripts/retrieval_control_retrieve.py`. These experiments are not an automated retrieval-quality assessment. The existing automated tests still exercise the Step 7 vector store, not the new Step 8 class.

Tests included:

1. A relevant annual-leave question.
2. Top-K retrieval with multiple candidates.
3. Similarity threshold filtering.
4. Source metadata filtering.
5. Search without a source filter.
6. An unrelated question producing an empty result.
7. A question demonstrating that a semantically similar but incomplete chunk can still pass a threshold.

The source filter operates inside Chroma before Top-K selection. The similarity threshold operates on the returned candidates after the search. Neither control modifies the stored embeddings.

---

# Interview questions

### 1. What is Top-K?

Top-K is the maximum number of nearest candidates requested from the vector database. It controls quantity, not relevance.

### 2. Why do we need a similarity threshold if we already have Top-K?

Top-K can return weak candidates. A threshold allows the application to reject candidates whose similarity is below the chosen minimum.

### 3. Does a high similarity score guarantee that the document answers the question?

No. Similarity measures vector-space relatedness. It is not a correctness or confidence guarantee.

### 4. What is metadata filtering?

Metadata filtering restricts retrieval to records matching metadata conditions, such as a particular source document.

### 5. What happens when no result passes the threshold?

The Step 8 vector store returns an empty list. The caller handles it explicitly. This means no candidates passed the current settings; it does not prove that the knowledge base has no answer.

### 6. Why shouldn't `VectorStore.search()` return a string when there are no results?

Because the method should have a consistent return type. Returning `[]` allows callers to handle empty results predictably.

### 7. Is poor retrieval the same as hallucination?

No. Poor retrieval means the system selected bad or insufficient context. Hallucination occurs when a generation model produces unsupported information. Poor retrieval can increase hallucination risk later.

### 8. Can we choose any similarity threshold such as 0.5 or 0.8?

The threshold is application-dependent. It should be evaluated against representative queries and relevant/irrelevant retrieval examples rather than chosen arbitrarily.

---

# What I learned

Retrieval is not simply:

```text
Query → Top-K
```

A practical retrieval layer needs controls that determine:

```text
How many candidates?
       ↓
Top-K

Which documents?
       ↓
Metadata filter

How relevant?
       ↓
Similarity threshold

What if nothing is relevant?
       ↓
Empty-result handling
```

I also learned that retrieval quality depends on more than the vector database. Chunk boundaries, embedding quality, thresholds and metadata all affect the final context.

A similarity score is useful for filtering and ranking, but it does not prove that a passage contains the correct answer.

---

# What is still missing, and next step

**Step 8 — Retrieval Controls is complete.**

Implemented:

* Top-K
* Similarity threshold
* Metadata filtering
* No relevant results handling

The current system still stops at retrieval. It does not yet:

* expose retrieval through a FastAPI endpoint
* generate an answer using an LLM
* implement `/chat`
* attach source citations to generated answers
* implement reranking
* implement hybrid search
* implement query rewriting
* implement retrieval evaluation

**Next learning chapter: [Step 9 — Retrieval API](09-retrieval-api.md).**

At the end of Step 8, exposing retrieval through HTTP was the next task. It is now implemented in Step 9. The scope and examples above describe Step 8 itself; see the linked chapter for the current API and its request validation.
