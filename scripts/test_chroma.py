from app.services.embedding_service import EmbeddingService
from app.services.vector_store import VectorStore

def main():
    embedding_service = EmbeddingService()
    vector_store = VectorStore()

    chunks = [
        "Employees are entitled to 20 days of annual leave per year.",
        "Employees can carry forward a maximum of 10 unused annual leave days.",
        "Employees are entitled to 12 days of sick leave per year.",
    ]

    embed_chunks = embedding_service.embed_texts(chunks)

    vector_store.upsert_chunks(
        chunks=chunks,
        embeddings=embed_chunks,
        source="company_policy.pdf"
    )

    print("Stored chunks:", len(chunks))


if __name__ == "__main__":
    main()
