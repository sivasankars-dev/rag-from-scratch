
"""Build contextual embeddings in isolated Level 3 stores."""

import argparse
import importlib.util
import sys
from pathlib import Path

LEVEL3 = Path(__file__).resolve().parents[1]
ROOT = LEVEL3.parents[1]
LEVEL2 = ROOT / "levels" / "level-2-practical-rag"

sys.path.insert(0, str(LEVEL3))

from services.contextual_ingestion import (
    build_contextual_record,
    embed_contextual_records,
    store_contextual_records,
)
from services.contextual_query_context import ContextualQueryContext
from services.parent_child_chunker import build_parent_child_chunks
from services.parent_child_store import ParentChildStore
from services.child_vector_store import ChildVectorStore

SOURCE = "rag_practice_employee_handbook.pdf"
PDF_PATH = ROOT / "data" / "documents" / SOURCE

DEFAULT_DATA_PATH = LEVEL3 / "data" / "contextual_retrieval"
COLLECTION_NAME = "contextual_employee_handbook"

PARENT_SIZE = 100
CHILD_SIZE = 30
CHILD_OVERLAP = 10


def load_level2_module(name, filename):
    path = LEVEL2 / "services" / filename
    spec = importlib.util.spec_from_file_location(name, path)

    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load Level 2 module: {filename}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ingest(dry_run=False, limit=None, data_path=DEFAULT_DATA_PATH):
    data_path = Path(data_path)
    parent_path = data_path / "parents.json"
    manifest_path = data_path / "contextual_chunks.json"
    chroma_path = data_path / "chroma"

    if limit is not None and limit < 1:
        raise ValueError("--limit must be at least 1")

    if not PDF_PATH.is_file():
        raise FileNotFoundError(f"Handbook PDF not found: {PDF_PATH}")

    # Never overwrite existing data accidentally.
    existing_paths = (parent_path, manifest_path, chroma_path)
    if any(path.exists() for path in existing_paths):
        raise FileExistsError(
            f"Contextual data already exists in {data_path}. "
            "Inspect it before rerunning ingestion."
        )

    loader_module = load_level2_module(
        "contextual_document_loader", "document_loader.py"
    )
    pages = loader_module.extract_text_from_pdf(PDF_PATH)

    if not pages:
        raise ValueError("The PDF contains no extractable text.")

    print(f"Pages with text: {len(pages)}")

    # Build parents and children, retaining the full parent text.
    parents = []
    children = []
    page_text_by_number = {}

    for page in pages:
        page_text = page["text"]

        if not page_text or not page_text.strip():
            continue

        page_number = page["page_number"]
        page_text_by_number[page_number] = page_text

        chunks = build_parent_child_chunks(
            text=page_text,
            source=SOURCE,
            page_number=page_number,
            parent_chunk_size=PARENT_SIZE,
            child_chunk_size=CHILD_SIZE,
            child_chunk_overlap=CHILD_OVERLAP,
        )

        parents.extend(chunks["parents"])
        children.extend(chunks["children"])

    if not children:
        raise ValueError("No child chunks were generated.")

    parent_by_id = {parent["parent_id"]: parent for parent in parents}

    if len(parent_by_id) != len(parents):
        raise ValueError("Duplicate parent IDs detected.")

    if len({child["child_id"] for child in children}) != len(children):
        raise ValueError("Duplicate child IDs detected.")

    print(f"Parent chunks: {len(parents)}")
    print(f"Child chunks: {len(children)}")

    if dry_run:
        print(
            "Dry run complete. No LLM calls, embeddings, or storage writes."
        )
        return

    if limit is not None:
        children = children[:limit]
        print(f"Limited ingestion: {len(children)} child chunks")

    # Generate contextual descriptions using the Level 2 OpenAI client.
    llm_module = load_level2_module(
        "contextual_llm_client", "llm_client.py"
    )
    context_generator = ContextualQueryContext(
        llm_client=llm_module.OpenAILLMClient()
    )

    records = []

    for index, child in enumerate(children, start=1):
        parent = parent_by_id[child["parent_id"]]
        page_text = page_text_by_number[child["page_number"]]

        record = build_contextual_record(
            document_text=page_text,
            child=child,
            context_generator=context_generator,
            parent=parent,
        )
        records.append(record)

        if index % 10 == 0 or index == len(children):
            print(f"Generated context for {index}/{len(children)} children")

    # Complete embedding before writing to persistent stores.
    embedding_module = load_level2_module(
        "contextual_embedding_service", "embedding_service.py"
    )
    embedding_service = embedding_module.EmbeddingService()
    embeddings = embed_contextual_records(records, embedding_service)

    if len(embeddings) != len(records):
        raise ValueError("Embedding count mismatch; refusing to store.")

    print(f"Generated embeddings: {len(embeddings)}")

    # Use dedicated contextual stores, not parent-child baseline stores.
    parent_store = ParentChildStore(storage_path=str(parent_path))
    child_store = ChildVectorStore(
        persist_directory=str(chroma_path),
        collection_name=COLLECTION_NAME,
    )

    store_contextual_records(
        records=records,
        embeddings=embeddings,
        parent_store=parent_store,
        child_vector_store=child_store,
        manifest_path=manifest_path,
    )

    print(f"Manifest: {manifest_path}")
    print(f"Stored parents: {len(parent_store.parents)}")
    print(f"Stored children: {child_store.collection.count()}")
    print("Contextual ingestion completed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Build contextual retrieval data."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count chunks without calling the LLM or writing data.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only the first N child chunks.",
    )
    parser.add_argument(
        "--data-path",
        type=Path,
        default=DEFAULT_DATA_PATH,
        help="Directory for contextual data and Chroma storage.",
    )

    args = parser.parse_args()
    ingest(
        dry_run=args.dry_run,
        limit=args.limit,
        data_path=args.data_path,
    )
