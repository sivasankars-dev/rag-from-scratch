# Query Rewriting

## 1. Overview

Query rewriting is a retrieval improvement technique that transforms a user's original query into a clearer, more retrieval-friendly query before sending it to the retrieval pipeline.

The goal is **not to answer the user's question**.

The goal is to preserve the user's intent while making the query easier for the retrieval system to understand and match against stored documents.

Example:

```text
Supplied conversation context:
The user is asking about annual leave.

Original query:
How many days can I take?

Rewritten query:
How many days of annual leave am I entitled to take per year?
```

The rewritten query provides more context for semantic and keyword-based retrieval.

This document focuses only on the query rewriting technique and its implementation in Level 2.

---

## 2. Why Query Rewriting Is Needed

Users do not always write queries in a form that is ideal for retrieval.

A user may use:

- Short questions
- Ambiguous wording
- Pronouns
- Conversational language
- Follow-up questions that depend on previous context

For example:

```text
User:
What is the annual leave policy?

User:
How many days can I take?
```

The second query is understandable to a human because it depends on the previous conversation.

However, a retrieval system receiving only:

```text
How many days can I take?
```

may not have enough information to identify that the user is asking about annual leave.

Query rewriting can transform it into:

```text
How many annual leave days can an employee take?
```

This gives the retrieval system a more explicit query.

---

## 3. Query Rewriting vs Query Expansion

These techniques are related but different.

### Query Rewriting

Rewriting aims to make the original query clearer while preserving its intent.

```text
Supplied conversation context:
The user is asking about annual leave.

Original:
How many days can I take?

Rewritten:
How many annual leave days can an employee take?
```

The original query is replaced by a clearer representation.

### Query Expansion

Expansion keeps the original concept and adds related terms.

For example:

```text
Original:
annual leave policy

Expanded:
annual leave policy vacation PTO paid time off employee leave
```

The goal is to increase the chance of matching relevant terms.

### Summary

| Technique | Main purpose |
|---|---|
| Query rewriting | Make the query clearer |
| Query expansion | Add related terms |
| Query rewriting | Usually produces one improved query |
| Query expansion | May produce additional terms or queries |

Our current implementation focuses on **query rewriting**.

---

## 4. When Query Rewriting Helps

Query rewriting is especially useful for:

### Ambiguous queries

```text
How many days can I take?
```

The topic is unclear without context.

### Conversational follow-up queries

```text
User:
Tell me about parental leave.

User:
What about the eligibility?
```

The second query depends on the previous conversation.

### Very short queries

```text
What about eligibility?
```

A rewritten query can make the missing subject explicit when the conversation provides enough information.

---

## 5. When Query Rewriting May Not Be Necessary

Not every query needs rewriting.

For example:

```text
What is the annual leave policy for full-time employees?
```

This query is already specific and retrieval-friendly.

Rewriting every query introduces additional:

- LLM latency
- API cost
- External API dependency

Therefore, in a production system, query rewriting should be treated as a retrieval optimization rather than a mandatory step for every query.

A future production implementation could decide whether rewriting is necessary before making an LLM call.

---

## 6. Conversational Context

Query rewriting can optionally use `conversation_context` supplied by the caller. The rewriter does not collect conversation history or maintain conversational state itself.

Example:

```text
Conversation context:
User is asking about annual leave.

Current query:
How many days can I take?
```

The rewriter can produce:

```text
How many days of annual leave am I entitled to take per year?
```

Without context, the system should not invent the missing topic.

For example, if the user only says:

```text
How many days can I take?
```

and there is no context explaining what "days" refers to, the system should not arbitrarily assume annual leave. The prompt asks the model to preserve intent and avoid inventing information, but those instructions are not guarantees.

---

## 7. Query Rewriting Prompt

The current implementation creates a prompt with explicit rules.

The prompt instructs the LLM to:

- Preserve the user's original intent.
- Use conversation context when it helps clarify the query.
- Do not answer the user's question.
- Do not invent missing information.
- Return only the rewritten query.

The prompt contains:

```text
Conversation context:
<context>

Current query:
<query>
```

This separates the previous context from the current user query.

---

## 8. Current Architecture

The current implementation separates query rewriting from the LLM client.

```text
rewrite_query()
      |
      v
build_rewrite_prompt()
      |
      v
llm_client.generate()
      |
      v
rewritten query
```

The responsibilities are intentionally separated.

### `rewrite_query()`

Responsible for orchestrating the rewriting operation.

### `build_rewrite_prompt()`

Responsible for creating the prompt sent to the LLM.

### `OpenAILLMClient`

Responsible for communicating with the OpenAI API.

This separation makes the query rewriting logic easier to test and change.

---

## 9. Query Rewriter Implementation

The current implementation is:

```python
def rewrite_query(query, conversation_context=None, llm_client=None):
    if llm_client is None:
        return query.strip()

    prompt = build_rewrite_prompt(
        query,
        conversation_context,
    )

    rewritten_query = llm_client.generate(prompt)

    return rewritten_query.strip()
```

There are two important paths.

### Without an LLM client

```python
rewrite_query("  What is the annual leave policy?  ")
```

returns:

```text
What is the annual leave policy?
```

This path returns only the stripped original query and ignores `conversation_context`, even if supplied. It requires no external API.

### With an LLM client

```python
rewrite_query(
    query,
    conversation_context,
    llm_client,
)
```

The function:

1. Builds the rewriting prompt.
2. Sends the prompt to the injected LLM client.
3. Receives the rewritten query.
4. Removes surrounding whitespace.
5. Returns the rewritten query.

This path does not fall back to the original query if the call fails or returns an empty response. Client exceptions propagate, and an empty or whitespace-only response becomes `""` after stripping.

---

## 10. Prompt Builder

The prompt builder is implemented separately:

```python
def build_rewrite_prompt(query, conversation_context=None):
    context = conversation_context or "None"

    return f"""
You are a query rewriting assistant.

Your task is to rewrite the user's query
into a clear, retrieval-friendly query.

Rules:
- Preserve the user's original intent.
- Use conversation context when it helps clarify the query.
- Do not answer the user's question.
- Do not invent missing information.
- Return only the rewritten query.

Conversation context:
{context}

Current query:
{query}
""".strip()
```

Keeping prompt construction in a separate function makes it easier to test the prompt independently.

---

## 11. LLM Client

The project uses a small wrapper around the OpenAI client.

```python
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()


class OpenAILLMClient:
    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY")

        if not api_key:
            raise ValueError("OPENAI_API_KEY is not set")

        self.client = OpenAI(api_key=api_key)

    def generate(self, prompt):
        response = self.client.responses.create(
            model="gpt-5-mini",
            input=prompt,
        )

        return response.output_text
```

`load_dotenv()` runs at module level when `llm_client.py` is imported, before the constructor calls `os.getenv("OPENAI_API_KEY")`. It discovers a `.env` file and loads its values into the environment when available. By default, it does not override environment variables that are already set.

A `.env` file is not mandatory if `OPENAI_API_KEY` is already set in the environment. The constructor raises `ValueError` if the resulting key is missing or empty.

The API key itself is never hard-coded in the source code.

---

## 12. Why the LLM Client Is Injected

The query rewriter accepts an `llm_client` argument:

```python
rewrite_query(
    query,
    conversation_context,
    llm_client,
)
```

This is dependency injection.

The query rewriter does not directly create an OpenAI client.

Instead, the caller provides an object that implements:

```python
generate(prompt)
```

This makes the component easier to test and allows the underlying LLM implementation to be changed later.

For example:

```text
Query Rewriter
      |
      +---- OpenAILLMClient
      |
      +---- FakeLLM (tests)
      |
      +---- Another LLM client (future)
```

---

## 13. Unit Testing

The query rewriter is tested without making real API calls.

A fake LLM client is used:

```python
class FakeLLM:
    def __init__(self, response):
        self.response = response
        self.received_prompt = None

    def generate(self, prompt):
        self.received_prompt = prompt
        return self.response
```

The fake client allows the test to control the LLM response.

For example:

```python
llm = FakeLLM(
    "How many annual leave days can an employee take?"
)
```

The test can then verify that the query rewriter returns that response.

---

## 14. Testing the Prompt

The fake client also stores the prompt it receives:

```python
self.received_prompt = prompt
```

This allows tests to verify that the query and caller-supplied conversation context were passed to the fake client, without sending them to a real LLM.

For example:

```python
assert "How many days can I take?" in llm.received_prompt

assert "User is asking about annual leave." in llm.received_prompt
```

This is not conversation memory. The production rewriter also relies on the caller to supply context; it does not collect history or maintain conversation state.

`received_prompt` is simply an attribute on the fake client used by the test to inspect the input passed to `generate()`.

---

## 15. Testing the OpenAI Client

The OpenAI client is also tested without making an actual network request.

A fake response object can simulate:

```python
response.output_text
```

This verifies that:

```text
generate()
    ↓
Fake response
    ↓
output_text
```

is handled correctly.

`FakeLLM` and `FakeResponses` verify application logic without making a real OpenAI request. The client tests cover missing-key rejection, response-text handling, and composition with the query rewriter. They do not verify real authentication, network behavior, exact API arguments, or real-model rewrite quality. Real API verification is separate from these mocked tests.

---

## 16. Real API Verification

During development, a real API call was manually observed with the following supplied context, query, and response. This is a developer-reported observation, not a result captured by the automated tests:

```text
Supplied conversation context:
The user is asking about annual leave.

Original query:
How many days can I take?

Rewritten query:
How many days of annual leave am I entitled to take per year?
```

This manual observation demonstrated a successful call through the query rewriting component at that time. Source code establishes the request path, and mocked tests establish application behavior; neither independently establishes this observed API result.

The exact rewritten wording may vary between model responses. The intended behavior is that the rewrite:

- Aims to preserve the user's intent.
- Adds useful context when available.
- Does not answer the question.
- Does not invent unsupported information.

---

## 17. Latency Consideration

During development, the real API request was manually observed to take approximately a few seconds. This is a rough observation, not an automated timing measurement or a latency guarantee; the tests do not capture it.

This is expected because the request involves:

```text
Application
    ↓
Network request
    ↓
LLM processing
    ↓
Network response
    ↓
Application
```

Therefore, query rewriting introduces additional latency compared with directly performing retrieval.

This is an important production consideration.

A production system should consider whether the query actually needs rewriting before making an LLM call.

---

## 18. Current Request Flow

The query rewriting component currently works independently:

```text
User Query
    |
    v
Query Rewriter
    |
    v
Rewritten Query
```

It is **not yet connected to the project's retrieval pipeline**.

The current implementation therefore demonstrates the query rewriting component itself rather than the complete end-to-end RAG flow.

---

## 19. Future Retrieval Integration

The intended practical RAG flow is:

```text
User Query
    |
    v
Query Rewriting
    |
    v
Hybrid Search
    |
    v
Candidate Chunks
    |
    v
Reranking
    |
    v
Top Relevant Chunks
    |
    v
LLM Answer Generation
```

For example:

```text
Supplied conversation context:
The user is asking about annual leave.

User:
How many days can I take?

        ↓ Query Rewriting

How many days of annual leave am I entitled to take per year?

        ↓ Hybrid Search

Relevant chunks

        ↓ Reranking

Best matching chunks

        ↓

Answer generation
```

This integration will be implemented separately from the current query rewriting component.

---

## 20. Current Limitations

The current implementation is intentionally simple.

### No rewrite decision layer

Every query that receives an LLM client is sent to the LLM for rewriting.

There is currently no classifier or rule that decides:

```text
Rewrite required?
    Yes → LLM
    No  → use original query
```

### No query quality validation

The implementation does not currently verify whether the rewritten query is actually better than the original query. Prompt instructions are not guarantees: an LLM rewrite can change intent or hurt retrieval.

The no-client path returns the stripped original query and ignores context. With a client, there is no application-level fallback on failure or empty output: exceptions propagate and blank responses return an empty string, as described in Section 9.

### No retrieval evaluation

We have not yet measured whether query rewriting improves:

- Hit Rate@K
- MRR@K
- Other retrieval metrics

This will be addressed in the retrieval evaluation phase.

### No end-to-end integration

The rewritten query is not yet automatically passed into the existing hybrid-search and reranking components.

---

## 21. Key Takeaways

Query rewriting:

- Transforms a user query into a retrieval-friendly query.
- Aims to preserve the original intent.
- Can use conversation context.
- Should not answer the user's question.
- Should not invent missing information.
- Can improve retrieval for ambiguous or conversational queries.
- Adds LLM latency and API cost.
- Should not necessarily be applied to every query.

The current implementation uses dependency injection so that the query rewriter can be tested independently from the real LLM API.

---

## 22. Verification Status

Automated tests verify application behavior using fake LLM/API responses:

```text
✓ Query rewriting logic tests
✓ Prompt construction tests
✓ Fake LLM tests
✓ Mocked LLM client tests
✓ Fake response handling tests
✓ Query/context propagation tests
```

These tests make no real OpenAI request and do not verify authentication, network behavior, exact API arguments, or real-model rewrite quality. Separately, a successful real API response and approximate latency were observed manually during development, as described in Sections 16–17; those observations are not captured by the automated tests.

The next step is to connect query rewriting with the existing retrieval workflow and later evaluate whether the rewritten queries actually improve retrieval quality.