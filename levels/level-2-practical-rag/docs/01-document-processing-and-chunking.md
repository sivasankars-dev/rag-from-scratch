# Level 2 — Document Processing and Chunking

## 1. What this stage implements

This stage separates PDF extraction from chunk construction. It keeps page information during extraction and uses paragraph boundaries, then sentences and words, to divide long text.

Refer to the [Level 1 learning documentation](../../level-1-fundamentals/README.md) if you need to review ingestion, embeddings, vector search, similarity, or retrieval. This chapter focuses on the current Level 2 code.

**Current implementation:** `chunk_text(text, chunk_limit)` uses a **word-count limit**. It does not accept a `strategy` argument. Paragraph, sentence, and word splitting form one fallback sequence; they are not three independently selectable strategies.

```text
PDF → page records containing text and page number
                  ↓ caller supplies a text string
             Paragraph boundaries
                  ↓ for oversized paragraphs
             Sentence grouping
                  ↓ for oversized sentences
             Word groups → chunk strings
```

The loader and chunker are separate functions. The existing runner prints extracted pages; it does not connect them into a complete ingestion pipeline.

## 2. PDF text extraction

[`services/document_loader.py`](../services/document_loader.py) defines `extract_text_from_pdf(filepath)` using `pypdf`:

```python
pdf_reader = PdfReader(filepath)
results = []
for page_number, page in enumerate(pdf_reader.pages, start=1):
    text = page.extract_text()
    if text:
        results.append({"text": text, "page_number": page_number})
return results
```

The result is a list of page dictionaries, not one string joined with newlines. Page numbers start at 1 and retain their original PDF positions even when an empty page is skipped.

The loader extracts text and records its page number. It does not chunk, clean, embed, or store the text. The `if text` check skips empty strings and `None`; it does not reject whitespace-only strings. There is no OCR or special handling for complex layouts. A missing file raises `FileNotFoundError`.

## 3. Keeping loading and chunking separate

[`services/chunker.py`](../services/chunker.py) works with a text string, so its tests do not need a PDF. The loader can be tested separately for extraction and page information.

The current entry point is:

```python
chunk_text(text, chunk_limit)
```

It returns a list of strings. A caller can supply a page record's `text`, but must retain the page number separately if it needs that information later. The chunker itself does not attach metadata.

## 4. Paragraph chunking

`split_into_paragraphs(text)` splits on two consecutive newline characters (`"\n\n"`) and discards whitespace-only pieces.

For each paragraph, `chunk_text` counts whitespace-separated words. A paragraph within `chunk_limit` becomes one chunk with leading and trailing whitespace removed. Neighboring short paragraphs are **not combined**, even if they would fit together.

For example, with `chunk_limit=5`:

```text
Input:  Annual leave requires approval.\n\nSick leave requires notification.
Output: ["Annual leave requires approval.",
         "Sick leave requires notification."]
```

This preserves existing paragraph boundaries and punctuation for paragraphs that fit. However, extracted PDF text may not contain reliable blank-line boundaries, and many short paragraphs can produce many small chunks. Long paragraphs use the next fallback.

## 5. Sentence chunking

`split_long_paragraph(paragraph, chunk_limit)` splits an oversized paragraph on the literal period (`"."`). It strips each piece, skips empty pieces, and groups consecutive pieces while their combined word count fits the limit.

With `chunk_limit=10`, this tested input:

```text
Python is easy to learn. FastAPI is used to build APIs. PostgreSQL stores application data.
```

produces:

```python
[
    "Python is easy to learn",
    "FastAPI is used to build APIs PostgreSQL stores application data",
]
```

Sentence grouping can keep related words together instead of splitting every paragraph immediately into fixed word groups. However, this implementation removes the periods when rebuilding chunks. It does not recognize `!` or `?` as sentence boundaries, and periods in abbreviations or decimals can split unexpectedly. It is a simple fallback, not complete sentence detection.

## 6. Word chunking

If a sentence piece is itself larger than the limit, it is split using `sentence.split()` and sliced into groups of at most `chunk_limit` words. Any accumulated sentence group is emitted first.

With `chunk_limit=5`:

```python
# Input: "Python is a very powerful programming language"
["Python is a very powerful", "programming language"]
```

This handles sentences that cannot fit as one chunk without cutting a word in half. It can still split an idea across chunks. The word-splitting fallback normalizes whitespace to single spaces, and a very long individual word remains intact. Sentence grouping preserves whitespace inside each sentence piece and inserts a single space between pieces.

## 7. What does chunk_limit measure?

The code uses `len(text.split())`: **whitespace-separated word count**, not characters or model tokens. `chunk_limit` is intended to be a positive integer, but explicit validation is not currently implemented.

```text
Current implementation: word count
Not implemented yet: character limit or token limit
```

For example, `chunk_limit=10` permits ten words, not ten characters. A single long word can therefore produce a chunk with many characters. Increasing the limit allows larger sentence or word groups, but does not merge separate paragraphs.

## 8. Input validation and edge cases

There is currently **no explicit input validation** in the chunker.

| Input or situation | Current behavior |
| --- | --- |
| Empty text | Returns `[]` |
| Whitespace-only text | Returns `[]` |
| Paragraph within the word limit | Returns that paragraph as one trimmed chunk |
| Paragraph over the word limit | Uses sentence grouping, then word splitting when necessary |
| Several small paragraphs | Returns separate chunks rather than packing them together |
| Invalid strategy | No strategy parameter exists; an unexpected `strategy` keyword raises Python's `TypeError` |
| Zero or negative limit | Not rejected explicitly; unsafe for nonempty input |

For a sentence containing words, the word-slicing loop advances by `chunk_limit`. Zero never advances it; a negative value moves it backward. Such inputs can cause a nonterminating loop, rather than a helpful validation error. Empty input can still return `[]` without checking the limit. Do not use zero or negative limits.

## 9. Practical trade-offs

| Boundary used | Benefit | Current limitation |
| --- | --- | --- |
| Paragraph | Keeps an existing paragraph together when it fits | Depends on blank lines; does not combine small paragraphs |
| Sentence fallback | Groups sentence pieces within the word limit | Period-only splitting removes periods and can misread abbreviations |
| Word fallback | Handles an oversized sentence without cutting individual words | Can separate related ideas; does not bound character or token count |

No approach is universally best. These choices make the current behavior understandable and provide a starting point for later retrieval experiments. The tests check chunk construction, not whether a strategy improves retrieval quality.

## 10. Automated tests and running the code

[`tests/test_document_loader.py`](../tests/test_document_loader.py) contains three tests: extracting page records from the sample PDF, retaining nonempty page text, and raising `FileNotFoundError` for a missing path.

[`tests/test_text_chunker.py`](../tests/test_text_chunker.py) contains twelve tests covering:

- Paragraph splitting, a single paragraph, and extra blank lines.
- Empty and whitespace-only input.
- Small, long, and mixed paragraphs.
- Sentence grouping within a word limit.
- An oversized sentence split into word groups, including an explicit word-count bound.
- Mixed normal and oversized sentences, checked against expected chunk strings.

There are no zero/negative-limit tests. Strategy selection and character-limit enforcement are outside the current API and test coverage.

Run from the repository root using the existing environment:

```bash
cd levels/level-2-practical-rag
PYTHONPATH=. ../../.venv/bin/python -m pytest tests -v -p no:cacheprovider
PYTHONPATH=. ../../.venv/bin/python -m scripts.run_document_loader
```

The working directory matters: the loader tests and runner use `../../data/documents/company_policy.pdf`. `PYTHONPATH=.` selects the Level 2 services. The runner keeps the `run_*` naming convention and prints the extracted page count and the first 300 characters of each retained page.

Validation for this documentation: **15 tests passed** using the test command above. This is the Level 2 test suite, not a combined Level 1–2 run.

## 11. Chunk Overlap Is Not Implemented Yet

Current chunks do not deliberately carry text from one chunk into the next:

```text
Chunk 1 [A B C D]
Chunk 2 [E F G H]
```

The future overlap concept would repeat some boundary information:

```text
Chunk 1 [A B C D]
Chunk 2 [D E F G]
```

These letters illustrate the distinction only. Chunk overlap will be implemented and evaluated in the next stage; it is not part of this Level 2 chunker yet.

## 12. Current boundaries

A connected ingestion coordinator, dedicated text cleaning, chunk metadata construction, and embedding and storage orchestration remain future work.

Token-aware chunking, semantic chunking, advanced chunk-quality evaluation, and production-grade document parsing also belong to later stages.

## 13. Interview explanation

> “I separated PDF extraction from chunking. The loader uses pypdf and returns text with its original page number. The chunker keeps short paragraphs intact, groups sentence pieces for long paragraphs, and splits oversized sentences into word groups. Its current limit counts words, and it returns plain chunk strings. Tests cover extraction and the main splitting cases. Input validation and punctuation handling still need work.”
