# Level 2 — Chunk Overlap

## 1. Purpose

This stage introduces a standalone chunking function with word overlap. It does not yet connect extraction, chunking, and storage into a complete ingestion pipeline.

Refer to [Level 1's overlap explanation](../../level-1-fundamentals/docs/13-better-chunking.md) for the basic concept. This document focuses on the **Level 2 implementation, tests, and limitations**.

---

## 2. Implementation

Stage 1 uses:

```text
services/chunker.py
```

Stage 2 keeps that implementation unchanged and introduces a separate overlap-based implementation:

```text
services/overlap_chunker.py
```

Current structure:

```text
services/
├── chunker.py
├── document_loader.py
└── overlap_chunker.py
```

The Stage 1 chunker remains available for paragraph/sentence-oriented chunking.

The Stage 2 implementation provides:

```python
chunk_text_with_overlap(text, chunk_limit, overlap=0)
```

This separation keeps the progression between the two stages explicit and makes the implementation easier to study.

---

## 3. Current Algorithm

The Stage 2 implementation treats the input as a sequence of whitespace-separated words.

```python
words = text.split()
```

The number of words allowed in each chunk is controlled by:

```python
chunk_limit
```

The overlap is controlled by:

```python
overlap
```

The distance between two chunk starting positions is calculated as:

```python
step = chunk_limit - overlap
```

For example:

```text
chunk_limit = 5
overlap     = 2

step = 5 - 2
     = 3
```

For:

```text
A B C D E F G H I J
```

the resulting chunks are:

```text
A B C D E
D E F G H
G H I J
```

The starting positions are effectively:

```text
0 → 3 → 6
```

because each new chunk starts three words after the previous chunk.

---

## 4. Current Implementation

The implementation is intentionally small:

```python
def chunk_text_with_overlap(text, chunk_limit, overlap=0):
    if chunk_limit <= 0:
        raise ValueError("chunk_limit must be greater than 0")

    if overlap < 0:
        raise ValueError("overlap cannot be negative")

    if overlap >= chunk_limit:
        raise ValueError("overlap must be less than chunk_limit")

    words = text.split()

    if not words:
        return []

    chunks = []
    step = chunk_limit - overlap

    for start in range(0, len(words), step):
        chunk = words[start:start + chunk_limit]

        chunks.append(" ".join(chunk))

        if start + chunk_limit >= len(words):
            break

    return chunks
```

The implementation provides three important controls:

```text
chunk_limit
    Maximum number of words in a chunk.

overlap
    Number of words shared between consecutive chunks.

step
    Number of words by which the next chunk moves.
```

---

## 5. Validation

The function checks the three numeric conditions below before processing the input. Use integer values for `chunk_limit` and `overlap`; there is no explicit type validation. These checks do not guarantee that arbitrary input types are accepted or produce `ValueError`.

### `chunk_limit` must be positive

```python
if chunk_limit <= 0:
    raise ValueError(...)
```

Therefore:

```text
chunk_limit = 0
chunk_limit = -1
```

are rejected.

This also prevents an invalid step calculation from creating an unusable loop.

### Overlap cannot be negative

```python
if overlap < 0:
    raise ValueError(...)
```

Therefore:

```text
overlap = -1
```

is rejected.

### Overlap must be smaller than the chunk limit

```python
if overlap >= chunk_limit:
    raise ValueError(...)
```

For example:

```text
chunk_limit = 5
overlap = 5
```

is invalid.

So is:

```text
chunk_limit = 5
overlap = 6
```

The valid relationship is:

```text
0 <= overlap < chunk_limit
```

---

## 6. Input Handling

The implementation uses:

```python
text.split()
```

Therefore whitespace is treated as the separator between words.

For example:

```text
A B C
```

and:

```text
A    B
C
D
```

are processed as whitespace-separated word sequences.

The implementation does not currently preserve paragraph boundaries.

For example:

```text
A B C D E

F G H I J
```

is treated as one continuous sequence:

```text
A B C D E F G H I J
```

Output words are joined with single spaces, so original spacing and line breaks are normalized. Punctuation attached to words is retained. Sentence and paragraph boundaries do not affect the windows.

---

## 7. Final Small Chunk

The final chunk is allowed to contain fewer words than `chunk_limit`.

For example:

```text
Input:

A B C D E F G
```

with:

```text
chunk_limit = 5
overlap = 2
```

produces:

```text
A B C D E
D E F G
```

The final chunk contains four words.

The implementation does not pad the final chunk to reach the configured limit. It stops as soon as a window reaches the end of the input, so it does not emit another chunk containing only an already-covered suffix. Input at or below the limit produces one chunk.

For valid integer settings, consecutive chunks share exactly `overlap` input word positions. This also holds for a shorter final chunk. With `overlap=0`, no positions are repeated.

---

## 8. Empty Input

With valid settings, empty input returns an empty list:

```python
chunk_text_with_overlap("", 5, 2)
```

returns:

```python
[]
```

Whitespace-only input behaves the same way because:

```python
"   ".split()
```

produces:

```python
[]
```

Invalid settings still raise an error for empty or whitespace-only text because configuration checks run first.

---

## 9. Tests

Stage 2 includes dedicated tests in:

```text
tests/test_overlap_chunker.py
```

There are **12 overlap tests**. They cover:

- Normal overlap behavior
- No-overlap behavior
- One-word overlap
- Multiple paragraphs treated as a continuous word sequence
- Empty and whitespace-only input
- Exact chunk-limit input
- Small final chunk
- Maximum chunk size
- Correct overlap between consecutive chunks
- Positive `chunk_limit` validation
- Negative overlap validation
- Overlap greater than or equal to `chunk_limit`

The overlap relationship is also tested directly.

For consecutive chunks:

```python
previous_words[-2:] == current_words[:2]
```

when:

```text
overlap = 2
```

This verifies the actual overlap rather than only checking a hard-coded output.

---

## 10. Verification

Run the complete Level 2 test suite from:

```text
levels/level-2-practical-rag
```

with:

```bash
PYTHONPATH=. ../../.venv/bin/python -m pytest tests -v -p no:cacheprovider
```

Current result:

```text
27 passed
```

This total includes **12 overlap tests, 12 Stage 1 chunker tests, and 3 PDF loader tests**. Both chunkers pass their tests in the same suite; this does not test a connected ingestion pipeline or establish improved retrieval quality.

---

## 11. Engineering Characteristics

The current implementation is deliberately simple and predictable.

### Word-based

The implementation works with whitespace-separated words rather than tokens from an LLM tokenizer.

Therefore:

```text
chunk_limit = 100
```

sets a maximum of:

```text
100 whitespace-separated words
```

It does **not** mean 100 model tokens.

See [Level 1 generation basics](../../level-1-fundamentals/docs/17-generation-basics.md) if you need to review word/token distinctions.

### Fixed sliding window

The implementation uses:

```python
step = chunk_limit - overlap
```

This creates a fixed-size sliding window over the word sequence.

### No metadata

The function currently returns:

```python
list[str]
```

It does not attach metadata such as:

```text
document_id
page_number
chunk_index
source
```

Metadata will be handled in a later Level 2 stage.

### No sentence awareness

The overlap implementation does not attempt to detect:

- sentences
- paragraphs
- headings
- semantic boundaries

It operates directly on the word sequence.

This is a deliberate simplification for the current stage.

---

## 12. Stage 1 vs Stage 2

The two implementations have different purposes.

| Feature | Stage 1 `chunker.py` | Stage 2 `overlap_chunker.py` |
|---|---|---|
| Paragraph handling | Splits on `"\n\n"`; does not combine paragraphs | Ignores boundaries |
| Sentence splitting | Period-based fallback for oversized paragraphs; removes periods | No; attached punctuation is retained |
| Word-based splitting | Yes, for oversized sentences | Yes |
| Overlap | No | Yes |
| Input model | Paragraph → sentence → word fallback | Continuous word sequence |
| Numeric validation | No explicit positive-limit check | Checks limit and overlap bounds |
| Metadata | No | No |
| Main purpose | Basic chunking | Fixed-word overlapping chunks |

The Stage 1 implementation is intentionally left unchanged.

---

## 13. Current Limitations

This implementation is a practical first version, not a production chunking strategy.

Current limitations include:

- Uses whitespace-separated words rather than tokenizer-based token counts.
- Does not preserve paragraph boundaries.
- Does not preserve sentence boundaries.
- Does not support semantic chunking.
- Does not attach metadata.
- Does not provide configurable overlap strategies.
- Does not explicitly validate parameter types.

Later stages can build on the chunk strings. Metadata and more advanced boundary handling are not part of this function.

---

## 14. Interview Explanation

A concise way to explain the implementation:

> "For this stage, I implemented a fixed-word sliding-window chunker. The `chunk_limit` defines the maximum number of words per chunk, and `overlap` defines how many words are shared between consecutive chunks. Each next chunk starts `chunk_limit - overlap` words after the previous start, so with a limit of 500 and overlap of 100, the window moves by 400 words. I also check that the limit is positive and that overlap is nonnegative and smaller than the limit."

If asked about the limitation:

> "This implementation is intentionally word-based. It doesn't preserve sentence or paragraph boundaries, because the goal of this stage was to isolate and test overlap behavior. The earlier chunker handles paragraph and sentence-oriented splitting, and later stages can introduce more advanced chunking strategies."

---

## 15. Stage Completion

Stage 2 is complete when:

```text
Implementation       ✅
Validation            ✅
Automated tests       ✅
Full Level 2 suite    ✅ 27 passed
Documentation         ✅
```

Planned next stage (not implemented by this chunker):

```text
Stage 3 — Metadata & Metadata Filtering
```
