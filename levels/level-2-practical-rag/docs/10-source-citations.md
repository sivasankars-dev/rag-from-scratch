# Source Citations

## 1. Goal

Source citations help users identify the retrieved document chunks associated with an answer.

This stage extends the [grounding controls](09-grounding-controls.md) with source, page, and chunk references. The service now returns a dictionary containing `answer` and `citations`, rather than only the answer string described in the earlier stage.

Citations identify retrieved source chunks. They do not independently prove that every generated claim is supported.

## 2. Why Do We Need Source Citations?

An answer alone does not tell the user where its information came from. A source reference gives the user a document name and location to inspect.

For example:

```text
Answer: Employees receive 20 days of annual leave.
Citation: Source: employee_handbook.pdf, Page: 2, Chunk: 3
```

This is an illustrative example matching the test fixtures, not a verified location in the real handbook. The reference helps a user check the passage; the application does not perform that check itself.

## 3. Components

File: [`services/source_citation.py`](../services/source_citation.py)

### 3.1 Building one citation

`build_source_citation(metadata)` formats one metadata dictionary as a string.

Required fields:

| Field | Purpose |
| --- | --- |
| `source` | Source document identifier or filename |
| `page_number` | Page recorded during document processing |
| `chunk_index` | Chunk index recorded during document processing |

Example:

```python
metadata = {
    "source": "employee_handbook.pdf",
    "page_number": 2,
    "chunk_index": 3,
}

build_source_citation(metadata)
```

Returns:

```text
Source: employee_handbook.pdf, Page: 2, Chunk: 3
```

The function uses the supplied values without renumbering them. It does not open the document or validate field types or locations. Missing required fields raise `KeyError` because the function accesses each field directly.

### 3.2 Building multiple citations

`build_source_citations(metadata_list)` calls the single-citation helper for every metadata entry and returns a list of strings in the same order.

An empty metadata list returns `[]`. Duplicate entries produce duplicate citations; the function does not deduplicate them.

The metadata comes from retrieval. See [Metadata Filtering](04-metadata-filtering.md) for how these fields are stored in Chroma.

## 4. GroundedRAGService Integration

File: [`services/grounded_rag_service.py`](../services/grounded_rag_service.py)

`GroundedRAGService.answer(question, results)` first builds context and checks `context.strip()`, as in the grounding-controls stage.

For nonempty context, it:

1. Builds the grounded prompt.
2. Calls `llm_service.generate(prompt)`.
3. Builds citations from `results["metadatas"][0]`.
4. Returns the answer and citation list together.

Example response:

```python
{
    "answer": "Employees receive 20 days of annual leave.",
    "citations": [
        "Source: employee_handbook.pdf, Page: 2, Chunk: 3"
    ],
}
```

Multiple retrieved metadata entries produce multiple citations. Citations are formatted by application code after generation; the LLM does not generate or select them.

### Chroma result structure

The current service expects a single-query result, with retrieved documents and metadata in their first nested lists:

```python
{
    "documents": [["Employees receive 20 days of annual leave."]],
    "metadatas": [[{
        "source": "employee_handbook.pdf",
        "page_number": 2,
        "chunk_index": 3,
    }]],
}
```

The service assumes the metadata corresponds to the retrieved documents. It does not validate their alignment or check which passages the answer actually uses.

### Empty or whitespace-only context

When the built context is empty or contains only whitespace, the service returns:

```python
{
    "answer": "I don't have enough information to answer that question.",
    "citations": [],
}
```

This return happens before calling the LLM or reading citation metadata. For this path, `{"documents": [[]]}` needs no `metadatas` key.

Nonempty but insufficient context still reaches the LLM. Even if the model says it lacks enough information, the service attaches citations for all supplied metadata entries; it does not inspect the answer to decide which citations to include.

## 5. Request Flow

```text
Retrieved Chroma results
        |
        v
ContextBuilder.build(results)
        |
        v
Check context.strip()
        |
        +---- Empty / whitespace only
        |            |
        |            v
        |      Return fallback answer + [] citations
        |      Do not call the LLM
        |
        +---- Context available
                     |
                     v
        build_grounded_prompt(question, context)
                     |
                     v
             llm_service.generate(prompt)
                     |
                     v
        build_source_citations(results["metadatas"][0])
                     |
                     v
          Return {"answer": ..., "citations": [...]}
```

The service accepts retrieval results; it does not execute retrieval itself.

## 6. Tests

Run commands from `levels/level-2-practical-rag`.

### 6.1 Citation helper tests

File: [`tests/test_source_citation.py`](../tests/test_source_citation.py)

The tests verify:

- The exact single-citation string format.
- `KeyError` when `chunk_index` is missing. Missing `source` or `page_number` also raises `KeyError` in the code, but those cases are not separately tested.
- Formatting multiple metadata entries, both through a list comprehension and through `build_source_citations()`.
- An empty metadata list returning `[]`.
- Building citations from the nested `results["metadatas"][0]` structure.

### 6.2 Grounded service tests

File: [`tests/test_grounded_rag_service.py`](../tests/test_grounded_rag_service.py)

The tests verify:

- The response dictionary contains the generated answer and one or multiple citation strings.
- Available context and the question are included in the prompt sent to the fake LLM.
- Empty and whitespace-only context returns the fallback dictionary with no citations and no LLM call.
- The real `ContextBuilder` and service work together for empty and whitespace-only document lists.

The tests use a fake LLM. They check application behavior without a real API call, and do not verify that an actual generated claim is supported by its cited passage.

### Run the focused tests

```bash
PYTHONPATH=. uv run pytest tests/test_source_citation.py tests/test_grounded_rag_service.py -q
```

### Run the full Level 2 test suite

```bash
PYTHONPATH=. uv run pytest -q
```

Run the suite to see the current total; it changes as learning stages add tests.

## 7. Limitations and Future Improvements

These are citations for retrieved chunks, not verified per-claim citations.

Current limitations:

- Retrieved chunks may not actually support the generated answer.
- Every supplied metadata entry is cited, regardless of whether the answer uses that chunk.
- References are plain strings, not clickable document links or inline claim references.
- Metadata accuracy and document/metadata alignment are assumed rather than checked.
- Missing or malformed metadata can raise an exception. On the nonempty-context path, citation building happens after generation, so the LLM may already have been called before a metadata error occurs.
- The implementation does not validate citation correctness or guarantee factual accuracy.

Later work could associate individual claims with supporting passages and verify that support. Those capabilities are not implemented in this stage.
