# Step 11 — LLM Usage & Cost Monitoring

> This chapter records its original learning checkpoint. The retrieval-to-generation connection described here as future work is now implemented in [Step 12 — RAG Orchestration and Integration](12-rag-orchestration.md). `/chat` and source/citation responses remain unimplemented.

## What are we learning, and why?

A generated answer has a resource cost. Tokens are the pieces of text processed by the model; they are not the same as words or Python characters. Longer input and output generally mean more billable work.

This step reads the provider's token counters, puts them into a small Python object, and calculates an estimate using a local price table. It prints the information to the terminal. It does not store billing records in a database.

## Simple analogy

Think of an LLM response as a receipt: input tokens describe material supplied, output tokens describe generated work, and cache details show which input work was reused or prepared for reuse. Different categories can have different prices, so one total token count is not enough to calculate cost.

## Current flow

```text
Prompt → OpenAI Responses API → response
                                  ├── output_text → returned to caller
                                  └── usage → LLMUsage
                                                ↓
                                          CostCalculator
                                                ↓
                                      cost + usage printed
```

---

## 1. Token categories

| Field in our object | Meaning |
| --- | --- |
| `input_tokens` | Total input tokens reported for the request, including cached input |
| `cached_input_tokens` | Input tokens reused from the provider's prompt cache |
| `cache_write_tokens` | Input tokens written into the provider's prompt cache, reported as cache-write usage for pricing and observability |
| `output_tokens` | Generated tokens reported by the API; may include reasoning tokens, not only visible answer text |
| `total_tokens` | Combined input and output usage reported by the API |

Cache-write tokens are already part of `input_tokens`, not an additional token count to add on top. The cache-write counter helps track cache activity and its pricing. Likewise, cached input tokens are included in input usage; do not add either cache counter again to `input_tokens + output_tokens`. The application copies the provider's `total_tokens`; it does not calculate or validate that total itself.

Cached input means reuse of input processing. It does not mean that an old final answer is simply returned. Cache writes prepare input for possible future reuse; they are different from cache reads. See the [official prompt caching guide](https://developers.openai.com/api/docs/guides/prompt-caching).

## 2. What LLMUsage represents

[`app/schemas/llm_usage.py`](../app/schemas/llm_usage.py) defines a dataclass:

```python
@dataclass
class LLMUsage:
    provider: str
    model: str
    input_tokens: int
    cached_input_tokens: int
    cache_write_tokens: int
    output_tokens: int
    total_tokens: int
```

A dataclass groups related values under named fields. Unlike the Step 9 Pydantic request model, this class does not enforce token ranges or validate field types at runtime.

`LLMService.generate()` copies these values from the actual API response:

```text
provider = "openai"
model = the selected model
input_tokens = response.usage.input_tokens
cached_input_tokens = response.usage.input_tokens_details.cached_tokens
cache_write_tokens = response.usage.input_tokens_details.cache_write_tokens
output_tokens = response.usage.output_tokens
total_tokens = response.usage.total_tokens
```

The installed OpenAI SDK 3.19.2 defines both cache detail fields. The service accesses them directly; it does not implement fallbacks for missing usage. It also does not retain the separate reasoning-token breakdown.

## 3. How CostCalculator works

[`app/services/cost_calculator.py`](../app/services/cost_calculator.py) has one model entry:

```python
PRICING = {
    "gpt-5.6-luna": {
        "input": 0.20,
        "cached_input": 0.02,
        "output": 1.20,
    },
}
```

These values are USD per one million tokens. They match the model's published standard text rates checked for this checkpoint. They are hardcoded, not fetched or updated automatically. Pricing is model-specific and can change. See the [official GPT-5.6 Luna model page](https://developers.openai.com/api/docs/models/gpt-5.6-luna).

The actual method signature is:

```python
def calculate(self, usage: LLMUsage):
```

The current calculation is:

```text
uncached_input = input_tokens - cached_input_tokens

input_cost        = uncached_input      / 1,000,000 × 0.20
cached_input_cost = cached_input_tokens / 1,000,000 × 0.02
output_cost       = output_tokens       / 1,000,000 × 1.20

total_cost = input_cost + cached_input_cost + output_cost
```

It returns a dictionary with `model`, `input_cost`, `cached_input_cost`, `output_cost`, and `total_cost`. It uses Python floating-point arithmetic. The provider field and total token count do not select prices or affect the calculation. An unknown model raises `KeyError`; there is no fallback price.

### Important estimate limitation: cache writes

`cache_write_tokens` is captured but **not used by CostCalculator**. There is no cache-write rate or cost component in its returned dictionary.

The official GPT-5.6 Luna page lists cache writes at **1.25 times the uncached input rate**. The current calculator treats input not read from cache at the ordinary input rate, so it does not account for that write premium. It also does not handle the model's special long-input pricing. This is a learning estimate, not an exact provider invoice. These limitations were documented without changing the code. [Official model pricing](https://developers.openai.com/api/docs/models/gpt-5.6-luna)

## 4. The numeric example available in the repository

[`scripts/run_cost_calculator_build_demo.py`](../scripts/run_cost_calculator_build_demo.py) contains these example inputs:

```text
model: gpt-5.6-luna
input_tokens: 1957
cached_input_tokens: 1954
output_tokens: 18
```

They are visible example values, but there is no saved API response proving their origin or linking them to a particular caching run. Cache-write and total-token values are not supplied by that script.

Using these numbers in the current calculator's formula gives:

| Component | Calculation | USD estimate |
| --- | --- | --- |
| Uncached input | `(1957 - 1954) / 1,000,000 × 0.20` | `0.00000060` |
| Cached input | `1954 / 1,000,000 × 0.02` | `0.00003908` |
| Output | `18 / 1,000,000 × 1.20` | `0.00002160` |
| Total | Sum of the three components | `0.00006128` |

This is reproducible arithmetic from the supplied example, **not a new live API measurement**. A local check using an `LLMUsage` object confirmed the calculation. The calculator ignores cache-write and total-token fields, so the example cannot establish the full provider charge.

### Visible script mismatch

The demonstration still calls:

```python
calculator.calculate(model=..., input_tokens=..., cached_input_tokens=..., output_tokens=...)
```

But the method now accepts one `LLMUsage` object. Running the local script during documentation produced:

```text
TypeError: CostCalculator.calculate() got an unexpected keyword argument 'model'
```

This issue is still present; it was not fixed during documentation. `LLMService` already passes an `LLMUsage` object correctly. The new files have no committed history yet, so we cannot establish when the interface changed or invent a history of resolved errors.

## 5. Prompt caching experiment

[`scripts/run_llm_cache_test.py`](../scripts/run_llm_cache_test.py):

1. Loads environment variables with `load_dotenv()`.
2. Constructs an `LLMService`.
3. Repeats a handwritten company-policy block **20 times**.
4. Builds a prompt asking how many annual-leave days employees receive.
5. Calls `generate(prompt)` once and prints the returned answer.

The text includes annual leave, sick leave, parental leave, carry-forward and work-from-home sections. It is a synthetic experiment fixture, not extracted PDF text or retrieved chunks. Its work-from-home paragraph must not be treated as content found in the earlier sample PDF.

```bash
.venv/bin/python -m scripts.run_llm_cache_test
```

This command makes a paid network request. Repeating it with the same prompt lets you inspect the printed usage for cache reuse. Repetition within a single prompt is not proof of a cache hit; the relevant evidence is the provider's `cached_tokens` field across requests. The script makes only one call per run and has no automatic comparison, timing measurement or saved result file.

**What the repository demonstrates:** a repeatable long-prompt experiment and extraction of cache counters. It does not preserve a before/after transcript proving a particular cache-hit rate, cost saving or latency improvement. No such outcome is invented here, and no live calls were made for this checkpoint.

## 6. Why cached input can cost less

For the local rates, reading cached input costs less per token than processing uncached input. Reusing a matching prompt prefix can therefore reduce the input portion of an estimate. Output still has its own cost, and writing the cache can also cost money. Matching content and provider caching behavior matter; a repeated request is not a promise of a cache hit. See the [prompt caching guide](https://developers.openai.com/api/docs/guides/prompt-caching).

This is provider-side prompt caching. The application has not built a response cache, cache database, explicit cache breakpoints or cache-management API.

## 7. Why we have not added database persistence yet

We intentionally keep this learning checkpoint focused on reading usage and understanding arithmetic before designing storage. The current code creates objects in memory and prints them. It does not insert usage rows, retain per-user history, or aggregate daily spend.

The existing Chroma database stores retrieval chunks; it is not being used as a billing database. Keeping cost storage for later avoids mixing a new persistence design into the token-accounting lesson.

Possible later development could preserve request IDs, timestamps, model/pricing versions, token counts and estimated costs, then compare aggregates with provider billing and add monitoring. Those are future ideas, not current features. First, the estimate would need to account for all applicable pricing categories, including cache writes.

## Common mistakes

* Counting cached input twice instead of recognizing it as part of total input.
* Treating tokens as words or characters.
* Pricing every token with the same rate.
* Assuming captured cache-write usage is already included correctly in the estimate.
* Calling example token values a verified caching benchmark without a response log.
* Treating console output as durable monitoring or a billing ledger.

## Interview questions

1. **Why track input and output separately?** They represent different work and have different rates.
2. **Why subtract cached input before pricing ordinary input?** Cached tokens are already inside the input count; they receive their own rate.
3. **Is a cache write the same as a cache hit?** No. One stores input for reuse; the other reuses it.
4. **Is this calculator an exact billing system?** No. It has static rates and omits cache-write pricing and other pricing variants.
5. **What did the experiment establish?** The code can submit a stable long prompt and expose cache usage, but saved comparative measurements are unavailable.
6. **Why no usage database yet?** The current lesson isolates usage extraction and cost estimation; storage and aggregation come later.

## What I learned and current completion

Implemented/documented: the `LLMUsage` dataclass, provider usage extraction, a simple cost estimate, console reporting and a prompt-cache experiment script. The outdated standalone cost script and estimate limitations remain visible and unfixed.

Not implemented: durable usage storage, production observability, exact billing reconciliation, or integration of retrieved chunks with generation.

Next implementation step: **Context Building / passing retrieved context to the LLM**. ContextBuilder, `/chat` and generated-answer sources/citations remain future work.
