# Step 10 — LLM Generation

## What are we learning, and why?

Steps 1–9 let us retrieve document chunks. Retrieval answers “Which passages look related to this question?” It does not compose a readable answer from those passages.

An LLM (large language model) generates text from instructions and input. It does not automatically know about passages retrieved by our application. It can use those passages only when the application explicitly includes them in the model input/context. Step 10 implements and tests the generation building block separately; connecting retrieved chunks to it is the next implementation task.

## Simple analogy

Retrieval is a librarian finding relevant pages. Generation is a writer using supplied material to explain something. We now have both building blocks, but we have not yet built the handoff from the librarian to the writer.

## Current flow and the missing connection

The intended RAG flow is:

```text
User Question → Embedding → Chroma Retrieval → Retrieved Chunks
                                                       ↓
                         Context Building / passing chunks (NEXT)
                                                       ↓
                                                      LLM
```

What actually runs today:

```text
POST /retrieve → embedding → Chroma → retrieved chunks → JSON

Separate generation script:
Manually supplied prompt → LLMService → OpenAI Responses API
                                     → usage/cost printed
                                     → generated text returned
```

`POST /retrieve` has not been changed to call the LLM. The caching experiment supplies handwritten policy text; it does not retrieve that text from Chroma.

---

## 1. The LLMService

[`app/services/llm_service.py`](../app/services/llm_service.py) imports `OpenAI`, `LLMUsage` and `CostCalculator`.

The generation portion is:

```python
class LLMService:
    def __init__(self):
        self.client = OpenAI()

    def generate(self, prompt):
        model = "gpt-5.6-luna"
        response = self.client.responses.create(model=model, input=prompt)
        # The current code also extracts usage and prints estimated cost.
        return response.output_text
```

This is a shortened walkthrough, not a replacement implementation. The full method builds an `LLMUsage` object, calculates cost, and prints both before returning the text. [Step 11](11-llm-usage-and-cost-monitoring.md) explains that part.

Step by step:

1. Construct the OpenAI SDK client once per `LLMService` instance.
2. Receive a prompt string in `generate(prompt)`.
3. Select the hardcoded model `gpt-5.6-luna`.
4. Make a synchronous Responses API request.
5. Read usage information and calculate the local estimate.
6. Return generated text to the caller.

The method returns a string, not a dictionary containing answer, usage and cost. If request processing or usage/cost extraction raises an exception, the method does not reach its text return. There is no application-specific exception handling here.

## 2. Why `input=prompt`?

`prompt` is our Python variable. `input` is the Responses API argument that carries the text to the model. A plain string is supported, so this exercise does not need to build a list of message objects.

```python
self.client.responses.create(model=model, input=prompt)
```

Naming a local variable `prompt` does not mean the API argument should also be named `prompt`. The call follows the Responses API's text-input interface. See the [official text generation guide](https://developers.openai.com/api/docs/guides/text).

## 3. Why `response.output_text`?

The response contains more than an answer: it includes output items and usage information. The Python SDK's `output_text` convenience property combines text from output-text content into a string. It avoids manually walking the output list for this simple text example. It can be empty when there is no output text; it is not a guarantee of a useful answer. The installed SDK defines this property, consistent with the [text generation guide](https://developers.openai.com/api/docs/guides/text).

The text is newly generated. It is not necessarily a quotation, a verified fact, or an answer grounded in our PDF. The service only knows the prompt it is given.

## 4. Environment and API key

`pyproject.toml` now declares `openai>=3.19.2`; the inspected environment has OpenAI SDK 3.19.2. The generation scripts call `load_dotenv()` before constructing `LLMService`. `OpenAI()` reads `OPENAI_API_KEY` from the environment by default.

At a high level:

1. Make an API key available through `OPENAI_API_KEY`, either in the shell environment or a local `.env` file.
2. Run the script from the repository root using `.venv`.
3. Keep the real key out of code and Git; `.env` is already ignored.

The service itself does not call `load_dotenv()`. That setup is currently in the scripts. Unlike local Sentence Transformer embeddings, these generation calls need network access, API access and incur usage charges. No keys were read or live API calls made during this documentation pass.

## 5. The basic generation test

[`scripts/test_llm.py`](../scripts/test_llm.py) runs:

```python
llm = LLMService()
result = llm.generate("Explain what an API is in one simple sentence.")
print(result)
```

With the environment configured:

```bash
.venv/bin/python -m scripts.test_llm
```

The service prints cost and usage; the script prints the returned text. This is a manual smoke test, not an automated assertion-based test. There is no saved answer transcript in the inspected repository, so this document does not invent one or claim a fresh live test passed.

## 6. What history and inspection establish

The new LLM files were untracked at inspection, so their earlier edits and any fixed API errors are not available in Git history. The current call correctly uses `input=prompt` and reads `response.output_text`; that does not establish which errors occurred before it was written.

One visible issue remains in the separate cost demonstration: it calls an older calculator interface. Step 11 records the observed error. No application code was changed for these notes.

## Common mistakes

* Assuming that adding an LLM service automatically connects it to retrieval.
* Treating a fluent response as proof of correctness.
* Confusing a prompt variable with an API parameter name.
* Assuming `generate()` returns usage and cost because it prints them.
* Calling a paid demonstration script as if it were a local unit test.

## Interview questions

1. **Why add an LLM after retrieval?** Retrieval selects passages; generation can turn supplied material into a readable answer.
2. **Is this already end-to-end RAG generation?** No. Retrieval and generation work as separate building blocks; the context handoff is next.
3. **What does `input=prompt` do?** It sends the prompt string as model input through the Responses API.
4. **What does `generate()` return?** The SDK's output-text string after usage/cost processing.

## What I learned

A small service makes the external model call explicit. The request, generated text, usage and estimated cost are separate parts of the response-processing flow.

## Completed and not yet implemented

Implemented: an OpenAI client wrapper, a Responses API call, text extraction, a simple generation script and the usage/cost hook documented in Step 11.

Not implemented: ContextBuilder, passing retrieved chunks into the LLM, `/chat`, generated-answer sources/citations, or an integrated RAG answer endpoint. No LangChain or LangGraph was introduced.

Next documentation chapter: [Step 11 — LLM Usage & Cost Monitoring](11-llm-usage-and-cost-monitoring.md). Next implementation step: **Context Building / passing retrieved context to the LLM**.
