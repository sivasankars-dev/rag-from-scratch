# Grounding Controls

## 1. Goal

Grounding controls help reduce unsupported answers in a Retrieval-Augmented Generation (RAG) application.

In this implementation, we use two controls:

1. **Prompt-level grounding:** Instruct the LLM to answer using only the retrieved context and avoid inventing facts.
2. **Service-level grounding:** If the retrieved context is empty or contains only whitespace, return a fallback answer without calling the LLM.

These controls reduce the chance of unsupported answers, but they do not guarantee that every generated answer is factually correct.

## 2. Why Do We Need Grounding Controls?

A RAG application retrieves relevant document chunks and sends their content to an LLM.

However, an LLM may produce unsupported information even when context is provided. Also, retrieval may return no documents relevant to the user's question.

Without grounding controls, the application might call the LLM with empty context or allow it to answer using information outside the retrieved documents.

Our implementation addresses the empty-context case at the service level and gives the LLM explicit grounding instructions in the prompt.

## 3. Components

### 3.1 ContextBuilder

File: `services/context_builder.py`

`ContextBuilder` converts Chroma query results into a single context string.

The current implementation expects the result to contain a `documents` key with one query group containing document strings.

Expected input examples:

```python
{
    "documents": [
        [
            "Employees receive 20 days of annual leave.",
            "Leave requests require manager approval.",
        ]
    ]
}
```

When no documents are retrieved:

```python
{"documents": [[]]}
```

Because this implementation performs a single query, it uses `results["documents"][0]` to access the first query's documents. It joins those documents using two newline characters.

If the documents list is empty, joining it returns an empty string (`""`).

**Input contract and limitations**

- The builder expects the `documents` key to exist.
- The outer `documents` list must contain at least one query group.
- The first query group is expected to contain strings.
- Missing keys, an empty outer list, or invalid values may raise exceptions such as `KeyError`, `IndexError`, or `TypeError`.
- If multiple query groups are supplied, only the first group is used.

These are limitations of the current input contract. The current single-query Chroma flow provides the expected structure, so this learning project does not add a separate result-normalization layer.


### 3.2 Grounded prompt builder

File: `services/grounded_prompt_builder.py`

Function: `build_grounded_prompt(question, context)`

This function builds a prompt containing:

- An instruction to answer using only the provided context.
- An instruction to say "not enough information" when the context does not contain sufficient information.
- An instruction not to invent facts or use unsupported information.
- The context.
- The user's question.

The function only builds the prompt. It does not call the LLM or decide what fallback answer the application should return.

### 3.3 GroundedRAGService

File: `services/grounded_rag_service.py`

`GroundedRAGService` connects context building, prompt construction, and LLM generation.

Its `answer(question, results)` method follows this flow:

1. Build a context string from the retrieval results.
2. Check whether the context is empty or contains only whitespace.
3. If the context is empty, return the fallback answer immediately.
4. Otherwise, build the grounded prompt.
5. Send the prompt to the LLM service.
6. Return the LLM's generated answer.

The fallback answer is:

```text
I don't have enough information to answer that question.
```

The service checks `context.strip()` so that whitespace-only context is treated as empty.

## 4. Request Flow

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
        |      Return fallback answer
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
              Return LLM answer
```

## 5. Why Check Context Before Calling the LLM?

Calling an LLM when no useful context was retrieved can encourage unsupported answers and unnecessarily use API resources.

The service-level check provides a predictable response when the context is empty.

This check does not establish that a non-empty context contains enough information to answer every question. When context exists but is insufficient, the prompt instructs the LLM to say "not enough information." That behaviour depends on the model following the instruction.

## 6. Tests

The following commands should be run from the `levels/level-2-practical-rag` directory.

### 6.1 Context builder tests

File: `tests/test_context_builder.py`

The tests verify:

- Multiple retrieved documents are joined with two newline characters.
- Empty retrieved documents produce an empty string.

### 6.2 Grounded prompt builder tests

File: `tests/test_grounded_prompt_builder.py`

The tests verify:

- The prompt contains the question and context.
- The prompt instructs the LLM not to invent facts or use unsupported information.
- The prompt instructs the LLM to say "not enough information" when the context is insufficient.

These tests verify the generated prompt text. They do not verify whether a real LLM will always follow the instructions.

### 6.3 Grounded RAG service tests

File: `tests/test_grounded_rag_service.py`

The tests verify:

- Empty context returns the fallback answer without calling the LLM.
- Available context and the question are included in the prompt sent to the LLM.
- The LLM's response is returned by the service.
- Whitespace-only context returns the fallback answer without calling the LLM.
- The actual `ContextBuilder` and `GroundedRAGService` work together for empty and whitespace-only retrieved documents.

The tests use a fake LLM service. They do not require a real OpenAI API call or API key.

### Run the focused tests

```bash
PYTHONPATH=. uv run pytest tests/test_context_builder.py tests/test_grounded_prompt_builder.py tests/test_grounded_rag_service.py -q
```

### Run the full Level 2 test suite

```bash
PYTHONPATH=. uv run pytest -q
```

The full suite passed with **127 tests** before the additional integration tests were added. Rerun the full suite to obtain the current total.


## 7. Limitations and Future Improvements

This implementation is a learning-focused grounding control, not a complete production hallucination-prevention system.

Current limitations:

- The prompt relies on the LLM following the grounding instructions.
- A non-empty context may still be irrelevant or insufficient for the question.
- The service does not independently verify whether the generated answer is supported by the retrieved documents.
- The service accepts Chroma's query-result structure directly through `results`; it is designed for the current single-query retrieval flow.
- The fallback is triggered by empty or whitespace-only context, not by semantic relevance or retrieval confidence.

Possible future improvements include:

- Detecting insufficient evidence even when context is non-empty.
- Verifying generated claims against retrieved evidence.
- Adding source citations to answers.
- Testing model behaviour with insufficient or conflicting context.
- Integrating retrieval, context building, and answer generation into a complete application flow.



