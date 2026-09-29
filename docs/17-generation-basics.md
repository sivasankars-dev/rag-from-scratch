# Step 17 — Generation Basics

## 1. Introduction to Generation in RAG

[Step 16](16-retrieval-failure-cases.md) explained that finding a useful passage does not guarantee a supported answer. Generation is the next part: the LLM produces an answer using the question, instructions, and information supplied to it.

This is a conceptual Level 1 chapter. It adds no implementation. Company-policy examples and token counts below are hypothetical teaching examples, not new measurements or changes to our PDF.

---

## 2. Basic RAG Generation Flow

```text
User Question → Retrieval → Retrieved Chunks
                                    ↓
                         Context → Prompt → LLM → Answer
```

Retrieval finds candidate passages. Context construction prepares information for the LLM. Prompt construction combines that information with instructions and the question. The LLM then generates text.

Retrieval can return irrelevant or incomplete passages. The answer still needs to be checked.

---

## 3. Retrieved Context

Keep these two terms separate:

| Term | Meaning in this chapter |
| --- | --- |
| Retrieved chunks | Results returned by retrieval, before context construction |
| Context | The supporting information actually provided to the LLM |

Suppose retrieval returns annual-leave, sick-leave, and parking chunks. If only the annual-leave passage is included in the prompt, that passage is the supplied context. The other retrieved chunks are not available to the LLM through that prompt.

In our current [Step 12 workflow](12-rag-orchestration.md), `ContextBuilder` joins all returned document strings in their existing order. It does not independently select, reorder, or check them. The selection and ordering discussed below are conceptual decisions, not new project features.

---

## 4. Context Quality vs Quantity

For the question “How many annual leave days do I get?”, compare:

| Context | What it provides |
| --- | --- |
| “Employees are entitled to annual leave.” | Relevant, but missing the number of days |
| “Employees receive 20 days of annual leave per year.” | Enough information for this simple entitlement question |
| Annual leave plus many unrelated travel and parking rules | More text, but potentially distracting information |

Too little context can omit an answer or an important condition. Sufficient, relevant context gives the LLM the evidence needed to answer the question. Too much irrelevant context consumes space and can introduce unrelated numbers or rules.

**More context != better context.** One relevant chunk is not always enough, and increasing `top_k` does not always improve the answer. We need the information required for the question, including any applicable conditions.

---

## 5. Context Window

The model's **context window** is its limit on the tokens it can handle in a request, including input and generated output according to that model's rules. It is measured in tokens, not chunks. Separate output limits can also apply.

### Tokenization vs chunking

- **Chunking** divides a document into passages for storage and retrieval.
- **Tokenization** converts text into model input pieces. A token may represent a word, part of a word, or punctuation.

A chunk can contain many tokens. Equal numbers of chunks do not imply equal token counts. Characters and tokens are not interchangeable either.

### A simple budget example

Imagine a model with a total window of 4,000 tokens:

| Item | Hypothetical tokens |
| --- | ---: |
| Instructions, question, and message formatting | 400 |
| Retrieved context included in the prompt | 2,600 |
| Space reserved for the answer | 1,000 |
| Total | 4,000 |

Retrieved context uses only part of the budget. Instructions, the question, any conversation history, and the answer need space too. These numbers illustrate budgeting; they are not the limits of our configured model or a budget enforced by our code.

### Context overflow

If we include 3,300 context tokens instead, the planned total becomes `400 + 3,300 + 1,000 = 4,700`, exceeding this hypothetical limit.

Depending on the service and settings, an oversized request may be rejected or text may be truncated. Do not assume the model sees everything. The input must fit while leaving enough room for the answer; silently dropping a policy condition can change its meaning.

---

## 6. Context Ordering

After retrieval, two separate decisions remain:

- **Selection:** which passages should be included?
- **Ordering:** in what sequence should those passages appear?

For example, if one passage gives the leave entitlement and another explains eligibility, their order in the supplied context should make the relationship between those facts clear.

Similarity order does not necessarily match document order or the clearest explanation order. There is no single order that guarantees a better answer. Select and order deliberately, preserve meaning, and evaluate the result.

Advanced re-ranking is a later Level 2 topic. No re-ranking or new context-ordering logic is implemented here.

---

## 7. Prompt Structure

A basic RAG prompt has three useful parts:

| Part | Purpose |
| --- | --- |
| Instructions | Tell the LLM what task to perform and how to use the evidence |
| Retrieved context | Supply information that may support the answer |
| User question | State what needs answering |

A conceptual prompt could look like this:

```text
INSTRUCTIONS:
Answer using the supplied context. If it does not establish the answer,
say what information is missing.

CONTEXT:
Employees receive 20 days of annual leave per year.

QUESTION:
How many annual leave days do employees receive per year?
```

The instructions describe the task, the context provides the fact, and the question identifies the requested detail. Retrieved text should be treated as evidence, not as instructions that override the task.

Our existing prompt already includes an instruction, context, and question. The explicit insufficient-evidence instruction above is a teaching example, not a change to that implementation. Prompting can guide behavior, but cannot eliminate hallucination by itself.

---

## 8. Grounded Generation

A **grounded answer** is supported by the supplied context. It can rephrase text or combine facts from several chunks, provided it preserves their meaning and conditions.

Suppose the context includes:

- “Employees receive 20 days of annual leave per year.”
- “Employees receive 12 days of sick leave per year.”

For “What are the annual and sick leave allowances?”, a supported answer is:

> Employees receive 20 days of annual leave and 12 days of sick leave per year.

The LLM does not need to copy the passages word for word. It must not invent a carry-forward allowance or remove an eligibility condition that the evidence contains.

Grounding is about support from the supplied information. It does not independently establish that a source policy is current or accurate.

---

## 9. Insufficient Context

Relevant context and sufficient context are different:

| Situation | Example for an annual-leave question | Expected behavior |
| --- | --- | --- |
| No relevant context | Only a parking policy is supplied | Explain that the supplied information does not establish the answer |
| Relevant but incomplete context | Annual leave is mentioned, but its allowance is missing | Identify the missing detail instead of guessing |
| Relevant and complete context | The allowance and applicable conditions are supplied | Answer using that evidence and preserve the conditions |

“Complete” means sufficient for this question, not the entire document.

Suppose the context says employees with one year of service receive 20 days. A user asks about six months of service. That passage is relevant, but it does not establish whether the six-month allowance is zero, ten, twenty, or something else.

A grounded response would say that the provided information does not specify the six-month case. If useful, the system can ask for clarification or the missing policy. This is desired behavior; our current workflow does not enforce it automatically.

---

## 10. Hallucination in RAG

In this chapter, **hallucination** means generated content that is unsupported by, or contradicts, the supplied evidence while being presented as factual.

```text
Context: Employees receive 20 days of annual leave per year.
Question: How many annual leave days do employees receive?
Answer: Employees receive 25 days.
```

The answer contradicts the context. Even if retrieval found the right passage, generation failed to stay grounded.

Unsupported generation can also add a rule that the context never mentions. RAG gives the model evidence to work with; it does not guarantee hallucination-free answers.

---

## 11. Temperature

Temperature is a generation parameter that changes how strongly the model favors higher-probability token choices during sampling.

| Setting | Typical effect |
| --- | --- |
| Lower temperature | Favors higher-probability choices more strongly; usually produces less variation |
| Higher temperature | Allows more variation and randomness; can produce more creative wording |

Lower temperature makes generation more deterministic in the everyday sense of being less variable. It does not necessarily guarantee identical output across repeated requests.

**Low temperature does not mean truth. It does not guarantee factual correctness or eliminate hallucination.** A model can repeatedly produce the same unsupported answer.

Temperature controls generation variability; it is not a grounding mechanism. Evidence, instructions, and evaluation still matter. Parameter support varies by model, and our current `LLMService` does not explicitly set temperature. This chapter adds no temperature configuration.

---

## 12. Retrieval Failure vs Generation/Grounding Failure

| Situation | Interpretation |
| --- | --- |
| Required evidence exists in the indexed material but is not retrieved | Retrieval failure |
| Required evidence is retrieved but omitted during context construction | Context-construction failure |
| Required evidence reaches the LLM, but it gives an unsupported answer | Generation/grounding failure |
| Context is relevant but incomplete, and the LLM correctly explains the limitation | Correct behavior under insufficient evidence |

If the policy does not contain the needed information at all, retrieval cannot create it. Missing evidence is not always a search failure.

Inspect both the retrieved chunks and the context actually sent to the LLM. A passage appearing in search results does not help generation if it never reaches the prompt.

---

## 13. Complete Basic RAG Generation Flow

```text
User Question
    ↓
Retrieval
    ↓
Retrieved Chunks (may include irrelevant or incomplete passages)
    ↓
Relevant Chunks (identified for the question; sufficiency still matters)
    ↓
Context Selection
    ↓
Context Ordering
    ↓
Prompt Construction
    ↓
LLM
    ↓
Grounded Answer (the goal, not a guarantee)
    ↓
Evaluation
```

This is a conceptual workflow. “Relevant Chunks” represents a decision about which retrieved results are useful for the question; it is not a separate implemented component in the current project. The project does not automatically verify relevance or sufficiency at this stage. Its context construction joins the returned texts in their existing order.

Evaluation checks whether retrieval found useful evidence and whether the final answer is supported and addresses the question. These are separate checks. Step 14 currently implements retrieval metrics only; final answer evaluation is not yet implemented. The final evaluation box describes review, not an automatic runtime stage already present in our service.

---

## 14. Interview Framing

### How does a basic RAG system generate an answer?

> “The system retrieves candidate passages for a question, prepares the selected information as context, and places it in a prompt with instructions and the question. The LLM generates an answer that should be supported by that context. We need enough relevant evidence within the token budget, and we evaluate the result because retrieval and prompting do not guarantee correctness.”

### How do retrieval and generation failures differ?

> “Retrieval fails when it misses the available information needed for the question. Generation fails when the needed information reaches the LLM but the answer is unsupported or wrong. If the evidence is incomplete and the model clearly says so, that can be correct behavior under insufficient evidence.”

### What should I remember?

- Retrieved chunks are search results; context is the supporting information actually supplied to the LLM.
- More chunks do not necessarily provide better evidence.
- Context windows count tokens, not chunks.
- Relevant information can still be incomplete.
- Low temperature reduces variation, not the need to check facts.
- Grounding and answer quality must be evaluated; RAG does not guarantee them.
