# Step 2 — PDF to text extraction

## What are we learning, and why is extraction required?

A PDF stores instructions for displaying pages: text positions, fonts, images and other objects. Our text embedding model accepts text strings, not PDF bytes. Parsing is the first ingestion step because it turns the document into something the chunker and model can process.

## Simple analogy

A PDF is a photographed or printed page in a binder. Extraction copies the readable words onto a plain sheet before we cut the sheet into useful pieces.

## Technical explanation and existing implementation

[`extract_text_from_pdf`](../app/services/document_loader.py) uses `pypdf.PdfReader`. It visits each page, calls `page.extract_text()`, keeps nonempty results and joins them with a newline:

```python
pdf_reader = PdfReader(file_path)
pages = []
for page in pdf_reader.pages:
    text = page.extract_text()
    if text:
        pages.append(text)
return "\n".join(pages)
```

Internally the parser interprets the page's text objects and produces Python strings. The helper does not preserve page metadata, identify sections, parse table cells, or run OCR. Both the upload endpoint and ingestion script call this same function.

## Input/output example

Input: `data/documents/company_policy.pdf`, one page. Actual extracted length: **343 characters**, including line breaks. It begins:

```text
Company Leave Policy
Annual Leave:
Employees are entitled to 20 days of annual leave per year.
Carry Forward:
```

The rest discusses carry-forward (10 days), sick leave (12 days) and parental leave. `company_policy_one.pdf` is an alternate one-page sample with a table-like layout and extra introductory text; the ingestion script does not use it. `docs/uploads/company_policy.pdf` was a generated copy and is ignored by Git.

Run a direct extraction from the repository root:

```bash
.venv/bin/python -c 'from app.services.document_loader import extract_text_from_pdf; text = extract_text_from_pdf("data/documents/company_policy.pdf"); print(len(text)); print(text)'
```

## Corrections found during validation

The original helper joined pages with `"/n"`, which inserts a slash and letter n. We changed it to `"\n"`, a newline. The one-page sample could not expose this bug, so a regression test builds a two-page PDF from the real sample.

The upload route originally joined the supplied filename directly to its directory. A filename containing `../` could escape that directory. Taking `Path(file.filename).name` keeps this existing upload behavior inside `docs/uploads`. This is a small correction to the current route, not a new ingestion API.

## Common problems and OCR

- Text PDFs usually expose text objects, but reading order can be surprising.
- Tables may become lines of words with row/column relationships lost.
- Images and scans need optical character recognition (OCR), which recognizes letters from pixels. pypdf itself does not perform OCR. A scan with an existing OCR text layer may be extractable. See the [pypdf extraction guide](https://github.com/py-pdf/pypdf/blob/main/docs/user/extract-text.md).
- Corrupt or encrypted files can fail. The current route checks the filename extension; it is not a comprehensive PDF validator.
- Empty extraction is possible. The helper returns an empty string when no page yields text.
- Bad reading order or missing text propagates into chunks, embeddings and retrieval. A vector database cannot restore missing source text.

## Interview questions

1. Why not embed the PDF directly? This model expects text, so binary page structure must first be parsed.
2. Does extracting text mean understanding tables? No; layout relationships need separate processing.
3. When do we need OCR? When the words exist only as image pixels.
4. Why test more than one page? Page joining is invisible on a single-page input.

## What I learned

Document parsing determines what information reaches the rest of RAG. A tiny sample is useful, but it cannot reveal every parser or layout problem.

## Next step

[Step 3 — Chunking](03-chunking.md).
