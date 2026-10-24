# Hierarchical / Document-Aware Retrieval

## 1. Objective

Normal chunking splits text into smaller pieces. Parent-child retrieval searches smaller child chunks and retrieves their associated parent context.

Document-aware retrieval adds document structure to this process. It preserves section and subsection identity so that retrieved text can be traced to its original context.

This implementation extends the existing Level 3 parent-child retrieval workflow. It does not replace the existing retrieval strategies.

## 2. Why This Approach Is Needed

Fixed-size chunk boundaries do not necessarily align with document section boundaries. A chunk can omit its heading or combine information from different topics.

For example:

- Section 2.2: Remote Work
- Section 2.3: Office Access

A fixed-size chunk can split text near the boundary between these sections. Without structural metadata, it becomes harder to determine the context of a retrieved chunk.

Document-aware chunking preserves section boundaries where they can be identified from the extracted text. It also stores metadata such as the section title, section path, and page range.

## 3. Architecture

```text
PDF
 |
 v
Level 2 PDF text extraction
 |
 v
Document section parser
 |  - Numbered section headings
 |  - Parent/child section relationships
 |  - Individual FAQ entries
 v
Hierarchical chunker
 |  - Bounded parent chunks
 |  - Smaller child chunks
 |  - Section metadata
 |
 +-----------------------+
 |                       |
 v                       v
ParentChildStore      ChildVectorStore
(JSON)                (Chroma)
 |                       |
 +-----------+-----------+
             |
             v
      Parent-child retrieval
             |
             v
      Parent context + metadata
```

## 4. Components

### 4.1 Document section parser

File: `services/document_section_parser.py`

The parser processes ordered page records from the existing Level 2 PDF loader. It recognizes numbered headings such as:

- `1. Company Overview`
- `1.1 Working Principles`
- `2.2 Remote Work`

The parser maintains section state across page boundaries until another recognized heading appears.

It identifies FAQ sections from their titles and splits question-and-answer entries when a question line ends with `?`.

Each parsed record can include:

- `document_id`
- `section_id`
- `section_number`
- `section_title`
- `section_type`
- `parent_section_id`
- `section_path`
- `start_page`
- `end_page`
- `text`

Text before the first recognized numbered heading is represented as a document-introduction preamble.

### 4.2 Hierarchical chunker

File: `services/hierarchical_chunker.py`

The chunker creates parent and child chunks from parsed sections. It does not combine text from different parsed sections into the same parent chunk.

Current configuration:

| Setting | Value |
|---|---:|
| Parent chunk size | 100 words |
| Child chunk size | 30 words |
| Child overlap | 10 words |

These values are initial project settings, not universal production defaults. The chunker currently uses whitespace-based word splitting. It does not guarantee preservation of paragraph or sentence boundaries.

Parent IDs and child IDs are deterministic for a given section and chunking configuration.

### 4.3 Parent store

File: `services/parent_child_store.py`

Parent records and their metadata are persisted in JSON:

`data/parent_child/parents.json`

The ingestion script uses the Level 3 data directory, so the active handbook store is under:

`levels/level-3-advanced-rag/data/parent_child/parents.json`

### 4.4 Child vector store

File: `services/child_vector_store.py`

Child text and embeddings are persisted in Chroma. Metadata includes available fields such as:

- `parent_id`
- `source`
- `page_number`
- `document_id`
- `section_id`
- `section_number`
- `section_title`
- `section_type`
- `parent_section_id`
- `section_path`
- `section_start_page`
- `section_end_page`

Optional metadata fields with `None` values are omitted because Chroma metadata does not accept Python `None` values.

### 4.5 Ingestion

Script: `scripts/run_parent_child_ingestion.py`

The ingestion process:

1. Extracts PDF text page by page.
2. Parses document sections.
3. Builds section-aware parent and child chunks.
4. Validates unique IDs and nonempty child content.
5. Creates child embeddings before replacing stored source records.
6. Replaces records for the target source while retaining other sources.
7. Reloads the stores and verifies persisted parent and child IDs.

The JSON and Chroma updates are separate operations and are not an atomic transaction. A failure between store updates can leave the stores inconsistent; this remains a limitation.

## 5. Retrieval Flow

The existing `ParentChildRetrievalService` performs these steps:

1. Embeds the user query.
2. Searches Chroma for matching child chunks.
3. Reads each matching child's `parent_id`.
4. Retrieves the corresponding parent from JSON.
5. Removes duplicate parent results.
6. Returns the parent records and their available section metadata.

The service currently does not traverse `parent_section_id` to fetch ancestor sections or sibling sections automatically. Section hierarchy is preserved as metadata, but full ancestor-context expansion has not been implemented.

## 6. Real Handbook Validation

Dataset: `data/documents/rag_practice_employee_handbook.pdf`

The synthetic employee handbook contains 12 PDF pages.

Validated parser and ingestion output:

| Metric | Result |
|---|---:|
| PDF pages | 12 |
| Parsed records | 65 |
| Preamble records | 1 |
| Regular section records | 53 |
| FAQ parent records | 1 |
| Individual FAQ entries | 10 |
| Parent chunks | 65 |
| Child chunks | 92 |
| Stored child embeddings | 92 |

A manual retrieval smoke test returned the Remote Work section for a remote-work question. For an annual-leave question, the Annual Leave section ranked first and the matching FAQ entry also appeared in the top three results.

These checks confirm that ingestion and example retrieval work. They do not establish a statistically reliable retrieval-quality improvement.

## 7. Tests

Parser tests:

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run pytest \
  levels/level-3-advanced-rag/tests/test_document_section_parser.py -q
```

Hierarchical chunker tests:

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run pytest \
  levels/level-3-advanced-rag/tests/test_hierarchical_chunker.py -q
```

Vector-store tests:

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run pytest \
  levels/level-3-advanced-rag/tests/test_child_vector_store.py -q
```

Ingestion tests:

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run pytest \
  levels/level-3-advanced-rag/tests/test_parent_child_ingestion.py -q
```

Full Level 3 suite:

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run pytest \
  levels/level-3-advanced-rag/tests -q
```

At documentation time, the full Level 3 suite passed with 200 tests.

## 8. Limitations and Risks

1. Heading detection uses heuristics over extracted text. Numbered list items, unusual headings, and unnumbered headings may be classified incorrectly or missed.
2. FAQ parsing uses question lines ending in `?`. Other FAQ layouts may need different parsing rules.
3. Word-based chunking can split sentences and does not preserve all original paragraph boundaries.
4. Word counts are not tokenizer token counts. The current sizes must not be treated as universal embedding-model or LLM context limits.
5. Long sections can produce multiple bounded parent chunks. Section metadata is preserved, but all chunks are not combined into one unbounded parent.
6. The retriever returns matched parents but does not yet expand the complete ancestor hierarchy.
7. Updating JSON and Chroma is not transactional across both stores.
8. The current handbook is a small synthetic dataset. Results from a small set of manual queries do not demonstrate production readiness.

## 9. Evaluation Status

**Status: Pending.**

Formal evaluation has been deferred until the planned Level 3 retrieval topics are implemented.

The future comparison should use a shared, representative question set and compare relevant baselines using metrics such as:

- Hit Rate@K
- MRR@K
- Retrieval latency
- Context relevance and completeness

The purpose is to determine whether document-aware retrieval improves retrieval quality enough to justify its added complexity. No claim of measured quality improvement is made at this stage.

## 10. Summary

This implementation adds section-aware parsing and chunking to the existing parent-child retrieval pipeline. It preserves available document structure in parent records and child-vector metadata while retaining bounded chunk sizes.

The implementation and regression tests pass, and the synthetic handbook has been ingested successfully. Comparative retrieval evaluation remains pending.
