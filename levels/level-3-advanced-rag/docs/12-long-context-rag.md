# Long Context RAG

## 1. Objective

Traditional RAG retrieves relevant documents and passes them to an LLM as context.

However, retrieval may return:
- Duplicate documents.
- Empty or invalid document text.
- More documents than the model can process efficiently.
- Documents that exceed the application's context budget.

Long Context RAG in this project focuses on building a bounded context from retrieved documents.

The implementation:
1. Receives retrieved documents.
2. Removes empty and duplicate document text.
3. Adds source and page information to each document.
4. Selects documents within a configurable token budget.
5. Builds a grounded prompt using the selected context.
6. Generates an answer and returns citations for included documents.
7. Reports context-building statistics.

**Implementation scope:** This is a token-budgeted context-building and question-answering service. It is not a complete production deployment or a benchmark proving that long-context models outperform ordinary RAG.

## 2. Architecture

```text
User question
     |
     v
Embedding Service
     |
     v
Retrieval Adapter
     |
     v
Retrieved documents
     |
     v
Long Context Builder
     |
     +--> Skip empty documents
     +--> Remove duplicate document text
     +--> Add source/page information
     +--> Enforce context token budget
     |
     v
Selected context
     |
     v
Grounded prompt builder
     |
     v
LLM Service
     |
     v
Answer + citations + statistics
```

## 3. Components

### 3.1 Long Context Builder

**File:** `services/long_context_builder.py`

`LongContextBuilder` constructs a context from retrieved document records.

Its main responsibilities are:

- Reject invalid token-budget configuration.
- Ignore empty or non-string document content.
- Remove duplicate document text.
- Include source and page information when available.
- Check the token count before accepting each document.
- Skip documents that exceed the remaining budget.
- Continue checking later documents when an earlier document does not fit.

The builder returns a `ContextBuildResult` containing:

| Field | Meaning |
|---|---|
| `context` | Final formatted context |
| `included_documents` | Number of included documents |
| `skipped_documents` | Number of skipped records |
| `estimated_words` | Word count of included document text |
| `estimated_tokens` | Token count of the final formatted context |

The skipped count includes invalid, duplicate and over-budget records.

#### Token counting

The default token counter uses `tiktoken` with the `gpt-5-mini` encoding:

```python
@staticmethod
@lru_cache(maxsize=1)
def _get_encoding():
    return tiktoken.encoding_for_model("gpt-5-mini")


@classmethod
def _count_tokens(cls, text: str) -> int:
    encoding = cls._get_encoding()
    return len(encoding.encode(text))
```

The builder also accepts an injectable `token_counter`. This makes deterministic unit tests possible without depending on a specific tokenizer for every test.

**Important:** Token counts depend on the tokenizer and the exact text being counted. The default counter is intended to estimate context tokens using the selected model's encoding.

### 3.2 Context token budget

**File:** `services/long_context_builder.py`

The default configuration is:

```python
LongContextBuilder(max_tokens=4000)
```

For each candidate document, the builder formats the document with its source/page citation and counts the tokens in the resulting context.

A document is included only when the complete candidate context remains within `max_tokens`.

For example, if the budget is 100 tokens and the current context uses 75 tokens, a candidate that would increase the context to 110 tokens is skipped.

The builder does not truncate documents. It skips a document that does not fit and continues checking subsequent candidates.

This preserves document content but means that an oversized document may be excluded even if part of it would have been useful.

### 3.3 Long Context RAG Service

**File:** `services/long_context_rag_service.py`

`LongContextRAGService` coordinates the complete in-process answering flow:

1. Validate the question.
2. Generate a query embedding.
3. Retrieve candidate documents using `RetrievalAdapter`.
4. Build a token-bounded context.
5. Return a fallback response if no usable context remains.
6. Build a grounded prompt.
7. Call the LLM service.
8. Return the answer, citations and context statistics.

The service accepts these dependencies:

- `embedding_service`
- `retrieval_adapter`
- `context_builder`
- `llm_service`

Dependencies are injected rather than constructed inside the service. This makes the implementation easier to test and allows different implementations to be supplied.

The `top_k` parameter controls the maximum number of documents requested from retrieval. It is separate from the context token budget.

### 3.4 Grounded prompt

The service instructs the LLM to:

- Answer using only the supplied context.
- State when the context does not contain enough information.
- Avoid inventing unsupported facts.

Prompt instructions can encourage grounded answers, but they cannot guarantee that a model will never produce an incorrect statement.

### 3.5 Citations

The service returns citations for documents included in the final context.

Each citation contains:

```python
{
    "source": "employee_handbook.pdf",
    "page_number": 3,
}
```

The page number is `None` when the retrieved document has no page metadata.

Duplicate citation references are removed.

**Important:** Citations identify the source documents included in the context. They do not independently prove that every statement in the generated answer is supported by that source.

### 3.6 Response statistics

The service returns:

| Field | Meaning |
|---|---|
| `answer` | Generated answer or fallback message |
| `citations` | Citations for included documents |
| `retrieved_documents` | Number of records returned by retrieval |
| `included_documents` | Number of records included in the context |
| `skipped_documents` | Number of records excluded by the builder |
| `estimated_tokens` | Estimated token count of the formatted context |

The token statistic measures the context only. It does not include the prompt instructions, question or generated answer.

## 4. Prerequisites

Run commands from the repository root.

Ensure that:

- Project dependencies are installed.
- The Python environment is available through `uv run`.
- `tiktoken` is installed.
- The LLM service has valid credentials if using the real OpenAI client.
- The selected retrieval implementation and its underlying vector store are configured if using real retrieval.

Unit tests use fake dependencies, so they do not require paid LLM calls.

## 5. Using the Context Builder

The builder accepts a list of document records:

```python
documents = [
    {
        "document": "Remote work requires manager approval.",
        "metadata": {
            "source": "employee_handbook.pdf",
            "page_number": 3,
        },
    },
    {
        "document": "Employees must follow the security policy.",
        "metadata": {
            "source": "employee_handbook.pdf",
            "page_number": 5,
        },
    },
]
```

Build a bounded context:

```python
from services.long_context_builder import LongContextBuilder

builder = LongContextBuilder(max_tokens=4000)
result = builder.build(documents)

print(result.context)
print("Included:", result.included_documents)
print("Skipped:", result.skipped_documents)
print("Estimated tokens:", result.estimated_tokens)
```

The formatted context includes source and page information, allowing the LLM to see where the supplied text originated.

The actual token count depends on the formatted content and tokenizer.

## 6. Using LongContextRAGService

The service receives its dependencies through its constructor:

```python
from services.long_context_builder import LongContextBuilder
from services.long_context_rag_service import LongContextRAGService

context_builder = LongContextBuilder(max_tokens=4000)

rag_service = LongContextRAGService(
    embedding_service=embedding_service,
    retrieval_adapter=retrieval_adapter,
    context_builder=context_builder,
    llm_service=llm_service,
    top_k=5,
)

result = rag_service.answer(
    "What approval is required for remote work?"
)

print(result["answer"])
print(result["citations"])
print(result["estimated_tokens"])
```

The variables `embedding_service`, `retrieval_adapter` and `llm_service` must be configured instances supplied by the application. They are placeholders in this example, not objects created automatically by the snippet.

The service is implemented as a Python component. A CLI command or dedicated HTTP endpoint for Long Context RAG has not been added as part of this implementation.

## 7. Handling Empty Context

If retrieval returns no usable documents, the service does not call the LLM.

Instead, it returns a fallback response:

```text
I don't have enough information to answer that question.
```

The response contains an empty citation list and context statistics.

This avoids generating an answer from an empty context, but it does not establish that retrieval found every document relevant to the question.

## 8. Testing

Run the focused tests:

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run pytest \
  levels/level-3-advanced-rag/tests/test_long_context_builder.py \
  levels/level-3-advanced-rag/tests/test_long_context_rag_service.py \
  -q
```

Run the complete Level 3 test suite:

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run pytest \
  levels/level-3-advanced-rag/tests/ -q
```

The tests cover:

- Context token-budget enforcement.
- Source and page formatting.
- Empty and duplicate document handling.
- Skipping oversized documents while considering later candidates.
- Token counting.
- Question validation.
- Retrieval and dependency interactions.
- Answer generation and citation selection.
- Avoiding an LLM call when no usable context remains.

The tests use fake dependencies for predictable results and to avoid unnecessary API costs.

A passing unit-test suite verifies the tested code paths. It does not establish retrieval quality, production latency, or answer correctness on real-world questions.

## 9. Current Limitations

### 9.1 Context budget is not the full model budget

`max_tokens` applies to the formatted context only.

The full model request also contains the prompt instructions and question. The generated answer may consume additional tokens.

A production implementation should reserve tokens for all request components and the expected output, and validate the total against the selected model's context window.

### 9.2 Oversized documents are skipped, not truncated

A large but relevant document may be excluded entirely if it cannot fit in the remaining budget.

Possible alternatives include chunking, controlled truncation, summarization or a second-stage retrieval strategy.

### 9.3 Retrieval order affects document selection

The builder processes documents in the order returned by retrieval.

It does not independently rerank documents by relevance, importance or token efficiency. Consequently, early documents can consume most of the available budget.

### 9.4 Duplicate detection uses document text

Duplicate removal is based on normalized document text after stripping surrounding whitespace.

Documents with the same text but different metadata are treated as duplicates. The first occurrence is retained.

This is simple and deterministic but may discard distinct source references for identical content.

### 9.5 Token estimates are tokenizer-dependent

The default tokenizer uses the encoding associated with `gpt-5-mini`. Token counts may differ if another model or tokenizer is used.

The current implementation does not account for every model-specific request overhead.

### 9.6 Grounded generation is not guaranteed

Prompt instructions reduce the risk of unsupported answers but cannot eliminate hallucinations.

Production systems should evaluate factual correctness and citation support separately.

### 9.7 End-to-end production integration remains separate

The service coordinates embedding, retrieval, context construction and generation in Python. It does not by itself provide an HTTP endpoint, production monitoring, retries, timeouts or a complete deployment configuration.

Those concerns should be implemented and tested at the application integration layer.

## 10. Future Improvements

Potential improvements include:

- Reserve tokens for instructions, question and output.
- Validate the total request against the model's context window.
- Compare context selection strategies using labeled evaluation questions.
- Use relevance-aware selection or reranking before context construction.
- Consider truncation, chunking or summarization for oversized documents.
- Add request timeouts, retries and structured error handling.
- Add an HTTP endpoint and integration tests.
- Measure retrieval quality, answer correctness, latency and token usage.
- Evaluate citation precision and whether generated claims are supported by cited text.

## 11. Summary

This Level 3 implementation builds a bounded context from retrieved documents, generates grounded answers and returns citations and context statistics.

The central idea is to manage how much retrieved text reaches the LLM while retaining source information.

**Context selection, retrieval relevance and answer correctness are separate concerns.** Each needs its own evaluation before the system can be considered production-ready.
