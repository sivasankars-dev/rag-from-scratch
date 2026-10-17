
from services.child_vector_store import ChildVectorStore
from services.parent_child_chunker import build_parent_child_chunks
from services.parent_child_retrieval import ParentChildRetrievalService
from services.parent_child_store import ParentChildStore


class FakeEmbeddingService:
    def embed_texts(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]

    def embed_text(self, text):
        return [1.0, 0.0, 0.0]


def test_parent_child_pipeline_end_to_end(tmp_path):
    text = (
        "Employees receive annual leave and submit "
        "leave requests through the HR system"
    )

    # 1. Create parent and child chunks.
    chunked = build_parent_child_chunks(
        text=text,
        source="handbook.pdf",
        page_number=1,
        parent_chunk_size=20,
        child_chunk_size=4,
        child_chunk_overlap=1,
    )

    # 2. Initialize persistent stores in temporary directories.
    parent_store = ParentChildStore(
        storage_path=tmp_path / "parents.json"
    )

    child_store = ChildVectorStore(
        persist_directory=str(tmp_path / "chroma"),
        collection_name="integration_test",
    )

    # 3. Store the parents.
    for parent in chunked["parents"]:
        parent_store.store_parent(parent)

    # 4. Embed and store the children.
    embedding_service = FakeEmbeddingService()
    child_embeddings = embedding_service.embed_texts(
        [child["text"] for child in chunked["children"]]
    )

    child_store.store_children(
        chunked["children"],
        child_embeddings,
    )

    # 5. Retrieve children and resolve their parent context.
    retrieval_service = ParentChildRetrievalService(
        embedding_service=embedding_service,
        child_vector_store=child_store,
        parent_store=parent_store,
    )

    results = retrieval_service.retrieve(
        question="How do employees request annual leave?",
        top_k=3,
    )

    # 6. Verify the complete flow.
    assert results
    assert results[0]["parent_id"] == chunked["parents"][0]["parent_id"]
    assert results[0]["text"] == text
    assert results[0]["source"] == "handbook.pdf"
