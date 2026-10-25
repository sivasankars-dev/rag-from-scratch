
import pytest

from services.multimodal.multimodal_vector_store import (
    MultimodalVectorStore,
)


@pytest.fixture
def store(tmp_path):
    return MultimodalVectorStore(
        persist_directory=str(tmp_path / "chroma"),
        collection_name="test_multimodal_records",
    )


def test_upsert_and_search_preserves_record_metadata(store):
    records = [
        {
            "record_id": "handbook:page:8:table:1",
            "source": "handbook.pdf",
            "page_number": 8,
            "content_type": "table",
            "text": (
                "Severity: SEV-1; "
                "Initial Response: Immediate response and incident leadership"
            ),
        }
    ]

    store.upsert_records(records, embeddings=[[0.1, 0.2, 0.3]])

    result = store.search(
        query_embedding=[0.1, 0.2, 0.3],
        top_k=3,
    )

    assert result["ids"][0] == ["handbook:page:8:table:1"]
    assert result["metadatas"][0][0]["content_type"] == "table"
    assert result["metadatas"][0][0]["page_number"] == 8
    assert "SEV-1" in result["documents"][0][0]


def test_upsert_rejects_mismatched_embedding_count(store):
    records = [
        {
            "record_id": "handbook:page:8:table:1",
            "source": "handbook.pdf",
            "page_number": 8,
            "content_type": "table",
            "text": "Severity: SEV-1",
        }
    ]

    with pytest.raises(ValueError, match="match"):
        store.upsert_records(records, embeddings=[])


def test_upsert_rejects_missing_metadata(store):
    records = [
        {
            "record_id": "handbook:page:8:table:1",
            "source": "handbook.pdf",
            "page_number": 8,
            "text": "Severity: SEV-1",
        }
    ]

    with pytest.raises(ValueError, match="content_type"):
        store.upsert_records(records, embeddings=[[0.1, 0.2, 0.3]])


def test_search_returns_empty_results_for_empty_collection(store):
    result = store.search(query_embedding=[0.1, 0.2, 0.3])

    assert result["ids"] == [[]]
    assert result["documents"] == [[]]
    assert result["metadatas"] == [[]]
    assert result["distances"] == [[]]


def test_upsert_rejects_blank_record_text(store):
    records = [
        {
            "record_id": "handbook:page:8:text",
            "source": "handbook.pdf",
            "page_number": 8,
            "content_type": "text",
            "text": "   ",
        }
    ]

    with pytest.raises(ValueError, match="empty"):
        store.upsert_records(records, embeddings=[[0.1, 0.2, 0.3]])
        
def test_replace_source_records_removes_stale_records_and_preserves_other_sources(
    store,
):
    handbook_records = [
        {
            "record_id": "handbook:page:1:text",
            "source": "handbook.pdf",
            "page_number": 1,
            "content_type": "text",
            "text": "Updated handbook content",
        }
    ]
    other_records = [
        {
            "record_id": "policy:page:1:text",
            "source": "policy.pdf",
            "page_number": 1,
            "content_type": "text",
            "text": "Separate policy content",
        }
    ]

    store.upsert_records(
        [
            {
                "record_id": "handbook:page:1:text",
                "source": "handbook.pdf",
                "page_number": 1,
                "content_type": "text",
                "text": "Old handbook content",
            },
            {
                "record_id": "handbook:page:2:text",
                "source": "handbook.pdf",
                "page_number": 2,
                "content_type": "text",
                "text": "Stale handbook content",
            },
        ],
        embeddings=[[0.1, 0.2, 0.3], [0.2, 0.3, 0.4]],
    )
    store.upsert_records(
        other_records,
        embeddings=[[0.3, 0.4, 0.5]],
    )

    store.replace_source_records(
        source="handbook.pdf",
        records=handbook_records,
        embeddings=[[0.5, 0.6, 0.7]],
    )

    all_records = store.collection.get(include=["metadatas", "documents"])

    assert set(all_records["ids"]) == {
        "handbook:page:1:text",
        "policy:page:1:text",
    }

    records_by_id = dict(
        zip(all_records["ids"], all_records["documents"])
    )
    assert records_by_id["handbook:page:1:text"] == (
        "Updated handbook content"
    )
    assert records_by_id["policy:page:1:text"] == (
        "Separate policy content"
    )


def test_replace_source_records_rejects_empty_records_without_deleting_data(
    store,
):
    store.upsert_records(
        [
            {
                "record_id": "handbook:page:1:text",
                "source": "handbook.pdf",
                "page_number": 1,
                "content_type": "text",
                "text": "Existing handbook content",
            }
        ],
        embeddings=[[0.1, 0.2, 0.3]],
    )

    with pytest.raises(ValueError, match="empty record list"):
        store.replace_source_records(
            source="handbook.pdf",
            records=[],
            embeddings=[],
        )

    assert store.collection.count() == 1
    
def test_upsert_and_search_preserves_table_row_metadata(store):
    records = [
        {
            "record_id": "handbook:page:8:table:1:row:1",
            "source": "handbook.pdf",
            "page_number": 8,
            "content_type": "table_row",
            "table_id": "handbook:page:8:table:1",
            "row_number": 1,
            "text": (
                "Severity: SEV-1; "
                "Typical Meaning: Critical customer or business impact; "
                "Initial Response: Immediate response and incident leadership"
            ),
        }
    ]

    store.upsert_records(
        records,
        embeddings=[[0.1, 0.2, 0.3]],
    )

    result = store.search(
        query_embedding=[0.1, 0.2, 0.3],
        top_k=1,
        where={"content_type": "table_row"},
    )

    metadata = result["metadatas"][0][0]

    assert metadata["content_type"] == "table_row"
    assert metadata["table_id"] == "handbook:page:8:table:1"
    assert metadata["row_number"] == 1
    assert metadata["page_number"] == 8
    assert "SEV-1" in result["documents"][0][0]
    
def test_upsert_and_search_retrieves_visual_description(store):
    records = [
        {
            "record_id": "diagram:page:2:visual_description",
            "source": "multimodal_rag_diagram_sample.pdf",
            "page_number": 2,
            "content_type": "visual_description",
            "text": (
                "RAG system architecture: a retriever uses vector and "
                "keyword search to find relevant text chunks. "
                "An LLM generates a source-grounded answer."
            ),
        }
    ]

    store.upsert_records(
        records,
        embeddings=[[0.1, 0.2, 0.3]],
    )

    result = store.search(
        query_embedding=[0.1, 0.2, 0.3],
        top_k=3,
        where={
            "$and": [
                {
                    "source": "multimodal_rag_diagram_sample.pdf"
                },
                {"content_type": "visual_description"},
            ]
        },
    )

    assert result["ids"][0] == [
        "diagram:page:2:visual_description"
    ]

    metadata = result["metadatas"][0][0]
    assert metadata["content_type"] == "visual_description"
    assert metadata["page_number"] == 2
    assert metadata["source"] == "multimodal_rag_diagram_sample.pdf"
    assert "retriever" in result["documents"][0][0].lower()
