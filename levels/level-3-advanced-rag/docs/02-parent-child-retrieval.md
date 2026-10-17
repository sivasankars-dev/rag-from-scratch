# Parent-Child Retrieval — Beginner-Friendly Implementation Guide

## 1. Learning objectives

This document explains the Parent-Child Retrieval implementation in Level 3, building on the RAG pipeline developed in Level 2.

The goals are to understand:

- Why ordinary chunking can lose useful context.
- The difference between parent chunks and child chunks.
- How parent-child relationships are represented.
- Why child chunks are indexed while parent chunks are stored separately.
- How retrieval returns parent context using matching children.
- How unit and integration tests verify the implementation.
- What limitations remain before this approach could be used in production.

Read this document alongside the source code. The examples are illustrative and are not evaluation results.

---

## 2. Refresh: What did Level 2 already teach me?

Level 2 established the core RAG pipeline:

1. Load and split documents into chunks.
2. Generate embeddings for the chunks.
3. Store embeddings, text, and metadata in Chroma.
4. Embed a user's question.
5. Retrieve relevant chunks.
6. Use retrieved context to generate a grounded answer.
7. Evaluate retrieval and answer quality.

For a refresher, see the [Level 2 overview](../../level-2-practical-rag/README.md) and [chunk overlap guide](../../level-2-practical-rag/docs/02-chunk-overlap.md). The [Multi-Query Retrieval guide](01-multi-query-retrieval.md) explains a different improvement: searching with alternative query wordings. Parent-Child Retrieval instead changes the size of the context returned; these implementations are not automatically combined.

Level 3 does not replace that pipeline. Parent-Child Retrieval changes how document chunks are organized and how retrieved evidence is returned.

---

## 3. The problem: Small chunks may lose context

Imagine a document contains:

> Employees receive annual leave and submit leave requests through the HR system.

Suppose we split the text into very small chunks:

- `Employees receive annual leave`
- `and submit leave requests`
- `through the HR system`

Small chunks can be useful for matching a specific question. However, a small chunk may not contain enough surrounding information to provide a complete answer.

For example, the question "How do employees request annual leave?" may match the second child chunk. Returning only that small chunk could omit useful context from the rest of the sentence.

Parent-Child Retrieval addresses this by separating two responsibilities:

- **Child chunks:** small pieces used for searching.
- **Parent chunks:** larger pieces returned as context after a child matches.

The goal is to search precisely while returning more surrounding context.

---

## 4. How Parent-Child Retrieval works

The pipeline is:

1. Split the input text into parent chunks.
2. Split each parent into smaller child chunks.
3. Assign parent and child identifiers derived from the supplied source and their positions.
4. Store parent text and metadata in the parent store.
5. Have the caller generate embeddings for child chunks. An embedding is a numeric vector used to compare text meaning.
6. Store child embeddings and their parent IDs in Chroma.
7. Embed the user's question.
8. Retrieve the most similar child chunks.
9. Read the parent IDs from the retrieved children.
10. Fetch and return the corresponding parent chunks, avoiding duplicate parents.

Conceptually:

```text
                  Document text
                        |
                        v
                  Parent chunker
                        |
              +---------+---------+
              |                   |
              v                   v
          Parent chunks       Child chunks
              |                   |
              v                   v
       JSON parent store    Child embeddings
                                  |
                                  v
                           Chroma vector store

User question
      |
      v
Question embedding
      |
      v
Search child vectors
      |
      v
Retrieve matching child chunks
      |
      v
Extract parent IDs
      |
      v
Fetch unique parent chunks
      |
      v
Return parent context
```

**Key idea:** Search using smaller chunks, but return the larger parent context associated with the matching children. The caller performs indexing (chunking, embedding children, and writing both stores); `ParentChildRetrievalService` handles question-time retrieval only. It returns context and does not generate an answer.

### Project file responsibilities

Paths below are relative to the Level 3 directory.

| File | Responsibility |
|---|---|
| [parent_child_chunker.py](../services/parent_child_chunker.py) | Build parent/child records; reuse Level 2's word-overlap function for children |
| [parent_child_store.py](../services/parent_child_store.py) | Resolve a parent ID to its JSON-backed record |
| [child_vector_store.py](../services/child_vector_store.py) | Store child vectors and return matching child records |
| [parent_child_retrieval.py](../services/parent_child_retrieval.py) | Connect question embedding, child search, deduplication, and parent lookup |
| [run_parent_child_chunker.py](../scripts/run_parent_child_chunker.py) | Print a small chunking example; not a retrieval-quality evaluation |

The sections below trace those responsibilities in order.

---

## 5. Component 1 — Parent-child chunking

**File:** `services/parent_child_chunker.py`

### Why do we need it?

The public function is `build_parent_child_chunks(text, source, page_number=1, parent_chunk_size=8, child_chunk_size=3, child_chunk_overlap=1)`. It returns a dictionary with `parents` and `children` lists.

The chunker creates parent chunks first, then creates child chunks separately inside each parent. It splits on whitespace and rejoins words with single spaces, so original line breaks and spacing are not preserved. Parent windows advance by `parent_chunk_size`: parents do not overlap. Children use the [Level 2 overlap chunker](../../level-2-practical-rag/services/overlap_chunker.py), advancing by `child_chunk_size - child_chunk_overlap` inside each parent.

For example, consider:

```text
one two three four five six seven eight
```

With `parent_chunk_size=8`, the text produces one parent:

```text
one two three four five six seven eight
```

With `child_chunk_size=3` and `child_chunk_overlap=1`, the children are:

```text
one two three
three four five
five six seven
seven eight
```

The overlap preserves some neighboring words between child chunks. It does not mean the children are separate parents.

### What do the parameters mean?

| Parameter | Default | Meaning |
|---|---|---|
| `text` | Required | Input string to split |
| `source` | Required | Caller-supplied identifier used in metadata and IDs |
| `page_number` | `1` | Same page label copied to every resulting parent and child |
| `parent_chunk_size` | `8` | Maximum words in one parent |
| `child_chunk_size` | `3` | Maximum words in one child |
| `child_chunk_overlap` | `1` | Words repeated between adjacent children within a parent |

This implementation measures chunk sizes using whitespace-separated words, not characters or tokenizer tokens.

Use integer sizes with `parent_chunk_size > 0`, `0 < child_chunk_size <= parent_chunk_size`, and `0 <= child_chunk_overlap < child_chunk_size`. Violating these bounds raises `ValueError`. This is not comprehensive type validation. After stripping the text, empty text or a falsy `source` returns `{"parents": [], "children": []}` before size validation; `source` is still a required function argument.

The last parent or child can be shorter. For example, appending `nine ten` to the eight-word example creates a second parent containing only `nine ten`, with one child of the same text. A child never crosses a parent boundary, and overlap does not carry into the next parent. This can still separate related information. `page_number` is a label supplied by the caller; the function does not detect pages or sentence boundaries.

### How are parent and child IDs related?

An example parent record is:

```python
{
    "parent_id": "handbook.pdf_parent_0",
    "text": "one two three four five six seven eight",
    "source": "handbook.pdf",
    "page_number": 1,
}
```

A child record is:

```python
{
    "child_id": "handbook.pdf_parent_0_child_0",
    "parent_id": "handbook.pdf_parent_0",
    "text": "one two three",
    "source": "handbook.pdf",
    "page_number": 1,
}
```

The child's `parent_id` links it to its parent. The retrieval service uses this relationship to find the larger context.

Parent IDs follow `{source}_parent_{index}`, with the index starting at zero on every function call. Child IDs follow `{parent_id}_child_{child_index}`, restarting within each parent. Neither the page number nor a content hash is included.

Stable source identifiers matter when reindexing the same content, but source stability alone does not prevent collisions. Calling the chunker separately for two pages with the same `source` repeats parent IDs even if `page_number` differs. The caller must use distinct source identifiers for independently chunked inputs, or process them as one input with an appropriate metadata strategy. Reusing an ID replaces its stored record; changing chunk sizes also changes which text occupies each ID. There is no automatic stale-record cleanup when a new version has fewer chunks.

---

## 6. Component 2 — ParentChildStore

**File:** `services/parent_child_store.py`

### Why do we need it?

The parent store saves larger chunks separately from the vector index.

`ParentChildStore(storage_path="data/parents.json")` creates the containing directory and loads an existing JSON file into memory, or starts with an empty dictionary. Relative storage paths resolve from the process's current working directory, not automatically from the Level 3 folder.

The JSON format is an object keyed by parent ID, with each value holding the full parent record:

```json
{
  "handbook.pdf_parent_0": {
    "parent_id": "handbook.pdf_parent_0",
    "text": "one two three four five six seven eight",
    "source": "handbook.pdf",
    "page_number": 1
  }
}
```

The store supports:

- `store_parent(parent)`: save or update a parent record.
- `get_parent(parent_id)`: retrieve a parent by ID.
- Persistence: load previously saved parents when the store is initialized again.

A child record contains a `parent_id`, not a full copy of the parent text. The parent store uses that ID to return the complete parent record when needed.

`store_parent()` requires a truthy `parent_id`, otherwise it raises `ValueError`. It replaces any existing record under that ID, rewrites the entire JSON dictionary immediately, and returns `None`. It does not validate the other fields. `get_parent()` returns the stored dictionary, or `None` for an unknown ID; it does not reread the file on each lookup.

This is a simple learning implementation. There is no file locking, atomic replacement, or transaction linking parent and child writes. Malformed JSON and file-access errors are not handled by a recovery layer. The in-memory dictionary and full-file writes are unsuitable for assuming safe concurrent updates or large-scale storage.

---

## 7. Component 3 — ChildVectorStore

**File:** `services/child_vector_store.py`

### Why do we need it?

The vector store indexes the child chunks so that semantic search can find the most relevant smaller pieces of text.

It stores:

- Child IDs.
- Child text.
- Metadata containing the parent ID, source, and page number.
- Embeddings supplied explicitly by the caller, normally using an embedding service.

`ChildVectorStore(persist_directory="data/parent_child_chroma", collection_name="parent_child_children")` uses Chroma's `PersistentClient`, so child vectors persist locally across instances using the same path and collection. As with parent storage, relative paths depend on the current working directory.

The constructor requests cosine distance when creating the collection. Cosine distance compares vector direction; smaller distances indicate closer vectors. Unlike Level 2's vector-store wrapper, this wrapper does not check the metric of an already-existing collection. Use a collection created with the intended configuration.

Its main operations are:

- `store_children(children, embeddings)`: store child records and their embeddings.
- `get_child_by_id(child_id)`: retrieve a child by its ID.
- `search(query_embedding, top_k)`: return matching children, including metadata and distances.

For nonempty child input, the number of children and embeddings must match or `store_children()` raises `ValueError`. Empty child input returns immediately, before this check. The method uses Chroma `upsert`: insert new IDs or update existing IDs. It does not delete obsolete children or check that parents exist. Both storage methods (`store_parent` and `store_children`) return `None`.

`child_id` is stored as the Chroma record ID, child `text` as its document, and `parent_id`, `source`, and `page_number` as metadata. `get_child_by_id()` returns `None` when absent; otherwise its result has this shape:

```python
{
    "child_id": "handbook.pdf_parent_0_child_0",
    "text": "one two three",
    "metadata": {
        "parent_id": "handbook.pdf_parent_0",
        "source": "handbook.pdf",
        "page_number": 1,
    },
}
```

`search(query_embedding, top_k=2)` returns a list of these dictionaries with an additional numeric `distance` field. No particular distance is guaranteed for real text. It returns `[]` for an empty collection; otherwise it requests `min(top_k, collection.count())` children and flattens Chroma's first query-result list, preserving its order. Supply a positive integer `top_k`; the wrapper has no explicit validation for invalid values.

Required record keys are accessed directly, and vector validity/dimensions are left to Chroma. There is no metadata-filter parameter in this wrapper's search API.

The vector store does not generate embeddings itself. This keeps embedding generation separate from storage. The caller must use compatible embeddings for child text and questions: the same model and preprocessing, with matching vector dimensions. Matching dimensions alone do not establish semantic compatibility.

---

## 8. Component 4 — ParentChildRetrievalService

**File:** `services/parent_child_retrieval.py`

This service coordinates retrieval through `ParentChildRetrievalService(embedding_service, child_vector_store, parent_store)`. Its public method is `retrieve(question, top_k=2)`. The embedding dependency must provide `embed_text(question)`; generating child embeddings is the indexing caller's responsibility.

### Step 1 — Embed the question

The service calls `embed_text(question)` to convert the user's question into a vector.

### Step 2 — Search child chunks

It sends the query embedding and `top_k` to the child vector store.

The vector store returns the most similar child chunks.

### Step 3 — Read each child's parent ID

Each child contains metadata with a `parent_id`.

For example:

```text
Child A -> handbook.pdf_parent_0
Child B -> handbook.pdf_parent_0
Child C -> handbook.pdf_parent_1
```

### Step 4 — Avoid duplicate parents

If Child A and Child B belong to the same parent, the service returns that parent only once.

A set tracks parent IDs that have already been processed.

### Step 5 — Fetch parent context

For each previously unseen parent ID, the service calls `get_parent(parent_id)`.

If a parent record is missing, the service skips it silently. Its ID has already been added to the seen set, so another child with that same ID does not cause another lookup during this call. This tolerates missing records but can hide an indexing inconsistency.

Missing parent *records* differ from missing child *metadata*: accessing `child["metadata"]["parent_id"]` directly means malformed child records can raise `KeyError`. Embedding, Chroma, and storage exceptions are not caught here.

The final result is a list of the stored parent dictionaries, normally containing `parent_id`, `text`, `source`, and `page_number`. Parents follow the first occurrence of each ID in the child ranking. There is no independent parent score, reranking, child-distance aggregation, or added matched-child field.

### Important: What does `top_k` mean here?

`top_k` limits the number of child results requested from vector search. It does not guarantee the same number of returned parents.

For example, if three retrieved children all belong to one parent, the service may return only one parent.

The returned parent list can also be shorter when a parent record is missing. The service does not fetch extra children to fill a target parent count. Increasing child `top_k` may expose more parents, but it does not guarantee more useful context or enforce a context-token budget.

---

## 9. Follow one complete example

Suppose a document is split into these parent records:

```text
Parent 0: Employees receive annual leave and submit leave requests.
Parent 1: Requests are reviewed by the HR team.
```

The child vector store contains smaller pieces of those parent chunks, each linked to its parent ID.

A user asks:

> How do employees request annual leave?

Imagine vector search returns two children that both belong to Parent 0.

The retrieval service:

1. Reads the parent ID from the first child.
2. Fetches Parent 0.
3. Reads the parent ID from the second child.
4. Recognizes that Parent 0 has already been returned.
5. Returns Parent 0 only once.

This example illustrates the data flow. Actual retrieval quality depends on the embedding model, indexed content, chunking choices, and query.

---

## 10. Runnable examples

From the repository root, with the project's dependencies available through `uv`, run the existing chunking demonstration:

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run python levels/level-3-advanced-rag/scripts/run_parent_child_chunker.py
```

It calls `build_parent_child_chunks()` with the eight-word example in Section 5 and prints one parent and four children, including their IDs and metadata. It does not write either store or perform semantic search.

For an executable example of the complete pipeline, run the existing integration test:

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run pytest levels/level-3-advanced-rag/tests/test_parent_child_integration.py -q
```

Read [the integration test](../tests/test_parent_child_integration.py) alongside its output: it chunks the annual-leave sentence, stores parents in temporary JSON, supplies fake child embeddings to temporary Chroma, and retrieves the parent through the public service. No embedding-model download, API key, or paid embedding call is needed by these examples. Dependency installation may require network access if the environment has not been prepared. This test is a pipeline demonstration, not a real semantic-search example.

---

## 11. Component 5 — Tests

The tests use controlled inputs and temporary storage to check the implementation.

### [Chunker tests](../tests/test_parent_child_chunker.py)

Verify parent and child creation, IDs and relationships, overlap, empty input, and invalid parameters.

### [Parent store tests](../tests/test_parent_child_store.py)

Verify saving and retrieving parents, unknown IDs, and persistence after reinitialization.

### [Child vector store tests](../tests/test_child_vector_store.py)

Verify storing and fetching a child, returning parent metadata from search, and empty-child storage followed by empty search. These tests use real temporary Chroma storage with supplied numeric vectors. They do not currently test mismatched embedding counts or unknown-child lookup.

### [Retrieval service tests](../tests/test_parent_child_retrieval.py)

Verify that parent context is returned, duplicate parent IDs are removed, and empty child results return an empty list.

### Integration test

`tests/test_parent_child_integration.py` connects the chunker, JSON parent store, Chroma child store, embedding fake, and retrieval service.

The integration test uses real temporary JSON and Chroma storage, but its fake embedding service returns the identical vector `[1.0, 0.0, 0.0]` for every child and question. The input fits in one parent. Therefore, any matching child leads to the same parent: the test cannot demonstrate meaningful semantic ranking or selection among different parents.

The focused component tests and this integration test verify different scopes: individual behavior versus the connections between components. Current tests do not cover missing-parent skipping, ID collisions across chunker calls, replacement of duplicate parent IDs, malformed storage, or concurrent writes. Those behaviors and risks above were identified from source inspection, not claimed as tested guarantees.

A passing integration test confirms the tested data flow. It does not by itself establish production readiness or prove that semantic retrieval is accurate for real questions.

### Run the tests

From the repository root:

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run pytest levels/level-3-advanced-rag/tests -q
```

The full Level 3 suite passed **41 tests** during this documentation review (2026-10-17). Rerun the suite after code changes and use the actual output as the source of truth.

---

## 12. Limitations and next steps

The current implementation is a learning POC. Important limitations include:

- Parent chunks are created using word counts rather than document structure or token-aware boundaries.
- The parent store uses a local JSON file, and child vectors use a separate local persistent Chroma collection. There is no transaction across the two stores, so interrupted indexing can leave unmatched records.
- The integration test uses fake embeddings, so it does not evaluate real semantic similarity.
- Retrieval quality has not yet been established through a labeled parent-child evaluation dataset.
- The implementation returns unique parents in the order their children are retrieved; it does not independently rerank parent documents.
- Stable source identifiers must also distinguish independently chunked inputs. IDs restart on each call and omit page numbers; reindexing has no stale-record deletion.
- Several top-ranked children can belong to one parent, reducing context diversity. Missing parents are silently skipped, with no fallback search.
- Returned parents have no context-token limit. Larger context may include irrelevant text and use more of the answer model's input budget.
- The service does not generate answers, filter by metadata, or combine this strategy with Multi-Query Retrieval.

There is no dedicated Parent-Child retrieval-quality evaluation script or recorded benchmark in this level yet. `run_parent_child_chunker.py` is a chunking demo, and the Multi-Query evaluation measures a different implementation.

Possible next steps:

1. Compare child-only and parent-child context on the same labeled questions using a real embedding model. Record child `top_k`, unique parents, and total returned context size, so larger context does not hide an unfair comparison.
2. Measure whether the required evidence appears and inspect contexts that are too broad or too narrow; evaluate answer quality separately if generation is added.
3. Add coverage for missing parents, ID collisions, and update behavior before changing storage.
4. Explore document-aware boundaries, consistent parent/child updates, and a context budget as separate improvements. These are future work, not current capabilities.

Do not assume that returning larger chunks automatically improves answer quality. Evaluate the trade-off between context completeness, irrelevant text, and the model's context-window budget.

---

## 13. Quick revision checklist

Before considering this topic complete, I should be able to explain:

- [ ] Why small chunks can lose useful context.
- [ ] The difference between a parent chunk and a child chunk.
- [ ] Why children are indexed while parents are stored separately.
- [ ] How `parent_id` connects each child to its parent.
- [ ] What `parent_chunk_size`, `child_chunk_size`, and `child_chunk_overlap` control.
- [ ] How child vector search leads to parent retrieval.
- [ ] Why multiple matching children can produce fewer unique parents.
- [ ] What the integration test verifies.
- [ ] Why passing tests do not prove semantic retrieval quality.
- [ ] Why calling the chunker twice with the same source can overwrite records.
- [ ] Which component generates embeddings and which only stores them.
- [ ] What happens when a parent record is missing.
- [ ] Why identical test vectors cannot demonstrate semantic retrieval quality.
- [ ] What limitations remain in the current POC.

If I can explain each point in my own words, I understand the implementation rather than merely recognizing the code.

---

## Final takeaway

Parent-Child Retrieval searches small child chunks to find relevant evidence, then returns the larger parent chunks linked to those matches.

The engineering lesson is to separate search granularity from context granularity, keep each component's responsibility clear, and evaluate whether the extra complexity improves retrieval for real questions.