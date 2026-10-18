"""Evaluate contextual child embeddings against original parent text."""

import argparse
import importlib.util
from pathlib import Path
import sys

LEVEL3 = Path(__file__).resolve().parents[1]
ROOT = LEVEL3.parents[1]
LEVEL2 = ROOT / "levels" / "level-2-practical-rag"
sys.path.insert(0, str(LEVEL3))

from services.parent_child_evaluator import (
    PROXY_NOTICE, evaluate, format_report, load_cases,
)

DATASET_PATH = LEVEL3 / "data" / "employee_handbook_challenging_evaluation.json"
PARENT_PATH = LEVEL3 / "data" / "contextual_retrieval_full" / "parents.json"
CHROMA_PATH = LEVEL3 / "data" / "contextual_retrieval_full" / "chroma"
COLLECTION_NAME = "contextual_employee_handbook"
INGEST_HINT = "Inspect the completed contextual_retrieval_full ingestion; evaluation never creates or repairs data."


def load_stores(cases, parent_factory, child_factory, client_factory,
                parent_path=PARENT_PATH, chroma_path=CHROMA_PATH):
    """Validate existing stores before loading embeddings or running queries."""
    parent_path, chroma_path = Path(parent_path), Path(chroma_path)
    if not parent_path.is_file():
        raise ValueError(f"Missing parent store: {parent_path}. {INGEST_HINT}")
    if not (chroma_path / "chroma.sqlite3").is_file():
        raise ValueError(f"Missing persistent Chroma database: {chroma_path}. {INGEST_HINT}")
    try:
        parents = parent_factory(storage_path=parent_path)
        if not isinstance(parents.parents, dict) or not parents.parents:
            raise ValueError("Parent store is empty or is not an ID-to-record mapping")
        for key, record in parents.parents.items():
            if not isinstance(record, dict) or record.get("parent_id") != key:
                raise ValueError(f"Invalid parent record: {key}")
            for field in ("source", "text"):
                if not isinstance(record.get(field), str) or not record[field].strip():
                    raise ValueError(f"Parent {key}: missing/nonempty string required for {field}")
        # get_collection fails if absent; do not silently create an empty collection.
        client = client_factory(path=str(chroma_path))
        collection = client.get_collection(name=COLLECTION_NAME)
        if collection.count() == 0:
            raise ValueError("Child collection is empty")
        stored = collection.get(include=["metadatas"])
        sources = set()
        for metadata in stored["metadatas"]:
            if not isinstance(metadata, dict):
                raise ValueError("Child metadata is missing")
            parent = parents.get_parent(metadata.get("parent_id"))
            if parent is None or parent["source"] != metadata.get("source"):
                raise ValueError("Child has missing parent or inconsistent source metadata")
            sources.add(parent["source"])
        required = {case["expected_source"] for case in cases}
        if not required.issubset(sources):
            raise ValueError(f"No indexed children for expected sources: {required - sources}")
        children = child_factory(client=client, collection=collection)
    except Exception as exc:
        raise ValueError(f"Cannot use contextual stores: {exc}. {INGEST_HINT}") from exc
    return parents, children


def existing_child_store(client, collection):
    """Reuse search behavior without invoking the get-or-create constructor."""
    from services.child_vector_store import ChildVectorStore

    class ExistingChildVectorStore(ChildVectorStore):
        def __init__(self):
            self.client = client
            self.collection = collection

    return ExistingChildVectorStore()


def load_embedding_service():
    path = LEVEL2 / "services" / "embedding_service.py"
    spec = importlib.util.spec_from_file_location("level2_contextual_eval_embedding", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load embedding service: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.EmbeddingService()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--show-context", action="store_true",
        help="Show returned parent previews for failed text-proxy matches.",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    print(PROXY_NOTICE)
    cases = load_cases(DATASET_PATH, expected_count=20)
    # Imports are delayed so offline helper and preflight tests need no Chroma/model.
    import chromadb
    from services.parent_child_store import ParentChildStore
    from services.parent_child_retrieval import ParentChildRetrievalService

    parents, children = load_stores(
        cases, ParentChildStore, existing_child_store, chromadb.PersistentClient
    )
    retrieval = ParentChildRetrievalService(
        embedding_service=load_embedding_service(),
        child_vector_store=children,
        parent_store=parents,
    )
    print("Contextual Retrieval — substring/source relevance proxies, not semantic answer quality")
    print(f"Dataset: {DATASET_PATH}")
    print(f"Parents: {PARENT_PATH}\nChroma: {CHROMA_PATH}\nCollection: {COLLECTION_NAME}")
    print(format_report(evaluate(cases, retrieval, top_k=3, show_context=args.show_context)))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as exc:
        raise SystemExit(f"Evaluation failed: {exc}") from exc
