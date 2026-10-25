
"""Ingest text, tables, and optional visual descriptions from PDFs."""

from pathlib import Path
import tempfile


class MultimodalIngestionService:
    def __init__(
        self,
        embedding_service,
        vector_store,
        vision_description_service=None,
        page_renderer=None,
        visual_pages=None,
    ):
        self.embedding_service = embedding_service
        self.vector_store = vector_store
        self.vision_description_service = vision_description_service
        self.page_renderer = page_renderer
        self.visual_pages = (
            set(visual_pages) if visual_pages is not None else None
        )

    def ingest_pdf(self, pdf_path):
        from services.multimodal.multimodal_pdf_loader import (
            load_pdf_records,
        )

        path = Path(pdf_path)
        records = load_pdf_records(path)

        if self.vision_description_service and self.page_renderer:
            import pymupdf

            with pymupdf.open(path) as pdf:
                for page_number, page in enumerate(pdf, start=1):
                    if (
                        self.visual_pages is not None
                        and page_number not in self.visual_pages
                    ):
                        continue

                    # Initial heuristic: process pages containing drawings.
                    if not page.get_drawings():
                        continue

                    with tempfile.TemporaryDirectory() as temp_dir:
                        image_path = self.page_renderer.render_page(
                            pdf_path=path,
                            page_number=page_number,
                            output_dir=temp_dir,
                        )
                        description = (
                            self.vision_description_service.describe_image(
                                image_path
                            )
                        )

                    if description.strip():
                        records.append(
                            {
                                "record_id": (
                                    f"{path.name}:page:{page_number}:"
                                    "visual_description"
                                ),
                                "source": path.name,
                                "page_number": page_number,
                                "content_type": "visual_description",
                                "text": description.strip(),
                            }
                        )

        if not records:
            return {
                "source": path.name,
                "record_count": 0,
                "records_by_type": {},
            }

        embeddings = self.embedding_service.embed_texts(
            [record["text"] for record in records]
        )

        if len(embeddings) != len(records):
            raise ValueError(
                "Embedding count must match extracted record count."
            )

        self.vector_store.replace_source_records(
            source=records[0]["source"],
            records=records,
            embeddings=embeddings,
        )

        records_by_type = {}
        for record in records:
            content_type = record["content_type"]
            records_by_type[content_type] = (
                records_by_type.get(content_type, 0) + 1
            )

        return {
            "source": records[0]["source"],
            "record_count": len(records),
            "records_by_type": records_by_type,
        }
