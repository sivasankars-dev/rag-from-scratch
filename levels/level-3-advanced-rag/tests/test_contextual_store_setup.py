import pytest
from services.child_vector_store import ChildVectorStore
from services.parent_child_store import ParentChildStore
from services.contextual_ingestion import store_contextual_records



def test_contextual_stores_use_separate_paths(tmp_path):
    contextual_dir = tmp_path / "contextual_retrieval"

    parent_store = ParentChildStore(
        storage_path=str(contextual_dir / "parents.json")
    )

    child_store = ChildVectorStore(
        persist_directory=str(contextual_dir / "chroma"),
        collection_name="contextual_employee_handbook",
    )

    parent = {
        "parent_id": "parent_1",
        "text": "Annual leave policy.",
        "source": "employee_handbook.pdf",
        "page_number": 2,
    }

    parent_store.store_parent(parent)

    child = {
        "child_id": "child_1",
        "text": "Employees receive 20 annual leave days.",
        "parent_id": "parent_1",
        "source": "employee_handbook.pdf",
        "page_number": 2,
    }

    child_store.store_children(
        [child],
        embeddings=[[0.1, 0.2, 0.3]],
    )

    assert parent_store.get_parent("parent_1") == parent
    assert child_store.get_child_by_id("child_1")["text"] == child["text"]
    assert child_store.collection.count() == 1


import json

from services.contextual_ingestion import store_contextual_records


def test_stores_contextual_records_and_manifest(tmp_path):
    contextual_dir = tmp_path / "contextual_retrieval"

    parent_store = ParentChildStore(
        storage_path=str(contextual_dir / "parents.json")
    )
    child_store = ChildVectorStore(
        persist_directory=str(contextual_dir / "chroma"),
        collection_name="contextual_employee_handbook",
    )

    records = [
        {
            "child_id": "child_1",
            "parent_id": "parent_1",
            "original_text": "Employees receive 20 annual leave days.",
            "context": "This section explains annual leave policy.",
            "retrieval_text": (
                "This section explains annual leave policy.\n\n"
                "Employees receive 20 annual leave days."
            ),
            "parent_text": "Employees receive 20 annual leave days under company policy.",
            "source": "employee_handbook.pdf",
            "page_number": 2,
        }
    ]

    embeddings = [[0.1, 0.2, 0.3]]
    manifest_path = contextual_dir / "contextual_chunks.json"

    store_contextual_records(
        records=records,
        embeddings=embeddings,
        parent_store=parent_store,
        child_vector_store=child_store,
        manifest_path=manifest_path,
    )

    saved_manifest = json.loads(
        manifest_path.read_text(encoding="utf-8")
    )

    saved_child = child_store.get_child_by_id("child_1")

    assert saved_manifest["child_1"]["context"] == (
        "This section explains annual leave policy."
    )
    assert saved_manifest["child_1"]["retrieval_text"] == (
        records[0]["retrieval_text"]
    )
    assert saved_manifest["child_1"]["original_text"] == (
        records[0]["original_text"]
    )
    assert saved_child["text"] == records[0]["retrieval_text"]
    assert parent_store.get_parent("parent_1")["text"] == (
        records[0]["parent_text"]
    )
    assert child_store.collection.count() == 1

def test_embedding_count_mismatch_writes_nothing(tmp_path):
    contextual_dir = tmp_path / "contextual_retrieval"

    parent_store = ParentChildStore(
        storage_path=str(contextual_dir / "parents.json")
    )
    child_store = ChildVectorStore(
        persist_directory=str(contextual_dir / "chroma"),
        collection_name="contextual_employee_handbook",
    )

    manifest_path = contextual_dir / "contextual_chunks.json"

    records = [
        {
            "child_id": "child_1",
            "parent_id": "parent_1",
            "original_text": "Annual leave is 20 days.",
            "context": "Annual leave policy.",
            "retrieval_text": "Annual leave policy.\n\nAnnual leave is 20 days.",
            "parent_text": "Annual leave is 20 days.",
            "source": "employee_handbook.pdf",
            "page_number": 2,
        }
    ]

    with pytest.raises(ValueError, match="count must match"):
        store_contextual_records(
            records=records,
            embeddings=[],
            parent_store=parent_store,
            child_vector_store=child_store,
            manifest_path=manifest_path,
        )

    assert not manifest_path.exists()
    assert parent_store.get_parent("parent_1") is None
    assert child_store.collection.count() == 0
