from services.vector_store import VectorStore


def test_upsert_processed_chunks(tmp_path):
    vector_store = VectorStore(
        persist_directory=str(tmp_path),
        collection_name="test_metadata",
    )

    processed_chunks = [
        {
            "chunk": "Employees get annual leave.",
            "page_number": 1,
            "chunk_index": 0,
            "source": "employee_handbook.pdf",
            "document_type": "hr_policy",
        }
    ]

    embeddings = [[0.1, 0.2, 0.3]]

    vector_store.upsert_processed_chunks(
        processed_chunks,
        embeddings,
    )

    result = vector_store.collection.get(
        ids=["employee_handbook.pdf_chunk_0"],
        include=["documents", "metadatas"],
    )

    assert len(result["documents"]) == 1
    assert result["documents"][0] == "Employees get annual leave."

    assert result["metadatas"][0]["source"] == "employee_handbook.pdf"
    assert result["metadatas"][0]["document_type"] == "hr_policy"
    assert result["metadatas"][0]["page_number"] == 1
    assert result["metadatas"][0]["chunk_index"] == 0


def test_upsert_multiple_processed_chunks(tmp_path):
    vector_store = VectorStore(
        persist_directory=str(tmp_path),
        collection_name="test_metadata",
    )

    processed_chunks = [
        {
            "chunk": "Employees get annual leave.",
            "page_number": 1,
            "chunk_index": 0,
            "source": "employee_handbook.pdf",
            "document_type": "hr_policy",
        },
        {
            "chunk": "Employees can carry forward unused leave.",
            "page_number": 2,
            "chunk_index": 1,
            "source": "employee_handbook.pdf",
            "document_type": "hr_policy",
        },
    ]

    embeddings = [
        [0.1, 0.2, 0.3],
        [0.4, 0.5, 0.6],
    ]

    vector_store.upsert_processed_chunks(
        processed_chunks,
        embeddings,
    )

    result = vector_store.collection.get(
        ids=[
            "employee_handbook.pdf_chunk_0",
            "employee_handbook.pdf_chunk_1",
        ],
        include=["documents", "metadatas"],
    )

    assert len(result["documents"]) == 2

    assert result["documents"][0] == "Employees get annual leave."
    assert result["documents"][1] == "Employees can carry forward unused leave."

    assert result["metadatas"][0]["source"] == "employee_handbook.pdf"
    assert result["metadatas"][0]["document_type"] == "hr_policy"
    assert result["metadatas"][0]["page_number"] == 1
    assert result["metadatas"][0]["chunk_index"] == 0

    assert result["metadatas"][1]["source"] == "employee_handbook.pdf"
    assert result["metadatas"][1]["document_type"] == "hr_policy"
    assert result["metadatas"][1]["page_number"] == 2
    assert result["metadatas"][1]["chunk_index"] == 1


def test_upsert_different_document_types(tmp_path):
    vector_store = VectorStore(
        persist_directory=str(tmp_path),
        collection_name="test_metadata",
    )

    processed_chunks = [
        {
            "chunk": "Employees get annual leave.",
            "page_number": 1,
            "chunk_index": 0,
            "source": "employee_handbook.pdf",
            "document_type": "hr_policy",
        },
        {
            "chunk": "Use strong passwords for all accounts.",
            "page_number": 1,
            "chunk_index": 1,
            "source": "security_handbook.pdf",
            "document_type": "security_policy",
        },
    ]

    embeddings = [
        [0.1, 0.2, 0.3],
        [0.4, 0.5, 0.6],
    ]

    vector_store.upsert_processed_chunks(
        processed_chunks,
        embeddings,
    )

    result = vector_store.collection.get(
        include=["documents", "metadatas"],
    )

    assert len(result["documents"]) == 2

    document_types = {
        metadata["document_type"]
        for metadata in result["metadatas"]
    }

    assert document_types == {
        "hr_policy",
        "security_policy",
    }


def test_upsert_empty_processed_chunks(tmp_path):
    vector_store = VectorStore(
        persist_directory=str(tmp_path),
        collection_name="test_metadata",
    )

    vector_store.upsert_processed_chunks(
        [],
        [],
    )

    assert vector_store.collection.count() == 0
    
def test_search_with_document_type_filter(tmp_path):
    vector_store = VectorStore(
        persist_directory=str(tmp_path),
        collection_name="test_metadata",
    )

    processed_chunks = [
        {
            "chunk": "Employees get annual leave.",
            "page_number": 1,
            "chunk_index": 0,
            "source": "employee_handbook.pdf",
            "document_type": "hr_policy",
        },
        {
            "chunk": "Use strong passwords for all accounts.",
            "page_number": 1,
            "chunk_index": 1,
            "source": "security_handbook.pdf",
            "document_type": "security_policy",
        },
    ]

    embeddings = [
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
    ]

    vector_store.upsert_processed_chunks(
        processed_chunks,
        embeddings,
    )

    result = vector_store.search(
        query_embedding=[1.0, 0.0, 0.0],
        top_k=2,
        where={"document_type": "hr_policy"},
    )

    assert len(result["documents"][0]) == 1
    assert result["documents"][0][0] == "Employees get annual leave."

    assert result["metadatas"][0][0]["document_type"] == "hr_policy"
    
def test_search_with_source_filter(tmp_path):
    vector_store = VectorStore(
        persist_directory=str(tmp_path),
        collection_name="test_metadata",
    )

    processed_chunks = [
        {
            "chunk": "Employees get annual leave.",
            "page_number": 1,
            "chunk_index": 0,
            "source": "employee_handbook.pdf",
            "document_type": "hr_policy",
        },
        {
            "chunk": "Employees can work remotely.",
            "page_number": 2,
            "chunk_index": 1,
            "source": "remote_work_policy.pdf",
            "document_type": "hr_policy",
        },
    ]

    embeddings = [
        [1.0, 0.0, 0.0],
        [0.9, 0.1, 0.0],
    ]

    vector_store.upsert_processed_chunks(
        processed_chunks,
        embeddings,
    )

    result = vector_store.search(
        query_embedding=[1.0, 0.0, 0.0],
        top_k=2,
        where={"source": "employee_handbook.pdf"},
    )

    assert len(result["documents"][0]) == 1
    assert result["documents"][0][0] == "Employees get annual leave."

    assert result["metadatas"][0][0]["source"] == "employee_handbook.pdf"
    
def test_search_with_page_number_filter(tmp_path):
    vector_store = VectorStore(
        persist_directory=str(tmp_path),
        collection_name="test_metadata",
    )

    processed_chunks = [
        {
            "chunk": "Employees get annual leave.",
            "page_number": 1,
            "chunk_index": 0,
            "source": "employee_handbook.pdf",
            "document_type": "hr_policy",
        },
        {
            "chunk": "Employees can carry forward unused leave.",
            "page_number": 2,
            "chunk_index": 1,
            "source": "employee_handbook.pdf",
            "document_type": "hr_policy",
        },
    ]

    embeddings = [
        [1.0, 0.0, 0.0],
        [0.9, 0.1, 0.0],
    ]

    vector_store.upsert_processed_chunks(
        processed_chunks,
        embeddings,
    )

    result = vector_store.search(
        query_embedding=[1.0, 0.0, 0.0],
        top_k=2,
        where={"page_number": 2},
    )

    assert len(result["documents"][0]) == 1
    assert result["documents"][0][0] == "Employees can carry forward unused leave."

    assert result["metadatas"][0][0]["page_number"] == 2
    
def test_search_with_combined_metadata_filters(tmp_path):
    vector_store = VectorStore(
        persist_directory=str(tmp_path),
        collection_name="test_metadata",
    )

    processed_chunks = [
        {
            "chunk": "Employees get annual leave.",
            "page_number": 1,
            "chunk_index": 0,
            "source": "employee_handbook.pdf",
            "document_type": "hr_policy",
        },
        {
            "chunk": "Employees can work remotely.",
            "page_number": 1,
            "chunk_index": 1,
            "source": "remote_work_policy.pdf",
            "document_type": "hr_policy",
        },
        {
            "chunk": "Use strong passwords for all accounts.",
            "page_number": 1,
            "chunk_index": 2,
            "source": "security_handbook.pdf",
            "document_type": "security_policy",
        },
    ]

    embeddings = [
        [1.0, 0.0, 0.0],
        [0.9, 0.1, 0.0],
        [0.8, 0.2, 0.0],
    ]

    vector_store.upsert_processed_chunks(
        processed_chunks,
        embeddings,
    )

    result = vector_store.search(
        query_embedding=[1.0, 0.0, 0.0],
        top_k=3,
        where={
            "$and": [
                {"document_type": "hr_policy"},
                {"source": "employee_handbook.pdf"},
            ]
        },
    )

    assert len(result["documents"][0]) == 1
    assert result["documents"][0][0] == "Employees get annual leave."

    assert result["metadatas"][0][0]["document_type"] == "hr_policy"
    assert result["metadatas"][0][0]["source"] == "employee_handbook.pdf"