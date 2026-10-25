from pathlib import Path

from services.multimodal.multimodal_ingestion import (
    MultimodalIngestionService,
)


class FakeEmbeddingService:
    def embed_texts(self, texts):
        return [[float(index + 1), 0.1, 0.2] for index, _ in enumerate(texts)]


class FakeVectorStore:
    def __init__(self):
        self.source = None
        self.records = None
        self.embeddings = None

    def replace_source_records(self, source, records, embeddings):
        self.source = source
        self.records = records
        self.embeddings = embeddings


def test_ingestion_stores_extracted_records(monkeypatch, tmp_path):
    source_path = tmp_path / "sample.pdf"
    source_path.touch()

    extracted_records = [
        {
            "record_id": "sample.pdf:page:1:text",
            "source": "sample.pdf",
            "page_number": 1,
            "content_type": "text",
            "text": "RAG retrieves relevant document content.",
        }
    ]

    monkeypatch.setattr(
        "services.multimodal.multimodal_pdf_loader.load_pdf_records",
        lambda path: extracted_records,
    )

    vector_store = FakeVectorStore()
    service = MultimodalIngestionService(
        embedding_service=FakeEmbeddingService(),
        vector_store=vector_store,
    )

    result = service.ingest_pdf(source_path)

    assert result["source"] == "sample.pdf"
    assert result["record_count"] == 1
    assert result["records_by_type"] == {"text": 1}
    assert vector_store.records == extracted_records
    assert len(vector_store.embeddings) == 1

class FakeVisionDescriptionService:
    def describe_image(self, image_path):
        assert Path(image_path).is_file()
        return (
            "RAG architecture diagram: documents flow into "
            "a retriever, which provides context to an LLM."
        )


class FakePageRenderer:
    def render_page(self, pdf_path, page_number, output_dir):
        image_path = Path(output_dir) / f"page_{page_number}.png"
        image_path.write_bytes(b"fake image")
        return image_path


def test_ingestion_adds_visual_description_records(
    monkeypatch, tmp_path
):
    source_path = tmp_path / "sample.pdf"
    source_path.touch()

    extracted_records = [
        {
            "record_id": "sample.pdf:page:1:text",
            "source": "sample.pdf",
            "page_number": 1,
            "content_type": "text",
            "text": "RAG retrieves document content.",
        }
    ]

    monkeypatch.setattr(
        "services.multimodal.multimodal_pdf_loader.load_pdf_records",
        lambda path: extracted_records.copy(),
    )

    class FakePage:
        def get_drawings(self):
            return [{"type": "drawing"}]

    class FakePDF:
        def __len__(self):
            return 1

        def __iter__(self):
            return iter([FakePage()])

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(
        "pymupdf.open",
        lambda path: FakePDF(),
    )

    vector_store = FakeVectorStore()
    service = MultimodalIngestionService(
        embedding_service=FakeEmbeddingService(),
        vector_store=vector_store,
        vision_description_service=FakeVisionDescriptionService(),
        page_renderer=FakePageRenderer(),
    )

    result = service.ingest_pdf(source_path)

    assert result["record_count"] == 2
    assert result["records_by_type"] == {
        "text": 1,
        "visual_description": 1,
    }

    visual_record = next(
        record
        for record in vector_store.records
        if record["content_type"] == "visual_description"
    )

    assert visual_record["record_id"] == (
        "sample.pdf:page:1:visual_description"
    )
    assert visual_record["page_number"] == 1
    assert "retriever" in visual_record["text"]
    assert len(vector_store.embeddings) == 2

def test_ingestion_processes_only_selected_visual_pages(
    monkeypatch, tmp_path
):
    source_path = tmp_path / "sample.pdf"
    source_path.touch()

    extracted_records = [
        {
            "record_id": "sample.pdf:page:1:text",
            "source": "sample.pdf",
            "page_number": 1,
            "content_type": "text",
            "text": "Page one text.",
        }
    ]

    monkeypatch.setattr(
        "services.multimodal.multimodal_pdf_loader.load_pdf_records",
        lambda path: extracted_records.copy(),
    )

    class FakePage:
        def get_drawings(self):
            return [{"type": "drawing"}]

    class FakePDF:
        def __iter__(self):
            return iter([FakePage(), FakePage(), FakePage()])

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("pymupdf.open", lambda path: FakePDF())

    vector_store = FakeVectorStore()
    service = MultimodalIngestionService(
        embedding_service=FakeEmbeddingService(),
        vector_store=vector_store,
        vision_description_service=FakeVisionDescriptionService(),
        page_renderer=FakePageRenderer(),
        visual_pages={2},
    )

    result = service.ingest_pdf(source_path)

    visual_records = [
        record
        for record in vector_store.records
        if record["content_type"] == "visual_description"
    ]

    assert len(visual_records) == 1
    assert visual_records[0]["page_number"] == 2
    assert result["records_by_type"]["visual_description"] == 1
