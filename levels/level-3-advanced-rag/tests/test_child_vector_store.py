
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


def test_store_and_retrieve_hierarchical_metadata(child_store):
    children = [{
        "child_id": "handbook_section_2_2_parent_0_child_0",
        "parent_id": "handbook_section_2_2_parent_0",
        "text": "Remote employees must protect company equipment.",
        "source": "handbook.pdf",
        "page_number": 3,
        "document_id": "employee_handbook",
        "section_id": "section_2_2",
        "section_number": "2.2",
        "section_title": "Remote Work",
        "section_type": "section",
        "parent_section_id": "section_2",
        "section_path": "Working Hours > Remote Work",
        "section_start_page": 3,
        "section_end_page": 4,
    }]

    child_store.store_children(children, [[1.0, 0.0, 0.0]])

    result = child_store.get_child_by_id(
        "handbook_section_2_2_parent_0_child_0"
    )
    metadata = result["metadata"]

    assert metadata["parent_id"] == "handbook_section_2_2_parent_0"
    assert metadata["document_id"] == "employee_handbook"
    assert metadata["section_id"] == "section_2_2"
    assert metadata["section_title"] == "Remote Work"
    assert metadata["section_type"] == "section"
    assert metadata["parent_section_id"] == "section_2"
    assert metadata["section_path"] == "Working Hours > Remote Work"
    assert metadata["section_start_page"] == 3
    assert metadata["section_end_page"] == 4


def test_store_children_omits_optional_none_metadata(child_store):
    children = [{
        "child_id": "preamble_child_0",
        "parent_id": "preamble_parent_0",
        "text": "Introduction to the handbook.",
        "source": "handbook.pdf",
        "page_number": 1,
        "document_id": "handbook.pdf",
        "section_id": "handbook.pdf::preamble",
        "section_number": None,
        "section_title": "Document Introduction",
        "section_type": "preamble",
        "parent_section_id": None,
        "section_path": "Document Introduction",
        "section_start_page": 1,
        "section_end_page": 1,
    }]

    child_store.store_children(children, [[1.0, 0.0, 0.0]])

    result = child_store.get_child_by_id("preamble_child_0")
    metadata = result["metadata"]

    assert metadata["section_id"] == "handbook.pdf::preamble"
    assert metadata["section_title"] == "Document Introduction"
    assert "section_number" not in metadata
    assert "parent_section_id" not in metadata
