from tempfile import TemporaryDirectory

from services.embedding_service import EmbeddingService
from services.vector_store import VectorStore

def main():
    embedding_service = EmbeddingService()

    chunks = [
        "Employees are entitled to 20 days of annual leave per year.",
        "Employees can carry forward a maximum of 10 unused annual leave days.",
        "Employees are entitled to 12 days of sick leave per year.",
    ]

    embed_chunks = embedding_service.embed_texts(chunks)

    # Keep this three-sentence experiment separate from the ingested PDF records.
    with TemporaryDirectory() as directory:
        vector_store = VectorStore(persist_directory=directory)
        vector_store.upsert_chunks(
            chunks=chunks,
            embeddings=embed_chunks,
            source="company_policy.pdf"
        )
        assert vector_store.collection.count() == len(chunks)
        print("Stored chunks:", vector_store.collection.count())


if __name__ == "__main__":
    main()
