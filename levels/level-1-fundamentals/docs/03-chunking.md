# Step 3 — Document chunking

> Level 1 learning note: this chapter preserves its original checkpoint. Steps 1–17 are now complete; see the [learning index](../../../README.md#level-1-learning-sequence). Commands below run from the repository root and select Level 1 with `PYTHONPATH`. Shared data remains under root `data/`.

## What are we learning, and why?

Chunking splits text into smaller pieces that can be embedded and retrieved independently. A whole short document can be embedded, but a long document may exceed the model's input limit. Even when it fits, a single vector can mix several topics and make specific facts harder to retrieve.

## Simple analogy

Instead of handing someone an entire policy binder, mark small passages they can find and read. Overlap repeats a little text across adjacent passages so a boundary is less likely to lose context.

## Technical explanation and current implementation

[`chunk_text`](../services/chunker.py) slides a window over a Python string. It takes `text[start:end]`, skips whitespace-only windows, strips outer whitespace from retained windows, and advances by `chunk_size - chunk_overlap`. The units are **characters**, not tokens. It can cut words and sentences in half.

The helper defaults to size 500 and overlap 50. The actual ingestion script explicitly chooses **size 100, overlap 20**. The existing upload route instead chooses size 100, overlap 10, producing four chunks from this sample. These are two separate experiments; uploading does not populate Chroma.

## Example: 343 characters, size 100, overlap 20

The stride is `100 - 20 = 80`. End positions below are exclusive Python slice boundaries:

| Chunk index | Slice | Raw characters |
| --- | --- | --- |
| 0 | `text[0:100]` | 100 |
| 1 | `text[80:180]` | 100 |
| 2 | `text[160:260]` | 100 |
| 3 | `text[240:340]` | 100 |
| 4 | `text[320:420]` | 23 (slice stops at 343) |

The implementation returns five nonempty chunks. `.strip()` can reduce the returned lengths, so they are not all exactly 100 characters. It continues while `start < len(text)`, even if the previous window already reached the end. This intentionally simple loop can emit a mostly overlapping final fragment.

A smaller example: `chunk_text("abcdefghijkl", 5, 2)` produces `abcde`, `defgh`, `ghijk`, `jkl`. Each new start advances three characters.

## Why overlap exists and what it costs

A fact can cross a window boundary. Overlap preserves some neighboring context, but cannot guarantee a full sentence survives. Too little overlap loses connections. Too much repeats content, increases embedding/storage work and may return near-duplicate passages.

Small chunks can focus on a fact but lose qualifiers and context. Large chunks preserve context but mix topics and may exceed token limits. There is no universal best size; 100/20 is a learning configuration, not a production recommendation.

## Character-based vs token-based chunking

Characters are Python string units; tokens are pieces chosen by a model tokenizer, sometimes whole words and sometimes word fragments. Their counts are not interchangeable. Our application chunks characters first. The embedding model later tokenizes each chunk internally. Production chunkers may count model tokens or use sentence/semantic boundaries, but those approaches are outside Step 3. [Step 13 — Better Chunking](13-better-chunking.md) now adds a separate sentence-based implementation. The ingestion script and upload route still use this Step 3 chunker.

## Common mistakes and the bug I encountered

The earlier `if chunks.strip()` failed because `chunks` is the output **list**, which has no string `.strip()` method. `chunk` is the current **string**, so the correct check is `if chunk.strip()`. That fix was already present at inspection.

Validation now rejects `chunk_size <= 0` explicitly. Previously size zero was indirectly rejected by the overlap comparison for normal nonnegative overlap, but the message did not clearly express the actual problem. Also reject negative overlap and overlap greater than or equal to size; otherwise the window might not advance.

Do not assume these chunks respect paragraphs, sentences or model token limits. Do not change chunk sizes without re-ingesting the document: stored vectors describe the previous chunks.

## What we implemented and verified

The existing character window algorithm is preserved. Only the size validation/message changed. Small standard-library tests cover overlap, the final fragment, empty/whitespace input and invalid settings. The sample pipeline confirms five chunks.

## Interview questions

1. Why overlap? To keep some context across boundaries.
2. Why not embed every document as one vector? Input limits and mixed topics can reduce useful retrieval.
3. Is 100 characters the same as 100 tokens? No; token counts depend on the tokenizer and text.
4. What guarantees this loop progresses? `0 <= overlap < size` with positive size.

## What I learned

Chunk boundaries affect what retrieval can return. A small loop makes those trade-offs visible, and distinguishing a list of chunks from an individual string avoids a basic Python type error.

## Next step

[Step 4 — Embeddings](04-embeddings.md).
