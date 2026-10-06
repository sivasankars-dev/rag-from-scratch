from services.retrieval import RetrievalService
from services.vector_store import VectorStore


class FakeVectorStore:
    def search(self, query_embedding, top_k=2, where=None):
        return {
            "documents": [["Employees get annual leave."]],
            "metadatas": [[
                {
                    "source": "employee_handbook.pdf",
                    "document_type": "hr_policy",
                    "page_number": 1,
                }
            ]],
        }


def test_retrieve_with_metadata_filter():
    vector_store = FakeVectorStore()
    retrieval_service = RetrievalService(vector_store)

    result = retrieval_service.retrieve(
        query_embedding=[1.0, 0.0, 0.0],
        top_k=2,
        metadata_filter={"document_type": "hr_policy"},
    )

    assert result["documents"][0][0] == "Employees get annual leave."
    assert result["metadatas"][0][0]["document_type"] == "hr_policy"

def test_retrieve_with_real_vector_store_and_metadata_filter(tmp_path):
    vector_store = VectorStore(
        persist_directory=str(tmp_path),
        collection_name="test_retrieval",
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
        [0.9, 0.1, 0.0],
    ]

    vector_store.upsert_processed_chunks(
        processed_chunks,
        embeddings,
    )

    retrieval_service = RetrievalService(vector_store)

    result = retrieval_service.retrieve(
        query_embedding=[1.0, 0.0, 0.0],
        top_k=2,
        metadata_filter={"document_type": "hr_policy"},
    )

    assert len(result["documents"][0]) == 1
    assert result["documents"][0][0] == "Employees get annual leave."
    assert result["metadatas"][0][0]["document_type"] == "hr_policy"