# Multimodal RAG

## 1. Objective

Traditional Retrieval-Augmented Generation (RAG) retrieves relevant text from documents.

Real-world PDFs may also contain:
- Tables with structured information.
- Architecture diagrams.
- Process flowcharts.
- Network diagrams.
- Visual relationships between system components.

Multimodal RAG makes information from these different content types searchable.

In this Level 3 implementation, we extract text and tables from PDFs, optionally generate text descriptions of diagrams using a vision-capable model, embed the resulting text records, and store them in Chroma.

**Implementation scope:** This project converts visual content into searchable text descriptions. It does not currently use native image embeddings.

## 2. Architecture

```text
PDF document
    |
    v
Multimodal PDF Loader
    |
    +--> Page text records
    |
    +--> Table records
    |
    +--> Table-row records
    |
    v
Optional visual processing
    |
    +--> Render selected PDF pages as PNG
    |
    +--> Vision model describes visible diagrams
    |
    v
Combine text, table, table-row and visual-description records
    |
    v
Embedding Service
    |
    v
Multimodal Chroma Vector Store
    |
    v
Semantic search + metadata filtering
```

## 3. Components

### 3.1 PDF Loader

**File:** `services/multimodal/multimodal_pdf_loader.py`

The loader uses PyMuPDF to extract:
- Page-level text.
- Whole-table records.
- Individual table-row records.

Table regions are removed from page text where possible to reduce duplicate content.

Each record includes:
- `record_id`
- `source`
- `page_number`
- `content_type`
- `text`

Table records may include `table_id`. Table-row records may include both `table_id` and `row_number`.

Supported loader content types:
- `text`
- `table`
- `table_row`

### 3.2 PDF Page Renderer

**File:** `services/multimodal/pdf_page_renderer.py`

`PDFPageRenderer` converts a selected PDF page into a PNG image using PyMuPDF.

Page numbers are **1-based**: page 1 means the first page.

The renderer uses a configurable scale and saves the rendered image to a temporary directory during ingestion.

### 3.3 Vision Description Service

**File:** `services/multimodal/vision_description_service.py`

The vision service sends the rendered page image to a vision-capable OpenAI model. The default configured model is `gpt-5-mini`.

The prompt asks the model to describe:
- Visible components.
- Diagram labels.
- Arrows and connections.
- Relationships between components.

It also instructs the model not to invent details that are not visible.

The returned description becomes a searchable record with:
- `content_type = "visual_description"`
- `source`
- `page_number`
- `record_id`
- `text`

A vision-generated description is a model interpretation, not guaranteed ground truth. For example, the model may misunderstand an arrow direction or a relationship between components.

### 3.4 Multimodal Ingestion Service

**File:** `services/multimodal/multimodal_ingestion.py`

The ingestion service coordinates the pipeline:

1. Extract text and table records from the PDF.
2. Optionally render pages containing drawings.
3. Generate visual descriptions for eligible pages.
4. Combine extracted records and visual descriptions.
5. Generate embeddings for all record text.
6. Replace the existing records belonging to the same source in Chroma.
7. Return the record count and counts by content type.

The optional `visual_pages` argument restricts which pages are sent for visual description.

**Important:** Selecting `visual_pages={2}` restricts vision processing to page 2. Text and table extraction still runs across the PDF.

### 3.5 Multimodal Vector Store

**File:** `services/multimodal/multimodal_vector_store.py`

The vector store uses Chroma.

- Collection: `multimodal_pdf_records`
- Default persistent directory: `data/multimodal_chroma`
- Distance metric: cosine

Records are stored with their text, embeddings and metadata.

Required metadata:
- `source`
- `page_number`
- `content_type`

Optional metadata:
- `table_id`
- `row_number`

Search supports `top_k` and metadata filters. For example, a search can be restricted to visual descriptions from one PDF.

The `replace_source_records()` method updates records for a specific source and removes stale records belonging to that source while preserving other sources.

### 3.6 Embedding Service

The project reuses the Level 2 `EmbeddingService` from:

`levels/level-2-practical-rag/services/embedding_service.py`

The ingestion pipeline creates embeddings from record text, including model-generated visual descriptions.

The script loads the Level 2 module by its explicit file path to avoid conflicts between the Level 2 and Level 3 packages, which both use a `services` package.

## 4. Prerequisites

Run commands from the repository root.

Ensure:
- Project dependencies are installed.
- The Python virtual environment is active, or use `uv run`.
- `.env` contains a valid `OPENAI_API_KEY` for vision processing.
- The PDF file exists at the supplied path.

Vision processing calls an external model and may incur API costs. A dry run does not call the vision model.

## 5. Running the Pipeline

### 5.1 Inspect PDF extraction without storing

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run python \
  levels/level-3-advanced-rag/scripts/run_multimodal_ingestion.py \
  --pdf data/documents/multimodal_rag_diagram_sample.pdf \
  --dry-run
```

The dry run reports:
- PDF path.
- Number of extracted records.
- Number of pages represented.
- Record counts by content type.

It does not generate embeddings, call the vision model, or write records to Chroma.

### 5.2 Ingest a PDF and describe page 2

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run python \
  levels/level-3-advanced-rag/scripts/run_multimodal_ingestion.py \
  --pdf data/documents/multimodal_rag_diagram_sample.pdf \
  --visual-pages 2
```

This extracts text and tables from the PDF and requests a visual description of page 2, provided PyMuPDF reports drawings on that page.

### 5.3 Describe all pages containing drawings

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run python \
  levels/level-3-advanced-rag/scripts/run_multimodal_ingestion.py \
  --pdf data/documents/multimodal_rag_diagram_sample.pdf
```

When `--visual-pages` is omitted, the implementation attempts vision processing on every page for which `page.get_drawings()` returns drawings.

### 5.4 Use another PDF

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run python \
  levels/level-3-advanced-rag/scripts/run_multimodal_ingestion.py \
  --pdf data/documents/rag_practice_employee_handbook.pdf \
  --visual-pages 2 4
```

The example restricts vision processing to pages 2 and 4. Replace these page numbers with the pages relevant to your PDF.

**Note:** `--visual-pages` accepts 1-based page numbers. The current script does not explicitly validate that every requested page number falls within the PDF's page range.

## 6. Understanding the Ingestion Output

The script first prints the records extracted by the PDF loader.

When ingestion completes, it prints a summary similar to:

```text
Ingestion complete:
source: multimodal_rag_diagram_sample.pdf
record_count: 9
records_by_type: {'table': 1, 'table_row': 3, 'text': 4, 'visual_description': 1}
```

The values above are an example from the sample PDF run, not a guarantee for every input.

The `record_count` includes both records extracted from the PDF and any successfully generated visual descriptions.

The `records_by_type` summary helps verify that visual descriptions were added alongside ordinary text and table records.

## 7. Searching the Stored Records

`MultimodalVectorStore.search()` accepts:
- A query embedding.
- `top_k`, the maximum number of results requested.
- An optional Chroma metadata filter.

For example, this filter restricts search to visual descriptions from the sample PDF:

```python
where = {
    "$and": [
        {"source": "multimodal_rag_diagram_sample.pdf"},
        {"content_type": "visual_description"},
    ]
}
```

The query embedding must be created using the project's embedding service. Pass the embedding and filter to `MultimodalVectorStore.search()`.

A successful result includes the stored text, metadata and distance.

**Cosine distance is not a relevance percentage.** Lower distances generally indicate closer vectors, but a distance value alone cannot establish whether the retrieved result answers a question correctly.

Retrieval quality should be evaluated with labeled questions and expected relevant records.

## 8. Testing

Run the focused multimodal tests:

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run pytest \
  levels/level-3-advanced-rag/tests/test_multimodal_pdf_loader.py \
  levels/level-3-advanced-rag/tests/test_multimodal_vector_store.py \
  levels/level-3-advanced-rag/tests/test_multimodal_ingestion.py \
  -q
```

The tests cover:
- PDF text and table extraction.
- Record metadata preservation.
- Embedding-count and invalid-record validation.
- Empty search results.
- Source-specific record replacement.
- Visual-description metadata and retrieval.
- Adding visual descriptions during ingestion.
- Restricting visual processing to selected pages.

Most ingestion tests use fake embedding, rendering and vision services. These tests validate pipeline behavior without requiring paid vision API calls.

A passing unit test does not prove that a vision model interprets every diagram correctly. That requires separate quality evaluation.

## 9. Current Limitations

### 9.1 Drawing detection is heuristic

The current implementation uses `page.get_drawings()` to decide whether a page should be sent for visual description.

A page containing a meaningful image but no detected vector drawings may be skipped. Decorative drawings may also trigger unnecessary processing.

### 9.2 Visual descriptions may contain errors

The vision model may misinterpret labels, arrow directions, or relationships. Critical technical facts should be verified against the original PDF.

### 9.3 Native image embeddings are not implemented

Visual content is converted into text descriptions and embedded as text. The project does not currently perform direct image-vector retrieval.

### 9.4 Table extraction depends on PDF layout

Complex, scanned, or irregularly formatted tables may not be extracted correctly. Scanned documents may require OCR, which is not implemented as a complete pipeline here.

### 9.5 Vision processing has a cost

Processing multiple pages may generate multiple API calls. Selecting specific pages can reduce unnecessary calls during experimentation.

### 9.6 Retrieval quality needs a dedicated evaluation

A successful ingestion or retrieval test does not prove that the system reliably answers questions about every diagram or table.

A labeled evaluation set is needed to measure retrieval quality and inspect incorrect results.

### 9.7 End-to-end answering is outside this component's scope

This implementation focuses on ingestion and retrieval. It does not yet provide a complete user-facing multimodal question-answering API with validated citations.

## 10. Future Improvements

Possible improvements include:

- Create a labeled evaluation dataset containing questions about text, tables and diagrams.
- Measure Hit Rate@k, MRR@k, latency and API cost.
- Review vision-generated descriptions against human-verified facts.
- Improve visual-page detection beyond the current drawing heuristic.
- Add OCR for scanned PDFs.
- Add source and page citations to final answers.
- Consider native image embeddings when visual similarity search is required.
- Add end-to-end tests for answering questions using retrieved multimodal records.

## 11. Summary

This Level 3 implementation makes PDF text, tables, table rows and model-generated diagram descriptions searchable through a common Chroma collection.

The central idea is to convert visual information into descriptive text so that text-based retrieval can find information that would otherwise be difficult to search.

The important distinction is that **ingestion success, retrieval success, and answer correctness are three separate things**. Each should be evaluated independently before treating the pipeline as production-ready.
