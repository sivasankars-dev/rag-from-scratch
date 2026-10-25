"""Run ingestion for the Level 3 multimodal PDF pipeline."""

import argparse
import importlib.util
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
LEVEL2 = ROOT / "levels" / "level-2-practical-rag"
LEVEL3 = ROOT / "levels" / "level-3-advanced-rag"
DEFAULT_PDF_PATH = (
    ROOT / "data" / "documents" / "rag_practice_employee_handbook.pdf"
)

sys.path.insert(0, str(LEVEL3))


def load_module(module_name, file_path):
    """Load a module from an explicit path to avoid namespace conflicts."""
    spec = importlib.util.spec_from_file_location(module_name, file_path)

    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {file_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(
        description="Ingest a PDF into the multimodal Chroma collection."
    )
    parser.add_argument(
        "--pdf",
        type=Path,
        default=DEFAULT_PDF_PATH,
        help="PDF to ingest (default: employee handbook).",
    )
    parser.add_argument(
        "--visual-pages",
        type=int,
        nargs="*",
        default=None,
        help="1-based pages to describe with vision; omit to process all pages with drawings.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Extract records and report counts without embedding or storing.",
    )
    args = parser.parse_args()
    pdf_path = args.pdf if args.pdf.is_absolute() else ROOT / args.pdf

    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    from services.multimodal.multimodal_pdf_loader import load_pdf_records

    records = load_pdf_records(pdf_path)
    counts = Counter(record["content_type"] for record in records)

    print(f"PDF: {pdf_path}")
    print(f"Extracted records: {len(records)}")
    print(f"Pages represented: {len({r['page_number'] for r in records})}")
    print(f"Records by type: {dict(sorted(counts.items()))}")

    if args.dry_run:
        print("Dry run complete. No embeddings created; nothing stored.")
        return

    embedding_module = load_module(
        "level2_embedding_service",
        LEVEL2 / "services" / "embedding_service.py",
    )

    from services.multimodal.multimodal_ingestion import (
        MultimodalIngestionService,
    )
    from services.multimodal.multimodal_vector_store import (
        MultimodalVectorStore,
    )
    from services.multimodal.pdf_page_renderer import PDFPageRenderer
    from services.multimodal.vision_description_service import (
        VisionDescriptionService,
    )

    embedding_service = embedding_module.EmbeddingService()
    vector_store = MultimodalVectorStore(
        persist_directory=str(ROOT / "data" / "multimodal_chroma")
    )
    ingestion_service = MultimodalIngestionService(
        embedding_service=embedding_service,
        vector_store=vector_store,
        vision_description_service=VisionDescriptionService(),
        page_renderer=PDFPageRenderer(),
        visual_pages=(
            set(args.visual_pages)
            if args.visual_pages is not None
            else None
        ),
    )

    result = ingestion_service.ingest_pdf(pdf_path)
    print("\nIngestion complete:")
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
