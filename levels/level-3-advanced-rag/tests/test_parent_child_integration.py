
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


def test_document_aware_retrieval_returns_correct_section_context(tmp_path):
    from services.document_section_parser import parse_document_sections
    from services.hierarchical_chunker import build_document_aware_chunks

    class SectionAwareEmbeddingService:
        def embed_texts(self, texts):
            return [
                [1.0, 0.0, 0.0]
                if "remote" in text.lower()
                else [0.0, 1.0, 0.0]
                for text in texts
            ]

        def embed_text(self, text):
            return (
                [1.0, 0.0, 0.0]
                if "remote" in text.lower()
                else [0.0, 1.0, 0.0]
            )

    pages = [{
        "page_number": 1,
        "text": (
            "2. Working Hours\n"
            "Standard collaboration hours are 10 AM to 4 PM on business days.\n"
            "2.1 Attendance\n"
            "Employees should maintain accurate attendance records.\n"
            "2.2 Remote Work\n"
            "Remote employees must protect company information. "
            "Company equipment must not be left unattended in public locations."
        ),
    }]

    # 1. Parse headings into document sections.
    sections = parse_document_sections(pages, "handbook.pdf")

    # 2. Create bounded hierarchical parent and child chunks.
    chunked = build_document_aware_chunks(
        sections,
        source="handbook.pdf",
        parent_chunk_size=100,
        child_chunk_size=12,
        child_chunk_overlap=2,
    )

    # 3. Save parents and index child embeddings.
    parent_store = ParentChildStore(
        storage_path=tmp_path / "hierarchical_parents.json"
    )
    for parent in chunked["parents"]:
        parent_store.store_parent(parent)

    embedding_service = SectionAwareEmbeddingService()
    child_store = ChildVectorStore(
        persist_directory=str(tmp_path / "hierarchical_chroma"),
        collection_name="hierarchical_integration_test",
    )
    embeddings = embedding_service.embed_texts(
        [child["text"] for child in chunked["children"]]
    )
    child_store.store_children(chunked["children"], embeddings)

    # 4. Retrieve the relevant child and recover its parent context.
    retrieval_service = ParentChildRetrievalService(
        embedding_service=embedding_service,
        child_vector_store=child_store,
        parent_store=parent_store,
    )
    results = retrieval_service.retrieve(
        "What should remote employees do to protect company equipment?",
        top_k=1,
    )

    # 5. Verify section identity and hierarchy survived the full pipeline.
    assert results
    assert results[0]["section_title"] == "Remote Work"
    assert results[0]["section_number"] == "2.2"
    assert results[0]["section_path"] == "Working Hours > Remote Work"
    assert results[0]["parent_section_id"] == (
        "handbook.pdf::section::2"
    )
    assert "Company equipment" in results[0]["text"]
