
"""Persistent vector storage for multimodal PDF records."""

from pathlib import Path

import chromadb


REQUIRED_METADATA_FIELDS = (
    "source",
    "page_number",
    "content_type",
)


class MultimodalVectorStore:
    def __init__(
        self,
        persist_directory="data/multimodal_chroma",
        collection_name="multimodal_pdf_records",
    ):
        Path(persist_directory).mkdir(parents=True, exist_ok=True)

        self.client = chromadb.PersistentClient(path=persist_directory)
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            configuration={"hnsw": {"space": "cosine"}},
        )

        if self.collection.configuration["hnsw"]["space"] != "cosine":
            raise ValueError(
                "Multimodal collection must use cosine distance."
            )

    def upsert_records(self, records, embeddings):
        if not records:
            if embeddings:
                raise ValueError(
                    "Embeddings were provided without records."
                )
            return

        if len(records) != len(embeddings):
            raise ValueError(
                "Number of records must match number of embeddings."
            )

        ids = []
        documents = []
        metadatas = []

        for record in records:
            for field in ("record_id", "text", *REQUIRED_METADATA_FIELDS):
                if field not in record or record[field] is None:
                    raise ValueError(
                        f"Record is missing required field: {field}"
                    )

            if not record["text"].strip():
                raise ValueError("Record text must not be empty.")

            metadata = {
                "source": record["source"],
                "page_number": int(record["page_number"]),
                "content_type": record["content_type"],
            }

            # Preserve table provenance when available.
            if record.get("table_id") is not None:
                metadata["table_id"] = record["table_id"]

            if record.get("row_number") is not None:
                metadata["row_number"] = int(record["row_number"])

            ids.append(record["record_id"])
            documents.append(record["text"])
            metadatas.append(metadata)

        self.collection.upsert(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )
        
    def replace_source_records(self, source, records, embeddings):
        """Replace one source's records without affecting other sources."""
        if not source or not source.strip():
            raise ValueError("Source must not be empty.")

        if not records:
            raise ValueError(
                "Cannot replace source records with an empty record list."
            )

        if any(record.get("source") != source for record in records):
            raise ValueError(
                "All records must belong to the specified source."
            )

        # Validate and upsert new records before deleting stale ones.
        # If validation or upsert fails, existing records are preserved.
        existing = self.collection.get(
            where={"source": source},
            include=["metadatas"],
        )
        existing_ids = set(existing["ids"])
        new_ids = {record["record_id"] for record in records}

        self.upsert_records(records, embeddings)

        stale_ids = existing_ids - new_ids
        if stale_ids:
            self.collection.delete(ids=sorted(stale_ids))

    def search(self, query_embedding, top_k=3, where=None):
        if top_k <= 0 or self.collection.count() == 0:
            return {
                "ids": [[]],
                "documents": [[]],
                "metadatas": [[]],
                "distances": [[]],
            }

        result = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, self.collection.count()),
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        return result
