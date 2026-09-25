from app.services.embedding_service import EmbeddingService
from app.services.retrieval_controls_vector_store import VectorStore

def main():
    embedding_service = EmbeddingService()
    vector_store = VectorStore()
    print("Collection count:", vector_store.collection.count())

    question = "How many annual leave days do I get?"
    # question = "What is the company's work from home policy?"
    # question = "do you know my name?"

    query_embedding = embedding_service.embed_text(question)

    results = vector_store.search(query_embedding=query_embedding, top_k=5, source="company_policy.pdf")

    print("Question:")
    print(question)

    print("\nRetrieved results:")
    if not results:
        print("No relevant documents found.")
        return

    for index, result in enumerate(results, start=1):
        
        print("\n" + "=" * 60)
        print("Rank:", index)
        print("Distance:", result["distance"])
        print("Cosine similarity:", result["similarity"])
        print("Document:", result["document"])
        print("Metadata:", result["metadata"])


if __name__ == "__main__":
    main()
