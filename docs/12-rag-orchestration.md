# Step 12 — RAG Orchestration and Integration

## What are we learning, and why?

Previously we had individual components for embedding, retrieval and LLM generation. We now also have context building and prompt construction. `RAGService` connects these components into one application-level workflow that accepts a question and returns generated text.

This is the basic end-to-end RAG checkpoint. It is plain Python service composition, not a new HTTP endpoint.

## Simple analogy

Think of an assistant coordinating a small team: one person finds the relevant pages, another collects their text, another prepares instructions, and a writer produces an answer. The coordinator does not redo each person's work. It calls them in the right order and passes along the results.

## End-to-end flow

Ingestion happens first using the existing ingestion script:

```text
PDF → text extraction → character chunking → embeddings → ChromaDB
```

Once the document is indexed, the answer path is:

```text
Question
   ↓
EmbeddingService
   ↓
Query Embedding
   ↓
VectorStore (Chroma search + retrieval controls)
   ↓
Retrieved Chunks
   ↓
ContextBuilder
   ↓
Context
   ↓
RAGPromptBuilder
   ↓
Prompt
   ↓
LLMService
   ↓
Answer
```

Unlike the standalone generation experiment in Step 10, this path explicitly includes retrieved document text in the model input. The LLM does not automatically read Chroma; the application supplies the context through the prompt.

---

## 1. Why RAGService exists

[`app/services/rag_service.py`](../app/services/rag_service.py) gives the workflow one entry point:

```python
answer = rag_service.answer(question)
```

Its job is orchestration: connecting the steps. Each component still performs its existing task. This preserves the small services and keeps the order of operations visible for learning.

## 2. Constructor dependencies: plain Python injection

The constructor receives five objects:

```python
class RAGService:
    def __init__(
        self,
        embedding_service,
        vector_store,
        context_builder,
        prompt_builder,
        llm_service,
    ):
        self.embedding_service = embedding_service
        self.vector_store = vector_store
        self.context_builder = context_builder
        self.prompt_builder = prompt_builder
        self.llm_service = llm_service
```

The caller creates the objects and passes them in. This is dependency injection at the plain Python level; there is no FastAPI `Depends()` involved in this step.

| Benefit | Simple explanation |
| --- | --- |
| Loose coupling | The coordinator uses each object's methods instead of constructing a particular implementation itself |
| Easier testing | A future test could supply small fake objects without calling an external API |
| Easier replacement | A component can be replaced if it provides the methods the coordinator expects |
| Clear responsibilities | Retrieval, context formatting, prompt construction and generation remain separate tasks |

These are benefits of the design, not a claim that mocked tests or alternative implementations have already been added.

## 3. What answer() does

The actual method is:

```python
def answer(self, question):
    query_embedding = self.embedding_service.embed_text(question)

    results = self.vector_store.search(
        query_embedding=query_embedding
    )

    context = self.context_builder.build(results)

    prompt = self.prompt_builder.build(
        question=question,
        context=context,
    )

    return self.llm_service.generate(prompt)
```

Step by step:

1. **Embed the question.** `embed_text(question)` creates the query vector using the Sentence Transformer service.
2. **Retrieve chunks.** The Step 8 `VectorStore.search()` queries Chroma and applies its similarity threshold.
3. **Build context.** `ContextBuilder.build(results)` combines the retrieved document strings.
4. **Build the prompt.** `RAGPromptBuilder.build(question=question, context=context)` places the question and context into instructions for the model.
5. **Generate and return text.** `LLMService.generate(prompt)` makes the existing model request and returns the generated answer string.

The coordinator supplies only `query_embedding` to search. Therefore the current store defaults apply: **Top-K 2**, **similarity threshold 0.50**, and **no source restriction**. This differs from the Step 9 API's default Top-K of 5. `answer()` does not expose retrieval settings or use the API's request validation.

## 4. ContextBuilder: documents become one string

[`app/services/context_builder.py`](../app/services/context_builder.py) takes each `result["document"]` and joins the strings with two newlines:

```python
context_parts = []
for result in results:
    context_parts.append(result["document"])
return "\n\n".join(context_parts)
```

For example, the local builder demo supplies two handwritten passages:

```text
Employees get 20 days annual leave.

Leave requests must be submitted through the HR portal.
```

Those are demonstration inputs in `scripts/run_context_builder_demo.py`, not a claim that both passages were retrieved from the sample PDF.

The builder preserves result order. It does not include metadata, distances, similarity scores or source labels. It does not remove duplicates or enforce a token budget. An empty result list produces an empty context string.

## 5. RAGPromptBuilder: context and question become model input

[`app/services/rag_prompt_builder.py`](../app/services/rag_prompt_builder.py) returns an f-string containing:

```text
Use the following context to answer the question.

CONTEXT:
{context}

QUESTION:
{question}
```

This diagram simplifies the whitespace; the actual multiline string retains its indentation. `{context}` and `{question}` are replaced with the supplied text.

The prompt asks the model to use the context. It does not implement a guarantee of grounded answers or an explicit instruction to refuse when context is insufficient. Prompt construction is now implemented, but advanced answer validation is not.

## 6. Integration script

[`scripts/run_rag_service_demo.py`](../scripts/run_rag_service_demo.py) loads `.env` before importing the services, then constructs:

```python
rag_service = RAGService(
    embedding_service=EmbeddingService(),
    vector_store=VectorStore(),
    context_builder=ContextBuilder(),
    prompt_builder=RAGPromptBuilder(),
    llm_service=LLMService(),
)
```

It asks the annual-leave question, calls `answer()`, and prints the question and answer. It uses the actual Sentence Transformer, persisted Chroma collection, builders, LLM service and OpenAI API. It is an **end-to-end integration smoke test**, not a mocked unit test. It prints results rather than asserting an expected answer.

From the repository root, after the sample is ingested and the environment/API access is configured:

```bash
uv run python -m scripts.run_rag_service_demo
```

For a fresh database, the existing ingestion command is:

```bash
uv run python -m scripts.run_ingest_document
```

The generation call consumes LLM API usage and cost. `LLMService` prints usage and its estimated cost before returning the answer. The returned value from `RAGService.answer()` is still just the answer string; there is no usage database or answer/usage response object. The cost estimate retains the limitations documented in [Step 11](11-llm-usage-and-cost-monitoring.md).

## 7. Successful happy-path verification

The developer reported successfully running the integration command with this output:

```text
Question:
How many annual leave days do I get?

Answer:
You get 20 days of annual leave per year.
```

The run also displayed LLM usage and cost information. No exact token/cost figures were supplied for this run, so none are invented here.

This verifies the happy path for one question and the indexed sample document. It does not prove that every possible question works, that every answer is supported, or that future generations will use identical wording. The paid integration script was not rerun for this documentation-only update.

## 8. Tokenizer warning and environment configuration

The reported run showed a Hugging Face tokenizer warning about forking after tokenizer parallelism had been used. Tokenizers disables parallelism in that situation to reduce the risk of deadlocks. The reported answer still completed; this warning was not a RAG failure. See the [Hugging Face discussion of the warning](https://github.com/huggingface/transformers/issues/5486).

The intended explicit setting in the local `.env` file is:

```dotenv
TOKENIZERS_PARALLELISM=false
```

Set it before tokenizer work begins. The integration script calls `load_dotenv()` before importing the services. This setting controls tokenizer parallelism, not the correctness of retrieval or generation. An existing shell environment value can take precedence over `.env` with the default `load_dotenv()` behavior.

The real `OPENAI_API_KEY` belongs in the local environment, not in documentation or Git. `.env` remains ignored and untracked; it was not changed during this update.

## 9. Current limits

* **No `/chat` endpoint.** The new workflow runs through a Python script. The existing `/retrieve` endpoint still returns retrieval results.
* **No source/citation response.** Metadata exists in retrieval, but ContextBuilder includes only text and `answer()` returns only a string.
* **No empty-context stop.** If retrieval returns `[]`, the coordinator still builds a prompt with empty context and calls the LLM. It does not guarantee a no-answer response.
* **No new input/error policy.** `answer()` does not strip or validate the question, catch component errors, or expose retrieval settings.
* **Simple character chunking remains.** There is no advanced chunking, context token budgeting, hybrid search, reranking or query rewriting.
* **No RAG evaluation or automated assertions for this new orchestration.** Earlier automated tests remain in `tests/`, and the new builder scripts are manual demos. This checkpoint adds the real-service integration smoke test, not a broader regression/evaluation suite.
* **No Dockerization, production deployment or agentic RAG.** No LangChain/LangGraph or new production architecture is introduced.
* **No usage/cost persistence.** Usage and estimates are still printed, not stored in a database.

## Interview questions

1. **What is orchestration here?** Calling the existing components in order and passing each output to the next component.
2. **Why inject dependencies into the constructor?** It keeps component construction outside the coordinator and makes replacement/testing easier.
3. **How does the LLM see the retrieved chunks?** ContextBuilder joins their text and RAGPromptBuilder includes that context in the model input.
4. **Why call this an integration smoke test?** It exercises real components and the external API, but has no assertions and covers one happy-path question.
5. **Does a successful answer establish general RAG quality?** No. It shows this path worked for the reported example; broader behavior is not established.

## What I learned and completion

The basic RAG chain now connects retrieval to generation explicitly. `RAGService` coordinates the work without taking over each component's responsibility.

Step 12 is complete as a basic integration checkpoint. The limitations above remain visible and intentional for this stage; no later feature was implemented during documentation.

## Next step

Continue with [Step 13 — Better Chunking](13-better-chunking.md) to learn sentence grouping and sentence overlap. Its separate `BetterChunker` class is implemented and tested; the ingestion script and upload route still use Step 3's character chunker. The workflow described above therefore remains accurate.
