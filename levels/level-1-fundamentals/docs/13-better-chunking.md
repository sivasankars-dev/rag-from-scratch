# Step 13 — Better Chunking

> Level 1 learning note: this chapter preserves its original checkpoint. Steps 1–17 are now complete; see the [learning index](../../../README.md#level-1-learning-sequence). Commands below run from the repository root and select Level 1 with `PYTHONPATH`. Shared data remains under root `data/`.

## 1. Where we are

At the end of [Step 12](12-rag-orchestration.md), our Python services could retrieve passages, collect them as context, build a prompt, and ask the LLM for an answer.

The full journey looks like this:

```text
PDF → text → chunks → embeddings → ChromaDB
                                     ↓
                                 retrieval → context → prompt → LLM → answer
```

We ingest the PDF first. Later, a question is embedded and used to retrieve stored chunks. `RAGService` coordinates the steps from the question to the answer.

[Step 3](03-chunking.md) created chunks using character windows. Step 13 introduces a separate sentence-based chunker. **The existing ingestion script and upload route still call Step 3's `chunk_text()`.** Completing this step does not change the stored Chroma chunks or automatically connect the new chunker to the answer workflow.

## 2. Why do we need better chunking?

A character window ends when its character count reaches the chosen size. That boundary can fall in the middle of a sentence:

```text
Chunk 1: Employees can take up to 20 days of annual
Chunk 2: leave every year.
```

If retrieval returns only the second piece, the reader loses the subject and the number of days. The context sent to the LLM may be less meaningful.

Character-based chunking is simple and useful for learning. It can also be adequate for some text. We now want to experiment with keeping complete sentences together where the size limit allows it.

This can preserve context, but it does not prove that retrieval or answers have improved. We will need to measure that separately.

## 3. What are we changing?

The new class is `BetterChunker` in [`levels/level-1-fundamentals/services/better_chunker.py`](../services/better_chunker.py).

It has two methods:

| Method | Job |
| --- | --- |
| `split_sentences(text)` | Turn a text string into a list of sentences |
| `build_chunks(sentences, max_chunk_size=500, overlap_sentences=0)` | Group that list into chunk strings |

We intentionally kept [`levels/level-1-fundamentals/services/chunker.py`](../services/chunker.py) unchanged. The separate implementations let us compare the two learning steps.

The caller uses the methods in order. `build_chunks()` expects the sentence list; it does not call `split_sentences()` for us.

## 4. Step 13 architecture

```text
Text
  → split into sentences
  → group sentences into chunks
  → optionally overlap sentences
  → handle oversized sentences
  → return chunks
```

This is a summary of the decisions. In the actual loop, the oversized-sentence check happens before normal grouping for each sentence.

The class returns a list of strings. It does not create embeddings, write to Chroma, retrieve passages, or call the LLM.

## 5. Sentence splitting

`split_sentences()` identifies simple sentence boundaries and keeps the ending punctuation.

Input:

```text
Python is useful. FastAPI is fast. PostgreSQL is powerful.
```

Output:

1. `Python is useful.`
2. `FastAPI is fast.`
3. `PostgreSQL is powerful.`

The current regular expression is `r"(?<=[.!?])\s+"`. In plain English, it splits at whitespace immediately after `.`, `!`, or `?`. Whitespace can include spaces or newlines. The punctuation stays with the preceding sentence.

The method trims whitespace from the outside of the input and each result. Blank input returns `[]`. Text without a matching boundary stays as one item; a final sentence does not need ending punctuation.

This is a small rule for finding sentence boundaries, not a complete understanding of written language.

## 6. Building chunks from sentences

`build_chunks()` collects complete sentences and joins them with a single space. When the size check says the next sentence will not fit, it saves the current chunk and starts another.

For example, use `max_chunk_size=9` and no overlap:

```text
Sentences: ["AAA.", "BBB.", "CCC."]

Chunk 1: "AAA. BBB."  → 9 characters
Chunk 2: "CCC."       → 4 characters
```

`AAA.` has four characters. Adding one space and `BBB.` gives nine. Adding `CCC.` would exceed the limit.

Try the two methods together from a Python session started in the repository root with `PYTHONPATH=levels/level-1-fundamentals uv run python`:

```python
from services.better_chunker import BetterChunker

chunker = BetterChunker()
sentences = chunker.split_sentences("AAA. BBB. CCC.")
chunks = chunker.build_chunks(sentences, max_chunk_size=9)
print(chunks)
# ['AAA. BBB.', 'CCC.']
```

At the end of the loop, any remaining sentences become the final chunk. An empty sentence list returns `[]` with valid settings.

One detail of the current implementation: after carrying overlap into a new chunk, its running length can count existing spaces again. This can end a chunk earlier than necessary. Treat the limit as a ceiling; the code does not promise to fill every chunk as tightly as possible.

## 7. What is max_chunk_size?

`max_chunk_size` is the maximum chunk length measured using Python's `len()` on strings. Spaces and punctuation count too. The default is **500 characters**.

For this lesson, use a positive integer. A value less than or equal to zero raises `ValueError` because a chunk needs room for text.

**Characters != tokens.** Tokens are the text pieces a model processes. Their count can differ from the number of Python string characters. Step 13 measures characters only; it does not calculate model token counts.

## 8. Sentence overlap

`overlap_sentences` controls how many sentences from the end of the previous chunk we try to repeat at the start of the next one. Its default is **0**, which means no overlap. Negative values raise `ValueError`.

With `max_chunk_size=23` and `overlap_sentences=1`:

```text
Sentences: ["Sentence A.", "Sentence B.", "Sentence C."]

Chunk 1: "Sentence A. Sentence B."
Chunk 2: "Sentence B. Sentence C."
```

Repeating Sentence B gives the second chunk some nearby context. This can help when a sentence depends on what came just before it. It also repeats text, so overlap is optional.

**Overlap must fit inside `max_chunk_size`.** The implementation checks the actual joined overlap plus the new sentence. If it does not fit, it drops that overlap and starts with the new sentence. It does not try progressively smaller amounts of overlap.

For example, with a limit of 10 and overlap of 1:

```text
Sentences: ["12345678.", "abcdefg."]

Together: 9 + 1 space + 8 = 18 characters → too large

Chunk 1: "12345678."
Chunk 2: "abcdefg."
```

The size limit takes priority over repeating a sentence.

## 9. Oversized sentences

What if one sentence is already longer than the limit? Keeping it whole would break the size rule.

The current practical fallback splits that sentence into character slices. For example, with `max_chunk_size=10`:

```text
Input item: "123456789012345"

Output pieces:
"1234567890"
"12345"
```

Before emitting these pieces, the chunker saves any sentences already collected, joining them with spaces. Each oversized piece is then emitted as its own chunk, including the short final piece.

Afterward, the chunker starts fresh. It does not carry sentence overlap across the oversized sentence or combine its last piece with the next sentence. With overlap set to 1:

```text
Input:  ["First.", "123456789012345", "Last."]
Output: ["First.", "1234567890", "12345", "Last."]
```

Character slicing can split words. For example, `Employees receive leave.` would become `Employees `, `receive le`, and `ave.` at a limit of 10. These slices keep their original characters, including a trailing space. This fallback is intentionally simple for the current learning project.

## 10. Why do we keep the old chunker?

The project grows step by step. Keeping both versions makes the change easier to understand:

| Learning step | File | Basic approach |
| --- | --- | --- |
| Step 3 | [`levels/level-1-fundamentals/services/chunker.py`](../services/chunker.py) | Character windows with character overlap |
| Step 13 | [`levels/level-1-fundamentals/services/better_chunker.py`](../services/better_chunker.py) | Sentence grouping with optional sentence overlap and an oversized-sentence fallback |

You can revisit the small Step 3 loop before studying the extra decisions in Step 13. Existing ingestion and upload behavior remains available for comparison.

## 11. Tests

The 11 automated tests live in [`levels/level-1-fundamentals/tests/test_better_chunker.py`](../tests/test_better_chunker.py). Each checks an expected result or error:

| Category | What it protects against |
| --- | --- |
| Sentence splitting | Losing or incorrectly grouping the three example sentences |
| Normal chunk building | Producing the wrong groups with the default overlap setting |
| No overlap | Repeating sentences when overlap is explicitly zero |
| Sentence overlap | Losing the intended shared sentence between neighboring chunks |
| Invalid maximum size | Accepting zero as a usable chunk size |
| Negative overlap | Accepting a negative sentence count |
| Oversized sentence | Losing preceding/following text or splitting the long item incorrectly |
| Oversized sentence with overlap | Carrying old overlap across the long sentence |
| Overlap size limit | Producing an oversized chunk when the overlap does not fit; this is `test_overlap_should_not_exceed_max_chunk_size` |
| Preserving spaces | Joining the sentences before an oversized item without a separating space |
| Oversized sentence with large overlap | Failing when overlap requests more sentences than are currently collected |

Run only these tests from the repository root:

```bash
PYTHONPATH=levels/level-1-fundamentals uv run python -m pytest levels/level-1-fundamentals/tests/test_better_chunker.py -v
```

Expected result: **11 passed**. The assertions check chunking behavior; they do not measure retrieval or answer quality.

## 12. Bugs we found during implementation

These are the three issues identified during development/review and protected by the current regression tests. A regression test checks that an old problem does not return after a later edit.

### Bug 1 — overlap could make a chunk too large

Repeating a previous sentence could push the next chunk beyond the configured limit. For example, the two items in the 10-character example above need 18 characters when joined.

The fix checks the joined overlap and new sentence before keeping them together. If they are too long, the new chunk starts with only the new sentence. `test_overlap_should_not_exceed_max_chunk_size` checks this case.

### Bug 2 — missing spaces between sentences

When saving accumulated sentences before an oversized sentence, joining without spaces could turn `AAA.` and `BBB.` into `AAA.BBB.`.

The current code uses `" ".join(current_sentences)`, preserving the separator. `test_oversized_sentence_preserves_space_before_it` expects `AAA. BBB.` before the long item's pieces.

### Bug 3 — oversized sentence + overlap edge case

The oversized-sentence path also needed to handle overlap requests larger than the number of collected sentences. The regression example has just `A.` collected, requests overlap of 2, and then encounters an 11-character item with a limit of 10.

The current code safely selects the available trailing sentences with a list slice, emits the oversized pieces, and clears the collected sentences. The result is `["A.", "1234567890", "1"]`. It neither needs two previous sentences nor carries the old sentence beyond the oversized item.

`test_oversized_sentence_with_large_overlap` checks that case. The separate overlap test with `First.` and `Last.` checks that normal processing resumes afterward.

## 13. What we intentionally did NOT solve yet

This step keeps the rules small enough to follow:

- Sentence splitting is regex-based. Abbreviations such as `Dr. Smith` and some punctuation patterns may not split as intended.
- Oversized sentences can be split in the middle of words.
- Character length is not token length.
- More advanced chunking strategies can be explored later.

These are intentionally deferred. The aim here is to understand sentence grouping, optional overlap, and a simple size fallback.

## 14. Step 13 interview explanation

> “I added a separate BetterChunker that splits text into sentences and groups them within a character limit. It can repeat sentences between chunks when they fit. If a single sentence is too long, it falls back to character slices. I kept the original chunker for comparison and added tests for normal behavior and the overlap and oversized-sentence edge cases. The new class is tested separately; the existing ingestion path still uses the original chunker.”

**Why not just split every 500 characters?**

That is simple, but it can cut a sentence in half. Grouping sentences can keep a useful statement together when it fits.

**Why use sentence overlap?**

It gives neighboring chunks some shared context. We keep it only when the resulting chunk fits the limit.

**What happens if one sentence is larger than the chunk size?**

We save the current chunk, split the long sentence into character slices, and start fresh afterward.

**Are characters and tokens the same?**

No. This implementation uses Python string length, which does not tell us the model's token count.

**Why didn't you replace the old chunker?**

Keeping both implementations helps us compare learning steps. The original still serves the existing ingestion and upload paths.

**What are the limitations?**

The sentence rule can misread punctuation or abbreviations, and oversized slices can cut words. These tests also do not establish better retrieval or answers.

## 15. Current Step 13 status

**Step 13 — Better Chunking**

**Status: COMPLETE** as a separate chunking implementation with automated tests.

| Item | Location or result |
| --- | --- |
| Implementation | [`levels/level-1-fundamentals/services/better_chunker.py`](../services/better_chunker.py) |
| Tests | [`levels/level-1-fundamentals/tests/test_better_chunker.py`](../tests/test_better_chunker.py) |
| Step 13 tests | 11 passed |
| Full project suite | 19 passed, 1 warning |

Run the full validation from the repository root:

```bash
PYTHONPATH=levels/level-1-fundamentals uv run python -m pytest
```

The current dependency deprecation warning comes from Starlette's test client using AnyIO's `BlockingPortal` alias. Tests pass; this is not a Step 13 application failure.

Completion here means the class and its tests are available. The existing ingestion path and stored chunks still use Step 3, and no measured improvement in RAG quality is claimed.

## 16. What comes next?

**Step 14 — RAG Evaluation.**

We have added a way to keep sentences together when creating chunks. Now we need to measure whether retrieval and generated answers are actually good. That is the next learning step.
