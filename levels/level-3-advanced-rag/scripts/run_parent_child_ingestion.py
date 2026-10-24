"""Replace this handbook's records in the dedicated Level 3 stores."""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile

LEVEL3 = Path(__file__).resolve().parents[1]
ROOT = LEVEL3.parents[1]
LEVEL2 = ROOT / "levels" / "level-2-practical-rag"
sys.path.insert(0, str(LEVEL3))

from services.child_vector_store import ChildVectorStore
from services.document_section_parser import parse_document_sections
from services.hierarchical_chunker import build_document_aware_chunks
from services.parent_child_store import ParentChildStore

SOURCE = "rag_practice_employee_handbook.pdf"
PDF_PATH = ROOT / "data" / "documents" / SOURCE
DATA_PATH = LEVEL3 / "data" / "parent_child"
PARENT_PATH = DATA_PATH / "parents.json"
CHROMA_PATH = DATA_PATH / "chroma"
COLLECTION_NAME = "parent_child_employee_handbook"

PARENT_SIZE = 100
CHILD_SIZE = 30
CHILD_OVERLAP = 10


def load_level2_module(name, filename):
    spec = importlib.util.spec_from_file_location(
        name,
        LEVEL2 / "services" / filename,
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load Level 2 module: {filename}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def replace_parent_records(path, records):
    """Write retained records atomically; never unlink the existing JSON first."""
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(records, handle, ensure_ascii=False, indent=2)

        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def ingest(
    load_pages,
    embedding_factory,
    parent_factory=ParentChildStore,
    child_factory=ChildVectorStore,
):
    """Prepare and validate all chunks/embeddings before replacing stored data."""
    pages = load_pages(PDF_PATH)
    print(f"Extracted pages with text: {len(pages)}")

    page_numbers = [page["page_number"] for page in pages]
    if len(set(page_numbers)) != len(page_numbers):
        raise ValueError(
            "Duplicate parent IDs would result from duplicate page numbers."
        )

    sections = parse_document_sections(pages, source=SOURCE)
    print(f"Parsed document sections: {len(sections)}")

    chunked = build_document_aware_chunks(
        sections=sections,
        source=SOURCE,
        parent_chunk_size=PARENT_SIZE,
        child_chunk_size=CHILD_SIZE,
        child_chunk_overlap=CHILD_OVERLAP,
    )
    parents = chunked["parents"]
    children = chunked["children"]

    print(f"Parent chunks: {len(parents)}")
    print(f"Child chunks: {len(children)}")

    if not children:
        raise ValueError(
            "No nonempty child chunks; existing stores were not reset."
        )

    if len({p["parent_id"] for p in parents}) != len(parents):
        raise ValueError("Duplicate parent IDs; existing stores were not reset.")

    if len({c["child_id"] for c in children}) != len(children):
        raise ValueError("Duplicate child IDs; existing stores were not reset.")

    # Complete embedding preparation before touching existing stores.
    embeddings = embedding_factory().embed_texts(
        [child["text"] for child in children]
    )
    if len(embeddings) != len(children):
        raise ValueError(
            "Embedding count does not match child count; stores not reset."
        )
    print(f"Embedded children: {len(embeddings)}")

    # Load and validate the existing parent JSON before deleting child records.
    parent_store = parent_factory(storage_path=PARENT_PATH)
    retained = {
        key: value
        for key, value in parent_store.parents.items()
        if value.get("source") != SOURCE
    }

    child_store = child_factory(
        persist_directory=str(CHROMA_PATH),
        collection_name=COLLECTION_NAME,
    )

    print(f"Replacing source {SOURCE} in {DATA_PATH}")

    child_store.collection.delete(where={"source": SOURCE})
    replace_parent_records(PARENT_PATH, retained)

    parent_store = parent_factory(storage_path=PARENT_PATH)
    for parent in parents:
        parent_store.store_parent(parent)

    child_store.store_children(children, embeddings)

    reloaded = parent_factory(storage_path=PARENT_PATH)
    stored_parent_ids = {
        key
        for key, value in reloaded.parents.items()
        if value.get("source") == SOURCE
    }
    stored_child_ids = set(
        child_store.collection.get(
            where={"source": SOURCE},
            include=["metadatas"],
        )["ids"]
    )

    print(f"Persisted parents: {len(stored_parent_ids)}")
    print(f"Stored children: {len(stored_child_ids)}")

    if stored_parent_ids != {parent["parent_id"] for parent in parents}:
        raise RuntimeError(
            "Persisted parent IDs/count differ from expected records."
        )

    if stored_child_ids != {child["child_id"] for child in children}:
        raise RuntimeError(
            "Stored child IDs/count differ from expected records."
        )

    print("Document-aware handbook ingestion completed successfully.")
    return {
        "pages": len(pages),
        "parents": len(parents),
        "children": len(children),
    }


def main():
    loader = load_level2_module(
        "level2_document_loader",
        "document_loader.py",
    )

    # Initialize the embedding model only after nonempty chunks exist.
    def embedding_factory():
        module = load_level2_module(
            "level2_embedding_service",
            "embedding_service.py",
        )
        return module.EmbeddingService()

    ingest(loader.extract_text_from_pdf, embedding_factory)


if __name__ == "__main__":
    main()
