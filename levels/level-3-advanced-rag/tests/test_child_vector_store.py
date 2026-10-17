
import pytest

from services.child_vector_store import ChildVectorStore


@pytest.fixture
def child_store(tmp_path):
    return ChildVectorStore(
        persist_directory=str(tmp_path / "chroma"),
        collection_name="test_parent_child",
    )


def test_store_child_chunks(child_store):
    children = [
        {
            "child_id": "handbook_parent_0_child_0",
            "parent_id": "handbook_parent_0",
            "text": "Employees receive annual leave.",
            "source": "handbook.pdf",
            "page_number": 1,
        }
    ]

    embeddings = [[0.1, 0.2, 0.3]]

    child_store.store_children(children, embeddings)

    result = child_store.get_child_by_id(
        "handbook_parent_0_child_0"
    )

    assert result["text"] == "Employees receive annual leave."
    assert result["metadata"]["parent_id"] == "handbook_parent_0"


def test_search_returns_parent_id(child_store):
    children = [
        {
            "child_id": "handbook_parent_0_child_0",
            "parent_id": "handbook_parent_0",
            "text": "Employees receive annual leave.",
            "source": "handbook.pdf",
            "page_number": 1,
        }
    ]

    embeddings = [[1.0, 0.0, 0.0]]

    child_store.store_children(children, embeddings)

    result = child_store.search(
        query_embedding=[1.0, 0.0, 0.0],
        top_k=1,
    )

    assert len(result) == 1
    assert result[0]["metadata"]["parent_id"] == "handbook_parent_0"


def test_store_empty_children_does_nothing(child_store):
    child_store.store_children([], [])

    result = child_store.search(
        query_embedding=[1.0, 0.0, 0.0],
        top_k=1,
    )

    assert result == []
