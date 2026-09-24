from app.services.embedding_service import EmbeddingService
from app.services.vector_store import VectorStore

def main():
    embedding_service = EmbeddingService()
    vector_store = VectorStore()
    print("Collection count:", vector_store.collection.count())

    question = "How many annual leave days do I get?"

    query_embedding = embedding_service.embed_text(question)

    results = vector_store.search(query_embedding=query_embedding, top_k=2)

    documents = results["documents"][0]
    distances = results["distances"][0]
    metadatas = results["metadatas"][0]

    print("Question:")
    print(question)

    print("\nRetrieved results:")

    for index, (document, distance, metadata) in enumerate(
        zip(documents, distances, metadatas),
        start=1,
    ):
        cosine_similarity = 1 - distance

        print("\n" + "=" * 60)
        print("Rank:", index)
        print("Distance:", distance)
        print("Cosine similarity:", cosine_similarity)
        print("Document:", document)
        print("Metadata:", metadata)


if __name__ == "__main__":
    main()
