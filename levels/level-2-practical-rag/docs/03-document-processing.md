# 03 — Document Processing

## 1. Purpose

This document describes the document-processing layer implemented in Level 2.

The goal of this layer is to take page-level text extracted from a PDF, split the text into chunks using the existing chunking logic, and preserve document-level metadata for each resulting chunk.

The implementation currently focuses on:

- Processing page-level PDF output.
- Reusing the existing chunking and overlap logic.
- Preserving the source page number.
- Assigning a continuous chunk index across the entire document.
- Ignoring empty pages that produce no chunks.

For the underlying concepts of chunking, chunk size, overlap, and related RAG fundamentals, refer to the corresponding Level 1 documentation instead of repeating those concepts here.

---

## 2. Current Processing Flow

The current Level 2 flow is:

```text
PDF file
   ↓
extract_text_from_pdf()
   ↓
Page-level records
   ↓
process_document()
   ↓
chunk_text_with_overlap()
   ↓
Processed chunk records
```

The PDF loader and chunker remain separate responsibilities.

The document processor acts as the layer that connects page-level document data with the chunking functionality.

---

## 3. Input Structure

The PDF loader returns a list of page-level records.

Each record contains:

```python
{
    "text": "...",
    "page_number": 1
}
```

For example:

```python
pages = [
    {
        "text": "Employees get annual leave.",
        "page_number": 1
    },
    {
        "text": "Employees get sick leave.",
        "page_number": 2
    }
]
```

The document processor accepts this list as its input.

---

## 4. Document Processor

The document processor is implemented as:

```python
def process_document(pages, chunk_limit, overlap=0):
```

Its responsibilities are:

1. Iterate through each page.
2. Extract the page text.
3. Pass the text to `chunk_text_with_overlap()`.
4. Create a record for every resulting chunk.
5. Preserve the page number.
6. Assign a continuous `chunk_index`.
7. Return all processed chunks as a list.

The processor does not implement a second chunking algorithm. It reuses the existing chunking function.

---

## 5. Output Structure

The processor returns a list of chunk records.

The current record structure is:

```python
{
    "chunk": "...",
    "page_number": 1,
    "chunk_index": 0
}
```

For example:

```python
[
    {
        "chunk": "Employees get annual leave.",
        "page_number": 1,
        "chunk_index": 0
    },
    {
        "chunk": "Employees get sick leave.",
        "page_number": 2,
        "chunk_index": 1
    }
]
```

The current implementation uses the key `chunk` for the generated chunk text.

---

## 6. Chunk Index Strategy

`chunk_index` is assigned at the document level rather than restarting for every page.

For example:

```text
Page 1
    chunk_index = 0
    chunk_index = 1

Page 2
    chunk_index = 2
    chunk_index = 3
```

The index is therefore continuous across the entire processed document.

This makes each generated chunk easier to identify within the document.

The index is assigned by the document processor because the processor has visibility across all pages and all generated chunks.

The PDF loader is responsible only for page-level information and does not generate chunk indexes.

---

## 7. Page Number Preservation

The original `page_number` from the PDF loader is preserved when chunks are created.

If one page produces multiple chunks:

```text
Page 1
    Chunk 0 → page_number = 1
    Chunk 1 → page_number = 1
    Chunk 2 → page_number = 1
```

If the next page produces chunks:

```text
Page 2
    Chunk 3 → page_number = 2
    Chunk 4 → page_number = 2
```

This allows later retrieval results to identify the page from which a chunk originated.

---

## 8. Empty Page Handling

An empty page should not create an empty chunk.

The existing chunking function returns an empty list when the input contains no words.

Therefore:

```python
{
    "text": "",
    "page_number": 1
}
```

does not produce:

```python
{
    "chunk": "",
    "page_number": 1,
    "chunk_index": 0
}
```

Instead, the processor skips that page because there are no chunks to process.

For example:

```text
Page 1 → empty → no chunk

Page 2 → valid text
       → chunk_index = 0
```

The chunk index therefore represents generated chunks, not PDF page numbers.

---

## 9. Overlap Handling

The document processor accepts:

```python
overlap=0
```

as the default.

The supplied `overlap` value is passed to the existing:

```python
chunk_text_with_overlap()
```

function.

For example:

```python
process_document(
    pages,
    chunk_limit=4,
    overlap=2
)
```

allows the existing overlap behavior to be applied while processing each page.

The document processor itself does not implement overlap logic.

For details about how overlap works and its current behavior, refer to the Level 1 chunk-overlap documentation.

---

## 10. Current Page Boundary Behavior

The current implementation processes each page independently.

Conceptually:

```text
Page 1
   ↓
chunk Page 1
   ↓
Page 2
   ↓
chunk Page 2
```

A chunk is not currently created by combining text from the end of one page with the beginning of another page.

This keeps page metadata unambiguous and makes the current implementation easier to reason about.

Cross-page chunking can be considered as a future improvement if the application requires it.

---

## 11. Tests

The document processor currently has tests covering:

### Single page with a single chunk

Verifies:

- Chunk text.
- Page number.
- Initial chunk index.

### Single page with multiple chunks

Verifies:

- Multiple chunks are generated.
- All chunks retain the correct page number.
- Chunk indexes increment correctly.

### Multiple pages

Verifies:

- Chunks from different pages retain their respective page numbers.
- Chunk indexes continue across pages.

### Multiple pages with multiple chunks

Verifies:

- Multiple chunks can be generated from each page.
- Page numbers remain correct.
- `chunk_index` remains continuous across the entire document.

### Empty page

Verifies:

- An empty page does not create an empty chunk.
- The next valid page is processed normally.
- Chunk indexing starts from the first generated chunk.

### Chunk overlap

Verifies:

- The configured overlap value is applied through the existing chunking function.
- Overlapping words appear in consecutive chunks.
- Page number and chunk index metadata remain correct.

---

## 12. Current Limitations

The current implementation intentionally keeps the document processor simple.

Current limitations include:

- No document-level `source` metadata yet.
- No file name/path metadata in the processed chunk records.
- No document ID.
- No embedding generation.
- No vector database storage.
- No deduplication.
- No ingestion status tracking.
- Pages are processed independently.
- The processor does not yet represent a complete ingestion pipeline.

These concerns can be addressed in later Level 2 phases as the RAG pipeline becomes more complete.

---

## 13. Responsibility Separation

The current implementation keeps responsibilities separated:

```text
document_loader.py
    ↓
Extract PDF pages
    ↓
Provides text + page_number

chunker.py
    ↓
Split text into chunks
    ↓
Handles chunk size and overlap

document_processor.py
    ↓
Connects pages with chunking
    ↓
Adds page_number + chunk_index
```

This separation allows each component to be tested independently and makes later changes easier.

---

## 14. Related Documentation

The fundamental concepts behind text chunking and overlap were covered earlier in Level 1.

Refer to the relevant Level 1 documentation when a concept needs to be reviewed instead of duplicating the explanation here.

This Level 2 document focuses on the practical implementation and integration of those concepts.